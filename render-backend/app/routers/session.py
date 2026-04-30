from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import ExamSession
from ..schemas import SessionStartRequest, SessionEndRequest

router = APIRouter(prefix="/session", tags=["Session"])


@router.post("/start")
def start_session(data: SessionStartRequest, db: Session = Depends(get_db)):
    """
    Called when a student begins an exam.
    Creates a new active session in the database.
    """
    # Check if session already exists
    existing = db.query(ExamSession).filter(
        ExamSession.session_id == data.session_id
    ).first()

    if existing:
        # Re-activate if it was ended
        existing.is_active = True
        existing.is_cheating = False
        existing.cheat_message = "Starting..."
        existing.student_name = data.student_name
        existing.exam_title = data.exam_title
        db.commit()
        return {"status": "session restarted", "session_id": data.session_id}

    session = ExamSession(
        session_id=data.session_id,
        student_id=data.student_id,
        student_name=data.student_name,
        exam_title=data.exam_title,
        is_active=True,
        is_cheating=False,
        cheat_message="Starting...",
    )
    db.add(session)
    db.commit()

    return {"status": "session started", "session_id": data.session_id}


@router.post("/end")
def end_session(data: SessionEndRequest, db: Session = Depends(get_db)):
    """Called when a student submits their exam."""
    session = db.query(ExamSession).filter(
        ExamSession.session_id == data.session_id
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.is_active = False
    session.is_cheating = False
    session.cheat_message = "Exam submitted"
    db.commit()

    return {"status": "session ended"}
