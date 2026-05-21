import json

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..models import Event, Session as SessionModel, User
from ..schemas import DetectionResponse, ProctorSimpleResponse, ProctorUpdateRequest
from ..security import get_db, get_current_user
from ..services.ai_service import ai_service
from ..services.side_camera import read_side_camera_frame
from ..state import clear_side_frame, manager, store_frame, store_side_frame

router = APIRouter(prefix="/proctor", tags=["proctor"])


def _risk(score: float) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 55:
        return "HIGH"
    if score >= 25:
        return "MEDIUM"
    return "LOW"


def _session_payload(session: SessionModel, message_type: str = "detection") -> dict:
    return {
        "type": message_type,
        "session_id": session.session_id,
        "student_id": session.student_id,
        "student_name": session.student_name,
        "subject": session.subject,
        "exam_title": session.exam_title,
        "side_camera_url": session.side_camera_url,
        "side_camera_status": session.side_camera_status,
        "is_active": session.is_active,
        "is_submitted": session.is_submitted,
        "is_terminated": session.is_terminated,
        "is_cheating": session.is_cheating,
        "cheating": session.is_cheating,
        "status": session.status,
        "candidate_status": session.status,
        "risk_level": session.risk_level,
        "cheat_type": session.cheat_type,
        "cheat_message": session.cheat_message,
        "message": session.cheat_message,
        "cheat_count": session.cheat_count,
        "warning_count": session.warning_count,
        "tab_switch_count": session.tab_switch_count,
        "disconnect_count": session.disconnect_count,
        "confidence": session.confidence,
        "cheat_score": session.cheat_score,
        "approval_status": session.approval_status,
        "approval_note": session.approval_note,
    }


@router.post("/upload-frame", response_model=DetectionResponse)
async def upload_frame(
    session_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.is_active:
        raise HTTPException(status_code=409, detail=f"Session is {session.status}")
    if session.is_terminated or session.is_submitted:
        raise HTTPException(status_code=409, detail="Session already closed")

    contents = await file.read()
    frame = cv2.imdecode(np.frombuffer(contents, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="Invalid image")

    detection = ai_service.process_frame(session_id, frame, camera="front")
    store_frame(session_id, contents, detection.annotated_jpeg)
    side_events = []
    side_ok = False
    if session.side_camera_url:
        side_ok, side_frame = read_side_camera_frame(session.side_camera_url)
        if side_ok:
            ok, side_buffer = cv2.imencode(".jpg", side_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            side_detection = ai_service.process_frame(f"{session_id}:side", side_frame, camera="side")
            store_side_frame(
                session_id,
                side_buffer.tobytes() if ok else b"",
                side_detection.annotated_jpeg,
            )
            side_events = [
                {
                    **event,
                    "event_type": f"SIDE_{event['event_type']}",
                    "message": event["message"] if event["message"].startswith("Side camera:") else f"Side camera: {event['message']}",
                }
                for event in side_detection.events
            ]
            session.side_camera_status = "ONLINE"
        else:
            clear_side_frame(session_id)
            session.side_camera_status = "OFFLINE"
            session.is_active = False
            session.is_terminated = True
            session.status = "TERMINATED"
            session.is_cheating = True
            session.cheat_type = "SIDE_CAMERA_DISCONNECTED"
            session.cheat_message = "Side camera feed stopped. Exam terminated."
            session.warning_count += 1
            session.cheat_score = min(100.0, session.cheat_score + 30)
            session.risk_level = _risk(session.cheat_score)
            db.add(Event(
                session_id=session_id,
                event_type="SIDE_CAMERA_DISCONNECTED",
                severity="CRITICAL",
                message="Side camera feed stopped during the exam",
                confidence=1.0,
                score_delta=30,
                metadata_json=json.dumps({"source": "side_camera"}),
            ))
            db.commit()
            db.refresh(session)
            await manager.broadcast(session_id, _session_payload(session, "terminated"))
            return DetectionResponse(
                session_id=session_id,
                cheating=True,
                message=session.cheat_message,
                cheat_type=session.cheat_type,
                confidence=1.0,
                cheat_score=session.cheat_score,
                risk_level=session.risk_level,
                status=session.status,
                warning_count=session.warning_count,
                candidate_status=session.status,
                side_camera_status=session.side_camera_status,
                events=[{
                    "event_type": "SIDE_CAMERA_DISCONNECTED",
                    "severity": "CRITICAL",
                    "message": "Side camera feed stopped during the exam",
                    "confidence": 1.0,
                    "score_delta": 30,
                }],
            )

    all_events = detection.events + side_events
    chargeable_events = [event for event in all_events if event.get("chargeable", True) and event["score_delta"] > 0]
    side_score_delta = sum(event["score_delta"] for event in side_events if event.get("chargeable", True))
    top_event = max(all_events, key=lambda item: item["confidence"], default=None)
    top_cheating_event = max(
        [event for event in all_events if event["severity"] in ("HIGH", "CRITICAL")],
        key=lambda item: item["confidence"],
        default=None,
    )

    session.is_cheating = detection.cheating or any(event["severity"] in ("HIGH", "CRITICAL") for event in side_events)
    session.cheat_type = top_cheating_event["event_type"] if top_cheating_event else ""
    session.cheat_message = top_event["message"] if top_event else "Clear"
    session.confidence = max([detection.confidence] + [event["confidence"] for event in side_events])
    session.cheat_score = min(100.0, session.cheat_score + detection.score_delta + side_score_delta)
    session.risk_level = _risk(session.cheat_score)
    session.status = "AUTO_SUBMIT_REQUIRED" if session.cheat_score >= 95 else (
        "WARNING" if session.is_cheating else "CLEAR"
    )

    if chargeable_events:
        session.cheat_count += 1
        session.warning_count += 1

    event_rows = []
    for event in chargeable_events:
        row = Event(
            session_id=session_id,
            event_type=event["event_type"],
            severity=event["severity"],
            message=event["message"],
            confidence=event["confidence"],
            score_delta=event["score_delta"],
            metadata_json=json.dumps({"source": "ai_frame"}),
        )
        db.add(row)
    event_rows = all_events

    db.commit()
    db.refresh(session)

    payload = _session_payload(session)
    payload["events"] = event_rows
    await manager.broadcast(session_id, payload)

    return DetectionResponse(
        session_id=session_id,
        cheating=session.is_cheating,
        message=session.cheat_message,
        cheat_type=session.cheat_type,
        confidence=session.confidence,
        cheat_score=session.cheat_score,
        risk_level=session.risk_level,
        status=session.status,
        warning_count=session.warning_count,
        candidate_status=session.status,
        side_camera_status=session.side_camera_status,
        events=event_rows,
    )


@router.post("/side-camera/check/{session_id}")
async def check_side_camera(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.is_active or session.is_submitted or session.is_terminated:
        return _session_payload(session, "side_camera_check")

    ok, side_frame = read_side_camera_frame(session.side_camera_url, timeout_seconds=1.25)
    if ok:
        encoded_ok, side_buffer = cv2.imencode(".jpg", side_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        side_detection = ai_service.process_frame(f"{session_id}:side", side_frame, camera="side")
        store_side_frame(
            session_id,
            side_buffer.tobytes() if encoded_ok else b"",
            side_detection.annotated_jpeg,
        )
        session.side_camera_status = "ONLINE"
        db.commit()
        db.refresh(session)
        payload = _session_payload(session, "side_camera_check")
        await manager.broadcast(session_id, payload)
        return payload

    clear_side_frame(session_id)
    session.side_camera_status = "OFFLINE"
    session.is_active = False
    session.is_terminated = True
    session.is_cheating = True
    session.status = "TERMINATED"
    session.cheat_type = "SIDE_CAMERA_DISCONNECTED"
    session.cheat_message = "Side camera feed stopped. Exam terminated."
    session.warning_count += 1
    session.cheat_score = min(100.0, session.cheat_score + 30)
    session.risk_level = _risk(session.cheat_score)
    db.add(Event(
        session_id=session_id,
        event_type="SIDE_CAMERA_DISCONNECTED",
        severity="CRITICAL",
        message="Side camera feed stopped during the exam",
        confidence=1.0,
        score_delta=30,
        metadata_json=json.dumps({"source": "side_camera_watchdog"}),
    ))
    db.commit()
    db.refresh(session)
    payload = _session_payload(session, "terminated")
    await manager.broadcast(session_id, payload)
    return payload


@router.post("/update", response_model=ProctorSimpleResponse)
async def proctor_update(
    payload: ProctorUpdateRequest,
    db: Session = Depends(get_db),
):
    session = db.query(SessionModel).filter(SessionModel.session_id == payload.session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    session.is_cheating = payload.cheating
    session.cheat_type = payload.cheat_type if payload.cheating else ""
    session.cheat_message = payload.message or "Clear"

    if payload.cheating:
        session.cheat_count += 1
        session.warning_count += 1
        session.cheat_score = min(100.0, session.cheat_score + (payload.cheat_score_delta or 10.0))
        session.risk_level = _risk(session.cheat_score)
        session.status = "AUTO_SUBMIT_REQUIRED" if session.cheat_score >= 95 else "WARNING"
        db.add(Event(
            session_id=payload.session_id,
            event_type=payload.cheat_type or "UNKNOWN",
            severity="HIGH" if session.risk_level in ("HIGH", "CRITICAL") else "MEDIUM",
            message=payload.message or "Suspicious activity detected",
            confidence=0.0,
            score_delta=payload.cheat_score_delta or 10.0,
            metadata_json=json.dumps({"source": "proctor_update"}),
        ))
    else:
        session.status = "CLEAR"

    db.commit()
    db.refresh(session)

    await manager.broadcast(payload.session_id, _session_payload(session, "proctor_update"))
    return ProctorSimpleResponse(cheating=session.is_cheating, message=session.cheat_message)
