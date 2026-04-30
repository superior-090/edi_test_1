from sqlalchemy import Column, String, Boolean, Integer, Float, DateTime, Text
from sqlalchemy.sql import func
from .database import Base


class ExamSession(Base):
    """
    Tracks every student currently taking an exam.
    Updated in real-time by the local AI proctoring server.
    """
    __tablename__ = "exam_sessions"

    session_id = Column(String, primary_key=True, index=True)
    student_id = Column(String, nullable=False, index=True)
    student_name = Column(String, default="Unknown")
    exam_title = Column(String, default="General Exam")

    # ── Live proctoring state ──
    is_active = Column(Boolean, default=True)
    is_cheating = Column(Boolean, default=False)
    cheat_type = Column(String, default="")        # "phone", "multi_face", "gaze_away", etc.
    cheat_message = Column(String, default="Clear")
    cheat_count = Column(Integer, default=0)        # total cheat events
    cheat_score = Column(Float, default=0.0)        # cumulative risk score
    risk_level = Column(String, default="LOW")      # LOW / MEDIUM / HIGH / CRITICAL

    # ── Timestamps ──
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CheatEvent(Base):
    """
    Individual cheat events logged over time for audit trail.
    """
    __tablename__ = "cheat_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, nullable=False, index=True)
    event_type = Column(String, nullable=False)     # PHONE, MULTI_FACE, GAZE_AWAY, etc.
    detail = Column(Text, default="")
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
