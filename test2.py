import cv2
import time
import os
import json
import threading
from datetime import datetime
from ultralytics import YOLO

# ─────────────────────────────────────────────
# Try importing MediaPipe (optional but needed for gaze)
# ─────────────────────────────────────────────
try:
    import mediapipe as mp
    MP_AVAILABLE = True
    mp_face_mesh = mp.solutions.face_mesh
    face_mesh = mp_face_mesh.FaceMesh(
        max_num_faces=2,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5
    )
except ImportError:
    MP_AVAILABLE = False
    print("[WARNING] MediaPipe not installed. Gaze detection disabled.")
    print("          Run: pip install mediapipe")

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
SIDE_CAM_URL     = "http://192.168.0.106:8080/video"   # Change to your phone IP
CHEAT_THRESHOLD  = 5          # Score to trigger CHEATING DETECTED
FACE_MISSING_MAX = 3.0        # Seconds before face-missing penalty kicks in
GAZE_AWAY_MAX    = 2.5        # Seconds looking away before penalty
EVIDENCE_DIR     = "evidence" # Folder for snapshot saves
LOG_FILE         = "cheat_log.json"

os.makedirs(EVIDENCE_DIR, exist_ok=True)

# ─────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────
yolo = YOLO("yolov8n.pt")

face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

# ─────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────
session_start     = time.time()
face_missing_time = 0.0
gaze_away_time    = 0.0
last_time         = time.time()

cheat_events      = []   # List of logged events
evidence_saved    = set()  # Avoid duplicate saves in same second

# Counters for final report
total_phone_detections   = 0
total_multi_face_events  = 0
total_face_missing_secs  = 0.0
total_gaze_away_secs     = 0.0

# ─────────────────────────────────────────────
# HELPER: LOG EVENT
# ─────────────────────────────────────────────
def log_event(event_type: str, detail: str = ""):
    entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event": event_type,
        "detail": detail
    }
    cheat_events.append(entry)
    print(f"[EVENT] {entry['time']} | {event_type} | {detail}")

# ─────────────────────────────────────────────
# HELPER: SAVE EVIDENCE SNAPSHOT
# ─────────────────────────────────────────────
def save_evidence(front, side, reason: str):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    key = ts[:15]  # Avoid saving more than once per 15-char timestamp window
    if key in evidence_saved:
        return
    evidence_saved.add(key)
    front_path = os.path.join(EVIDENCE_DIR, f"{ts}_front_{reason}.jpg")
    side_path  = os.path.join(EVIDENCE_DIR, f"{ts}_side_{reason}.jpg")
    cv2.imwrite(front_path, front)
    cv2.imwrite(side_path, side)
    log_event("EVIDENCE_SAVED", f"{front_path}, {side_path}")

# ─────────────────────────────────────────────
# HELPER: DETECT FACES (returns count + rects)
# ─────────────────────────────────────────────
def detect_faces(frame):
    gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=5)
    return faces  # numpy array of (x,y,w,h)

# ─────────────────────────────────────────────
# HELPER: DETECT PHONE
# ─────────────────────────────────────────────
def detect_phone(frame):
    results = yolo(frame, conf=0.4, verbose=False)
    for r in results:
        for box in r.boxes:
            if yolo.names[int(box.cls[0])] == "cell phone":
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                return True
    return False

# ─────────────────────────────────────────────
# HELPER: GAZE DETECTION via MediaPipe
# Returns True if gaze is looking away from screen
# ─────────────────────────────────────────────
def detect_gaze_away(frame):
    if not MP_AVAILABLE:
        return False
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(rgb)
    if not results.multi_face_landmarks:
        return False  # No face → handled separately

    h, w = frame.shape[:2]
    face_lms = results.multi_face_landmarks[0].landmark

    # Iris landmarks: Left iris center=468, Right iris center=473
    # Eye corners: Left eye: outer=33, inner=133 | Right eye: outer=362, inner=263
    def lm(idx):
        return face_lms[idx].x * w, face_lms[idx].y * h

    # Left eye
    l_outer, l_inner = lm(33),  lm(133)
    l_iris           = lm(468)
    l_eye_width      = abs(l_inner[0] - l_outer[0])
    l_ratio          = (l_iris[0] - l_outer[0]) / (l_eye_width + 1e-6)

    # Right eye
    r_outer, r_inner = lm(362), lm(263)
    r_iris           = lm(473)
    r_eye_width      = abs(r_inner[0] - r_outer[0])
    r_ratio          = (r_iris[0] - r_outer[0]) / (r_eye_width + 1e-6)

    avg_ratio = (l_ratio + r_ratio) / 2.0

    # Draw iris dots
    cv2.circle(frame, (int(l_iris[0]), int(l_iris[1])), 3, (0, 255, 255), -1)
    cv2.circle(frame, (int(r_iris[0]), int(r_iris[1])), 3, (0, 255, 255), -1)

    # If iris ratio is too far left (<0.35) or right (>0.65), gaze is away
    gaze_away = avg_ratio < 0.35 or avg_ratio > 0.65
    return gaze_away

# ─────────────────────────────────────────────
# HELPER: DRAW OVERLAY BOX
# ─────────────────────────────────────────────
def draw_overlay(frame, cheat_score, status, color, elapsed):
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (frame.shape[1], 100), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
    cv2.putText(frame, f"Status: {status}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    cv2.putText(frame, f"Cheat Score: {cheat_score}  |  Time: {int(elapsed)}s",
                (10, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 1)

# ─────────────────────────────────────────────
# HELPER: SAVE FINAL REPORT
# ─────────────────────────────────────────────
def save_report():
    session_duration = time.time() - session_start
    risk_score = 0
    if total_phone_detections  > 0:  risk_score += 3
    if total_multi_face_events > 2:  risk_score += 2
    if total_face_missing_secs > 10: risk_score += 2
    if total_gaze_away_secs    > 20: risk_score += 1

    if   risk_score >= 6: risk_level = "HIGH"
    elif risk_score >= 3: risk_level = "MEDIUM"
    else:                 risk_level = "LOW"

    report = {
        "session_duration_secs"  : round(session_duration, 1),
        "phone_detections"       : total_phone_detections,
        "multi_face_events"      : total_multi_face_events,
        "face_missing_secs"      : round(total_face_missing_secs, 1),
        "gaze_away_secs"         : round(total_gaze_away_secs, 1),
        "risk_score"             : risk_score,
        "risk_level"             : risk_level,
        "events"                 : cheat_events
    }

    with open(LOG_FILE, "w") as f:
        json.dump(report, f, indent=2)

    print("\n" + "="*55)
    print("         SESSION REPORT")
    print("="*55)
    print(f"  Duration          : {report['session_duration_secs']}s")
    print(f"  Phone Detections  : {total_phone_detections}")
    print(f"  Multi-Face Events : {total_multi_face_events}")
    print(f"  Face Missing Time : {report['face_missing_secs']}s")
    print(f"  Gaze Away Time    : {report['gaze_away_secs']}s")
    print(f"  Risk Score        : {risk_score}")
    print(f"  Risk Level        : {risk_level}")
    print(f"  Full log saved to : {LOG_FILE}")
    print(f"  Snapshots saved to: {EVIDENCE_DIR}/")
    print("="*55)

# ─────────────────────────────────────────────
# CAMERAS
# ─────────────────────────────────────────────
print("[INFO] Connecting to cameras...")
front_cam = cv2.VideoCapture(0)
side_cam  = cv2.VideoCapture(SIDE_CAM_URL)

if not front_cam.isOpened():
    print("[ERROR] Front camera (index 0) not available.")
    exit()
if not side_cam.isOpened():
    print(f"[WARNING] Side camera not available at {SIDE_CAM_URL}. Using front cam only.")
    side_cam = cv2.VideoCapture(0)  # Fallback to same cam for testing

print("[INFO] Starting exam monitoring. Press ESC to end session.\n")

# ─────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────
while True:
    ret1, front = front_cam.read()
    ret2, side  = side_cam.read()

    if not ret1:
        print("[ERROR] Front camera stream lost.")
        break
    if not ret2:
        side = front.copy()  # Fallback

    now   = time.time()
    dt    = now - last_time
    last_time = now

    elapsed     = now - session_start
    cheat_score = 0
    warnings    = []

    # ── 1. FACE DETECTION (count + positions) ────────────────────
    faces = detect_faces(front)
    num_faces = len(faces)

    # Draw face rectangles
    for (x, y, w, h) in faces:
        cv2.rectangle(front, (x, y), (x+w, y+h), (0, 255, 0), 2)

    if num_faces == 0:
        face_missing_time += dt
        total_face_missing_secs += dt
        if face_missing_time > FACE_MISSING_MAX:
            cheat_score += 2
            warnings.append("FACE NOT DETECTED")
            cv2.putText(front, "FACE NOT DETECTED", (20, 130),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    else:
        if face_missing_time > FACE_MISSING_MAX:
            log_event("FACE_MISSING", f"Missing for {face_missing_time:.1f}s")
        face_missing_time = 0.0

    # ── 2. MULTIPLE FACES ────────────────────────────────────────
    if num_faces > 1:
        cheat_score += 3
        total_multi_face_events += 1
        warnings.append("MULTIPLE FACES")
        cv2.putText(front, f"MULTIPLE FACES ({num_faces})", (20, 160),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        log_event("MULTIPLE_FACES", f"{num_faces} faces detected")

    # ── 3. GAZE DETECTION ────────────────────────────────────────
    if num_faces > 0:
        gaze_away = detect_gaze_away(front)
        if gaze_away:
            gaze_away_time += dt
            total_gaze_away_secs += dt
            if gaze_away_time > GAZE_AWAY_MAX:
                cheat_score += 1
                warnings.append("GAZE AWAY")
                cv2.putText(front, "GAZE AWAY", (20, 190),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
        else:
            if gaze_away_time > GAZE_AWAY_MAX:
                log_event("GAZE_AWAY", f"Looking away for {gaze_away_time:.1f}s")
            gaze_away_time = 0.0

    # ── 4. PHONE DETECTION (side cam) ────────────────────────────
    phone_detected = detect_phone(side)
    if phone_detected:
        cheat_score += 5
        total_phone_detections += 1
        warnings.append("PHONE DETECTED")
        cv2.putText(side, "PHONE DETECTED", (20, 130),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
        log_event("PHONE_DETECTED", "Cell phone seen on side camera")

    # ── 5. DECISION + OVERLAY ────────────────────────────────────
    if cheat_score >= CHEAT_THRESHOLD:
        status = "!! CHEATING DETECTED !!"
        color  = (0, 0, 255)
        save_evidence(front, side, "cheat")
    else:
        status = "NORMAL"
        color  = (0, 220, 0)

    draw_overlay(front, cheat_score, status, color, elapsed)
    draw_overlay(side,  cheat_score, f"SIDE | {status}", color, elapsed)

    # Warning list on side cam
    for i, w_text in enumerate(warnings):
        cv2.putText(side, f"[!] {w_text}", (10, 160 + i * 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    # ── 6. DISPLAY ───────────────────────────────────────────────
    cv2.imshow("Front Camera (Laptop Webcam)", front)
    cv2.imshow("Side Camera (Phone)", side)

    if cv2.waitKey(1) & 0xFF == 27:  # ESC to quit
        print("\n[INFO] Session ended by user.")
        break

# ─────────────────────────────────────────────
# CLEANUP + FINAL REPORT
# ─────────────────────────────────────────────
front_cam.release()
side_cam.release()
cv2.destroyAllWindows()

if MP_AVAILABLE:
    face_mesh.close()

save_report()