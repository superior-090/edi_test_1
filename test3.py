import cv2
import time
import os
import json
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
    print("[INFO] MediaPipe loaded. Gaze detection enabled.")
except ImportError:
    MP_AVAILABLE = False
    print("[WARNING] MediaPipe not installed. Gaze detection disabled.")
    print("          Run: pip install mediapipe")

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
SIDE_CAM_URL         = "http://192.168.0.106:8080/video"  # Change to your phone IP
CHEAT_THRESHOLD      = 10       # Cumulative score to trigger CHEATING DETECTED
FACE_MISSING_MAX     = 3.0     # Seconds before face-missing penalty kicks in
GAZE_AWAY_MAX        = 2.5     # Seconds looking away before penalty
EVIDENCE_DIR         = "evidence"
LOG_FILE             = "cheat_log.json"

os.makedirs(EVIDENCE_DIR, exist_ok=True)

# ─────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────
print("[INFO] Loading YOLO models...")
# Main YOLO for object detection (phone etc.)
yolo_obj = YOLO("yolov8n.pt")

# YOLO for face detection — much better than Haar Cascade
# Uses the COCO 'person' class + face via yolov8n-face if available, else fallback
try:
    yolo_face = YOLO("yolov8n-face.pt")   # Download auto if not present
    YOLO_FACE_AVAILABLE = True
    print("[INFO] YOLOv8 face model loaded.")
except Exception:
    YOLO_FACE_AVAILABLE = False
    print("[WARNING] yolov8n-face.pt not found. Using Haar Cascade as fallback.")
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

# ─────────────────────────────────────────────
# SESSION STATE  (PERSISTENT across frames)
# ─────────────────────────────────────────────
session_start        = time.time()
face_missing_time    = 0.0
gaze_away_time       = 0.0
last_time            = time.time()

# ★ CUMULATIVE CHEAT SCORE — never resets
cumulative_score     = 0

cheat_events         = []
evidence_saved       = set()

# Totals for report
total_phone_detections  = 0
total_multi_face_events = 0
total_face_missing_secs = 0.0
total_gaze_away_secs    = 0.0

# Cooldowns to avoid spamming score every frame
cooldown = {
    "face_missing"  : 0.0,
    "multi_face"    : 0.0,
    "gaze_away"     : 0.0,
    "phone"         : 0.0,
}
COOLDOWN_SECS = 2.0   # Add score at most once per 2s per event type

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def log_event(event_type, detail=""):
    entry = {
        "time"  : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event" : event_type,
        "detail": detail
    }
    cheat_events.append(entry)
    print(f"[EVENT] {entry['time']} | {event_type} | {detail}")


def save_evidence(front, side, reason):
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    key = ts[:15]
    if key in evidence_saved:
        return
    evidence_saved.add(key)
    cv2.imwrite(os.path.join(EVIDENCE_DIR, f"{ts}_front_{reason}.jpg"), front)
    cv2.imwrite(os.path.join(EVIDENCE_DIR, f"{ts}_side_{reason}.jpg"),  side)
    log_event("EVIDENCE_SAVED", ts)


def detect_faces_yolo(frame):
    """Returns list of (x1,y1,x2,y2) face boxes using YOLOv8-face."""
    results = yolo_face(frame, conf=0.4, verbose=False)
    boxes = []
    for r in results:
        for box in r.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            boxes.append((x1, y1, x2, y2))
    return boxes


def detect_faces_haar(frame):
    """Fallback: returns list of (x1,y1,x2,y2) using Haar Cascade."""
    gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=4)
    return [(x, y, x+w, y+h) for (x, y, w, h) in faces]


def get_faces(frame):
    if YOLO_FACE_AVAILABLE:
        return detect_faces_yolo(frame)
    return detect_faces_haar(frame)


def detect_phone(frame):
    results = yolo_obj(frame, conf=0.4, verbose=False)
    for r in results:
        for box in r.boxes:
            if yolo_obj.names[int(box.cls[0])] == "cell phone":
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cv2.rectangle(frame, (x1,y1), (x2,y2), (0,0,255), 2)
                cv2.putText(frame, "PHONE", (x1, y1-8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)
                return True
    return False


def detect_gaze_away(frame):
    if not MP_AVAILABLE:
        return False
    rgb     = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(rgb)
    if not results.multi_face_landmarks:
        return False
    h, w    = frame.shape[:2]
    lms     = results.multi_face_landmarks[0].landmark

    def lm(i):
        return lms[i].x * w, lms[i].y * h

    l_outer, l_inner = lm(33),  lm(133)
    l_iris           = lm(468)
    l_ratio = (l_iris[0] - l_outer[0]) / (abs(l_inner[0] - l_outer[0]) + 1e-6)

    r_outer, r_inner = lm(362), lm(263)
    r_iris           = lm(473)
    r_ratio = (r_iris[0] - r_outer[0]) / (abs(r_inner[0] - r_outer[0]) + 1e-6)

    avg = (l_ratio + r_ratio) / 2.0
    cv2.circle(frame, (int(l_iris[0]), int(l_iris[1])), 4, (0,255,255), -1)
    cv2.circle(frame, (int(r_iris[0]), int(r_iris[1])), 4, (0,255,255), -1)
    return avg < 0.35 or avg > 0.65


def add_score(amount, key, now):
    """Add to cumulative score only if cooldown has passed."""
    global cumulative_score
    if now - cooldown[key] >= COOLDOWN_SECS:
        cumulative_score += amount
        cooldown[key]     = now
        return True
    return False


def draw_hud(frame, label="FRONT"):
    """Draw semi-transparent HUD with cumulative score."""
    h, w = frame.shape[:2]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 110), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    # Risk bar
    bar_w   = int((min(cumulative_score, CHEAT_THRESHOLD) / CHEAT_THRESHOLD) * (w - 40))
    bar_col = (0,200,0) if cumulative_score < 5 else (0,165,255) if cumulative_score < CHEAT_THRESHOLD else (0,0,255)
    cv2.rectangle(frame, (20, 80), (20 + bar_w, 100), bar_col, -1)
    cv2.rectangle(frame, (20, 80), (w - 20, 100), (180,180,180), 1)

    status = "!! CHEATING DETECTED !!" if cumulative_score >= CHEAT_THRESHOLD else "NORMAL"
    col    = (0,0,255) if cumulative_score >= CHEAT_THRESHOLD else (0,220,0)

    elapsed = int(time.time() - session_start)
    cv2.putText(frame, f"[{label}]  {status}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.85, col, 2)
    cv2.putText(frame, f"Cumulative Score: {cumulative_score} / {CHEAT_THRESHOLD}   Time: {elapsed}s",
                (10, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 1)


def save_report():
    duration   = round(time.time() - session_start, 1)
    risk_score = 0
    if total_phone_detections  > 0:  risk_score += 3
    if total_multi_face_events > 2:  risk_score += 2
    if total_face_missing_secs > 10: risk_score += 2
    if total_gaze_away_secs    > 20: risk_score += 1

    risk_level = "HIGH" if risk_score >= 6 else "MEDIUM" if risk_score >= 3 else "LOW"

    report = {
        "session_duration_secs" : duration,
        "cumulative_cheat_score": cumulative_score,
        "phone_detections"      : total_phone_detections,
        "multi_face_events"     : total_multi_face_events,
        "face_missing_secs"     : round(total_face_missing_secs, 1),
        "gaze_away_secs"        : round(total_gaze_away_secs, 1),
        "risk_level"            : risk_level,
        "events"                : cheat_events
    }
    with open(LOG_FILE, "w") as f:
        json.dump(report, f, indent=2)

    print("\n" + "="*55)
    print("            FINAL SESSION REPORT")
    print("="*55)
    print(f"  Duration            : {duration}s")
    print(f"  Cumulative Score    : {cumulative_score}")
    print(f"  Phone Detections    : {total_phone_detections}")
    print(f"  Multi-Face Events   : {total_multi_face_events}")
    print(f"  Face Missing Time   : {round(total_face_missing_secs,1)}s")
    print(f"  Gaze Away Time      : {round(total_gaze_away_secs,1)}s")
    print(f"  Risk Level          : {risk_level}")
    print(f"  Log saved to        : {LOG_FILE}")
    print(f"  Snapshots in        : {EVIDENCE_DIR}/")
    print("="*55)


# ─────────────────────────────────────────────
# CAMERAS
# ─────────────────────────────────────────────
print("[INFO] Connecting to cameras...")
front_cam = cv2.VideoCapture(0)
side_cam  = cv2.VideoCapture(SIDE_CAM_URL)

if not front_cam.isOpened():
    print("[ERROR] Front camera not available. Exiting.")
    exit()

if not side_cam.isOpened():
    print(f"[WARNING] Side camera not reachable at {SIDE_CAM_URL}. Using front cam as fallback.")
    side_cam = cv2.VideoCapture(0)

print("[INFO] Monitoring started. Press ESC to end session.\n")

# ─────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────
while True:
    ret1, front = front_cam.read()
    ret2, side  = side_cam.read()

    if not ret1:
        print("[ERROR] Front camera feed lost.")
        break
    if not ret2:
        side = front.copy()

    now = time.time()
    dt  = now - last_time
    last_time = now

    frame_warnings = []

    # ── 1. FACE DETECTION ────────────────────────────────────────
    face_boxes = get_faces(front)
    num_faces  = len(face_boxes)

    for (x1, y1, x2, y2) in face_boxes:
        cv2.rectangle(front, (x1,y1), (x2,y2), (0,255,0), 2)
        cv2.putText(front, "Face", (x1, y1-6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,255,0), 1)

    # ── 2. NO FACE ───────────────────────────────────────────────
    if num_faces == 0:
        face_missing_time       += dt
        total_face_missing_secs += dt
        if face_missing_time > FACE_MISSING_MAX:
            frame_warnings.append("FACE NOT DETECTED")
            cv2.putText(front, "FACE NOT DETECTED", (20, 145),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,0,255), 2)
            if add_score(2, "face_missing", now):
                log_event("FACE_MISSING", f"Missing for {face_missing_time:.1f}s")
    else:
        if face_missing_time > FACE_MISSING_MAX:
            log_event("FACE_RETURNED", f"Was missing for {face_missing_time:.1f}s")
        face_missing_time = 0.0

    # ── 3. MULTIPLE FACES ────────────────────────────────────────
    if num_faces > 1:
        total_multi_face_events += 1
        frame_warnings.append(f"MULTIPLE FACES ({num_faces})")
        cv2.putText(front, f"!! MULTIPLE FACES: {num_faces} !!", (20, 175),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0,0,255), 2)
        if add_score(3, "multi_face", now):
            log_event("MULTIPLE_FACES", f"{num_faces} faces detected")

    # ── 4. GAZE AWAY ─────────────────────────────────────────────
    if num_faces > 0 and MP_AVAILABLE:
        gaze_away = detect_gaze_away(front)
        if gaze_away:
            gaze_away_time       += dt
            total_gaze_away_secs += dt
            if gaze_away_time > GAZE_AWAY_MAX:
                frame_warnings.append("GAZE AWAY")
                cv2.putText(front, "GAZE AWAY", (20, 205),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,165,255), 2)
                if add_score(1, "gaze_away", now):
                    log_event("GAZE_AWAY", f"{gaze_away_time:.1f}s")
        else:
            if gaze_away_time > GAZE_AWAY_MAX:
                log_event("GAZE_RETURNED", f"Was away for {gaze_away_time:.1f}s")
            gaze_away_time = 0.0

    # ── 5. PHONE DETECTION ───────────────────────────────────────
    phone_found = detect_phone(side)
    if phone_found:
        total_phone_detections += 1
        frame_warnings.append("PHONE DETECTED")
        cv2.putText(side, "!! PHONE DETECTED !!", (20, 145),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,0,255), 2)
        if add_score(5, "phone", now):
            log_event("PHONE_DETECTED", "Cell phone on side camera")

    # ── 6. EVIDENCE SAVE ─────────────────────────────────────────
    if cumulative_score >= CHEAT_THRESHOLD:
        save_evidence(front, side, "cheat")

    # ── 7. HUD OVERLAY ───────────────────────────────────────────
    draw_hud(front, "FRONT")
    draw_hud(side,  "SIDE")

    # Show active warnings on side cam
    for i, warn in enumerate(frame_warnings):
        cv2.putText(side, f"[!] {warn}", (10, 160 + i * 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0,0,255), 2)

    cv2.imshow("Front Camera (Laptop Webcam)", front)
    cv2.imshow("Side Camera (Phone)",          side)

    if cv2.waitKey(1) & 0xFF == 27:
        print("\n[INFO] ESC pressed — ending session.")
        break

# ─────────────────────────────────────────────
# CLEANUP
# ─────────────────────────────────────────────
front_cam.release()
side_cam.release()
cv2.destroyAllWindows()
if MP_AVAILABLE:
    face_mesh.close()

save_report()
