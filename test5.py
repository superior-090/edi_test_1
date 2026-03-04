import cv2
import numpy as np
import time
from ultralytics import YOLO
import mediapipe as mp
import threading

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
SIDE_CAM_URL = "https://192.168.88.167:8080/video"
CHEAT_THRESHOLD = 10
FACE_MISSING_MAX = 3.0
COOLDOWN_SECS = 3
YOLO_INTERVAL = 3
RESIZE_WIDTH_FRONT = 640
RESIZE_WIDTH_SIDE = 640
YOLO_SIDE_INPUT_SIZE = 480          # Larger input for side YOLO (better small-object detection)
YOLO_CONF_FRONT = 0.15             # Very low – catch small / partial phones
YOLO_CONF_SIDE = 0.15              # Very low for IP camera (noisy / lower quality)
YOLO_IMGSZ = 960                   # Higher resolution input for better small-object detection
BRIGHTNESS_ALPHA = 1.2             # Brightness multiplier for pre-processing (1.0 = no change)
BRIGHTNESS_BETA = 15               # Brightness offset (added to each pixel)
HAND_MOVEMENT_THRESHOLD = 100.0    # Minimum displacement per frame to count as a "spike"
HAND_MOVEMENT_WINDOW = 2.0         # Seconds window for tracking spikes
HAND_MOVEMENT_COUNT_LIMIT = 6      # Need this many spikes in window to trigger alert
GAZE_SIDE_THRESHOLD = 0.38
PHONE_HAND_OVERLAP_THRESH = 0.05

# Score decay
SCORE_DECAY_INTERVAL = 3.0           # Every N seconds with no new cheating event…
SCORE_DECAY_AMOUNT = 1               # …reduce score by this much

HAND_BOX_PADDING = 40              # Generous padding around hand bounding box
PHONE_NEAR_HAND_DIST = 120         # Pixel distance: phone center near hand center = holding

# Intruder IoU thresholds
IOU_SAME_PERSON = 0.5              # IoU > this → same person (update primary box)
IOU_INTRUDER = 0.3                 # IoU < this → different person (flag intruder)
PRIMARY_BOX_SMOOTH = 0.7           # EMA weight for primary box update (higher = more stable)

# ─────────────────────────────────────────────────────────────────────────────
# LOAD MODELS
# ─────────────────────────────────────────────────────────────────────────────
print("[INFO] Loading YOLO model (yolov8s)...")
yolo = YOLO("yolov8s.pt")

print("[INFO] Initializing MediaPipe Face Mesh...")
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    static_image_mode=False,
    max_num_faces=3,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
)

print("[INFO] Initializing MediaPipe Hands...")
mp_hands = mp.solutions.hands
hands_detector = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=2,
    min_detection_confidence=0.4,      # Lower for IP camera
    min_tracking_confidence=0.4,
)

mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles

# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────────────────
cumulative_score = 0
last_time = time.time()
face_missing_start = None

cooldown = {
    "intruder": 0,
    "phone_front": 0,
    "phone_hand": 0,
    "phone_side": 0,
    "face_missing": 0,
    "multiple_faces": 0,
    "hand_movement": 0,
    "gaze": 0,
    "phone_crop_front": 0,
    "phone_crop_side": 0,
}

# Score decay tracking
last_score_change_time = time.time()
last_decay_time = time.time()

primary_person_box = None
frame_count = 0

# Cached YOLO results
cached_front_persons = []
cached_front_phones = []
cached_front_books = []
cached_side_persons = []
cached_side_phones = []
cached_side_phone_boxes_raw = []     # Keep raw float boxes for distance calc

# Hand tracking history
hand_positions_history = []
hand_movement_timestamps = []

# Gaze tracking
gaze_side_count = 0
gaze_side_start = None

# Alert messages with expiry
active_alerts_front = {}
active_alerts_side = {}
ALERT_DURATION = 2.0

# ─────────────────────────────────────────────────────────────────────────────
# THREADED IP CAMERA READER (avoids buffer lag)
# ─────────────────────────────────────────────────────────────────────────────
class IPCameraReader:
    """Reads IP camera in a background thread so we always get the latest frame."""
    def __init__(self, url):
        self.cap = cv2.VideoCapture(url)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.frame = None
        self.ret = False
        self.running = False
        self.lock = threading.Lock()

        if self.cap.isOpened():
            self.running = True
            self.thread = threading.Thread(target=self._reader, daemon=True)
            self.thread.start()

    def _reader(self):
        while self.running:
            ret, frame = self.cap.read()
            with self.lock:
                self.ret = ret
                self.frame = frame
            if not ret:
                time.sleep(0.1)

    def read(self):
        with self.lock:
            if self.frame is not None:
                return self.ret, self.frame.copy()
            return False, None

    def isOpened(self):
        return self.cap.isOpened() and self.running

    def release(self):
        self.running = False
        self.cap.release()


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def resize_frame(frame, width):
    h, w = frame.shape[:2]
    if w > width:
        ratio = width / w
        return cv2.resize(frame, (width, int(h * ratio)))
    return frame


def is_overlapping(box1, box2, threshold=0.3):
    if box1 is None or box2 is None:
        return False
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    if x2 <= x1 or y2 <= y1:
        return False
    inter_area = (x2 - x1) * (y2 - y1)
    area_small = min(
        max((box1[2] - box1[0]) * (box1[3] - box1[1]), 1),
        max((box2[2] - box2[0]) * (box2[3] - box2[1]), 1),
    )
    return (inter_area / area_small) > threshold


def box_center(box):
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def center_distance(box1, box2):
    c1 = box_center(box1)
    c2 = box_center(box2)
    return np.sqrt((c1[0] - c2[0])**2 + (c1[1] - c2[1])**2)


def box_iou(box1, box2):
    if box1 is None or box2 is None:
        return 0.0
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    a1 = max((box1[2] - box1[0]) * (box1[3] - box1[1]), 1)
    a2 = max((box2[2] - box2[0]) * (box2[3] - box2[1]), 1)
    return inter / (a1 + a2 - inter + 1e-6)


def expand_box(box, pad):
    """Expand a bounding box by pad pixels on each side."""
    return (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)


def update_cheating_score(amount, key, now):
    global cumulative_score, last_score_change_time
    if now - cooldown.get(key, 0) > COOLDOWN_SECS:
        cumulative_score += amount
        cooldown[key] = now
        last_score_change_time = now
        return True
    return False


def apply_score_decay(now):
    """Gradually reduce cheating score when no new events occur,
    allowing STATUS to return to NORMAL."""
    global cumulative_score, last_decay_time
    if cumulative_score > 0:
        time_since_last_event = now - last_score_change_time
        if time_since_last_event > SCORE_DECAY_INTERVAL:
            if now - last_decay_time >= SCORE_DECAY_INTERVAL:
                cumulative_score = max(cumulative_score - SCORE_DECAY_AMOUNT, 0)
                last_decay_time = now
    else:
        last_decay_time = now


def set_alert(alerts_dict, key, message, now):
    alerts_dict[key] = {"msg": message, "expire": now + ALERT_DURATION}


def get_active_alerts(alerts_dict, now):
    active = []
    expired_keys = []
    for k, v in alerts_dict.items():
        if now < v["expire"]:
            active.append(v["msg"])
        else:
            expired_keys.append(k)
    for k in expired_keys:
        del alerts_dict[k]
    return active


# ─────────────────────────────────────────────────────────────────────────────
# DETECTION MODULES
# ─────────────────────────────────────────────────────────────────────────────

def enhance_frame(frame):
    """Slightly boost brightness and contrast to help YOLO detect dark/small objects."""
    return cv2.convertScaleAbs(frame, alpha=BRIGHTNESS_ALPHA, beta=BRIGHTNESS_BETA)


def detect_objects(frame, source="front"):
    """Run YOLO detection with brightness-enhanced input at imgsz=960.
    Side camera uses a separate upscale path for very small phones."""

    # Enhance brightness before detection
    enhanced = enhance_frame(frame)

    if source == "side":
        conf = YOLO_CONF_SIDE
        # Also upscale low-res IP camera frames for better small-object detection
        h_orig, w_orig = enhanced.shape[:2]
        scale = YOLO_SIDE_INPUT_SIZE / min(h_orig, w_orig) if min(h_orig, w_orig) < YOLO_SIDE_INPUT_SIZE else 1.0
        if scale > 1.0:
            inp = cv2.resize(enhanced, (int(w_orig * scale), int(h_orig * scale)))
        else:
            inp = enhanced
            scale = 1.0
    else:
        conf = YOLO_CONF_FRONT
        inp = enhanced
        scale = 1.0

    results = yolo(inp, conf=conf, imgsz=YOLO_IMGSZ, verbose=False)
    persons = []
    phones = []
    books = []

    for r in results:
        for box in r.boxes:
            cls = int(box.cls[0])
            label = yolo.names[cls]
            raw = box.xyxy[0].cpu().numpy()
            # Scale back to original frame coordinates
            coords = (
                int(raw[0] / scale),
                int(raw[1] / scale),
                int(raw[2] / scale),
                int(raw[3] / scale),
            )
            box_conf = float(box.conf[0])

            if label == "person":
                persons.append(coords)
            elif label == "cell phone":
                phones.append(coords)
                print(f"[{source.upper()}] Phone detected  conf={box_conf:.2f}  box={coords}")
            elif label == "book":
                books.append(coords)

    return persons, phones, books


def detect_phone_in_person_crop(frame, persons, source="front"):
    """Run a second YOLO pass on cropped person regions with very low confidence
    to catch small / partially visible phones that the full-frame pass misses.

    Steps:
      1) For each person bounding box, crop with padding.
      2) Run YOLO at conf=0.15 on the crop.
      3) If a phone is found, convert coordinates back to original frame.
      4) Return all phone boxes found this way.
    """
    crop_phones = []
    h_frame, w_frame = frame.shape[:2]

    for person in persons:
        x1, y1, x2, y2 = person
        pw = x2 - x1
        ph = y2 - y1

        # Expand crop by 20% on each side to catch phones near the body
        pad_x = int(pw * 0.20)
        pad_y = int(ph * 0.10)
        cx1 = max(x1 - pad_x, 0)
        cy1 = max(y1 - pad_y, 0)
        cx2 = min(x2 + pad_x, w_frame)
        cy2 = min(y2 + pad_y, h_frame)

        crop = frame[cy1:cy2, cx1:cx2]
        if crop.shape[0] < 30 or crop.shape[1] < 30:
            continue

        # Enhance brightness on crop for better detection
        crop = enhance_frame(crop)

        # Run YOLO with very low confidence on the crop at high resolution
        results = yolo(crop, conf=0.15, imgsz=YOLO_IMGSZ, verbose=False)

        for r in results:
            for box in r.boxes:
                cls = int(box.cls[0])
                label = yolo.names[cls]
                if label == "cell phone":
                    raw = box.xyxy[0].cpu().numpy()
                    # Convert crop-local coordinates back to full-frame coordinates
                    fx1 = int(raw[0]) + cx1
                    fy1 = int(raw[1]) + cy1
                    fx2 = int(raw[2]) + cx1
                    fy2 = int(raw[3]) + cy1
                    box_conf = float(box.conf[0])
                    crop_phones.append((fx1, fy1, fx2, fy2))
                    print(f"[{source.upper()} CROP] Phone found  conf={box_conf:.2f}  box=({fx1},{fy1},{fx2},{fy2})")

    return crop_phones


def detect_phone_in_hand_crop(frame, hand_boxes, source="side"):
    """Run a dedicated YOLO pass on cropped hand regions with very low confidence.
    Phones held in hand are often tiny and partially occluded — cropping around
    the detected hand landmarks and running YOLO on that small region at high
    resolution dramatically improves detection.

    Steps:
      1) For each hand bounding box, expand generously (50% each side).
      2) Crop that region from the frame.
      3) Enhance brightness.
      4) Run YOLO at conf=0.15 / imgsz=960 on the crop.
      5) Convert phone coordinates back to full-frame space.
    """
    crop_phones = []
    h_frame, w_frame = frame.shape[:2]

    for hand in hand_boxes:
        hx1, hy1, hx2, hy2 = hand
        hw = hx2 - hx1
        hh = hy2 - hy1

        # Expand by 50% on each side to capture phone near hand
        pad_x = int(hw * 0.50)
        pad_y = int(hh * 0.50)
        cx1 = max(hx1 - pad_x, 0)
        cy1 = max(hy1 - pad_y, 0)
        cx2 = min(hx2 + pad_x, w_frame)
        cy2 = min(hy2 + pad_y, h_frame)

        crop = frame[cy1:cy2, cx1:cx2]
        if crop.shape[0] < 20 or crop.shape[1] < 20:
            continue

        # Enhance brightness
        crop = enhance_frame(crop)

        # Run YOLO at very low confidence on the hand crop
        results = yolo(crop, conf=0.15, imgsz=YOLO_IMGSZ, verbose=False)

        for r in results:
            for box in r.boxes:
                cls = int(box.cls[0])
                label = yolo.names[cls]
                if label == "cell phone":
                    raw = box.xyxy[0].cpu().numpy()
                    # Convert crop-local → full-frame coordinates
                    fx1 = int(raw[0]) + cx1
                    fy1 = int(raw[1]) + cy1
                    fx2 = int(raw[2]) + cx1
                    fy2 = int(raw[3]) + cy1
                    box_conf = float(box.conf[0])
                    crop_phones.append((fx1, fy1, fx2, fy2))
                    print(f"[{source.upper()} HAND-CROP] Phone found  conf={box_conf:.2f}  box=({fx1},{fy1},{fx2},{fy2})")

    return crop_phones


def detect_face(frame, now):
    """Use MediaPipe Face Mesh to detect faces, gaze, and count."""
    global face_missing_start, gaze_side_count, gaze_side_start

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(rgb)

    face_count = 0
    gaze_direction = "CENTER"

    if results.multi_face_landmarks:
        face_count = len(results.multi_face_landmarks)
        for face_landmarks in results.multi_face_landmarks:
            mp_drawing.draw_landmarks(
                frame, face_landmarks, mp_face_mesh.FACEMESH_CONTOURS,
                landmark_drawing_spec=None,
                connection_drawing_spec=mp_drawing_styles.get_default_face_mesh_contours_style(),
            )

            h, w = frame.shape[:2]
            try:
                left_inner = face_landmarks.landmark[33]
                left_outer = face_landmarks.landmark[133]
                left_iris = face_landmarks.landmark[468]

                right_inner = face_landmarks.landmark[362]
                right_outer = face_landmarks.landmark[263]
                right_iris = face_landmarks.landmark[473]

                left_range = abs(left_outer.x - left_inner.x)
                left_pos = (left_iris.x - min(left_inner.x, left_outer.x)) / (left_range + 1e-6)

                right_range = abs(right_outer.x - right_inner.x)
                right_pos = (right_iris.x - min(right_inner.x, right_outer.x)) / (right_range + 1e-6)

                avg_pos = (left_pos + right_pos) / 2.0

                if avg_pos < GAZE_SIDE_THRESHOLD:
                    gaze_direction = "LEFT"
                elif avg_pos > (1.0 - GAZE_SIDE_THRESHOLD):
                    gaze_direction = "RIGHT"

                nose = face_landmarks.landmark[1]
                left_cheek = face_landmarks.landmark[234]
                right_cheek = face_landmarks.landmark[454]
                nose_ratio = (nose.x - left_cheek.x) / (right_cheek.x - left_cheek.x + 1e-6)
                if nose_ratio < 0.35:
                    gaze_direction = "HEAD_LEFT"
                elif nose_ratio > 0.65:
                    gaze_direction = "HEAD_RIGHT"

            except (IndexError, AttributeError):
                pass

    # ── FACE MISSING LOGIC ──
    if face_count == 0:
        if face_missing_start is None:
            face_missing_start = now
        elapsed = now - face_missing_start
        if elapsed > FACE_MISSING_MAX:
            set_alert(active_alerts_front, "face_missing", "NO FACE DETECTED", now)
            update_cheating_score(2, "face_missing", now)
    else:
        face_missing_start = None

    # ── MULTIPLE FACES ──
    if face_count >= 2:
        set_alert(active_alerts_front, "multi_face", "MULTIPLE CANDIDATES", now)
        update_cheating_score(5, "multiple_faces", now)

    # ── GAZE ALERTS ──
    if gaze_direction in ("LEFT", "RIGHT", "HEAD_LEFT", "HEAD_RIGHT"):
        set_alert(active_alerts_front, "gaze", f"GAZE: {gaze_direction}", now)
        update_cheating_score(2, "gaze", now)

    return face_count, gaze_direction


def detect_hands(frame, now):
    """Use MediaPipe Hands to detect hand landmarks and track movement.
    Returns hand bounding boxes with generous padding for phone-overlap check."""
    global hand_positions_history

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = hands_detector.process(rgb)
    h, w = frame.shape[:2]

    hand_boxes = []

    if results.multi_hand_landmarks:
        for idx, hand_landmarks in enumerate(results.multi_hand_landmarks):
            mp_drawing.draw_landmarks(
                frame, hand_landmarks, mp_hands.HAND_CONNECTIONS,
                mp_drawing_styles.get_default_hand_landmarks_style(),
                mp_drawing_styles.get_default_hand_connections_style(),
            )

            xs = [lm.x * w for lm in hand_landmarks.landmark]
            ys = [lm.y * h for lm in hand_landmarks.landmark]
            pad = HAND_BOX_PADDING
            x_min = max(int(min(xs)) - pad, 0)
            x_max = min(int(max(xs)) + pad, w)
            y_min = max(int(min(ys)) - pad, 0)
            y_max = min(int(max(ys)) + pad, h)
            hand_boxes.append((x_min, y_min, x_max, y_max))

            # Draw hand bounding box (cyan)
            cv2.rectangle(frame, (x_min, y_min), (x_max, y_max), (255, 255, 0), 1)

            # Wrist position for movement tracking
            wrist = hand_landmarks.landmark[mp_hands.HandLandmark.WRIST]
            cx, cy = wrist.x * w, wrist.y * h
            hand_positions_history.append({"x": cx, "y": cy, "t": now})

            # Label hand
            handedness = "Hand"
            if results.multi_handedness and idx < len(results.multi_handedness):
                handedness = results.multi_handedness[idx].classification[0].label
            cv2.putText(frame, handedness, (x_min, y_min - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

    # ── HAND MOVEMENT ANALYSIS (spike-counting method) ──
    # Prune old entries outside the time window
    hand_positions_history = [
        p for p in hand_positions_history if now - p["t"] < HAND_MOVEMENT_WINDOW
    ]

    # Count distinct movement "spikes" — frames where displacement exceeds threshold
    if len(hand_positions_history) >= 2:
        spike_count = 0
        for i in range(1, len(hand_positions_history)):
            dx = hand_positions_history[i]["x"] - hand_positions_history[i - 1]["x"]
            dy = hand_positions_history[i]["y"] - hand_positions_history[i - 1]["y"]
            displacement = np.sqrt(dx * dx + dy * dy)
            # Only count as a spike if displacement is large enough (ignore jitter)
            if displacement > HAND_MOVEMENT_THRESHOLD:
                spike_count += 1

        # Only trigger alert if we see enough distinct spikes in the window
        if spike_count >= HAND_MOVEMENT_COUNT_LIMIT:
            set_alert(active_alerts_side, "hand_move", "EXCESSIVE HAND MOVEMENT", now)
            update_cheating_score(2, "hand_movement", now)

    return hand_boxes


def smooth_box_update(old_box, new_box, alpha=PRIMARY_BOX_SMOOTH):
    """Exponential moving average update of bounding box for stable tracking.
    alpha = weight given to old box (higher = more stable, slower to drift)."""
    if old_box is None:
        return new_box
    return tuple(
        int(alpha * o + (1.0 - alpha) * n)
        for o, n in zip(old_box, new_box)
    )


def detect_intruder(persons, now):
    """Check for intruder among detected persons on front camera.
    Uses IoU-based matching:
      - IoU > IOU_SAME_PERSON (0.5) → same person, update primary box smoothly
      - IoU < IOU_INTRUDER (0.3) → different person → flag as intruder
      - IoU in between → ambiguous, ignore (no alert, no update)
    """
    global primary_person_box

    if len(persons) == 0:
        return False

    # ── First time: lock onto the largest person ──
    if primary_person_box is None:
        largest = max(persons, key=lambda b: (b[2]-b[0])*(b[3]-b[1]))
        primary_person_box = largest
        return False

    # ── Find the best IoU match to current primary ──
    best_iou = 0.0
    best_box = None
    for p in persons:
        iou_val = box_iou(primary_person_box, p)
        if iou_val > best_iou:
            best_iou = iou_val
            best_box = p

    # Smoothly update primary box ONLY if IoU is high enough (same person)
    if best_box is not None and best_iou > IOU_SAME_PERSON:
        primary_person_box = smooth_box_update(primary_person_box, best_box)
    elif best_box is not None and best_iou > IOU_INTRUDER:
        # Ambiguous zone – still likely same person with a big shift.
        # Update slowly (higher stability weight)
        primary_person_box = smooth_box_update(primary_person_box, best_box, alpha=0.9)

    # ── Check for intruders (only when >1 person) ──
    intruder_found = False
    if len(persons) > 1:
        for p in persons:
            iou_val = box_iou(primary_person_box, p)
            if iou_val < IOU_INTRUDER:
                # Confirm it's actually a separate person (not a tiny detection artifact)
                p_area = (p[2] - p[0]) * (p[3] - p[1])
                primary_area = (primary_person_box[2] - primary_person_box[0]) * \
                               (primary_person_box[3] - primary_person_box[1])
                # Ignore tiny boxes less than 10% the size of the primary person
                if p_area > primary_area * 0.10:
                    set_alert(active_alerts_front, "intruder", "INTRUDER DETECTED", now)
                    update_cheating_score(4, "intruder", now)
                    intruder_found = True
                    break

    return intruder_found


def check_phone_in_hand(hand_boxes, phone_boxes, frame, now):
    """Check if any phone bounding box overlaps with OR is close to a hand box.
    Uses three complementary strategies:
      1) IoU check  – proper intersection-over-union of phone & hand boxes
      2) Center-distance proximity check – phone center near hand center
      3) Expanded-hand-box containment – phone center inside padded hand region
    Any single strategy triggering is enough → PHONE IN HAND.
    """
    phone_in_hand = False

    for phone in phone_boxes:
        phone_cx, phone_cy = box_center(phone)

        for hand in hand_boxes:
            # ── Strategy 1: IoU-based overlap ──
            iou_val = box_iou(phone, hand)
            overlap = iou_val > PHONE_HAND_OVERLAP_THRESH

            # Also check ratio of intersection to PHONE area (small phone inside
            # large hand box can have low IoU but high overlap relative to phone)
            inter_over_phone = 0.0
            ix1 = max(phone[0], hand[0])
            iy1 = max(phone[1], hand[1])
            ix2 = min(phone[2], hand[2])
            iy2 = min(phone[3], hand[3])
            if ix2 > ix1 and iy2 > iy1:
                inter = (ix2 - ix1) * (iy2 - iy1)
                phone_area = max((phone[2]-phone[0])*(phone[3]-phone[1]), 1)
                inter_over_phone = inter / phone_area
            # If >20% of the phone is inside the hand box, that counts
            if inter_over_phone > 0.20:
                overlap = True

            # ── Strategy 2: Center distance ──
            dist = center_distance(phone, hand)
            close = dist < PHONE_NEAR_HAND_DIST

            # ── Strategy 3: Phone center inside expanded hand box ──
            exp = expand_box(hand, HAND_BOX_PADDING)
            inside = (exp[0] <= phone_cx <= exp[2]) and (exp[1] <= phone_cy <= exp[3])

            if overlap or close or inside:
                phone_in_hand = True
                # Draw highlight
                cv2.rectangle(frame, (hand[0], hand[1]), (hand[2], hand[3]),
                              (0, 0, 255), 3)
                cv2.rectangle(frame, (phone[0], phone[1]), (phone[2], phone[3]),
                              (0, 0, 255), 3)
                cv2.putText(frame, "PHONE IN HAND", (hand[0], hand[1] - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                method = f"iou={iou_val:.2f}" if overlap else (f"dist={dist:.0f}" if close else "contain")
                cv2.putText(frame, f"[{method}]",
                            (hand[0], hand[3] + 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)
                set_alert(active_alerts_side, "phone_hand", "PHONE IN HAND", now)
                update_cheating_score(7, "phone_hand", now)
                break
        if phone_in_hand:
            break

    return phone_in_hand


def check_phone_near_person_side(persons, phones, frame, now):
    """If phone detected on side camera near any person (but not necessarily
    in hand), still flag as suspicious."""
    for phone in phones:
        for person in persons:
            if is_overlapping(phone, person, threshold=0.05) or center_distance(phone, person) < 200:
                cv2.rectangle(frame, (phone[0], phone[1]), (phone[2], phone[3]),
                              (0, 100, 255), 2)
                cv2.putText(frame, "PHONE NEAR BODY", (phone[0], phone[1] - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 100, 255), 2)
                set_alert(active_alerts_side, "phone_near", "PHONE NEAR BODY", now)
                update_cheating_score(5, "phone_side", now)
                return True
    return False


def draw_status(frame, camera_label, alerts_dict, now):
    """Draw status overlay on frame."""
    h, w = frame.shape[:2]

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 45), (30, 30, 30), -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

    cv2.putText(frame, camera_label, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

    status = "CHEATING DETECTED" if cumulative_score >= CHEAT_THRESHOLD else "NORMAL"
    color = (0, 0, 255) if cumulative_score >= CHEAT_THRESHOLD else (0, 255, 0)

    score_text = f"Score: {cumulative_score}"
    cv2.putText(frame, score_text, (w - 180, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    overlay2 = frame.copy()
    cv2.rectangle(overlay2, (0, h - 40), (w, h), (30, 30, 30), -1)
    cv2.addWeighted(overlay2, 0.7, frame, 0.3, 0, frame)
    cv2.putText(frame, f"STATUS: {status}", (10, h - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    alerts = get_active_alerts(alerts_dict, now)
    y_offset = 70
    for alert_msg in alerts:
        text_size = cv2.getTextSize(alert_msg, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
        cv2.rectangle(frame, (8, y_offset - 22), (18 + text_size[0], y_offset + 6),
                      (0, 0, 180), -1)
        cv2.putText(frame, alert_msg, (12, y_offset),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        y_offset += 35


def draw_bounding_boxes(frame, persons, phones, books, is_primary=False):
    """Draw all detection bounding boxes on the frame."""
    for i, p in enumerate(persons):
        x1, y1, x2, y2 = p
        if is_primary and primary_person_box is not None:
            iou_val = box_iou(primary_person_box, p)
            if iou_val > IOU_INTRUDER:
                # This person matches or is close to the primary → green box
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, f"CANDIDATE (IoU={iou_val:.2f})", (x1, y1 - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                continue
        # Person that doesn't match primary → orange / potential intruder
        color = (0, 0, 255) if is_primary else (255, 180, 0)
        label = "INTRUDER" if is_primary else "Person"
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, label, (x1, y1 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    for p in phones:
        x1, y1, x2, y2 = p
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.putText(frame, "PHONE DETECTED", (x1, y1 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    for b in books:
        x1, y1, x2, y2 = b
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 165, 255), 2)
        cv2.putText(frame, "BOOK", (x1, y1 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)


# ─────────────────────────────────────────────────────────────────────────────
# CAMERAS
# ─────────────────────────────────────────────────────────────────────────────
print("[INFO] Opening front camera...")
front_cam = cv2.VideoCapture(0)
front_cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)

side_cam_active = True
print(f"[INFO] Opening side camera at {SIDE_CAM_URL}...")
side_cam = IPCameraReader(SIDE_CAM_URL)

if not front_cam.isOpened():
    print("[ERROR] Front camera not available. Exiting.")
    exit(1)

if not side_cam.isOpened():
    print("[WARN] Side camera not reachable. Running in front-only mode.")
    side_cam_active = False

print("[INFO] ═══════════════════════════════════════════════")
print("[INFO]   AI Exam Proctoring System Active")
print("[INFO]   Press ESC to exit  |  R to reset score")
print("[INFO] ═══════════════════════════════════════════════")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────
fps_timer = time.time()
fps_count = 0
display_fps = 0.0

while True:
    ret1, front = front_cam.read()
    if not ret1:
        print("[ERROR] Front camera read failed.")
        break

    if side_cam_active:
        ret2, side = side_cam.read()
        if not ret2 or side is None:
            print("[WARN] Side camera disconnected. Falling back.")
            side_cam_active = False
            side = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(side, "SIDE CAMERA OFFLINE", (100, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
    else:
        side = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(side, "SIDE CAMERA OFFLINE", (100, 240),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

    now = time.time()
    frame_count += 1

    # Resize for display/processing
    front = resize_frame(front, RESIZE_WIDTH_FRONT)
    side = resize_frame(side, RESIZE_WIDTH_SIDE)

    # ── RUN YOLO EVERY N FRAMES ──────────────────────────────────────────
    run_yolo = (frame_count % YOLO_INTERVAL == 0)

    if run_yolo:
        cached_front_persons, cached_front_phones, cached_front_books = detect_objects(front, "front")
        if side_cam_active:
            cached_side_persons, cached_side_phones, _ = detect_objects(side, "side")

    # ── SCORE DECAY (allows status to return to NORMAL) ────────────────
    apply_score_decay(now)

    # ── FRONT CAMERA PROCESSING ──────────────────────────────────────────

    # Face detection (every frame for responsiveness)
    face_count, gaze_dir = detect_face(front, now)

    # Intruder detection
    detect_intruder(cached_front_persons, now)

    # Phone detection (front) — full-frame pass
    if len(cached_front_phones) > 0:
        set_alert(active_alerts_front, "phone", "PHONE DETECTED", now)
        update_cheating_score(5, "phone_front", now)

    # Person-crop phone re-detection (front) — catches small/partial phones
    if run_yolo and len(cached_front_persons) > 0 and len(cached_front_phones) == 0:
        crop_phones_front = detect_phone_in_person_crop(front, cached_front_persons, "front")
        if len(crop_phones_front) > 0:
            cached_front_phones.extend(crop_phones_front)
            set_alert(active_alerts_front, "phone", "PHONE DETECTED", now)
            update_cheating_score(5, "phone_crop_front", now)

    # Hand-crop phone re-detection (front) — catches phone held up to face
    if run_yolo and len(cached_front_phones) == 0:
        # Detect hands on front camera temporarily for crop detection
        front_rgb = cv2.cvtColor(front, cv2.COLOR_BGR2RGB)
        front_hand_result = hands_detector.process(front_rgb)
        front_hand_boxes = []
        if front_hand_result.multi_hand_landmarks:
            fh, fw = front.shape[:2]
            for hlm in front_hand_result.multi_hand_landmarks:
                xs = [lm.x * fw for lm in hlm.landmark]
                ys = [lm.y * fh for lm in hlm.landmark]
                pad = HAND_BOX_PADDING
                front_hand_boxes.append((
                    max(int(min(xs)) - pad, 0),
                    max(int(min(ys)) - pad, 0),
                    min(int(max(xs)) + pad, fw),
                    min(int(max(ys)) + pad, fh),
                ))
        if len(front_hand_boxes) > 0:
            hand_crop_phones_front = detect_phone_in_hand_crop(front, front_hand_boxes, "front")
            if len(hand_crop_phones_front) > 0:
                cached_front_phones.extend(hand_crop_phones_front)
                set_alert(active_alerts_front, "phone", "PHONE DETECTED", now)
                update_cheating_score(5, "phone_crop_front", now)

    # Book detection (front)
    if len(cached_front_books) > 0:
        set_alert(active_alerts_front, "book", "BOOK DETECTED", now)

    # Draw front detections
    draw_bounding_boxes(front, cached_front_persons, cached_front_phones,
                        cached_front_books, is_primary=True)

    # ── SIDE CAMERA PROCESSING ───────────────────────────────────────────
    if side_cam_active:
        # Hand detection (runs every frame for smooth tracking)
        hand_boxes = detect_hands(side, now)

        # Person-crop phone re-detection (side) — catches hidden phones
        if run_yolo and len(cached_side_persons) > 0 and len(cached_side_phones) == 0:
            crop_phones_side = detect_phone_in_person_crop(side, cached_side_persons, "side")
            if len(crop_phones_side) > 0:
                cached_side_phones.extend(crop_phones_side)

        # Hand-crop phone re-detection (side) — catches phone held in hand
        if run_yolo and len(hand_boxes) > 0 and len(cached_side_phones) == 0:
            hand_crop_phones = detect_phone_in_hand_crop(side, hand_boxes, "side")
            if len(hand_crop_phones) > 0:
                cached_side_phones.extend(hand_crop_phones)

        # Phone-in-hand check (primary – uses overlap + proximity + containment)
        phone_in_hand = False
        if len(cached_side_phones) > 0 and len(hand_boxes) > 0:
            phone_in_hand = check_phone_in_hand(hand_boxes, cached_side_phones, side, now)

        # Phone near person body (secondary – if phone visible but not in hand)
        if len(cached_side_phones) > 0 and not phone_in_hand:
            if len(cached_side_persons) > 0:
                check_phone_near_person_side(cached_side_persons, cached_side_phones, side, now)
            else:
                # Phone visible but no person/hand context – still suspicious
                set_alert(active_alerts_side, "phone_side_raw", "PHONE VISIBLE (SIDE)", now)
                update_cheating_score(5, "phone_side", now)

        # Draw side detections
        draw_bounding_boxes(side, cached_side_persons, cached_side_phones, [],
                            is_primary=False)

        # Draw hand boxes explicitly for debugging
        for hb in hand_boxes:
            cv2.rectangle(side, (hb[0], hb[1]), (hb[2], hb[3]), (255, 255, 0), 1)

    # ── DRAW STATUS OVERLAYS ─────────────────────────────────────────────
    draw_status(front, "FRONT CAMERA", active_alerts_front, now)
    draw_status(side, "SIDE CAMERA", active_alerts_side, now)

    # ── FPS COUNTER ──────────────────────────────────────────────────────
    fps_count += 1
    if now - fps_timer >= 1.0:
        display_fps = fps_count / (now - fps_timer)
        fps_count = 0
        fps_timer = now

    cv2.putText(front, f"FPS: {display_fps:.1f}", (front.shape[1] - 130, 65),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    cv2.putText(side, f"FPS: {display_fps:.1f}", (side.shape[1] - 130, 65),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

    # ── DISPLAY ──────────────────────────────────────────────────────────
    cv2.imshow("Front Camera", front)
    cv2.imshow("Side Camera", side)

    key = cv2.waitKey(1) & 0xFF
    if key == 27:  # ESC
        print("[INFO] ESC pressed. Exiting...")
        break
    elif key == ord('r'):
        cumulative_score = 0
        print("[INFO] Score reset.")

# ─────────────────────────────────────────────────────────────────────────────
# CLEANUP
# ─────────────────────────────────────────────────────────────────────────────
print("[INFO] Releasing resources...")
front_cam.release()
if side_cam_active:
    side_cam.release()
face_mesh.close()
hands_detector.close()
cv2.destroyAllWindows()
print("[INFO] Proctoring session ended.")
