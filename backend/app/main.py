from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from .database import engine
from .models import Base, Exam, Session as ExamSession, Subject, Teacher, User
from .routers import admin, auth, proctor, session, student, teacher
from .security import get_db, hash_password

app = FastAPI(
    title="ProctorAI Unified API",
    version="3.1.0",
    description="Single backend for local AI proctoring, Render deployment, auth, sessions, and admin monitoring.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def ensure_schema():
    additions = {
        "exam_id": "INTEGER",
        "subject": "VARCHAR DEFAULT 'GENERAL'",
        "side_camera_url": "VARCHAR DEFAULT ''",
        "side_camera_status": "VARCHAR DEFAULT 'UNKNOWN'",
        "approval_status": "VARCHAR DEFAULT 'NOT_REQUIRED'",
        "approval_note": "TEXT DEFAULT ''",
    }
    with engine.begin() as connection:
        existing = {column["name"] for column in inspect(connection).get_columns("sessions")}
        for column, definition in additions.items():
            if column not in existing:
                connection.execute(text(f"ALTER TABLE sessions ADD COLUMN {column} {definition}"))

def seed_users():
    defaults = [
        ("candidate", "candidate@exam.ai", "Candidate Demo", "candidate", "student123"),
        ("student", "student@exam.ai", "Student Demo", "candidate", "student123"),
        ("teacher", "teacher@exam.ai", "Faculty Demo", "teacher", "teacher123"),
        ("proctor", "proctor@exam.ai", "Proctor Demo", "proctor", "proctor123"),
        ("admin", "admin@proctor.ai", "Proctor Admin", "admin", "admin123"),
    ]
    db = Session(bind=engine)
    try:
        for username, email, full_name, role, password in defaults:
            exists = db.query(User).filter(User.username == username).first()
            if exists is None:
                db.add(User(
                    username=username,
                    email=email,
                    full_name=full_name,
                    role=role,
                    password_hash=hash_password(password),
                ))
        db.commit()

        teacher_user = db.query(User).filter(User.username == "teacher").first()
        if teacher_user is not None:
            teacher_profile = db.query(Teacher).filter(Teacher.user_id == teacher_user.id).first()
            if teacher_profile is None:
                teacher_profile = Teacher(
                    user_id=teacher_user.id,
                    full_name=teacher_user.full_name,
                    email=teacher_user.email,
                    password_hash=teacher_user.password_hash,
                    department="Computer Science",
                    employee_id="FAC-1001",
                )
                db.add(teacher_profile)
                db.commit()
                db.refresh(teacher_profile)

            if db.query(Subject).filter(Subject.created_by_teacher_id == teacher_profile.id).count() == 0:
                subjects = [
                    Subject(
                        subject_name="Computer Science 101",
                        subject_code="CS",
                        branch="CSE",
                        semester="1",
                        division="A",
                        created_by_teacher_id=teacher_profile.id,
                    ),
                    Subject(
                        subject_name="AI and Ethics",
                        subject_code="AI",
                        branch="CSE",
                        semester="1",
                        division="A",
                        created_by_teacher_id=teacher_profile.id,
                    ),
                    Subject(
                        subject_name="Digital Security",
                        subject_code="SEC",
                        branch="CSE",
                        semester="1",
                        division="A",
                        created_by_teacher_id=teacher_profile.id,
                    ),
                ]
                db.add_all(subjects)
                db.commit()
                for subject in subjects:
                    db.refresh(subject)
                db.add_all([
                    Exam(
                        title="Computer Science 101",
                        subject_id=subjects[0].id,
                        teacher_id=teacher_profile.id,
                        duration_minutes=60,
                        total_marks=100,
                        instructions="Answer all questions.",
                        is_published=True,
                    ),
                    Exam(
                        title="AI and Ethics",
                        subject_id=subjects[1].id,
                        teacher_id=teacher_profile.id,
                        duration_minutes=45,
                        total_marks=50,
                        instructions="Use concise answers.",
                        is_published=True,
                    ),
                    Exam(
                        title="Digital Security",
                        subject_id=subjects[2].id,
                        teacher_id=teacher_profile.id,
                        duration_minutes=30,
                        total_marks=50,
                        instructions="Do not leave the exam screen.",
                        is_published=True,
                    ),
                ])
                db.commit()
    finally:
        db.close()


app.include_router(auth.router)
app.include_router(session.router)
app.include_router(student.router)
app.include_router(proctor.router)
app.include_router(admin.router)
app.include_router(teacher.router)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    seed_users()


@app.get("/")
def root(db: Session = Depends(get_db)):
    active_sessions = db.query(ExamSession).filter(ExamSession.is_active == True).count()
    return {
        "status": "ProctorAI Unified API running",
        "version": "3.1.0",
        "active_sessions": active_sessions,
    }


@app.get("/health")
def health(db: Session = Depends(get_db)):
    active_sessions = db.query(ExamSession).filter(ExamSession.is_active == True).count()
    return {"status": "ok", "active_sessions": active_sessions}
