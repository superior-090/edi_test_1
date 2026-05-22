import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from jose import JWTError
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import (
    Answer,
    Event,
    Exam,
    ExamAttempt,
    ExamQuestionImage,
    ProctorLog,
    Question,
    QuestionImage,
    Result,
    Session as SessionModel,
    Subject,
    User,
)
from ..role_filter import admin_session_payload, is_staff_role, student_session_payload
from ..schemas import (
    AttemptResultAnswerOut,
    AutosaveAnswersRequest,
    ClientEventRequest,
    EventOut,
    QuestionImageOut,
    SessionStartRequest,
    StudentQuestionOut,
    StudentResultOut,
    SubmitExamRequest,
)
from ..security import decode_token_without_db, get_db, get_current_user, require_role
from ..services.ai_service import ai_service
from ..services.side_camera import (
    get_latest_side_camera_frame,
    normalize_side_camera_url,
    validate_side_camera_url,
)
from ..state import manager, store_side_frame

router = APIRouter(prefix="/session", tags=["session"])
logger = logging.getLogger(__name__)
QUESTION_IMAGE_DIR = Path(__file__).resolve().parents[2] / "uploads" / "question_images"


def _cv2():
    import cv2

    return cv2


def _risk(score: float) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 55:
        return "HIGH"
    if score >= 25:
        return "MEDIUM"
    return "LOW"


def _serialize_session(session: SessionModel, message_type: str = "session") -> dict:
    return admin_session_payload(session, message_type)


def _attempt_for_session(db: Session, session_id: str) -> ExamAttempt | None:
    return db.query(ExamAttempt).filter(ExamAttempt.session_id == session_id).first()


def _attempt_student(db: Session, session: SessionModel) -> User | None:
    return db.query(User).filter(User.username == session.student_id).first()


def _authorize_session_access(session: SessionModel, user: User) -> None:
    if not is_staff_role(user.role) and session.student_id != user.username:
        raise HTTPException(status_code=403, detail="Candidate cannot access another student's session")


def _record_event(
    db: Session,
    session: SessionModel,
    event_type: str,
    message: str,
    severity: str = "INFO",
    confidence: float = 0.0,
    score_delta: float = 0.0,
    metadata: dict | None = None,
) -> Event:
    event = Event(
        session_id=session.session_id,
        event_type=event_type,
        severity=severity,
        message=message,
        confidence=confidence,
        score_delta=score_delta,
        metadata_json=json.dumps(metadata or {}),
    )
    db.add(event)
    student = _attempt_student(db, session)
    db.add(ProctorLog(
        exam_id=session.exam_id,
        student_id=student.id if student else None,
        event_type=event_type,
        event_details=message,
        ai_score=session.cheat_score + score_delta,
    ))

    if event_type == "TAB_SWITCH":
        session.tab_switch_count += 1
    if event_type == "DISCONNECT":
        session.disconnect_count += 1
    if severity in ("MEDIUM", "HIGH", "CRITICAL"):
        session.warning_count += 1
    if score_delta > 0:
        session.cheat_score = min(100.0, session.cheat_score + score_delta)
    session.risk_level = _risk(session.cheat_score)
    if event_type != "EXAM_SUBMITTED":
        session.status = "AUTO_SUBMIT_REQUIRED" if session.cheat_score >= 95 else session.risk_level
    session.cheat_message = message
    session.is_cheating = session.risk_level in ("HIGH", "CRITICAL")
    attempt = _attempt_for_session(db, session.session_id)
    if attempt is not None:
        if event_type == "TAB_SWITCH":
            attempt.tab_switch_count += 1
        if severity in ("MEDIUM", "HIGH", "CRITICAL"):
            attempt.suspicious_events += 1
        attempt.ai_risk_level = session.risk_level
    db.commit()
    db.refresh(event)
    db.refresh(session)
    return event


def _question_image_url(question: Question) -> str:
    return f"/session/questions/{question.id}/image" if question.question_image else ""


def _student_result(db: Session, attempt: ExamAttempt) -> dict:
    exam = db.query(Exam).filter(Exam.id == attempt.exam_id).first()
    questions = {
        question.id: question
        for question in db.query(Question).filter(Question.exam_id == attempt.exam_id).all()
    }
    answer_rows = (
        db.query(Answer)
        .filter(Answer.attempt_id == attempt.id)
        .order_by(Answer.question_id.asc())
        .all()
    )
    total_marks = sum(question.marks for question in questions.values())
    answer_payloads = []
    for answer in answer_rows:
        question = questions.get(answer.question_id)
        if question is None:
            continue
        answer_payloads.append(AttemptResultAnswerOut(
            question_id=question.id,
            question_text=question.question_text,
            selected_option=answer.selected_option,
            correct_option=question.correct_option,
            is_correct=answer.is_correct,
            marks_awarded=answer.marks_awarded,
            marks=question.marks,
            explanation=question.explanation,
        ))
    percentage = (attempt.score / total_marks * 100) if total_marks else 0.0
    return StudentResultOut(
        attempt_id=attempt.id,
        exam_id=attempt.exam_id,
        exam_title=exam.title if exam else "Exam",
        score=attempt.score,
        total_marks=total_marks,
        percentage=round(percentage, 2),
        submitted_at=attempt.submitted_at,
        answers=answer_payloads,
    ).model_dump(mode="json")


@router.post("/start")
async def start_session(
    payload: SessionStartRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("candidate", "student", "admin", "proctor")),
):
    if not is_staff_role(user.role) and payload.student_id != user.username:
        raise HTTPException(status_code=403, detail="Candidate cannot start another student's session")

    exam = None
    if payload.exam_id is not None:
        exam = db.query(Exam).filter(Exam.id == payload.exam_id).first()
        if exam is None:
            raise HTTPException(status_code=404, detail="Exam not found")
        if not is_staff_role(user.role) and not exam.is_published:
            raise HTTPException(status_code=403, detail="Exam is not published")
        now = datetime.now(timezone.utc)
        if not is_staff_role(user.role) and exam.start_time and exam.start_time > now:
            raise HTTPException(status_code=409, detail="Exam has not started yet")
        if not is_staff_role(user.role) and exam.end_time and exam.end_time < now:
            raise HTTPException(status_code=409, detail="Exam window has ended")
        subject = db.query(Subject).filter(Subject.id == exam.subject_id).first()
        payload.exam_title = exam.title
        if subject is not None:
            payload.subject = subject.subject_code

    side_camera_frame = None
    try:
        side_camera_url, side_camera_frame = validate_side_camera_url(payload.side_camera_url)
    except ValueError as exc:
        side_camera_url = normalize_side_camera_url(payload.side_camera_url)
        if side_camera_url.lower().startswith("rtsp://"):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        logger.warning(
            "Browser-validated side camera accepted without initial backend frame; "
            "session_id=%s url=%s error=%s",
            payload.session_id,
            side_camera_url,
            exc,
        )

    previous = (
        db.query(SessionModel)
        .filter(
            SessionModel.student_id == payload.student_id,
            SessionModel.exam_title == payload.exam_title,
            SessionModel.is_submitted == False,
            SessionModel.session_id != payload.session_id,
        )
        .order_by(SessionModel.created_at.desc())
        .first()
    )

    session = db.query(SessionModel).filter(SessionModel.session_id == payload.session_id).first()
    if session is None:
        session = SessionModel(session_id=payload.session_id)
        db.add(session)

    session.student_id = payload.student_id
    session.student_name = payload.student_name or user.full_name
    session.exam_id = payload.exam_id
    session.subject = payload.subject
    session.exam_title = payload.exam_title
    session.side_camera_url = side_camera_url
    session.side_camera_status = "ONLINE"
    session.is_submitted = False
    session.is_terminated = False
    session.approval_note = ""

    if previous is not None:
        session.is_active = False
        session.status = "REJOIN_PENDING"
        session.approval_status = "PENDING"
        session.cheat_message = "Waiting for proctor approval to rejoin this exam"
        db.add(Event(
            session_id=session.session_id,
            event_type="REJOIN_REQUEST",
            severity="MEDIUM",
            message=f"{session.student_name} requested to rejoin {session.exam_title}",
            score_delta=0,
            metadata_json=json.dumps({"previous_session_id": previous.session_id}),
        ))
    else:
        session.is_active = True
        session.status = "MONITORING"
        session.approval_status = "NOT_REQUIRED"
        session.cheat_message = "AI monitoring active"

    db.commit()
    db.refresh(session)
    attempt = None
    if exam is not None:
        attempt = (
            db.query(ExamAttempt)
            .filter(
                ExamAttempt.exam_id == exam.id,
                ExamAttempt.student_id == user.id,
                ExamAttempt.status == "IN_PROGRESS",
            )
            .order_by(ExamAttempt.started_at.desc())
            .first()
        )
        if attempt is None:
            attempt = ExamAttempt(
                exam_id=exam.id,
                student_id=user.id,
                session_id=session.session_id,
                side_camera_ok=True,
                ai_risk_level=session.risk_level,
            )
            db.add(attempt)
        else:
            attempt.session_id = session.session_id
            attempt.side_camera_ok = True
        db.commit()
        db.refresh(attempt)

    if side_camera_frame is not None:
        cv2 = _cv2()
        encoded_ok, side_buffer = cv2.imencode(
            ".jpg",
            side_camera_frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), 80],
        )
        side_detection = ai_service.process_frame(
            f"{session.session_id}:side",
            side_camera_frame,
            camera="side",
        )
        store_side_frame(
            session.session_id,
            side_buffer.tobytes() if encoded_ok else b"",
            side_detection.annotated_jpeg,
        )

    await manager.broadcast_admin(_serialize_session(session, "session_started"))
    payload_out = admin_session_payload(session, "session_started") if is_staff_role(user.role) else student_session_payload(session, "session_started")
    if attempt is not None:
        payload_out["attempt_id"] = attempt.id
    return payload_out


@router.get("/{session_id}/status")
def get_status(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    _authorize_session_access(session, user)
    return admin_session_payload(session, "status") if is_staff_role(user.role) else student_session_payload(session, "status")


def _raw_side_stream(session_id: str):
    db = SessionLocal()
    frames_sent = 0
    fps_window_at = time.monotonic()
    logger.info("Student side MJPEG stream connected; session_id=%s", session_id)
    try:
        while True:
            frame = _student_side_frame(session_id, db)
            if frame:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                frames_sent += 1
            now = time.monotonic()
            elapsed = now - fps_window_at
            if elapsed >= 5.0:
                logger.info(
                    "Student side MJPEG stream fps=%.1f frames=%s; session_id=%s",
                    frames_sent / elapsed,
                    frames_sent,
                    session_id,
                )
                frames_sent = 0
                fps_window_at = now
            time.sleep(0.1)
    except GeneratorExit:
        pass
    except Exception:
        logger.exception("Student side stream failed; session_id=%s", session_id)
    finally:
        logger.info("Student side MJPEG stream disconnected; session_id=%s", session_id)
        db.close()


def _authorize_session_media(session_id: str, db: Session, user: User) -> None:
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if not is_staff_role(user.role) and session.student_id != user.username:
        raise HTTPException(status_code=403, detail="Insufficient role")


def _media_user(token: str, db: Session) -> User:
    try:
        payload = decode_token_without_db(token)
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Inactive user")
    return user


def _encode_frame(frame):
    cv2 = _cv2()
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    return buffer.tobytes() if ok else None


def _student_side_frame(session_id: str, db: Session) -> bytes | None:
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is not None and session.side_camera_url:
        ok, camera_frame = get_latest_side_camera_frame(session.side_camera_url)
        if ok:
            encoded = _encode_frame(camera_frame)
            if encoded:
                store_side_frame(session_id, encoded)
                return encoded
    return None


@router.get("/questions", response_model=list[StudentQuestionOut])
def exam_questions(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if exam is None:
        raise HTTPException(status_code=404, detail="Exam not found")
    if not is_staff_role(user.role) and not exam.is_published:
        raise HTTPException(status_code=403, detail="Exam is not published")
    rows = (
        db.query(Question)
        .filter(Question.exam_id == exam.id)
        .order_by(Question.sort_order.asc(), Question.id.asc())
        .all()
    )
    return [
        StudentQuestionOut(
            id=question.id,
            exam_id=question.exam_id,
            question_text=question.question_text,
            image_url=_question_image_url(question),
            option_a=question.option_a,
            option_b=question.option_b,
            option_c=question.option_c,
            option_d=question.option_d,
            marks=question.marks,
            sort_order=question.sort_order,
        )
        for question in rows
    ]


@router.get("/questions/{question_id}/image")
def exam_question_image(
    question_id: int,
    token: str,
    db: Session = Depends(get_db),
):
    _media_user(token, db)
    question = db.query(Question).filter(Question.id == question_id).first()
    if question is None or not question.question_image:
        raise HTTPException(status_code=404, detail="Question image not found")
    image_path = QUESTION_IMAGE_DIR / question.question_image
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Question image file is missing")
    return FileResponse(
        image_path,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/question-images", response_model=list[QuestionImageOut])
def exam_question_images(
    subject: str | None = None,
    exam_title: str | None = None,
    exam_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if exam_id is not None:
        rows = (
            db.query(QuestionImage, Exam, Subject)
            .join(Exam, QuestionImage.exam_id == Exam.id)
            .join(Subject, Exam.subject_id == Subject.id)
            .filter(QuestionImage.exam_id == exam_id)
            .order_by(QuestionImage.question_number.asc(), QuestionImage.id.asc())
            .all()
        )
        return [
            QuestionImageOut(
                id=image.id,
                exam_id=image.exam_id,
                subject=subject.subject_code,
                exam_title=exam.title,
                original_filename=image.original_filename,
                content_type=image.content_type,
                sort_order=image.question_number,
                question_number=image.question_number,
                created_at=image.created_at,
            )
            for image, exam, subject in rows
        ]

    if not subject or not exam_title:
        raise HTTPException(status_code=422, detail="exam_id or subject and exam_title are required")
    normalized_subject = subject.strip().upper() or "GENERAL"
    normalized_title = " ".join(exam_title.strip().split())
    if not normalized_title:
        raise HTTPException(status_code=422, detail="exam_title is required")
    return (
        db.query(ExamQuestionImage)
        .filter(
            ExamQuestionImage.subject == normalized_subject,
            ExamQuestionImage.exam_title == normalized_title,
            ExamQuestionImage.is_active == True,
        )
        .order_by(ExamQuestionImage.sort_order.asc(), ExamQuestionImage.id.asc())
        .all()
    )


@router.get("/question-images/{image_id}/file")
def exam_question_image_file(
    image_id: int,
    token: str,
    db: Session = Depends(get_db),
):
    _media_user(token, db)
    new_image = db.query(QuestionImage).filter(QuestionImage.id == image_id).first()
    if new_image is not None:
        image_path = QUESTION_IMAGE_DIR / new_image.image_path
        if not image_path.exists():
            raise HTTPException(status_code=404, detail="Question image file is missing")
        return FileResponse(
            image_path,
            media_type=new_image.content_type,
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    image = (
        db.query(ExamQuestionImage)
        .filter(ExamQuestionImage.id == image_id, ExamQuestionImage.is_active == True)
        .first()
    )
    if image is None:
        raise HTTPException(status_code=404, detail="Question image not found")
    image_path = QUESTION_IMAGE_DIR / image.stored_filename
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Question image file is missing")
    return FileResponse(
        image_path,
        media_type=image.content_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{session_id}/side-stream")
def student_side_stream(
    session_id: str,
    token: str,
    db: Session = Depends(get_db),
):
    user = _media_user(token, db)
    _authorize_session_media(session_id, db, user)
    return StreamingResponse(
        _raw_side_stream(session_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{session_id}/side-snapshot")
def student_side_snapshot(
    session_id: str,
    token: str,
    db: Session = Depends(get_db),
):
    user = _media_user(token, db)
    _authorize_session_media(session_id, db, user)
    frame = _student_side_frame(session_id, db)
    if not frame:
        raise HTTPException(status_code=404, detail="Side frame not available yet")
    return Response(
        content=frame,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/{session_id}/event")
async def client_event(
    session_id: str,
    payload: ClientEventRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    _authorize_session_access(session, user)

    event = _record_event(
        db,
        session,
        payload.event_type,
        payload.message,
        payload.severity,
        score_delta=payload.score_delta,
        metadata=payload.metadata,
    )

    admin_message = {**_serialize_session(session, "event"), "latest_event": EventOut(
        id=event.id,
        session_id=event.session_id,
        event_type=event.event_type,
        severity=event.severity,
        message=event.message,
        confidence=event.confidence,
        score_delta=event.score_delta,
        metadata=json.loads(event.metadata_json or "{}"),
        created_at=event.created_at,
    ).model_dump(mode="json")}
    await manager.broadcast_admin(admin_message)
    await manager.broadcast_session(session.session_id, student_session_payload(session, "event"))
    return admin_message["latest_event"] if is_staff_role(user.role) else {"status": "recorded"}


@router.put("/{session_id}/autosave")
def autosave_answers(
    session_id: str,
    payload: AutosaveAnswersRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    _authorize_session_access(session, user)
    attempt = _attempt_for_session(db, session_id)
    if attempt is None or attempt.submitted_at is not None:
        raise HTTPException(status_code=409, detail="Active exam attempt not found")
    attempt.autosave_json = json.dumps(payload.answers)
    session.answers_json = attempt.autosave_json
    db.commit()
    return {"status": "saved", "attempt_id": attempt.id, "saved_answers": len(payload.answers)}


@router.post("/{session_id}/submit")
async def submit_exam(
    session_id: str,
    payload: SubmitExamRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    _authorize_session_access(session, user)
    if session.is_submitted:
        return admin_session_payload(session, "exam_submitted") if is_staff_role(user.role) else student_session_payload(session, "exam_submitted")

    session.answers_json = json.dumps(payload.answers)
    session.is_active = False
    session.is_submitted = True
    session.status = "SUBMITTED"
    session.submitted_at = datetime.now(timezone.utc)
    _record_event(db, session, "EXAM_SUBMITTED", f"Exam submitted: {payload.reason}", "INFO")
    attempt = _attempt_for_session(db, session.session_id)
    if session.exam_id is not None:
        student = db.query(User).filter(User.username == session.student_id).first()
        if student is not None:
            if attempt is None:
                attempt = ExamAttempt(
                    exam_id=session.exam_id,
                    student_id=student.id,
                    session_id=session.session_id,
                    side_camera_ok=session.side_camera_status == "ONLINE",
                )
                db.add(attempt)
                db.flush()
            questions = (
                db.query(Question)
                .filter(Question.exam_id == session.exam_id)
                .order_by(Question.sort_order.asc(), Question.id.asc())
                .all()
            )
            score = 0.0
            for question in questions:
                selected = str(payload.answers.get(str(question.id), "")).strip().upper()
                if selected not in {"A", "B", "C", "D"}:
                    selected = ""
                answer = (
                    db.query(Answer)
                    .filter(Answer.attempt_id == attempt.id, Answer.question_id == question.id)
                    .first()
                )
                if answer is None:
                    answer = Answer(attempt_id=attempt.id, question_id=question.id)
                    db.add(answer)
                answer.selected_option = selected
                answer.is_correct = bool(selected and selected == question.correct_option.upper())
                answer.marks_awarded = question.marks if answer.is_correct else 0.0
                score += answer.marks_awarded
            attempt.autosave_json = session.answers_json
            attempt.submitted_at = session.submitted_at
            attempt.auto_submitted = payload.reason != "submitted_by_candidate"
            attempt.score = score
            attempt.status = "SUBMITTED"
            attempt.tab_switch_count = session.tab_switch_count
            attempt.ai_risk_level = session.risk_level
            attempt.front_camera_ok = True
            attempt.side_camera_ok = session.side_camera_status == "ONLINE"
            existing = (
                db.query(Result)
                .filter(Result.student_id == student.id, Result.exam_id == session.exam_id)
                .first()
            )
            violation_count = db.query(Event).filter(Event.session_id == session.session_id).count()
            result = existing or Result(student_id=student.id, exam_id=session.exam_id)
            result.score = score
            result.submitted_at = session.submitted_at
            result.ai_suspicion_score = session.cheat_score
            result.violation_count = violation_count
            result.status = "SUBMITTED"
            db.add(result)
            db.commit()

    await manager.broadcast_admin(_serialize_session(session, "exam_submitted"))
    await manager.broadcast_session(session.session_id, student_session_payload(session, "exam_submitted"))
    response = admin_session_payload(session, "exam_submitted") if is_staff_role(user.role) else student_session_payload(session, "exam_submitted")
    if attempt is not None and not is_staff_role(user.role):
        response["result"] = _student_result(db, attempt)
    return response


@router.get("/{session_id}/result")
def attempt_result(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    _authorize_session_access(session, user)
    attempt = _attempt_for_session(db, session_id)
    if attempt is None or attempt.submitted_at is None:
        raise HTTPException(status_code=409, detail="Result is not ready")
    return _student_result(db, attempt)


@router.post("/end")
async def end_session(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("candidate", "student", "admin", "proctor")),
):
    session_id = str(payload.get("session_id", "")).strip()
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")

    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    session.is_active = False
    session.is_cheating = False
    session.status = "SUBMITTED"
    session.cheat_message = "Exam submitted"
    db.commit()
    db.refresh(session)

    await manager.broadcast_admin(_serialize_session(session, "session_ended"))
    return {"status": "session ended", "session_id": session_id}
