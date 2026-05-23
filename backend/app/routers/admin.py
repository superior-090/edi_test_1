import asyncio
import base64
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from jose import JWTError
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Event, ExamQuestionImage, Session as SessionModel, User
from ..role_filter import admin_session_payload, broadcast_monitoring_update
from ..schemas import DashboardStats, EventOut, QuestionImageOut, SessionOut
from ..security import decode_token_without_db, get_db, require_role
from ..services.side_camera import get_latest_side_camera_frame
from ..state import (
    latest_annotated_frames,
    latest_frames,
    latest_side_annotated_frames,
    latest_side_frames,
    manager,
    store_frame,
)

router = APIRouter(tags=["admin"])
logger = logging.getLogger(__name__)
QUESTION_IMAGE_DIR = Path(__file__).resolve().parents[2] / "uploads" / "question_images"
ALLOWED_QUESTION_IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg"}


def _cv2():
    import cv2

    return cv2


def _current_session_filter():
    recent_cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    return or_(
        (
            (SessionModel.is_active == True)
            & (SessionModel.is_submitted == False)
            & (SessionModel.is_terminated == False)
            & (SessionModel.updated_at >= recent_cutoff)
        ),
        SessionModel.approval_status == "PENDING",
    )


def _serialize_event(event: Event) -> dict:
    return EventOut(
        id=event.id,
        session_id=event.session_id,
        event_type=event.event_type,
        severity=event.severity,
        message=event.message,
        confidence=event.confidence,
        score_delta=event.score_delta,
        metadata=json.loads(event.metadata_json or "{}"),
        created_at=event.created_at,
    ).model_dump(mode="json")


def _question_image_path(stored_filename: str) -> Path:
    return QUESTION_IMAGE_DIR / stored_filename


def _serialize_question_image(image: ExamQuestionImage) -> dict:
    return QuestionImageOut.model_validate(image).model_dump(mode="json")


def _normalize_exam_title(value: str) -> str:
    normalized = " ".join(value.strip().split())
    if not normalized:
        raise HTTPException(status_code=422, detail="exam_title is required")
    return normalized


@router.get("/admin/sessions", response_model=list[SessionOut])
def get_sessions(
    subject: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "proctor")),
):
    query = db.query(SessionModel).filter(_current_session_filter())
    if subject and subject.upper() != "ALL":
        query = query.filter(SessionModel.subject == subject)
    return query.order_by(SessionModel.updated_at.desc()).all()


@router.get("/admin/sessions/{session_id}")
def get_session_detail(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "proctor")),
):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    events = (
        db.query(Event)
        .filter(Event.session_id == session_id)
        .order_by(Event.created_at.desc())
        .limit(50)
        .all()
    )

    return {
        "session": SessionOut.model_validate(session).model_dump(mode="json"),
        "events": [_serialize_event(event) for event in events],
    }


@router.get("/admin/stats", response_model=DashboardStats)
def stats(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "proctor")),
):
    sessions = (
        db.query(SessionModel)
        .filter(_current_session_filter())
        .all()
    )
    session_ids = [item.session_id for item in sessions]
    events_count = db.query(Event).filter(Event.session_id.in_(session_ids)).count() if session_ids else 0
    return DashboardStats(
        total_active=sum(1 for item in sessions if item.is_active),
        total_cheating=sum(1 for item in sessions if item.is_active and item.is_cheating),
        total_high_risk=sum(1 for item in sessions if item.risk_level in ("HIGH", "CRITICAL")),
        total_submitted=0,
        total_events=events_count,
    )


@router.get("/admin/question-images", response_model=list[QuestionImageOut])
def list_question_images(
    subject: str | None = None,
    exam_title: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    query = db.query(ExamQuestionImage).filter(ExamQuestionImage.is_active == True)
    if subject and subject.upper() != "ALL":
        query = query.filter(ExamQuestionImage.subject == subject.upper())
    if exam_title:
        query = query.filter(ExamQuestionImage.exam_title == _normalize_exam_title(exam_title))
    return query.order_by(
        ExamQuestionImage.subject.asc(),
        ExamQuestionImage.exam_title.asc(),
        ExamQuestionImage.sort_order.asc(),
        ExamQuestionImage.id.asc(),
    ).all()


@router.post("/admin/question-images", response_model=QuestionImageOut)
async def upload_question_image(
    subject: str = Form("GENERAL"),
    exam_title: str = Form(...),
    sort_order: int | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_QUESTION_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Upload a PNG or JPG question image")

    normalized_subject = subject.strip().upper() or "GENERAL"
    normalized_exam_title = _normalize_exam_title(exam_title)
    if sort_order is None:
        current_max = (
            db.query(ExamQuestionImage.sort_order)
            .filter(
                ExamQuestionImage.subject == normalized_subject,
                ExamQuestionImage.exam_title == normalized_exam_title,
                ExamQuestionImage.is_active == True,
            )
            .order_by(ExamQuestionImage.sort_order.desc())
            .first()
        )
        sort_order = (current_max[0] + 1) if current_max else 1

    extension = ALLOWED_QUESTION_IMAGE_TYPES[content_type]
    stored_filename = f"{uuid.uuid4().hex}{extension}"
    QUESTION_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=422, detail="Uploaded image is empty")
    _question_image_path(stored_filename).write_bytes(contents)

    image = ExamQuestionImage(
        subject=normalized_subject,
        exam_title=normalized_exam_title,
        original_filename=file.filename or "question-image",
        stored_filename=stored_filename,
        content_type=content_type,
        sort_order=sort_order,
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    return image


@router.delete("/admin/question-images/{image_id}")
def delete_question_image(
    image_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    image = db.query(ExamQuestionImage).filter(ExamQuestionImage.id == image_id).first()
    if image is None:
        raise HTTPException(status_code=404, detail="Question image not found")
    image.is_active = False
    db.commit()
    return {"status": "deleted", "id": image_id}


@router.get("/admin/events", response_model=list[EventOut])
def events(
    limit: int = 80,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "proctor")),
):
    active_session_ids = [
        row.session_id
        for row in db.query(SessionModel.session_id)
        .filter(_current_session_filter())
        .all()
    ]
    if not active_session_ids:
        return []
    rows = (
        db.query(Event)
        .filter(Event.session_id.in_(active_session_ids))
        .order_by(Event.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_serialize_event(row) for row in rows]


@router.post("/admin/session/{session_id}/terminate", response_model=SessionOut)
async def terminate_session(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "proctor")),
):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session.is_active = False
    session.is_terminated = True
    session.status = "TERMINATED"
    event = Event(
        session_id=session_id,
        event_type="TERMINATED",
        severity="CRITICAL",
        message="Exam session terminated by proctor",
        score_delta=0,
    )
    db.add(event)
    db.commit()
    db.refresh(session)
    await broadcast_monitoring_update(manager, session, "terminated")
    return session


@router.post("/admin/session/{session_id}/flag", response_model=SessionOut)
async def flag_session(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "proctor")),
):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session.cheat_score = min(100, session.cheat_score + 20)
    session.warning_count += 1
    session.risk_level = "HIGH" if session.cheat_score >= 55 else "MEDIUM"
    session.status = "FLAGGED"
    session.cheat_message = "Flagged manually by proctor"
    db.add(Event(
        session_id=session_id,
        event_type="MANUAL_FLAG",
        severity="HIGH",
        message="Flagged manually by proctor",
        score_delta=20,
    ))
    db.commit()
    db.refresh(session)
    await broadcast_monitoring_update(manager, session, "manual_flag")
    return session


import asyncio

def _stream(session_id: str):
    async def generator():
        while True:
            frame = latest_annotated_frames.get(session_id) or latest_frames.get(session_id)
            if frame:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            await asyncio.sleep(0.25)
    return generator()


@router.get("/admin/stream/{session_id}")
def stream(session_id: str):
    return StreamingResponse(_stream(session_id), media_type="multipart/x-mixed-replace; boundary=frame")


@router.get("/admin/snapshot/{session_id}")
def snapshot(session_id: str):
    frame = latest_annotated_frames.get(session_id) or latest_frames.get(session_id)
    if not frame:
        raise HTTPException(status_code=404, detail="Frame not available yet")
    return Response(
        content=frame,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/admin/snapshot/{session_id}/front-raw")
def front_raw_snapshot(session_id: str):
    frame = latest_frames.get(session_id)
    if not frame:
        raise HTTPException(status_code=404, detail="Front frame not available yet")
    return Response(
        content=frame,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


def _encode_frame(frame):
    cv2 = _cv2()
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    return buffer.tobytes() if ok else None


def _side_frame(session_id: str, db: Session):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is not None and session.side_camera_url:
        ok, frame = get_latest_side_camera_frame(session.side_camera_url)
        if ok:
            encoded = _encode_frame(frame)
            if encoded:
                return encoded
    return latest_side_annotated_frames.get(session_id) or latest_side_frames.get(session_id)


async def _side_stream(session_id: str):
    db = SessionLocal()
    try:
        while True:
            frame = _side_frame(session_id, db)
            if frame:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            await asyncio.sleep(0.25)
    finally:
        db.close()


@router.get("/admin/stream/{session_id}/side")
def side_stream(session_id: str):
    return StreamingResponse(_side_stream(session_id), media_type="multipart/x-mixed-replace; boundary=frame")


@router.get("/admin/snapshot/{session_id}/side")
def side_snapshot(
    session_id: str,
    db: Session = Depends(get_db),
):
    frame = _side_frame(session_id, db)
    if not frame:
        raise HTTPException(status_code=404, detail="Side frame not available yet")
    return Response(
        content=frame,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/admin/session/{session_id}/approve-rejoin", response_model=SessionOut)
async def approve_rejoin(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "proctor")),
):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.approval_status != "PENDING":
        raise HTTPException(status_code=409, detail="This session is not waiting for approval")

    session.approval_status = "APPROVED"
    session.approval_note = f"Approved by {user.full_name}"
    session.is_active = True
    session.is_terminated = False
    session.status = "MONITORING"
    session.cheat_message = "Rejoin approved. AI monitoring active"
    db.add(Event(
        session_id=session_id,
        event_type="REJOIN_APPROVED",
        severity="INFO",
        message=session.approval_note,
    ))
    db.commit()
    db.refresh(session)
    await broadcast_monitoring_update(manager, session, "rejoin_approved")
    return session


@router.post("/admin/session/{session_id}/deny-rejoin", response_model=SessionOut)
async def deny_rejoin(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "proctor")),
):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.approval_status != "PENDING":
        raise HTTPException(status_code=409, detail="This session is not waiting for approval")

    session.approval_status = "DENIED"
    session.approval_note = f"Denied by {user.full_name}"
    session.is_active = False
    session.is_terminated = True
    session.status = "REJOIN_DENIED"
    session.cheat_message = "Rejoin denied by proctor"
    db.add(Event(
        session_id=session_id,
        event_type="REJOIN_DENIED",
        severity="HIGH",
        message=session.approval_note,
    ))
    db.commit()
    db.refresh(session)
    await broadcast_monitoring_update(manager, session, "rejoin_denied")
    return session


@router.websocket("/ws/admin")
async def ws_admin(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if token:
        try:
            payload = decode_token_without_db(token)
            if payload.get("role") not in {"admin", "proctor"}:
                await websocket.close(code=1008)
                return
        except JWTError:
            await websocket.close(code=1008)
            return
    await manager.connect_admin(websocket)
    db = SessionLocal()
    try:
        sessions = (
            db.query(SessionModel)
            .filter(_current_session_filter())
            .order_by(SessionModel.updated_at.desc())
            .all()
        )
        await websocket.send_json({
            "type": "dashboard_snapshot",
            "sessions": [
                admin_session_payload(session, "dashboard_snapshot")
                for session in sessions
            ],
        })
        while True:
            try:
                text = await asyncio.wait_for(websocket.receive_text(), timeout=35)
                try:
                    message = json.loads(text)
                except json.JSONDecodeError:
                    message = {"type": text}
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect_admin(websocket)
    except Exception:
        logger.exception("Admin websocket failed")
        manager.disconnect_admin(websocket)
    finally:
        db.close()


@router.websocket("/ws/session/{session_id}")
async def ws_session(session_id: str, websocket: WebSocket):
    token = websocket.query_params.get("token")
    if token:
        try:
            decode_token_without_db(token)
        except JWTError:
            await websocket.close(code=1008)
            return
    await manager.connect_session(session_id, websocket)
    try:
        while True:
            try:
                text = await asyncio.wait_for(websocket.receive_text(), timeout=35)
                try:
                    message = json.loads(text)
                except json.JSONDecodeError:
                    message = {"type": text}
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif message.get("type") == "front_frame":
                    payload = str(message.get("data") or "")
                    if "," in payload:
                        payload = payload.split(",", 1)[1]
                    try:
                        frame = base64.b64decode(payload)
                    except Exception:
                        frame = b""
                    if frame:
                        store_frame(session_id, frame)
                        await websocket.send_json({"type": "front_frame_ack"})
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect_session(session_id, websocket)
    except Exception:
        logger.exception("Session websocket failed; session_id=%s", session_id)
        manager.disconnect_session(session_id, websocket)
