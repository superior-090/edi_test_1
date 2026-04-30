from pydantic import BaseModel
from typing import Optional
from datetime import datetime


# ═══════════════════════════════════════════════
# REQUEST SCHEMAS
# ═══════════════════════════════════════════════

class SessionStartRequest(BaseModel):
    session_id: str
    student_id: str
    student_name: Optional[str] = "Unknown"
    exam_title: Optional[str] = "General Exam"


class ProctorUpdateRequest(BaseModel):
    """Sent by the local AI server after analysing a frame."""
    session_id: str
    cheating: bool
    cheat_type: Optional[str] = ""
    message: Optional[str] = "Clear"
    cheat_score_delta: Optional[float] = 0.0


class SessionEndRequest(BaseModel):
    session_id: str


# ═══════════════════════════════════════════════
# RESPONSE SCHEMAS
# ═══════════════════════════════════════════════

class SessionResponse(BaseModel):
    session_id: str
    student_id: str
    student_name: str
    exam_title: str
    is_active: bool
    is_cheating: bool
    cheat_type: str
    cheat_message: str
    cheat_count: int
    cheat_score: float
    risk_level: str
    started_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProctorResponse(BaseModel):
    cheating: bool
    message: str


class HealthResponse(BaseModel):
    status: str
    active_sessions: int
