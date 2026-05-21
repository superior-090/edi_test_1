import json
from datetime import datetime, timezone

import cv2
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..models import Event, Session as SessionModel, User
from ..schemas import ClientEventRequest, EventOut, SessionOut, SessionStartRequest, SubmitExamRequest
from ..security import get_db, get_current_user, require_role
from ..services.ai_service import ai_service
from ..services.side_camera import validate_side_camera_url
from ..state import manager, store_side_frame

router = APIRouter(prefix="/session", tags=["session"])


def _risk(score: float) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 55:
        return "HIGH"
    if score >= 25:
        return "MEDIUM"
    return "LOW"


def _serialize_session(session: SessionModel) -> dict:
    return SessionOut.model_validate(session).model_dump(mode="json")


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
    db.commit()
    db.refresh(event)
    db.refresh(session)
    return event


@router.post("/start", response_model=SessionOut)
async def start_session(
    payload: SessionStartRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("candidate", "admin")),
):
    try:
        side_camera_url, side_camera_frame = validate_side_camera_url(payload.side_camera_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    await manager.broadcast_admin({"type": "session_started", **_serialize_session(session)})
    return session


@router.get("/{session_id}/status", response_model=SessionOut)
def get_status(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/{session_id}/event", response_model=EventOut)
async def client_event(
    session_id: str,
    payload: ClientEventRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    event = _record_event(
        db,
        session,
        payload.event_type,
        payload.message,
        payload.severity,
        score_delta=payload.score_delta,
        metadata=payload.metadata,
    )

    message = {"type": "event", **_serialize_session(session), "latest_event": EventOut(
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
    await manager.broadcast(session.session_id, message)
    return message["latest_event"]


@router.post("/{session_id}/submit", response_model=SessionOut)
async def submit_exam(
    session_id: str,
    payload: SubmitExamRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    session.answers_json = json.dumps(payload.answers)
    session.is_active = False
    session.is_submitted = True
    session.status = "SUBMITTED"
    session.submitted_at = datetime.now(timezone.utc)
    _record_event(db, session, "EXAM_SUBMITTED", f"Exam submitted: {payload.reason}", "INFO")

    await manager.broadcast_admin({"type": "exam_submitted", **_serialize_session(session)})
    return session


@router.post("/end")
async def end_session(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("candidate", "admin")),
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

    await manager.broadcast_admin({"type": "session_ended", **_serialize_session(session)})
    return {"status": "session ended", "session_id": session_id}
