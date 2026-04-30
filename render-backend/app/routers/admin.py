from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from ..models import ExamSession, CheatEvent

router = APIRouter(tags=["Admin"])


# ═══════════════════════════════════════════════
# WEBSOCKET CONNECTION MANAGER
# ═══════════════════════════════════════════════

class ConnectionManager:
    """Manages WebSocket connections for all admin dashboard clients."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Send data to every connected admin dashboard."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)


manager = ConnectionManager()


# ═══════════════════════════════════════════════
# WEBSOCKET ENDPOINT
# ═══════════════════════════════════════════════

@router.websocket("/ws/admin")
async def admin_websocket(websocket: WebSocket):
    """
    Admin dashboard connects here for real-time updates.
    On connect, it receives the full list of active sessions immediately.
    Then it receives incremental updates as students are proctored.
    """
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; client can send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ═══════════════════════════════════════════════
# REST ENDPOINTS FOR ADMIN
# ═══════════════════════════════════════════════

@router.get("/admin/sessions")
def get_all_sessions(db: Session = Depends(get_db)):
    """
    Returns ALL active exam sessions.
    Sorted: cheating students FIRST, then by cheat_score descending.
    """
    sessions = db.query(ExamSession).filter(
        ExamSession.is_active == True
    ).order_by(
        ExamSession.is_cheating.desc(),    # cheating → top
        ExamSession.cheat_score.desc(),    # highest risk → top
        ExamSession.started_at.asc(),      # oldest first within same group
    ).all()

    result = []
    for s in sessions:
        result.append({
            "session_id": s.session_id,
            "student_id": s.student_id,
            "student_name": s.student_name,
            "exam_title": s.exam_title,
            "is_active": s.is_active,
            "is_cheating": s.is_cheating,
            "cheat_type": s.cheat_type,
            "cheat_message": s.cheat_message,
            "cheat_count": s.cheat_count,
            "cheat_score": s.cheat_score,
            "risk_level": s.risk_level,
            "started_at": s.started_at.isoformat() if s.started_at else "",
            "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else "",
        })

    return result


@router.get("/admin/sessions/{session_id}")
def get_session_detail(session_id: str, db: Session = Depends(get_db)):
    """Get detailed info + cheat events for a single student."""
    session = db.query(ExamSession).filter(
        ExamSession.session_id == session_id
    ).first()

    if not session:
        return {"error": "Session not found"}

    events = db.query(CheatEvent).filter(
        CheatEvent.session_id == session_id
    ).order_by(CheatEvent.timestamp.desc()).limit(50).all()

    return {
        "session": {
            "session_id": session.session_id,
            "student_id": session.student_id,
            "student_name": session.student_name,
            "exam_title": session.exam_title,
            "is_cheating": session.is_cheating,
            "cheat_type": session.cheat_type,
            "cheat_message": session.cheat_message,
            "cheat_count": session.cheat_count,
            "cheat_score": session.cheat_score,
            "risk_level": session.risk_level,
        },
        "events": [
            {
                "event_type": e.event_type,
                "detail": e.detail,
                "timestamp": e.timestamp.isoformat() if e.timestamp else "",
            }
            for e in events
        ],
    }


@router.get("/admin/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    """Quick stats for the admin dashboard header."""
    total_active = db.query(ExamSession).filter(ExamSession.is_active == True).count()
    total_cheating = db.query(ExamSession).filter(
        ExamSession.is_active == True,
        ExamSession.is_cheating == True
    ).count()
    total_high_risk = db.query(ExamSession).filter(
        ExamSession.is_active == True,
        ExamSession.risk_level.in_(["HIGH", "CRITICAL"])
    ).count()

    return {
        "total_active": total_active,
        "total_cheating": total_cheating,
        "total_high_risk": total_high_risk,
    }
