from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    prn = Column(String, default="", index=True)
    branch = Column(String, default="", index=True)
    division = Column(String, default="", index=True)
    year = Column(String, default="", index=True)
    subject_specialization = Column(String, default="")
    profile_completed = Column(Boolean, default=False, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Session(Base):
    __tablename__ = "sessions"

    session_id = Column(String, primary_key=True, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id"), nullable=True, index=True)
    student_id = Column(String, index=True)
    student_name = Column(String, default="Candidate")
    subject = Column(String, default="GENERAL", index=True)
    exam_title = Column(String, default="Secure Exam")
    side_camera_url = Column(String, default="")
    side_camera_status = Column(String, default="UNKNOWN")
    is_active = Column(Boolean, default=True)
    is_submitted = Column(Boolean, default=False)
    is_terminated = Column(Boolean, default=False)
    is_cheating = Column(Boolean, default=False)
    status = Column(String, default="STARTING")
    risk_level = Column(String, default="LOW")
    cheat_type = Column(String, default="")
    cheat_message = Column(String, default="AI monitoring active")
    cheat_count = Column(Integer, default=0)
    warning_count = Column(Integer, default=0)
    tab_switch_count = Column(Integer, default=0)
    disconnect_count = Column(Integer, default=0)
    confidence = Column(Float, default=0.0)
    cheat_score = Column(Float, default=0.0)
    approval_status = Column(String, default="NOT_REQUIRED")
    approval_note = Column(Text, default="")
    answers_json = Column(Text, default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    submitted_at = Column(DateTime(timezone=True), nullable=True)


class Teacher(Base):
    __tablename__ = "teachers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=True, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    department = Column(String, default="")
    employee_id = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False, index=True)
    prn = Column(String, unique=True, index=True, nullable=False)
    branch = Column(String, default="", index=True)
    division = Column(String, default="", index=True)
    semester = Column(String, default="", index=True)
    year = Column(String, default="", index=True)
    full_name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Subject(Base):
    __tablename__ = "subjects"

    id = Column(Integer, primary_key=True, index=True)
    subject_name = Column(String, nullable=False)
    subject_code = Column(String, index=True, nullable=False)
    branch = Column(String, default="", index=True)
    semester = Column(String, default="", index=True)
    division = Column(String, default="", index=True)
    created_by_teacher_id = Column(Integer, ForeignKey("teachers.id"), index=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Exam(Base):
    __tablename__ = "exams"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False, index=True)
    description = Column(Text, default="")
    subject_id = Column(Integer, ForeignKey("subjects.id"), index=True, nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), index=True, nullable=False)
    duration_minutes = Column(Integer, default=60)
    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    total_marks = Column(Float, default=100.0)
    instructions = Column(Text, default="")
    question_image_enabled = Column(Boolean, default=True)
    is_published = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class QuestionImage(Base):
    __tablename__ = "question_images"

    id = Column(Integer, primary_key=True, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id"), index=True, nullable=False)
    image_path = Column(String, nullable=False)
    original_filename = Column(String, default="")
    content_type = Column(String, default="image/png")
    question_number = Column(Integer, default=1, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id"), index=True, nullable=False)
    question_text = Column(Text, nullable=False)
    question_image = Column(String, default="")
    option_a = Column(Text, nullable=False)
    option_b = Column(Text, nullable=False)
    option_c = Column(Text, nullable=False)
    option_d = Column(Text, nullable=False)
    correct_option = Column(String, nullable=False)
    marks = Column(Float, default=1.0)
    explanation = Column(Text, default="")
    sort_order = Column(Integer, default=0, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ExamAttempt(Base):
    __tablename__ = "exam_attempts"

    id = Column(Integer, primary_key=True, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id"), index=True, nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=True, index=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    auto_submitted = Column(Boolean, default=False)
    score = Column(Float, default=0.0)
    tab_switch_count = Column(Integer, default=0)
    suspicious_events = Column(Integer, default=0)
    ai_risk_level = Column(String, default="LOW")
    front_camera_ok = Column(Boolean, default=False)
    side_camera_ok = Column(Boolean, default=False)
    status = Column(String, default="IN_PROGRESS", index=True)
    autosave_json = Column(Text, default="{}")


class Answer(Base):
    __tablename__ = "answers"

    id = Column(Integer, primary_key=True, index=True)
    attempt_id = Column(Integer, ForeignKey("exam_attempts.id"), index=True, nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id"), index=True, nullable=False)
    selected_option = Column(String, default="")
    is_correct = Column(Boolean, default=False)
    marks_awarded = Column(Float, default=0.0)
    saved_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProctorLog(Base):
    __tablename__ = "proctor_logs"

    id = Column(Integer, primary_key=True, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id"), nullable=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    event_type = Column(String, index=True)
    event_details = Column(Text, default="")
    ai_score = Column(Float, default=0.0)


class Result(Base):
    __tablename__ = "results"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    exam_id = Column(Integer, ForeignKey("exams.id"), index=True, nullable=False)
    score = Column(Float, default=0.0)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    ai_suspicion_score = Column(Float, default=0.0)
    violation_count = Column(Integer, default=0)
    status = Column(String, default="SUBMITTED", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ExamQuestionImage(Base):
    __tablename__ = "exam_question_images"

    id = Column(Integer, primary_key=True, index=True)
    subject = Column(String, default="GENERAL", index=True)
    exam_title = Column(String, default="Secure Exam", index=True)
    original_filename = Column(String, default="")
    stored_filename = Column(String, nullable=False)
    content_type = Column(String, default="image/png")
    sort_order = Column(Integer, default=0, index=True)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), index=True)
    event_type = Column(String, index=True)
    severity = Column(String, default="INFO")
    message = Column(String)
    confidence = Column(Float, default=0.0)
    score_delta = Column(Float, default=0.0)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
