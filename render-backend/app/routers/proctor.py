from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import ExamSession, CheatEvent
from ..schemas import ProctorUpdateRequest, ProctorResponse
from .admin import manager

router = APIRouter(prefix="/proctor", tags=["Proctor"])


def _compute_risk_level(score: float) -> str:
    """Map cumulative cheat score to a human-readable risk level."""
    if score >= 200:
        return "CRITICAL"
    elif score >= 100:
        return "HIGH"
    elif score >= 40:
        return "MEDIUM"
    return "LOW"


@router.post("/update", response_model=ProctorResponse)
async def proctor_update(data: ProctorUpdateRequest, db: Session = Depends(get_db)):
    """
    Called by the LOCAL AI server (server.py) after processing a frame.
    This endpoint receives the detection result and:
      1. Updates the session in PostgreSQL
      2. Logs a CheatEvent if cheating was detected
      3. Broadcasts the update to all connected admin WebSockets
    """
    session = db.query(ExamSession).filter(
        ExamSession.session_id == data.session_id
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # ── Update session state ──
    session.is_cheating = data.cheating
    session.cheat_message = data.message or "Clear"
    session.cheat_type = data.cheat_type or ""

    if data.cheating:
        session.cheat_count += 1
        session.cheat_score += (data.cheat_score_delta or 10.0)
        session.risk_level = _compute_risk_level(session.cheat_score)

        # Log the event
        event = CheatEvent(
            session_id=data.session_id,
            event_type=data.cheat_type or "UNKNOWN",
            detail=data.message or "",
        )
        db.add(event)
    else:
        session.cheat_type = ""

    db.commit()
    db.refresh(session)

    # ── Broadcast to all admin WebSocket clients ──
    await manager.broadcast({
        "session_id": session.session_id,
        "student_id": session.student_id,
        "student_name": session.student_name,
        "exam_title": session.exam_title,
        "is_active": session.is_active,
        "is_cheating": session.is_cheating,
        "cheat_type": session.cheat_type,
        "cheat_message": session.cheat_message,
        "cheat_count": session.cheat_count,
        "cheat_score": session.cheat_score,
        "risk_level": session.risk_level,
        "last_seen_at": session.last_seen_at.isoformat() if session.last_seen_at else "",
    })

    return ProctorResponse(cheating=data.cheating, message=session.cheat_message)
