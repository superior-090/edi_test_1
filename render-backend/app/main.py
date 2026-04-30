from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import engine, get_db
from .models import Base
from .schemas import HealthResponse
from .routers import session, proctor, admin
from sqlalchemy.orm import Session
from fastapi import Depends

# ═══════════════════════════════════════════════
# CREATE TABLES ON STARTUP
# ═══════════════════════════════════════════════
Base.metadata.create_all(bind=engine)

# ═══════════════════════════════════════════════
# APP SETUP
# ═══════════════════════════════════════════════
app = FastAPI(
    title="ProctorAI Cloud API",
    version="2.0",
    description="Cloud backend for the EYE-q AI proctoring system. Deployed on Render.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════
# INCLUDE ROUTERS
# ═══════════════════════════════════════════════
app.include_router(session.router)
app.include_router(proctor.router)
app.include_router(admin.router)


# ═══════════════════════════════════════════════
# HEALTH CHECK (Render uses this for uptime)
# ═══════════════════════════════════════════════
@app.get("/", response_model=HealthResponse)
def root(db: Session = Depends(get_db)):
    from .models import ExamSession
    count = db.query(ExamSession).filter(ExamSession.is_active == True).count()
    return {"status": "ProctorAI Cloud API running", "active_sessions": count}


@app.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)):
    from .models import ExamSession
    count = db.query(ExamSession).filter(ExamSession.is_active == True).count()
    return {"status": "ok", "active_sessions": count}
