import cv2
import time
from ultralytics import YOLO

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
SIDE_CAM_URL = "http://192.168.0.102:8080/video"   # Change IP
CHEAT_THRESHOLD = 10
FACE_MISSING_MAX = 3.0

# ─────────────────────────────────────────────
# LOAD YOLO MODEL
# ─────────────────────────────────────────────
print("[INFO] Loading YOLO model...")
yolo = YOLO("yolov8n.pt")

# ─────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────
cumulative_score = 0
last_time = time.time()
face_missing_time = 0

cooldown = {
    "intruder": 0,
    "phone": 0,
    "face_missing": 0,
}
COOLDOWN_SECS = 2

primary_person_box = None
frame_count = 0

# ─────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────

def is_overlapping(box1, box2, threshold=0.6):
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    if x2 < x1 or y2 < y1:
        return False

    inter_area = (x2 - x1) * (y2 - y1)
    area1 = (box1[2]-box1[0])*(box1[3]-box1[1])

    return inter_area / (area1 + 1e-6) > threshold


def add_score(amount, key, now):
    global cumulative_score
    if now - cooldown[key] > COOLDOWN_SECS:
        cumulative_score += amount
        cooldown[key] = now
        return True
    return False


def detect_objects(frame):
    results = yolo(frame, conf=0.5, verbose=False)
    persons = []
    phone_detected = False

    for r in results:
        for box in r.boxes:
            cls = int(box.cls[0])
            label = yolo.names[cls]
            x1, y1, x2, y2 = map(int, box.xyxy[0])

            if label == "person":
                persons.append((x1, y1, x2, y2))
                cv2.rectangle(frame,(x1,y1),(x2,y2),(255,0,0),2)

            if label == "cell phone":
                phone_detected = True
                cv2.rectangle(frame,(x1,y1),(x2,y2),(0,0,255),2)

    return persons, phone_detected


# ─────────────────────────────────────────────
# CAMERAS
# ─────────────────────────────────────────────
front_cam = cv2.VideoCapture(0)
side_cam  = cv2.VideoCapture(SIDE_CAM_URL)

if not front_cam.isOpened():
    print("Front cam not working")
    exit()

if not side_cam.isOpened():
    print("Side cam not reachable — fallback to front")
    side_cam = cv2.VideoCapture(0)

print("[INFO] Monitoring started. Press ESC to stop.")

# ─────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────
while True:
    ret1, front = front_cam.read()
    ret2, side  = side_cam.read()

    if not ret1:
        break
    if not ret2:
        side = front.copy()

    now = time.time()
    dt = now - last_time
    last_time = now
    frame_count += 1

    # Run YOLO every 3 frames (performance boost)
    if frame_count % 3 == 0:
        persons, phone_found = detect_objects(front)
    else:
        persons = []
        phone_found = False

    # ── PRIMARY PERSON LOCK ─────────────────────
    if primary_person_box is None and len(persons) > 0:
        primary_person_box = persons[0]

    # ── INTRUDER DETECTION ─────────────────────
    if len(persons) > 1:
        for person in persons:
            if not is_overlapping(primary_person_box, person):
                cv2.putText(front,"INTRUDER DETECTED",(20,80),
                            cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,255),3)
                add_score(4,"intruder",now)
                break

    # ── PHONE DETECTION ─────────────────────
    if phone_found:
        cv2.putText(front,"PHONE DETECTED",(20,120),
                    cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,255),3)
        add_score(5,"phone",now)

    # ── FACE MISSING (based on person detection) ─────────────────────
    if len(persons) == 0:
        face_missing_time += dt
        if face_missing_time > FACE_MISSING_MAX:
            cv2.putText(front,"NO PERSON DETECTED",(20,160),
                        cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,255),3)
            add_score(2,"face_missing",now)
    else:
        face_missing_time = 0

    # ── STATUS DISPLAY ─────────────────────
    status = "CHEATING DETECTED" if cumulative_score >= CHEAT_THRESHOLD else "NORMAL"
    color = (0,0,255) if cumulative_score >= CHEAT_THRESHOLD else (0,255,0)

    cv2.putText(front,f"Score: {cumulative_score}",(20,200),
                cv2.FONT_HERSHEY_SIMPLEX,0.8,color,2)
    cv2.putText(front,status,(20,230),
                cv2.FONT_HERSHEY_SIMPLEX,1,color,3)

    cv2.imshow("Front Camera", front)
    cv2.imshow("Side Camera", side)

    if cv2.waitKey(1) & 0xFF == 27:
        break

# ─────────────────────────────────────────────
# CLEANUP
# ─────────────────────────────────────────────
front_cam.release()
side_cam.release()
cv2.destroyAllWindows()