import json
import time
from datetime import datetime, timedelta, timezone

import cv2
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from jose import JWTError
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Event, Session as SessionModel, User
from ..schemas import DashboardStats, EventOut, SessionOut
from ..security import decode_token_without_db, get_db, require_role
from ..services.side_camera import get_latest_side_camera_frame
from ..state import (
    latest_annotated_frames,
    latest_frames,
    latest_side_annotated_frames,
    latest_side_frames,
    manager,
)

router = APIRouter(tags=["admin"])


def _current_session_filter():
    fresh_after = datetime.now(timezone.utc) - timedelta(minutes=3)
    return or_(
        (SessionModel.is_active == True) & (SessionModel.updated_at >= fresh_after),
        (SessionModel.approval_status == "PENDING") & (SessionModel.updated_at >= fresh_after),
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


@router.get("/admin/sessions", response_model=list[SessionOut])
def get_sessions(
    subject: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    query = db.query(SessionModel).filter(_current_session_filter())
    if subject and subject.upper() != "ALL":
        query = query.filter(SessionModel.subject == subject)
    return query.order_by(SessionModel.updated_at.desc()).all()


@router.get("/admin/sessions/{session_id}")
def get_session_detail(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
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
    user: User = Depends(require_role("admin")),
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


@router.get("/admin/events", response_model=list[EventOut])
def events(
    limit: int = 80,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
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
    user: User = Depends(require_role("admin")),
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
    await manager.broadcast(session_id, {"type": "terminated", **SessionOut.model_validate(session).model_dump(mode="json")})
    return session


@router.post("/admin/session/{session_id}/flag", response_model=SessionOut)
async def flag_session(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
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
    await manager.broadcast(session_id, {"type": "manual_flag", **SessionOut.model_validate(session).model_dump(mode="json")})
    return session


def _stream(session_id: str):
    while True:
        frame = latest_annotated_frames.get(session_id) or latest_frames.get(session_id)
        if frame:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        time.sleep(0.25)


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


def _encode_frame(frame):
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


def _side_stream(session_id: str):
    db = SessionLocal()
    try:
        while True:
            frame = _side_frame(session_id, db)
            if frame:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            time.sleep(0.1)
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
    user: User = Depends(require_role("admin")),
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
    await manager.broadcast(session_id, {"type": "rejoin_approved", **SessionOut.model_validate(session).model_dump(mode="json")})
    return session


@router.post("/admin/session/{session_id}/deny-rejoin", response_model=SessionOut)
async def deny_rejoin(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
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
    await manager.broadcast(session_id, {"type": "rejoin_denied", **SessionOut.model_validate(session).model_dump(mode="json")})
    return session


@router.websocket("/ws/admin")
async def ws_admin(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if token:
        try:
            payload = decode_token_without_db(token)
            if payload.get("role") != "admin":
                await websocket.close(code=1008)
                return
        except JWTError:
            await websocket.close(code=1008)
            return
    await manager.connect_admin(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_admin(websocket)


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
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_session(session_id, websocket)
