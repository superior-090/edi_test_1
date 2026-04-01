"""
FastAPI wrapper for the AI Proctoring backend.
──────────────────────────────────────────────
This file adds the HTTP layer Flutter talks to.
Detection logic (test6.py) is NOT touched.

Run with:
    uvicorn server:app --host 0.0.0.0 --port 8000 --reload
"""

import tempfile
import os
import cv2
import numpy as np
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from ultralytics import YOLO
import mediapipe as mp

# ── Import ONLY the detection helpers from your existing test6.py ──
from test6 import (
    CFG,
    state,
    SessionState,
    detect_objects,
    validate_phones,
    get_hand_boxes_simple,
    detect_phone_in_crop,
    enhance_frame,
    resize_frame,
)

# ═══════════════════════════════════════════════════════════════
# APP SETUP
# ═══════════════════════════════════════════════════════════════
app = FastAPI(title="ProctorAI API", version="1.0.0")

# Allow Flutter (any origin) to reach this server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Load models once at startup (expensive — do NOT put inside endpoint) ──
print("[INFO] Loading YOLO model...")
yolo = YOLO("yolov8s.pt")

print("[INFO] Initialising MediaPipe Hands...")
mp_hands   = mp.solutions.hands
hands_model = mp_hands.Hands(
    static_image_mode=True,   # single-image mode for API requests
    max_num_hands=2,
    min_detection_confidence=0.4,
    min_tracking_confidence=0.4,
)

print("[INFO] FastAPI server ready.")


# ═══════════════════════════════════════════════════════════════
# RESPONSE SCHEMA
# ═══════════════════════════════════════════════════════════════
class ProctorResponse(BaseModel):
    cheating: bool
    message:  str


# ═══════════════════════════════════════════════════════════════
# ENDPOINT  →  POST /proctor/upload-frame
# ═══════════════════════════════════════════════════════════════
@app.post("/proctor/upload-frame", response_model=ProctorResponse)
async def upload_frame(file: UploadFile = File(...)):
    """
    Receives a JPEG/PNG frame from the Flutter app,
    runs phone detection, and returns the result.

    Flutter sends:  multipart/form-data  key="file"
    Returns:        { "cheating": bool, "message": str }
    """

    # ── 1. Validate file type ────────────────────────────────
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Send JPEG or PNG.",
        )

    # ── 2. Read bytes → OpenCV frame ─────────────────────────
    try:
        contents = await file.read()
        np_arr   = np.frombuffer(contents, np.uint8)
        frame    = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("cv2.imdecode returned None")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot decode image: {e}")

    # ── 3. Pre-process (same pipeline as your desktop app) ───
    frame = resize_frame(frame, CFG.RESIZE_WIDTH_FRONT)
    h, w  = frame.shape[:2]

    # ── 4. Hand detection ────────────────────────────────────
    hand_boxes = get_hand_boxes_simple(frame, hands_model)

    # ── 5. YOLO object detection ─────────────────────────────
    persons, raw_phones, books = detect_objects(frame, yolo, source="front")

    # ── 6. Phone validation (your existing logic, unchanged) ──
    validated_phones = validate_phones(
        raw_phones, persons, hand_boxes, h, w, source="front"
    )

    # Crop-based fallback — same logic as desktop main loop
    if not validated_phones and persons:
        crop_phones = detect_phone_in_crop(frame, persons, yolo, "front", "person")
        if crop_phones:
            validated_phones = validate_phones(
                crop_phones, persons, hand_boxes, h, w, source="front"
            )

    if not validated_phones and hand_boxes:
        hand_phones = detect_phone_in_crop(frame, hand_boxes, yolo, "front", "hand")
        if hand_phones:
            validated_phones = validate_phones(
                hand_phones, persons, hand_boxes, h, w, source="front"
            )

    # ── 7. Build response ────────────────────────────────────
    cheating_detected = len(validated_phones) > 0
    message = "Mobile phone detected!" if cheating_detected else "Clear"

    return ProctorResponse(cheating=cheating_detected, message=message)


# ═══════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════════════════════
@app.get("/health")
async def health():
    return {"status": "ok"}
