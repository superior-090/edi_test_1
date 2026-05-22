import csv
import html
import io
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..models import (
    Event,
    Exam,
    QuestionImage,
    Result,
    Session as SessionModel,
    StudentProfile,
    Subject,
    Teacher,
    User,
)
from ..schemas import (
    ExamIn,
    ExamOut,
    QuestionImageOut,
    ResultOut,
    SubjectIn,
    SubjectOut,
    TeacherDashboardStats,
    TeacherStudentOut,
    ViolationOut,
)
from ..security import get_db, require_role

router = APIRouter(prefix="/teacher", tags=["teacher"])

QUESTION_IMAGE_DIR = Path(__file__).resolve().parents[2] / "uploads" / "question_images"
ALLOWED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}


def _teacher_profile(db: Session, user: User) -> Teacher:
    teacher = db.query(Teacher).filter(Teacher.user_id == user.id).first()
    if teacher is None:
        teacher = db.query(Teacher).filter(Teacher.email == user.email).first()
    if teacher is None:
        teacher = Teacher(
            user_id=user.id,
            full_name=user.full_name,
            email=user.email,
            password_hash=user.password_hash,
            department="",
            employee_id=f"EMP-{user.id}",
        )
        db.add(teacher)
        db.commit()
        db.refresh(teacher)
    return teacher


def _subject_for_teacher(db: Session, subject_id: int, teacher_id: int) -> Subject:
    subject = (
        db.query(Subject)
        .filter(Subject.id == subject_id, Subject.created_by_teacher_id == teacher_id)
        .first()
    )
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return subject


def _exam_for_teacher(db: Session, exam_id: int, teacher_id: int) -> Exam:
    exam = db.query(Exam).filter(Exam.id == exam_id, Exam.teacher_id == teacher_id).first()
    if exam is None:
        raise HTTPException(status_code=404, detail="Exam not found")
    return exam


def _exam_out(db: Session, exam: Exam) -> dict:
    subject = db.query(Subject).filter(Subject.id == exam.subject_id).first()
    question_count = db.query(QuestionImage).filter(QuestionImage.exam_id == exam.id).count()
    data = ExamOut.model_validate(exam).model_dump(mode="json")
    if subject is not None:
        data.update({
            "subject_name": subject.subject_name,
            "subject_code": subject.subject_code,
            "branch": subject.branch,
            "division": subject.division,
            "semester": subject.semester,
        })
    data["question_count"] = question_count
    return data


def _question_image_out(image: QuestionImage, exam: Exam | None = None, subject: Subject | None = None) -> dict:
    return QuestionImageOut(
        id=image.id,
        exam_id=image.exam_id,
        subject=subject.subject_code if subject else "",
        exam_title=exam.title if exam else "",
        original_filename=image.original_filename,
        content_type=image.content_type,
        sort_order=image.question_number,
        question_number=image.question_number,
        created_at=image.created_at,
    ).model_dump(mode="json")


def _content_type_from_filename(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(suffix, "")


def _content_type_from_bytes(contents: bytes) -> str:
    if contents.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if contents.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if contents.startswith(b"GIF87a") or contents.startswith(b"GIF89a"):
        return "image/gif"
    if contents.startswith(b"BM"):
        return "image/bmp"
    if len(contents) >= 12 and contents[:4] == b"RIFF" and contents[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _resolve_image_type(file: UploadFile, contents: bytes) -> str:
    candidates = [
        (file.content_type or "").split(";")[0].strip().lower(),
        _content_type_from_filename(file.filename),
        _content_type_from_bytes(contents),
    ]
    for content_type in candidates:
        if content_type in ALLOWED_IMAGE_TYPES:
            return content_type
    raise HTTPException(status_code=415, detail="Upload a valid image file")


def _teacher_exam_ids(db: Session, teacher_id: int) -> list[int]:
    return [row.id for row in db.query(Exam.id).filter(Exam.teacher_id == teacher_id).all()]


def _result_rows(
    db: Session,
    teacher_id: int,
    subject_id: int | None = None,
    branch: str | None = None,
    division: str | None = None,
    search: str | None = None,
) -> list[dict]:
    query = (
        db.query(Result, User, StudentProfile, Exam, Subject)
        .join(User, Result.student_id == User.id)
        .outerjoin(StudentProfile, StudentProfile.user_id == User.id)
        .join(Exam, Result.exam_id == Exam.id)
        .join(Subject, Exam.subject_id == Subject.id)
        .filter(Exam.teacher_id == teacher_id)
    )
    if subject_id:
        query = query.filter(Subject.id == subject_id)
    if branch:
        query = query.filter(StudentProfile.branch == branch)
    if division:
        query = query.filter(StudentProfile.division == division)
    rows = []
    normalized_search = (search or "").strip().lower()
    for result, user, profile, exam, subject in query.order_by(Result.submitted_at.desc()).all():
        name = profile.full_name if profile else user.full_name
        prn = profile.prn if profile else ""
        if normalized_search and normalized_search not in f"{name} {prn} {user.username}".lower():
            continue
        total = exam.total_marks or 0
        percentage = (result.score / total * 100) if total else 0
        rows.append(ResultOut(
            id=result.id,
            student_id=user.id,
            exam_id=exam.id,
            student_name=name,
            prn=prn,
            branch=profile.branch if profile else "",
            division=profile.division if profile else "",
            semester=profile.semester if profile else "",
            year=profile.year if profile else "",
            subject=subject.subject_name,
            subject_code=subject.subject_code,
            exam_title=exam.title,
            marks=result.score,
            total_marks=total,
            percentage=round(percentage, 2),
            submitted_at=result.submitted_at,
            ai_suspicion_score=result.ai_suspicion_score,
            violation_count=result.violation_count,
            status=result.status,
        ).model_dump(mode="json"))
    return rows


@router.get("/summary", response_model=TeacherDashboardStats)
def dashboard_summary(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("teacher")),
):
    teacher = _teacher_profile(db, user)
    exam_ids = _teacher_exam_ids(db, teacher.id)
    return TeacherDashboardStats(
        subjects=db.query(Subject).filter(Subject.created_by_teacher_id == teacher.id).count(),
        exams=len(exam_ids),
        published_exams=db.query(Exam).filter(Exam.teacher_id == teacher.id, Exam.is_published == True).count(),
        students=db.query(StudentProfile).count(),
        results=db.query(Result).filter(Result.exam_id.in_(exam_ids)).count() if exam_ids else 0,
        violations=(
            db.query(Event)
            .join(SessionModel, Event.session_id == SessionModel.session_id)
            .filter(SessionModel.exam_id.in_(exam_ids))
            .count()
            if exam_ids else 0
        ),
    )


@router.get("/subjects", response_model=list[SubjectOut])
def list_subjects(
    branch: str | None = None,
    division: str | None = None,
    semester: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("teacher")),
):
    teacher = _teacher_profile(db, user)
    query = db.query(Subject).filter(Subject.created_by_teacher_id == teacher.id)
    if branch:
        query = query.filter(Subject.branch == branch)
    if division:
        query = query.filter(Subject.division == division)
    if semester:
        query = query.filter(Subject.semester == semester)
    return query.order_by(Subject.created_at.desc()).all()


@router.post("/subjects", response_model=SubjectOut)
def create_subject(
    payload: SubjectIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("teacher")),
):
    teacher = _teacher_profile(db, user)
    subject = Subject(
        subject_name=payload.subject_name.strip(),
        subject_code=payload.subject_code.strip().upper(),
        branch=payload.branch.strip().upper(),
        semester=payload.semester.strip(),
        division=payload.division.strip().upper(),
        created_by_teacher_id=teacher.id,
    )
    db.add(subject)
    db.commit()
    db.refresh(subject)
    return subject


@router.put("/subjects/{subject_id}", response_model=SubjectOut)
def update_subject(
    subject_id: int,
    payload: SubjectIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("teacher")),
):
    teacher = _teacher_profile(db, user)
    subject = _subject_for_teacher(db, subject_id, teacher.id)
    subject.subject_name = payload.subject_name.strip()
    subject.subject_code = payload.subject_code.strip().upper()
    subject.branch = payload.branch.strip().upper()
    subject.semester = payload.semester.strip()
    subject.division = payload.division.strip().upper()
    db.commit()
    db.refresh(subject)
    return subject


@router.delete("/subjects/{subject_id}")
def delete_subject(
    subject_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("teacher")),
):
    teacher = _teacher_profile(db, user)
    subject = _subject_for_teacher(db, subject_id, teacher.id)
    if db.query(Exam).filter(Exam.subject_id == subject.id).first() is not None:
        raise HTTPException(status_code=409, detail="Delete exams under this subject first")
    db.delete(subject)
    db.commit()
    return {"status": "deleted", "id": subject_id}


@router.get("/exams")
def list_exams(
    subject_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("teacher")),
):
    teacher = _teacher_profile(db, user)
    query = db.query(Exam).filter(Exam.teacher_id == teacher.id)
    if subject_id:
        query = query.filter(Exam.subject_id == subject_id)
    return [_exam_out(db, exam) for exam in query.order_by(Exam.created_at.desc()).all()]


@router.post("/exams")
def create_exam(
    payload: ExamIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("teacher")),
):
    teacher = _teacher_profile(db, user)
    _subject_for_teacher(db, payload.subject_id, teacher.id)
    exam = Exam(
        title=payload.title.strip(),
        subject_id=payload.subject_id,
        teacher_id=teacher.id,
        duration_minutes=payload.duration_minutes,
        start_time=payload.start_time,
        end_time=payload.end_time,
        total_marks=payload.total_marks,
        instructions=payload.instructions,
        is_published=payload.is_published,
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)
    return _exam_out(db, exam)


@router.put("/exams/{exam_id}")
def update_exam(
    exam_id: int,
    payload: ExamIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("teacher")),
):
    teacher = _teacher_profile(db, user)
    exam = _exam_for_teacher(db, exam_id, teacher.id)
    _subject_for_teacher(db, payload.subject_id, teacher.id)
    exam.title = payload.title.strip()
    exam.subject_id = payload.subject_id
    exam.duration_minutes = payload.duration_minutes
    exam.start_time = payload.start_time
    exam.end_time = payload.end_time
    exam.total_marks = payload.total_marks
    exam.instructions = payload.instructions
    exam.is_published = payload.is_published
    db.commit()
    db.refresh(exam)
    return _exam_out(db, exam)


@router.post("/exams/{exam_id}/publish")
def publish_exam(
    exam_id: int,
    published: bool = Form(True),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("teacher")),
):
    teacher = _teacher_profile(db, user)
    exam = _exam_for_teacher(db, exam_id, teacher.id)
    exam.is_published = published
    db.commit()
    db.refresh(exam)
    return _exam_out(db, exam)


@router.delete("/exams/{exam_id}")
def delete_exam(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("teacher")),
):
    teacher = _teacher_profile(db, user)
    exam = _exam_for_teacher(db, exam_id, teacher.id)
    for image in db.query(QuestionImage).filter(QuestionImage.exam_id == exam.id).all():
        image_path = QUESTION_IMAGE_DIR / image.image_path
        if image_path.exists():
            image_path.unlink()
        db.delete(image)
    db.delete(exam)
    db.commit()
    return {"status": "deleted", "id": exam_id}


@router.get("/exams/{exam_id}/question-images", response_model=list[QuestionImageOut])
def list_question_images(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("teacher")),
):
    teacher = _teacher_profile(db, user)
    exam = _exam_for_teacher(db, exam_id, teacher.id)
    subject = db.query(Subject).filter(Subject.id == exam.subject_id).first()
    images = (
        db.query(QuestionImage)
        .filter(QuestionImage.exam_id == exam.id)
        .order_by(QuestionImage.question_number.asc(), QuestionImage.id.asc())
        .all()
    )
    return [_question_image_out(image, exam, subject) for image in images]


@router.post("/exams/{exam_id}/question-images", response_model=list[QuestionImageOut])
async def upload_question_images(
    exam_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("teacher")),
):
    teacher = _teacher_profile(db, user)
    exam = _exam_for_teacher(db, exam_id, teacher.id)
    subject = db.query(Subject).filter(Subject.id == exam.subject_id).first()
    QUESTION_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    current_max = (
        db.query(QuestionImage.question_number)
        .filter(QuestionImage.exam_id == exam.id)
        .order_by(QuestionImage.question_number.desc())
        .first()
    )
    next_number = (current_max[0] + 1) if current_max else 1
    saved: list[QuestionImage] = []
    for offset, file in enumerate(files):
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=422, detail=f"{file.filename or 'image'} is empty")
        content_type = _resolve_image_type(file, contents)
        stored_name = f"{uuid.uuid4().hex}{ALLOWED_IMAGE_TYPES[content_type]}"
        (QUESTION_IMAGE_DIR / stored_name).write_bytes(contents)
        image = QuestionImage(
            exam_id=exam.id,
            image_path=stored_name,
            original_filename=file.filename or "question-image",
            content_type=content_type,
            question_number=next_number + offset,
        )
        db.add(image)
        saved.append(image)
    db.commit()
    for image in saved:
        db.refresh(image)
    return [_question_image_out(image, exam, subject) for image in saved]


@router.delete("/question-images/{image_id}")
def delete_question_image(
    image_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("teacher")),
):
    teacher = _teacher_profile(db, user)
    image = db.query(QuestionImage).filter(QuestionImage.id == image_id).first()
    if image is None:
        raise HTTPException(status_code=404, detail="Question image not found")
    _exam_for_teacher(db, image.exam_id, teacher.id)
    image_path = QUESTION_IMAGE_DIR / image.image_path
    if image_path.exists():
        image_path.unlink()
    db.delete(image)
    db.commit()
    return {"status": "deleted", "id": image_id}


@router.get("/students", response_model=list[TeacherStudentOut])
def list_students(
    branch: str | None = None,
    division: str | None = None,
    semester: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("teacher")),
):
    query = (
        db.query(StudentProfile, User)
        .join(User, StudentProfile.user_id == User.id)
        .filter(User.role.in_(["candidate", "student"]))
    )
    if branch:
        query = query.filter(StudentProfile.branch == branch)
    if division:
        query = query.filter(StudentProfile.division == division)
    if semester:
        query = query.filter(StudentProfile.semester == semester)
    needle = (search or "").strip().lower()
    rows = []
    for profile, student in query.order_by(StudentProfile.full_name.asc()).all():
        if needle and needle not in f"{profile.full_name} {profile.prn} {student.username}".lower():
            continue
        rows.append(TeacherStudentOut(
            id=profile.id,
            user_id=student.id,
            username=student.username,
            email=student.email,
            full_name=profile.full_name,
            prn=profile.prn,
            branch=profile.branch,
            division=profile.division,
            semester=profile.semester,
            year=profile.year,
        ))
    return rows


@router.get("/results", response_model=list[ResultOut])
def list_results(
    subject_id: int | None = None,
    branch: str | None = None,
    division: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("teacher")),
):
    teacher = _teacher_profile(db, user)
    return _result_rows(db, teacher.id, subject_id, branch, division, search)


@router.get("/results/export")
def export_results(
    format: str = "csv",
    subject_id: int | None = None,
    branch: str | None = None,
    division: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("teacher")),
):
    teacher = _teacher_profile(db, user)
    rows = _result_rows(db, teacher.id, subject_id, branch, division, search)
    headers = [
        "student_name", "prn", "branch", "division", "semester", "year",
        "subject", "subject_code", "exam_title", "marks", "total_marks",
        "percentage", "submitted_at", "ai_suspicion_score", "violation_count", "status",
    ]
    if format.lower() in {"xls", "excel"}:
        table_rows = "".join(
            "<tr>" + "".join(f"<td>{html.escape(str(row.get(header, '')))}</td>" for header in headers) + "</tr>"
            for row in rows
        )
        table = "<table><thead><tr>" + "".join(f"<th>{header}</th>" for header in headers) + "</tr></thead><tbody>" + table_rows + "</tbody></table>"
        return Response(
            table,
            media_type="application/vnd.ms-excel",
            headers={"Content-Disposition": 'attachment; filename="exam-results.xls"'},
        )

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="exam-results.csv"'},
    )


@router.get("/violations", response_model=list[ViolationOut])
def list_violations(
    subject_id: int | None = None,
    branch: str | None = None,
    division: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("teacher")),
):
    teacher = _teacher_profile(db, user)
    exams = db.query(Exam).filter(Exam.teacher_id == teacher.id).all()
    if subject_id:
        exams = [exam for exam in exams if exam.subject_id == subject_id]
    exam_ids = [exam.id for exam in exams]
    if not exam_ids:
        return []
    exam_map = {exam.id: exam for exam in exams}
    subject_map = {
        subject.id: subject
        for subject in db.query(Subject).filter(Subject.id.in_({exam.subject_id for exam in exams})).all()
    }
    sessions = db.query(SessionModel).filter(SessionModel.exam_id.in_(exam_ids)).all()
    session_map = {session.session_id: session for session in sessions}
    users = {
        user.username: user
        for user in db.query(User).filter(User.username.in_({session.student_id for session in sessions})).all()
    }
    profiles = {
        profile.user_id: profile
        for profile in db.query(StudentProfile).filter(StudentProfile.user_id.in_({user.id for user in users.values()})).all()
    }
    needle = (search or "").strip().lower()
    rows: list[ViolationOut] = []
    for event in (
        db.query(Event)
        .filter(Event.session_id.in_(session_map.keys()))
        .order_by(Event.created_at.desc())
        .limit(500)
        .all()
    ):
        session = session_map.get(event.session_id)
        if session is None:
            continue
        student = users.get(session.student_id)
        profile = profiles.get(student.id) if student else None
        exam = exam_map.get(session.exam_id)
        subject = subject_map.get(exam.subject_id) if exam else None
        if branch and profile and profile.branch != branch:
            continue
        if division and profile and profile.division != division:
            continue
        student_name = profile.full_name if profile else session.student_name
        if needle and needle not in f"{student_name} {profile.prn if profile else ''} {event.event_type}".lower():
            continue
        rows.append(ViolationOut(
            id=event.id,
            session_id=event.session_id,
            student_name=student_name,
            prn=profile.prn if profile else "",
            branch=profile.branch if profile else "",
            division=profile.division if profile else "",
            subject=subject.subject_name if subject else session.subject,
            exam_title=exam.title if exam else session.exam_title,
            event_type=event.event_type,
            severity=event.severity,
            message=event.message,
            confidence=event.confidence,
            score_delta=event.score_delta,
            screenshot_url="",
            created_at=event.created_at,
        ))
    return rows
