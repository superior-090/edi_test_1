import cv2
import numpy as np
import time
import httpx
from typing import Dict
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from ultralytics import YOLO
import mediapipe as mp

# ── Import detection helpers ──
from test6 import (
    CFG,
    detect_objects,
    validate_phones,
    get_hand_boxes_simple,
    detect_phone_in_crop,
    resize_frame,
)

# ═══════════════════════════════════════════════
# APP SETUP
# ═══════════════════════════════════════════════
app = FastAPI(title="ProctorAI API", version="2.0")

# ── Cloud backend URL (update after Render deploy) ──
CLOUD_API_URL = "https://proctorai-api.onrender.com"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════
# GLOBAL SESSION STORE
# ═══════════════════════════════════════════════
sessions: Dict[str, dict] = {}

# ═══════════════════════════════════════════════
# LOAD MODELS
# ═══════════════════════════════════════════════
print("[INFO] Loading YOLO...")
yolo = YOLO("yolov8s.pt")

print("[INFO] Loading MediaPipe Hands...")
mp_hands = mp.solutions.hands
hands_model = mp_hands.Hands(
    static_image_mode=True,
    max_num_hands=2,
    min_detection_confidence=0.4,
)

print("[INFO] Server Ready")

# ═══════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════
class SessionData(BaseModel):
    session_id: str
    student_id: str

class SideCamData(BaseModel):
    session_id: str
    url: str

class ProctorResponse(BaseModel):
    cheating: bool
    message: str

# ═══════════════════════════════════════════════
# START SESSION
# ═══════════════════════════════════════════════
@app.post("/session/start")
async def start_session(data: SessionData):
    sessions[data.session_id] = {
        "student_id": data.student_id,
        "cheating": False,
        "message": "Starting...",
        "last_frame": None,
        "side_cam_url": None,
        "timestamp": time.time()
    }

    return {"status": "session started"}

# ═══════════════════════════════════════════════
# REGISTER SIDE CAMERA
# ═══════════════════════════════════════════════
@app.post("/session/sidecam")
async def register_sidecam(data: SideCamData):
    if data.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    sessions[data.session_id]["side_cam_url"] = data.url
    return {"status": "side camera registered"}

# ═══════════════════════════════════════════════
# UPLOAD FRAME (AI DETECTION)
# ═══════════════════════════════════════════════
@app.post("/proctor/upload-frame", response_model=ProctorResponse)
async def upload_frame(
    session_id: str,
    file: UploadFile = File(...)
):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    # Validate
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(status_code=415, detail="Invalid file")

    # Read image
    contents = await file.read()
    np_arr = np.frombuffer(contents, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    if frame is None:
        raise HTTPException(status_code=400, detail="Invalid image")

    # Preprocess
    frame = resize_frame(frame, CFG.RESIZE_WIDTH_FRONT)
    h, w = frame.shape[:2]

    # Hands
    hand_boxes = get_hand_boxes_simple(frame, hands_model)

    # YOLO detection
    persons, raw_phones, books = detect_objects(frame, yolo, "front")

    validated_phones = validate_phones(
        raw_phones, persons, hand_boxes, h, w, "front"
    )

    # Crop fallback
    if not validated_phones and persons:
        crop = detect_phone_in_crop(frame, persons, yolo, "front", "person")
        if crop:
            validated_phones = validate_phones(
                crop, persons, hand_boxes, h, w, "front"
            )

    if not validated_phones and hand_boxes:
        crop = detect_phone_in_crop(frame, hand_boxes, yolo, "front", "hand")
        if crop:
            validated_phones = validate_phones(
                crop, persons, hand_boxes, h, w, "front"
            )

    # Result
    cheating = len(validated_phones) > 0
    message = "Mobile phone detected!" if cheating else "Clear"

    # Store session data
    sessions[session_id]["cheating"] = cheating
    sessions[session_id]["message"] = message
    sessions[session_id]["last_frame"] = frame
    sessions[session_id]["timestamp"] = time.time()

    # ── Forward result to Render cloud backend ──
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{CLOUD_API_URL}/proctor/update",
                json={
                    "session_id": session_id,
                    "cheating": cheating,
                    "cheat_type": "PHONE" if cheating else "",
                    "message": message,
                    "cheat_score_delta": 10.0 if cheating else 0.0,
                },
            )
    except Exception as e:
        print(f"[WARN] Cloud push failed: {e}")

    return {"cheating": cheating, "message": message}

# ═══════════════════════════════════════════════
# ADMIN: GET ALL SESSIONS
# ═══════════════════════════════════════════════
@app.get("/admin/sessions")
async def get_sessions():
    return sessions

# ═══════════════════════════════════════════════
# VIDEO STREAM (MAIN CAM)
# ═══════════════════════════════════════════════
def generate_frames(session_id: str):
    while True:
        if session_id not in sessions:
            break

        frame = sessions[session_id]["last_frame"]

        if frame is None:
            continue

        _, buffer = cv2.imencode(".jpg", frame)
        frame_bytes = buffer.tobytes()

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
        )

@app.get("/admin/stream/{session_id}")
async def stream_video(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404)

    return StreamingResponse(
        generate_frames(session_id),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

# ═══════════════════════════════════════════════
# HEALTH
# ═══════════════════════════════════════════════
@app.get("/health")
async def health():
    return {"status": "ok"}