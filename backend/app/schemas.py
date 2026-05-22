from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)
    role: str
    remember_me: bool = False


class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2)
    email: EmailStr
    password: str = Field(..., min_length=6)
    role: str = "student"
    username: Optional[str] = None


class UserOut(BaseModel):
    id: int
    username: str
    email: EmailStr
    full_name: str
    role: str

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class SessionStartRequest(BaseModel):
    session_id: str
    exam_id: Optional[int] = None
    student_id: str
    student_name: str = "Candidate"
    exam_title: str = "Secure Exam"
    subject: str = "GENERAL"
    side_camera_url: str


class DetectionResponse(BaseModel):
    session_id: str
    cheating: bool
    message: str
    cheat_type: str = ""
    confidence: float = 0.0
    cheat_score: float = 0.0
    risk_level: str = "LOW"
    status: str = "CLEAR"
    warning_count: int = 0
    candidate_status: str = "CLEAR"
    side_camera_status: str = "UNKNOWN"
    events: List[Dict[str, Any]] = Field(default_factory=list)


class StudentMonitoringResponse(BaseModel):
    type: str = "monitoring"
    session_id: str
    student_id: str
    student_name: str
    subject: str
    exam_title: str
    side_camera_status: str = "UNKNOWN"
    is_active: bool
    is_submitted: bool
    is_terminated: bool
    status: str = "MONITORING"
    candidate_status: str = "MONITORING"
    approval_status: str = "NOT_REQUIRED"
    approval_note: str = ""

    class Config:
        from_attributes = True


class ProctorUpdateRequest(BaseModel):
    session_id: str
    cheating: bool
    cheat_type: str = ""
    message: str = "Clear"
    cheat_score_delta: float = 0.0


class SideCameraValidationRequest(BaseModel):
    camera_input: Optional[str] = None
    side_camera_url: Optional[str] = None


class SideCameraValidationResponse(BaseModel):
    success: bool
    message: str
    side_camera_url: str = ""
    resolved_url: str = ""
    stream_type: str = "UNKNOWN"
    state: str = "STREAM_FAILED"


class ProctorSimpleResponse(BaseModel):
    cheating: bool
    message: str


class ClientEventRequest(BaseModel):
    event_type: str
    message: str
    severity: str = "INFO"
    score_delta: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SubmitExamRequest(BaseModel):
    answers: Dict[str, str]
    reason: str = "submitted_by_candidate"


class AutosaveAnswersRequest(BaseModel):
    answers: Dict[str, str] = Field(default_factory=dict)


class StudentProfileIn(BaseModel):
    full_name: str = Field(..., min_length=2)
    prn: str = Field(..., min_length=2)
    branch: str = Field(..., min_length=1)
    division: str = Field(..., min_length=1)
    semester: str = Field(..., min_length=1)
    year: str = Field(..., min_length=1)


class StudentProfileOut(BaseModel):
    id: int
    user_id: int
    full_name: str
    prn: str
    branch: str
    division: str
    semester: str
    year: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class SubjectIn(BaseModel):
    subject_name: str = Field(..., min_length=2)
    subject_code: str = Field(..., min_length=1)
    branch: str = Field(..., min_length=1)
    semester: str = Field(..., min_length=1)
    division: str = Field(..., min_length=1)


class SubjectOut(BaseModel):
    id: int
    subject_name: str
    subject_code: str
    branch: str
    semester: str
    division: str
    created_by_teacher_id: int
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class ExamIn(BaseModel):
    title: str = Field(..., min_length=2)
    description: str = ""
    subject_id: int
    duration_minutes: int = Field(60, ge=1)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_marks: float = Field(100.0, ge=0)
    instructions: str = ""
    question_image_enabled: bool = True
    is_published: bool = False


class ExamOut(BaseModel):
    id: int
    title: str
    description: str = ""
    subject_id: int
    teacher_id: int
    duration_minutes: int
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    total_marks: float
    instructions: str
    question_image_enabled: bool = True
    is_published: bool
    created_at: Optional[datetime]
    subject_name: str = ""
    subject_code: str = ""
    branch: str = ""
    division: str = ""
    semester: str = ""
    question_count: int = 0

    class Config:
        from_attributes = True


class QuestionIn(BaseModel):
    question_text: str = Field(..., min_length=1)
    option_a: str = Field(..., min_length=1)
    option_b: str = Field(..., min_length=1)
    option_c: str = Field(..., min_length=1)
    option_d: str = Field(..., min_length=1)
    correct_option: str = Field(..., pattern="^[ABCDabcd]$")
    marks: float = Field(1.0, gt=0)
    explanation: str = ""


class QuestionOrderRequest(BaseModel):
    question_ids: List[int] = Field(default_factory=list)


class QuestionOut(BaseModel):
    id: int
    exam_id: int
    question_text: str
    question_image: str = ""
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_option: str
    marks: float
    explanation: str = ""
    sort_order: int = 0
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class StudentQuestionOut(BaseModel):
    id: int
    exam_id: int
    question_text: str
    image_url: str = ""
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    marks: float
    sort_order: int = 0


class AttemptResultAnswerOut(BaseModel):
    question_id: int
    question_text: str
    selected_option: str = ""
    correct_option: str
    is_correct: bool
    marks_awarded: float
    marks: float
    explanation: str = ""


class StudentResultOut(BaseModel):
    attempt_id: int
    exam_id: int
    exam_title: str
    score: float
    total_marks: float
    percentage: float
    submitted_at: Optional[datetime]
    answers: List[AttemptResultAnswerOut] = Field(default_factory=list)


class QuestionImageOut(BaseModel):
    id: int
    exam_id: Optional[int] = None
    subject: str = ""
    exam_title: str = ""
    original_filename: str = ""
    content_type: str = "image/png"
    sort_order: int = 0
    question_number: int = 0
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class TeacherStudentOut(BaseModel):
    id: int
    user_id: int
    username: str
    email: str
    full_name: str
    prn: str
    branch: str
    division: str
    semester: str
    year: str


class ResultOut(BaseModel):
    id: int
    student_id: int
    exam_id: int
    student_name: str
    prn: str
    branch: str
    division: str
    semester: str
    year: str
    subject: str
    subject_code: str
    exam_title: str
    marks: float
    total_marks: float
    percentage: float
    submitted_at: Optional[datetime]
    ai_suspicion_score: float
    violation_count: int
    status: str


class ViolationOut(BaseModel):
    id: int
    session_id: str
    student_name: str
    prn: str = ""
    branch: str = ""
    division: str = ""
    subject: str = ""
    exam_title: str = ""
    event_type: str
    severity: str
    message: str
    confidence: float
    score_delta: float
    screenshot_url: str = ""
    created_at: Optional[datetime]


class TeacherDashboardStats(BaseModel):
    subjects: int
    exams: int
    published_exams: int
    students: int
    results: int
    violations: int


class SessionOut(BaseModel):
    session_id: str
    exam_id: Optional[int] = None
    student_id: str
    student_name: str
    subject: str
    exam_title: str
    side_camera_url: str
    side_camera_status: str
    is_active: bool
    is_submitted: bool
    is_terminated: bool
    is_cheating: bool
    status: str
    risk_level: str
    cheat_type: str
    cheat_message: str
    cheat_count: int
    warning_count: int
    tab_switch_count: int
    disconnect_count: int
    confidence: float
    cheat_score: float
    approval_status: str
    approval_note: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    submitted_at: Optional[datetime]

    class Config:
        from_attributes = True


class EventOut(BaseModel):
    id: int
    session_id: str
    event_type: str
    severity: str
    message: str
    confidence: float
    score_delta: float
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime]


class DashboardStats(BaseModel):
    total_active: int
    total_cheating: int
    total_high_risk: int
    total_submitted: int
    total_events: int
