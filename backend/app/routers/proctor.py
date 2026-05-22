import asyncio
import json
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..models import Event, Session as SessionModel, User
from ..role_filter import admin_session_payload, broadcast_monitoring_update, is_staff_role, student_session_payload
from ..schemas import (
    DetectionResponse,
    ProctorSimpleResponse,
    ProctorUpdateRequest,
    SideCameraValidationRequest,
    SideCameraValidationResponse,
)
from ..security import get_db, get_current_user, require_role
from ..services.ai_service import Detection, ai_service
from ..services.side_camera import read_side_camera_frame, test_camera_connection_detailed
from ..state import clear_side_frame, manager, store_frame, store_side_frame

router = APIRouter(prefix="/proctor", tags=["proctor"])
logger = logging.getLogger(__name__)
side_camera_failures: dict[str, int] = {}


async def _run_blocking(func, *args, timeout_seconds: float = 5.0):
    return await asyncio.wait_for(
        asyncio.to_thread(func, *args),
        timeout=timeout_seconds,
    )


def _cv2():
    import cv2

    return cv2


def _decode_frame(contents: bytes):
    import numpy as np

    cv2 = _cv2()
    return cv2.imdecode(np.frombuffer(contents, np.uint8), cv2.IMREAD_COLOR)


def _risk(score: float) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 55:
        return "HIGH"
    if score >= 25:
        return "MEDIUM"
    return "LOW"


def _session_payload(session: SessionModel, message_type: str = "detection") -> dict:
    return admin_session_payload(session, message_type)


def _student_response(session: SessionModel, message_type: str = "monitoring") -> dict:
    return student_session_payload(session, message_type)


def _authorize_session_access(session: SessionModel, user: User) -> None:
    if not is_staff_role(user.role) and session.student_id != user.username:
        raise HTTPException(status_code=403, detail="Candidate cannot access another student's session")


def _attempts_payload(validation) -> list[dict]:
    return [
        {
            "url": attempt.url,
            "stream_type": attempt.stream_type,
            "http_status": attempt.http_status,
            "latency_ms": attempt.latency_ms,
            "success": attempt.success,
            "live": attempt.live,
            "error": attempt.error,
        }
        for attempt in validation.attempts
    ]


@router.post("/validate-side-camera", response_model=SideCameraValidationResponse)
async def validate_side_camera(
    payload: SideCameraValidationRequest,
    user: User = Depends(get_current_user),
):
    camera_input = (payload.camera_input or payload.side_camera_url or "").strip()
    try:
        validation = test_camera_connection_detailed(
            camera_input,
            timeout_seconds=3.0,
        )
    except ValueError as exc:
        return SideCameraValidationResponse(
            success=False,
            message=str(exc),
            state="INVALID_IP",
        )

    attempted_url = validation.resolved_url or (validation.attempts[-1].url if validation.attempts else "")
    attempted_urls = [attempt.url for attempt in validation.attempts]
    attempts = _attempts_payload(validation)

    if not validation.success or validation.frame is None or validation.frame.size == 0:
        return SideCameraValidationResponse(
            success=False,
            message="Unable to connect to side camera with live updating frames",
            state="STREAM_FAILED",
            attempted_url=attempted_url,
            attempted_urls=attempted_urls,
            http_status=validation.http_status,
            latency_ms=validation.latency_ms,
            live_frames_confirmed=False,
            attempts=attempts,
        )

    cv2 = _cv2()
    encoded_ok, buffer = cv2.imencode(".jpg", validation.frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not encoded_ok or not buffer.any():
        return SideCameraValidationResponse(
            success=False,
            message="Unable to read a valid side camera frame",
            side_camera_url=validation.resolved_url,
            resolved_url=validation.resolved_url,
            stream_type=validation.stream_type,
            state="CAMERA_OFFLINE",
            attempted_url=attempted_url,
            attempted_urls=attempted_urls,
            http_status=validation.http_status,
            latency_ms=validation.latency_ms,
            live_frames_confirmed=False,
            attempts=attempts,
        )

    return SideCameraValidationResponse(
        success=True,
        message="Camera connected with live updating frames",
        side_camera_url=validation.resolved_url,
        resolved_url=validation.resolved_url,
        stream_type=validation.stream_type,
        state="ONLINE",
        attempted_url=validation.resolved_url,
        attempted_urls=attempted_urls,
        http_status=validation.http_status,
        latency_ms=validation.latency_ms,
        live_frames_confirmed=True,
        attempts=attempts,
    )


@router.post("/side-camera/reconnect/{session_id}", response_model=SideCameraValidationResponse)
async def reconnect_side_camera(
    session_id: str,
    payload: SideCameraValidationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    _authorize_session_access(session, user)

    validation = await validate_side_camera(payload, user)
    if not validation.success:
        session.side_camera_status = validation.state
        session.cheat_message = validation.message
        db.commit()
        db.refresh(session)
        await manager.broadcast_admin(_session_payload(session, "side_camera_reconnect_failed"))
        await manager.broadcast_session(session_id, _student_response(session, "side_camera_reconnect_failed"))
        return validation

    session.side_camera_url = validation.resolved_url or validation.side_camera_url
    session.side_camera_status = "ONLINE"
    session.cheat_message = "Side camera reconnected"
    side_camera_failures[session_id] = 0
    ok, side_frame = read_side_camera_frame(validation.resolved_url or validation.side_camera_url, timeout_seconds=2.0)
    if ok:
        cv2 = _cv2()
        encoded_ok, side_buffer = cv2.imencode(".jpg", side_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        store_side_frame(session_id, side_buffer.tobytes() if encoded_ok else b"")
    db.commit()
    db.refresh(session)
    await manager.broadcast_admin(_session_payload(session, "side_camera_reconnected"))
    await manager.broadcast_session(session_id, _student_response(session, "side_camera_reconnected"))
    return validation


@router.post("/upload-frame")
async def upload_frame(
    session_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    _authorize_session_access(session, user)
    if not session.is_active:
        raise HTTPException(status_code=409, detail=f"Session is {session.status}")
    if session.is_terminated or session.is_submitted:
        raise HTTPException(status_code=409, detail="Session already closed")

    contents = await file.read()
    frame = _decode_frame(contents)
    if frame is None:
        raise HTTPException(status_code=400, detail="Invalid image")

    store_frame(session_id, contents)
    logger.info(
        "Front frame received; session_id=%s bytes=%s",
        session_id,
        len(contents),
    )
    cv2 = _cv2()
    try:
        detection = await _run_blocking(
            ai_service.process_frame,
            session_id,
            frame,
            "front",
            timeout_seconds=4.0,
        )
        store_frame(session_id, contents, detection.annotated_jpeg)
        logger.info(
            "Front AI detection complete; session_id=%s events=%s score_delta=%s",
            session_id,
            len(detection.events),
            detection.score_delta,
        )
    except Exception:
        logger.exception("Front AI detection failed or timed out; session_id=%s", session_id)
        detection = Detection(
            cheating=False,
            message="Clear",
            confidence=0.0,
            score_delta=0.0,
            events=[],
        )
    side_events = []
    side_ok = False
    if session.side_camera_url:
        try:
            side_ok, side_frame = await _run_blocking(
                read_side_camera_frame,
                session.side_camera_url,
                0.8,
                timeout_seconds=1.0,
            )
        except Exception:
            logger.exception("Side camera read failed or timed out; session_id=%s", session_id)
            side_ok, side_frame = False, None
        if side_ok:
            side_camera_failures[session_id] = 0
            ok, side_buffer = cv2.imencode(".jpg", side_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            store_side_frame(session_id, side_buffer.tobytes() if ok else b"")
            try:
                side_detection = await _run_blocking(
                    ai_service.process_frame,
                    f"{session_id}:side",
                    side_frame,
                    "side",
                    timeout_seconds=3.0,
                )
            except Exception:
                logger.exception("Side AI detection failed or timed out; session_id=%s", session_id)
                side_detection = Detection(
                    cheating=False,
                    message="Clear",
                    confidence=0.0,
                    score_delta=0.0,
                    events=[],
                )
            store_side_frame(
                session_id,
                side_buffer.tobytes() if ok else b"",
                getattr(side_detection, "annotated_jpeg", None),
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
            failures = side_camera_failures.get(session_id, 0) + 1
            side_camera_failures[session_id] = failures
            if failures < 12:
                logger.warning(
                    "Side camera read miss; session_id=%s failures=%s",
                    session_id,
                    failures,
                )
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
                await broadcast_monitoring_update(manager, session, "terminated")
                admin_response = DetectionResponse(
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
                ).model_dump(mode="json")
                return admin_response if is_staff_role(user.role) else _student_response(session, "terminated")

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
    await manager.broadcast_admin(payload)
    await manager.broadcast_session(session_id, _student_response(session))

    admin_response = DetectionResponse(
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
    ).model_dump(mode="json")
    return admin_response if is_staff_role(user.role) else _student_response(session)


@router.post("/side-camera/check/{session_id}")
async def check_side_camera(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    _authorize_session_access(session, user)
    if not session.is_active or session.is_submitted or session.is_terminated:
        return _session_payload(session, "side_camera_check") if is_staff_role(user.role) else _student_response(session, "side_camera_check")

    ok, side_frame = read_side_camera_frame(session.side_camera_url, timeout_seconds=1.25)
    if ok:
        cv2 = _cv2()
        side_camera_failures[session_id] = 0
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
        await manager.broadcast_admin(payload)
        await manager.broadcast_session(session_id, _student_response(session, "side_camera_check"))
        return payload if is_staff_role(user.role) else _student_response(session, "side_camera_check")

    failures = side_camera_failures.get(session_id, 0) + 1
    side_camera_failures[session_id] = failures
    session.side_camera_status = "RECONNECTING" if failures < 12 else "OFFLINE"
    if failures < 12:
        session.cheat_message = "Side camera reconnecting"
        db.commit()
        db.refresh(session)
        payload = _session_payload(session, "side_camera_reconnecting")
        await manager.broadcast_admin(payload)
        await manager.broadcast_session(session_id, _student_response(session, "side_camera_reconnecting"))
        return payload if is_staff_role(user.role) else _student_response(session, "side_camera_reconnecting")

    clear_side_frame(session_id)
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
    await manager.broadcast_admin(payload)
    await manager.broadcast_session(session_id, _student_response(session, "terminated"))
    return payload if is_staff_role(user.role) else _student_response(session, "terminated")


@router.post("/update", response_model=ProctorSimpleResponse)
async def proctor_update(
    payload: ProctorUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "proctor")),
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

    await broadcast_monitoring_update(manager, session, "proctor_update")
    return ProctorSimpleResponse(cheating=session.is_cheating, message=session.cheat_message)
