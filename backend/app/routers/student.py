import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import Exam, ExamAttempt, Question, QuestionImage, Result, StudentProfile, Subject, User
from ..schemas import StudentProfileIn, StudentProfileOut
from ..security import get_current_user, get_db, require_role

router = APIRouter(prefix="/student", tags=["student"])
logger = logging.getLogger(__name__)


def _profile_complete(profile: StudentProfile | None) -> bool:
    if profile is None:
        return False
    return all([
        profile.full_name.strip(),
        profile.prn.strip(),
        profile.branch.strip(),
        profile.division.strip(),
        profile.semester.strip(),
        profile.year.strip(),
    ])


def _profile_payload(profile: StudentProfile | None, user: User) -> dict:
    if profile is None:
        return {
            "complete": False,
            "user_id": user.id,
            "full_name": user.full_name,
            "prn": "",
            "branch": "",
            "division": "",
            "semester": "",
            "year": "",
        }
    data = StudentProfileOut.model_validate(profile).model_dump(mode="json")
    data["complete"] = _profile_complete(profile)
    return data


@router.get("/profile")
def get_profile(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("candidate", "student")),
):
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == user.id).first()
    return _profile_payload(profile, user)


@router.put("/profile")
def update_profile(
    payload: StudentProfileIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("candidate", "student")),
):
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == user.id).first()
    if profile is None:
        profile = StudentProfile(
            user_id=user.id,
            full_name=payload.full_name.strip(),
            prn=payload.prn.strip().upper(),
            branch=payload.branch.strip().upper(),
            division=payload.division.strip().upper(),
            semester=payload.semester.strip(),
            year=payload.year.strip(),
        )
        db.add(profile)
    else:
        profile.full_name = payload.full_name.strip()
        profile.prn = payload.prn.strip().upper()
        profile.branch = payload.branch.strip().upper()
        profile.division = payload.division.strip().upper()
        profile.semester = payload.semester.strip()
        profile.year = payload.year.strip()
    user.full_name = payload.full_name.strip()
    user.prn = profile.prn
    user.branch = profile.branch
    user.division = profile.division
    user.year = profile.year
    user.profile_completed = _profile_complete(profile)
    db.commit()
    db.refresh(profile)
    return _profile_payload(profile, user)


@router.get("/exams")
def available_exams(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("candidate", "student")),
):
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == user.id).first()
    if not _profile_complete(profile):
        raise HTTPException(status_code=409, detail="Complete student profile before joining exams")

    now = datetime.now(timezone.utc)
    rows = (
        db.query(Exam, Subject)
        .join(Subject, Exam.subject_id == Subject.id)
        .filter(Exam.is_published.is_(True))
        .filter(or_(Exam.end_time.is_(None), Exam.end_time > now))
        .order_by(Exam.created_at.desc())
        .all()
    )
    logger.info(
        "Student exams fetched; user_id=%s profile=%s/%s/%s rows=%s",
        user.id,
        profile.branch,
        profile.division,
        profile.semester,
        len(rows),
    )
    exams = []
    for exam, subject in rows:
        if subject.branch and subject.branch != profile.branch:
            continue
        if subject.division and subject.division != profile.division:
            continue
        if subject.semester and subject.semester != profile.semester:
            continue
        attempt = (
            db.query(ExamAttempt)
            .filter(ExamAttempt.exam_id == exam.id, ExamAttempt.student_id == user.id)
            .order_by(ExamAttempt.started_at.desc())
            .first()
        )
        result = db.query(Result).filter(Result.exam_id == exam.id, Result.student_id == user.id).first()
        question_count = db.query(Question).filter(Question.exam_id == exam.id).count()
        if question_count == 0:
            question_count = db.query(QuestionImage).filter(QuestionImage.exam_id == exam.id).count()
        exams.append({
            "id": exam.id,
            "title": exam.title,
            "subject_id": subject.id,
            "subject": subject.subject_code,
            "subject_name": subject.subject_name,
            "branch": subject.branch,
            "division": subject.division,
            "semester": subject.semester,
            "duration_minutes": exam.duration_minutes,
            "total_marks": exam.total_marks,
            "instructions": exam.instructions,
            "start_time": exam.start_time,
            "end_time": exam.end_time,
            "question_count": question_count,
            "attempt_status": attempt.status if attempt else "NOT_STARTED",
            "score": result.score if result else None,
            "completed": result is not None,
        })
    return exams
