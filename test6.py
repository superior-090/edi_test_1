"""
AI Exam Proctoring System - Fixed Phone Detection
==================================================
Key fixes for phone detection:
- Lowered YOLO confidence for phones
- Relaxed phone validation rules
- Added person-crop and hand-crop phone detection
- Fixed temporal smoothing for YOLO interval
- Added debug output for phone detection
"""

import cv2
import numpy as np
import time
import math
from collections import deque
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional, Deque
from ultralytics import YOLO
import mediapipe as mp
import threading

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Config:
    """Central configuration for all system parameters."""
    
    # Camera settings
    SIDE_CAM_URL: str = "https://192.168.0.111:8080/video"
    RESIZE_WIDTH_FRONT: int = 640
    RESIZE_WIDTH_SIDE: int = 640
    
    # YOLO settings - FIX: Lower confidence for better phone detection
    YOLO_INTERVAL: int = 3
    YOLO_CONF_FRONT: float = 0.20  # Lowered from 0.25
    YOLO_CONF_SIDE: float = 0.20
    YOLO_CONF_PHONE: float = 0.15  # Even lower for phone-specific detection
    YOLO_IMGSZ: int = 640
    YOLO_SIDE_INPUT_SIZE: int = 480
    
    # Scoring
    CHEAT_THRESHOLD: int = 10
    SCORE_DECAY_INTERVAL: float = 5.0
    SCORE_DECAY_AMOUNT: int = 1
    EVENT_COOLDOWN_SECS: float = 5.0
    
    # Face detection
    FACE_MISSING_MAX: float = 3.0
    FACE_BOX_SMOOTH_ALPHA: float = 0.7
    FACE_PERSIST_TIMEOUT: float = 2.0
    
    # Temporal smoothing - FIX: Adjusted for YOLO interval
    DETECTION_HISTORY_LEN: int = 5
    DETECTION_CONFIRM_MIN: int = 2  # Lowered from 3 - only need 2/5 now
    DETECTION_RESET_FRAMES: int = 5
    
    # Phone validation - FIX: Much more relaxed
    PHONE_MIN_AREA: int = 800  # Lowered from 1500
    PHONE_MAX_AREA_RATIO: float = 0.5  # Phone can't be more than 50% of frame
    PHONE_MIN_FRAMES: int = 2  # Lowered from 3
    PHONE_HAND_OVERLAP_THRESH: float = 0.10
    PHONE_NEAR_HAND_DIST: int = 120
    PHONE_PERSON_MARGIN: int = 100  # Pixels outside person still valid
    
    # Intruder detection
    INTRUDER_MIN_AREA_RATIO: float = 0.10
    INTRUDER_MAX_IOU: float = 0.30
    INTRUDER_PERSIST_FRAMES: int = 3
    PRIMARY_PERSON_TIMEOUT: float = 5.0
    
    # Hand movement
    HAND_MOVEMENT_THRESHOLD: float = 50.0
    HAND_MOVEMENT_WINDOW: float = 2.0
    HAND_MOVEMENT_SPIKE_LIMIT: int = 8
    DESK_ZONE_Y_RATIO: float = 0.65
    HAND_BOX_PADDING: int = 40
    
    # Gaze detection
    GAZE_LEFT_THRESHOLD: float = 0.35
    GAZE_RIGHT_THRESHOLD: float = 0.65
    GAZE_PERSIST_TIME: float = 1.5
    
    # Head pose
    HEAD_YAW_THRESHOLD: float = 30.0
    HEAD_PITCH_DOWN_THRESHOLD: float = -20.0
    HEAD_POSE_PERSIST_TIME: float = 1.0
    HEAD_POSE_SMOOTH_ALPHA: float = 0.7
    
    # Camera obstruction
    CAM_BLOCK_BRIGHTNESS_MIN: int = 50
    CAM_BLOCK_LAPLACIAN_MIN: float = 40.0
    CAM_BLOCK_DARK_RATIO: float = 0.75
    CAM_BLOCK_CONDITIONS_REQUIRED: int = 2
    CAM_BLOCK_SCORE: int = 6
    BRIGHTNESS_HISTORY_LEN: int = 30
    BRIGHTNESS_DROP_RATIO: float = 0.45
    
    # UI
    ALERT_DURATION: float = 2.5
    
    # Debug
    DEBUG_PHONE: bool = True  # Enable phone detection debug output
    
    # Brightness enhancement
    BRIGHTNESS_ALPHA: float = 1.15
    BRIGHTNESS_BETA: int = 10


CFG = Config()


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class BoundingBox:
    """Bounding box with helper methods."""
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float = 1.0  # Added confidence tracking
    
    @property
    def center(self) -> Tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)
    
    @property
    def area(self) -> int:
        return max(0, (self.x2 - self.x1) * (self.y2 - self.y1))
    
    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)
    
    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)
    
    @property
    def aspect_ratio(self) -> float:
        return self.width / max(self.height, 1)
    
    def iou(self, other: 'BoundingBox') -> float:
        ix1 = max(self.x1, other.x1)
        iy1 = max(self.y1, other.y1)
        ix2 = min(self.x2, other.x2)
        iy2 = min(self.y2, other.y2)
        
        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0
        
        inter = (ix2 - ix1) * (iy2 - iy1)
        union = self.area + other.area - inter
        return inter / max(union, 1e-6)
    
    def intersection_over_self(self, other: 'BoundingBox') -> float:
        """What fraction of self is covered by other."""
        ix1 = max(self.x1, other.x1)
        iy1 = max(self.y1, other.y1)
        ix2 = min(self.x2, other.x2)
        iy2 = min(self.y2, other.y2)
        
        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0
        
        inter = (ix2 - ix1) * (iy2 - iy1)
        return inter / max(self.area, 1)
    
    def distance_to(self, other: 'BoundingBox') -> float:
        c1 = self.center
        c2 = other.center
        return math.sqrt((c1[0] - c2[0])**2 + (c1[1] - c2[1])**2)
    
    def contains_point(self, x: float, y: float) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2
    
    def expand(self, padding: int) -> 'BoundingBox':
        return BoundingBox(
            self.x1 - padding, self.y1 - padding,
            self.x2 + padding, self.y2 + padding,
            self.confidence
        )
    
    def clamp(self, width: int, height: int) -> 'BoundingBox':
        return BoundingBox(
            max(0, min(self.x1, width)),
            max(0, min(self.y1, height)),
            max(0, min(self.x2, width)),
            max(0, min(self.y2, height)),
            self.confidence
        )
    
    def smooth_update(self, new_box: 'BoundingBox', alpha: float) -> 'BoundingBox':
        return BoundingBox(
            int(alpha * self.x1 + (1 - alpha) * new_box.x1),
            int(alpha * self.y1 + (1 - alpha) * new_box.y1),
            int(alpha * self.x2 + (1 - alpha) * new_box.x2),
            int(alpha * self.y2 + (1 - alpha) * new_box.y2),
            new_box.confidence
        )


@dataclass
class DetectionHistory:
    """Rolling buffer for temporal smoothing."""
    history: Deque[bool] = field(default_factory=lambda: deque(maxlen=CFG.DETECTION_HISTORY_LEN))
    absent_count: int = 0
    last_detection_frame: int = 0
    
    def update(self, detected: bool, frame_num: int = 0):
        if detected:
            self.absent_count = 0
            self.last_detection_frame = frame_num
        else:
            self.absent_count += 1
            if self.absent_count >= CFG.DETECTION_RESET_FRAMES:
                self.history.clear()
        
        self.history.append(detected)
    
    def is_confirmed(self) -> bool:
        """Check if detection is temporally confirmed."""
        if len(self.history) < 1:
            return False
        # FIX: More lenient - if detected in recent frames, confirm it
        recent = list(self.history)[-3:] if len(self.history) >= 3 else list(self.history)
        return sum(recent) >= min(CFG.DETECTION_CONFIRM_MIN, len(recent))
    
    def reset(self):
        self.history.clear()
        self.absent_count = 0


@dataclass 
class PersistenceTracker:
    """Track how long a condition has persisted."""
    start_time: Optional[float] = None
    last_active: float = 0.0
    
    def update(self, is_active: bool, now: float) -> float:
        if is_active:
            if self.start_time is None:
                self.start_time = now
            self.last_active = now
            return now - self.start_time
        else:
            if self.start_time is not None and (now - self.last_active) > 0.3:
                self.start_time = None
            return 0.0
    
    def reset(self):
        self.start_time = None


@dataclass
class KalmanBoxFilter:
    """Simple filter for box stabilization."""
    state: Optional[BoundingBox] = None
    last_update: float = 0.0
    
    def update(self, measurement: Optional[BoundingBox], now: float) -> Optional[BoundingBox]:
        if measurement is None:
            if self.state is not None and (now - self.last_update) < CFG.FACE_PERSIST_TIMEOUT:
                return self.state
            return None
        
        if self.state is None:
            self.state = measurement
            self.last_update = now
            return self.state
        
        self.state = self.state.smooth_update(measurement, CFG.FACE_BOX_SMOOTH_ALPHA)
        self.last_update = now
        return self.state
    
    def reset(self):
        self.state = None


# ═══════════════════════════════════════════════════════════════════════════════
# THREADED IP CAMERA READER
# ═══════════════════════════════════════════════════════════════════════════════

class IPCameraReader:
    """Reads IP camera in background thread."""
    
    def __init__(self, url: str):
        self.url = url
        self.cap = cv2.VideoCapture(url)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.frame: Optional[np.ndarray] = None
        self.ret = False
        self.running = False
        self.lock = threading.Lock()
        self.error_count = 0
        
        if self.cap.isOpened():
            self.running = True
            self.thread = threading.Thread(target=self._reader, daemon=True)
            self.thread.start()
    
    def _reader(self):
        while self.running:
            try:
                ret, frame = self.cap.read()
                with self.lock:
                    self.ret = ret
                    if ret:
                        self.frame = frame
                        self.error_count = 0
                    else:
                        self.error_count += 1
                
                if not ret:
                    time.sleep(0.1)
                    if self.error_count > 30:
                        self._reconnect()
            except Exception:
                time.sleep(0.1)
    
    def _reconnect(self):
        try:
            self.cap.release()
            self.cap = cv2.VideoCapture(self.url)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.error_count = 0
        except Exception:
            pass
    
    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        with self.lock:
            if self.frame is not None:
                return self.ret, self.frame.copy()
            return False, None
    
    def isOpened(self) -> bool:
        return self.cap.isOpened() and self.running
    
    def release(self):
        self.running = False
        try:
            self.cap.release()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ═══════════════════════════════════════════════════════════════════════════════

class SessionState:
    """Centralized session state management."""
    
    def __init__(self):
        self.cumulative_score = 0
        self.last_score_change_time = time.time()
        self.last_decay_time = time.time()
        self.event_last_time: Dict[str, float] = {}
        
        self.face_filter = KalmanBoxFilter()
        self.face_missing_start: Optional[float] = None
        self.current_face_landmarks = None
        
        self.primary_person_box: Optional[BoundingBox] = None
        self.primary_person_last_seen: Optional[float] = None
        
        self.smoothed_yaw = 0.0
        self.smoothed_pitch = 0.0
        self.yaw_persist = PersistenceTracker()
        self.pitch_persist = PersistenceTracker()
        
        self.gaze_persist = PersistenceTracker()
        self.last_gaze_direction = "CENTER"
        
        self.phone_history_front = DetectionHistory()
        self.phone_history_side = DetectionHistory()
        self.intruder_history = DetectionHistory()
        
        # Phone tracking across frames
        self.phone_tracks_front: Dict[str, Dict] = {}
        self.phone_tracks_side: Dict[str, Dict] = {}
        
        self.hand_positions: Deque[Dict] = deque(maxlen=100)
        
        # Cached YOLO results
        self.cached_front_persons: List[BoundingBox] = []
        self.cached_front_phones: List[BoundingBox] = []
        self.cached_front_books: List[BoundingBox] = []
        self.cached_side_persons: List[BoundingBox] = []
        self.cached_side_phones: List[BoundingBox] = []
        
        # Raw detections (before validation)
        self.raw_front_phones: List[BoundingBox] = []
        self.raw_side_phones: List[BoundingBox] = []
        
        self.brightness_history_front: Deque[float] = deque(maxlen=CFG.BRIGHTNESS_HISTORY_LEN)
        self.brightness_history_side: Deque[float] = deque(maxlen=CFG.BRIGHTNESS_HISTORY_LEN)
        
        self.alerts_front: Dict[str, Dict] = {}
        self.alerts_side: Dict[str, Dict] = {}
        
        self.fps_front = 0.0
        self.fps_side = 0.0
        self.fps_front_counter = 0
        self.fps_side_counter = 0
        self.fps_front_timer = time.time()
        self.fps_side_timer = time.time()
        
        self.frame_count = 0
    
    def reset(self):
        self.cumulative_score = 0
        self.event_last_time.clear()
        self.face_filter.reset()
        self.face_missing_start = None
        self.primary_person_box = None
        self.primary_person_last_seen = None
        self.smoothed_yaw = 0.0
        self.smoothed_pitch = 0.0
        self.yaw_persist.reset()
        self.pitch_persist.reset()
        self.gaze_persist.reset()
        self.phone_history_front.reset()
        self.phone_history_side.reset()
        self.intruder_history.reset()
        self.phone_tracks_front.clear()
        self.phone_tracks_side.clear()
        self.hand_positions.clear()
        self.cached_front_persons.clear()
        self.cached_front_phones.clear()
        self.cached_front_books.clear()
        self.cached_side_persons.clear()
        self.cached_side_phones.clear()
        self.raw_front_phones.clear()
        self.raw_side_phones.clear()
        self.alerts_front.clear()
        self.alerts_side.clear()


state = SessionState()


# ═══════════════════════════════════════════════════════════════════════════════
# ALERT AND SCORING
# ═══════════════════════════════════════════════════════════════════════════════

def set_alert(alerts: Dict, key: str, message: str, now: float):
    alerts[key] = {"msg": message, "expire": now + CFG.ALERT_DURATION}


def get_active_alerts(alerts: Dict, now: float) -> List[str]:
    active = []
    expired = []
    for key, val in alerts.items():
        if now < val["expire"]:
            active.append(val["msg"])
        else:
            expired.append(key)
    for key in expired:
        del alerts[key]
    return active


def is_event_suppressed(key: str, now: float) -> bool:
    last_time = state.event_last_time.get(key, 0)
    return (now - last_time) < CFG.EVENT_COOLDOWN_SECS


def update_score(amount: int, key: str, now: float) -> bool:
    if is_event_suppressed(key, now):
        return False
    
    state.cumulative_score += amount
    state.last_score_change_time = now
    state.event_last_time[key] = now
    print(f"[SCORE] +{amount} for {key}, total={state.cumulative_score}")
    return True


def apply_score_decay(now: float):
    if state.cumulative_score <= 0:
        state.last_decay_time = now
        return
    
    time_since_event = now - state.last_score_change_time
    if time_since_event > CFG.SCORE_DECAY_INTERVAL:
        if now - state.last_decay_time >= CFG.SCORE_DECAY_INTERVAL:
            state.cumulative_score = max(0, state.cumulative_score - CFG.SCORE_DECAY_AMOUNT)
            state.last_decay_time = now


# ═══════════════════════════════════════════════════════════════════════════════
# IMAGE PROCESSING
# ═══════════════════════════════════════════════════════════════════════════════

def resize_frame(frame: np.ndarray, width: int) -> np.ndarray:
    h, w = frame.shape[:2]
    if w > width:
        ratio = width / w
        return cv2.resize(frame, (width, int(h * ratio)))
    return frame


def enhance_frame(frame: np.ndarray) -> np.ndarray:
    return cv2.convertScaleAbs(frame, alpha=CFG.BRIGHTNESS_ALPHA, beta=CFG.BRIGHTNESS_BETA)


# ═══════════════════════════════════════════════════════════════════════════════
# CAMERA OBSTRUCTION DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def detect_camera_block(frame: np.ndarray, camera: str, now: float) -> Tuple[bool, str, Dict]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    frame_area = h * w
    debug = {}
    conditions_failed = 0
    reasons = []
    
    brightness_history = (state.brightness_history_front if camera == "front" 
                         else state.brightness_history_side)
    
    brightness = float(np.mean(gray))
    debug["brightness"] = brightness
    if brightness < CFG.CAM_BLOCK_BRIGHTNESS_MIN:
        conditions_failed += 1
        reasons.append("DARK")
    
    laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    debug["laplacian"] = laplacian_var
    if laplacian_var < CFG.CAM_BLOCK_LAPLACIAN_MIN:
        conditions_failed += 1
        reasons.append("BLUR")
    
    dark_pixels = int(np.sum(gray < 40))
    dark_ratio = dark_pixels / frame_area
    debug["dark_ratio"] = dark_ratio
    if dark_ratio > CFG.CAM_BLOCK_DARK_RATIO:
        conditions_failed += 1
        reasons.append("MOSTLY_DARK")
    
    brightness_history.append(brightness)
    if len(brightness_history) >= 10:
        avg_brightness = np.mean(list(brightness_history)[:-1])
        if avg_brightness > 0 and brightness < avg_brightness * CFG.BRIGHTNESS_DROP_RATIO:
            conditions_failed += 1
            reasons.append("SUDDEN_DROP")
    
    edges = cv2.Canny(gray, 50, 150)
    edge_density = np.count_nonzero(edges) / frame_area
    debug["edge_density"] = edge_density
    if edge_density < 0.01:
        conditions_failed += 1
        reasons.append("NO_EDGES")
    
    is_blocked = conditions_failed >= CFG.CAM_BLOCK_CONDITIONS_REQUIRED
    reason = " + ".join(reasons) if is_blocked else ""
    
    return is_blocked, reason, debug


# ═══════════════════════════════════════════════════════════════════════════════
# YOLO OBJECT DETECTION - FIXED PHONE DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def detect_objects(frame: np.ndarray, yolo: YOLO, source: str = "front") -> Tuple[
    List[BoundingBox], List[BoundingBox], List[BoundingBox]]:
    """Run YOLO detection with improved phone detection."""
    
    enhanced = enhance_frame(frame)
    h_frame, w_frame = frame.shape[:2]
    frame_area = h_frame * w_frame
    
    # Use lower confidence for phones
    conf = CFG.YOLO_CONF_PHONE  # Use phone-specific lower confidence
    
    results = yolo(enhanced, conf=conf, imgsz=CFG.YOLO_IMGSZ, verbose=False)
    
    persons = []
    phones = []
    books = []
    
    for r in results:
        for box in r.boxes:
            cls = int(box.cls[0])
            label = yolo.names[cls]
            raw = box.xyxy[0].cpu().numpy()
            box_conf = float(box.conf[0])
            
            bbox = BoundingBox(
                int(raw[0]), int(raw[1]),
                int(raw[2]), int(raw[3]),
                box_conf
            )
            
            if label == "person":
                persons.append(bbox)
            elif label == "cell phone":
                # Basic size filtering only
                if bbox.area >= CFG.PHONE_MIN_AREA:
                    area_ratio = bbox.area / frame_area
                    if area_ratio < CFG.PHONE_MAX_AREA_RATIO:
                        phones.append(bbox)
                        if CFG.DEBUG_PHONE:
                            print(f"[{source.upper()}] Phone detected: conf={box_conf:.2f}, "
                                  f"area={bbox.area}, box=({bbox.x1},{bbox.y1},{bbox.x2},{bbox.y2})")
            elif label == "book":
                books.append(bbox)
    
    return persons, phones, books


def detect_phone_in_crop(
    frame: np.ndarray, 
    regions: List[BoundingBox], 
    yolo: YOLO,
    source: str = "front",
    region_type: str = "person"
) -> List[BoundingBox]:
    """
    Run YOLO on cropped regions to find phones that might be missed.
    FIX: This catches phones that are partially occluded or in hands.
    """
    crop_phones = []
    h_frame, w_frame = frame.shape[:2]
    
    for region in regions:
        # Expand region with padding
        if region_type == "person":
            pad_x = int((region.x2 - region.x1) * 0.15)
            pad_y = int((region.y2 - region.y1) * 0.10)
        else:  # hand
            pad_x = int((region.x2 - region.x1) * 0.50)
            pad_y = int((region.y2 - region.y1) * 0.50)
        
        cx1 = max(region.x1 - pad_x, 0)
        cy1 = max(region.y1 - pad_y, 0)
        cx2 = min(region.x2 + pad_x, w_frame)
        cy2 = min(region.y2 + pad_y, h_frame)
        
        crop = frame[cy1:cy2, cx1:cx2]
        if crop.shape[0] < 30 or crop.shape[1] < 30:
            continue
        
        crop = enhance_frame(crop)
        
        # Very low confidence for crop detection
        results = yolo(crop, conf=0.12, imgsz=CFG.YOLO_IMGSZ, verbose=False)
        
        for r in results:
            for box in r.boxes:
                cls = int(box.cls[0])
                label = yolo.names[cls]
                
                if label == "cell phone":
                    raw = box.xyxy[0].cpu().numpy()
                    box_conf = float(box.conf[0])
                    
                    # Convert back to full frame coordinates
                    bbox = BoundingBox(
                        int(raw[0]) + cx1,
                        int(raw[1]) + cy1,
                        int(raw[2]) + cx1,
                        int(raw[3]) + cy1,
                        box_conf
                    )
                    
                    # Basic size check
                    if bbox.area >= CFG.PHONE_MIN_AREA // 2:  # More lenient for crops
                        crop_phones.append(bbox)
                        if CFG.DEBUG_PHONE:
                            print(f"[{source.upper()} {region_type.upper()}-CROP] Phone found: "
                                  f"conf={box_conf:.2f}, box=({bbox.x1},{bbox.y1},{bbox.x2},{bbox.y2})")
    
    return crop_phones


def validate_phones(
    phones: List[BoundingBox],
    persons: List[BoundingBox],
    hands: List[BoundingBox],
    frame_h: int,
    frame_w: int,
    source: str = "front"
) -> List[BoundingBox]:
    """
    FIX: Much more lenient phone validation.
    A phone is valid if ANY of these conditions are met:
    1. High confidence (>0.3)
    2. Overlaps with hand
    3. Near a hand
    4. Inside or near person box
    5. Has phone-like aspect ratio
    """
    validated = []
    frame_area = frame_h * frame_w
    
    for phone in phones:
        is_valid = False
        reason = ""
        
        # Condition 1: High confidence phone
        if phone.confidence >= 0.30:
            is_valid = True
            reason = "HIGH_CONF"
        
        # Condition 2: Overlaps with hand
        if not is_valid:
            for hand in hands:
                if phone.iou(hand) > 0.05 or phone.intersection_over_self(hand) > 0.2:
                    is_valid = True
                    reason = "HAND_OVERLAP"
                    break
        
        # Condition 3: Near a hand
        if not is_valid:
            for hand in hands:
                if phone.distance_to(hand) < CFG.PHONE_NEAR_HAND_DIST:
                    is_valid = True
                    reason = "NEAR_HAND"
                    break
        
        # Condition 4: Inside or near person
        if not is_valid:
            for person in persons:
                # Check if inside person box
                cx, cy = phone.center
                if person.contains_point(cx, cy):
                    is_valid = True
                    reason = "IN_PERSON"
                    break
                
                # Check if near person (with margin)
                expanded = person.expand(CFG.PHONE_PERSON_MARGIN)
                if expanded.contains_point(cx, cy):
                    is_valid = True
                    reason = "NEAR_PERSON"
                    break
                
                # Check overlap
                if phone.iou(person) > 0.05:
                    is_valid = True
                    reason = "PERSON_OVERLAP"
                    break
        
        # Condition 5: Phone-like aspect ratio (0.4 to 2.5 typical)
        if not is_valid:
            ar = phone.aspect_ratio
            if 0.3 <= ar <= 3.0 and phone.confidence >= 0.20:
                is_valid = True
                reason = "PHONE_SHAPE"
        
        # Condition 6: If no persons detected, accept any reasonable phone
        if not is_valid and len(persons) == 0:
            if phone.confidence >= 0.20:
                is_valid = True
                reason = "NO_PERSON_CHECK"
        
        if is_valid:
            validated.append(phone)
            if CFG.DEBUG_PHONE:
                print(f"[{source.upper()}] Phone VALIDATED: {reason}, conf={phone.confidence:.2f}")
        else:
            if CFG.DEBUG_PHONE:
                print(f"[{source.upper()}] Phone REJECTED: conf={phone.confidence:.2f}")
    
    return validated


# ═══════════════════════════════════════════════════════════════════════════════
# FACE DETECTION AND HEAD POSE
# ═══════════════════════════════════════════════════════════════════════════════

def extract_face_box(face_landmarks, h: int, w: int) -> Optional[BoundingBox]:
    try:
        indices = [10, 152, 234, 454, 33, 263, 1, 61, 291]
        xs = []
        ys = []
        for idx in indices:
            lm = face_landmarks.landmark[idx]
            xs.append(lm.x * w)
            ys.append(lm.y * h)
        
        if not xs:
            return None
        
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        pad_x = (x_max - x_min) * 0.15
        pad_y = (y_max - y_min) * 0.15
        
        return BoundingBox(
            int(max(0, x_min - pad_x)),
            int(max(0, y_min - pad_y)),
            int(min(w, x_max + pad_x)),
            int(min(h, y_max + pad_y))
        )
    except (IndexError, AttributeError):
        return None


def estimate_head_pose(face_landmarks, h: int, w: int) -> Tuple[float, float, float]:
    try:
        model_points = np.array([
            (0.0, 0.0, 0.0),
            (0.0, -330.0, -65.0),
            (-225.0, 170.0, -135.0),
            (225.0, 170.0, -135.0),
            (-150.0, -150.0, -125.0),
            (150.0, -150.0, -125.0),
        ], dtype=np.float64)
        
        indices = [1, 152, 33, 263, 61, 291]
        image_points = np.array([
            (face_landmarks.landmark[idx].x * w, face_landmarks.landmark[idx].y * h)
            for idx in indices
        ], dtype=np.float64)
        
        focal_length = w
        center = (w / 2, h / 2)
        camera_matrix = np.array([
            [focal_length, 0, center[0]],
            [0, focal_length, center[1]],
            [0, 0, 1]
        ], dtype=np.float64)
        
        dist_coeffs = np.zeros((4, 1))
        
        success, rotation_vec, _ = cv2.solvePnP(
            model_points, image_points, camera_matrix, dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE
        )
        
        if not success:
            return 0.0, 0.0, 0.0
        
        rotation_mat, _ = cv2.Rodrigues(rotation_vec)
        
        sy = math.sqrt(rotation_mat[0, 0]**2 + rotation_mat[1, 0]**2)
        singular = sy < 1e-6
        
        if not singular:
            x = math.atan2(rotation_mat[2, 1], rotation_mat[2, 2])
            y = math.atan2(-rotation_mat[2, 0], sy)
            z = math.atan2(rotation_mat[1, 0], rotation_mat[0, 0])
        else:
            x = math.atan2(-rotation_mat[1, 2], rotation_mat[1, 1])
            y = math.atan2(-rotation_mat[2, 0], sy)
            z = 0
        
        pitch = max(-90, min(90, math.degrees(x)))
        yaw = max(-90, min(90, math.degrees(y)))
        roll = math.degrees(z)
        
        return yaw, pitch, roll
        
    except Exception:
        return 0.0, 0.0, 0.0


def detect_gaze(face_landmarks, h: int, w: int) -> str:
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
        
        if avg_pos < CFG.GAZE_LEFT_THRESHOLD:
            return "LEFT"
        elif avg_pos > CFG.GAZE_RIGHT_THRESHOLD:
            return "RIGHT"
        
        nose = face_landmarks.landmark[1]
        left_cheek = face_landmarks.landmark[234]
        right_cheek = face_landmarks.landmark[454]
        nose_ratio = (nose.x - left_cheek.x) / (right_cheek.x - left_cheek.x + 1e-6)
        
        if nose_ratio < 0.35:
            return "HEAD_LEFT"
        elif nose_ratio > 0.65:
            return "HEAD_RIGHT"
        
        return "CENTER"
        
    except (IndexError, AttributeError):
        return "CENTER"


def detect_face(frame: np.ndarray, face_mesh, now: float) -> Tuple[int, str]:
    h, w = frame.shape[:2]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(rgb)
    
    face_count = 0
    gaze_direction = "CENTER"
    new_face_box = None
    
    mp_drawing = mp.solutions.drawing_utils
    mp_drawing_styles = mp.solutions.drawing_styles
    mp_face_mesh = mp.solutions.face_mesh
    
    if results.multi_face_landmarks:
        face_count = len(results.multi_face_landmarks)
        primary_face = results.multi_face_landmarks[0]
        state.current_face_landmarks = primary_face
        
        new_face_box = extract_face_box(primary_face, h, w)
        
        for face_lm in results.multi_face_landmarks:
            mp_drawing.draw_landmarks(
                frame, face_lm, mp_face_mesh.FACEMESH_CONTOURS,
                landmark_drawing_spec=None,
                connection_drawing_spec=mp_drawing_styles.get_default_face_mesh_contours_style()
            )
        
        yaw, pitch, roll = estimate_head_pose(primary_face, h, w)
        
        state.smoothed_yaw = (CFG.HEAD_POSE_SMOOTH_ALPHA * state.smoothed_yaw + 
                             (1 - CFG.HEAD_POSE_SMOOTH_ALPHA) * yaw)
        state.smoothed_pitch = (CFG.HEAD_POSE_SMOOTH_ALPHA * state.smoothed_pitch + 
                               (1 - CFG.HEAD_POSE_SMOOTH_ALPHA) * pitch)
        
        yaw_active = abs(state.smoothed_yaw) > CFG.HEAD_YAW_THRESHOLD
        yaw_duration = state.yaw_persist.update(yaw_active, now)
        if yaw_duration > CFG.HEAD_POSE_PERSIST_TIME:
            direction = "LEFT" if state.smoothed_yaw < 0 else "RIGHT"
            set_alert(state.alerts_front, "head_yaw", f"LOOKING {direction}", now)
            update_score(2, "head_yaw", now)
        
        pitch_active = state.smoothed_pitch < CFG.HEAD_PITCH_DOWN_THRESHOLD
        pitch_duration = state.pitch_persist.update(pitch_active, now)
        if pitch_duration > CFG.HEAD_POSE_PERSIST_TIME:
            set_alert(state.alerts_front, "head_pitch", "LOOKING DOWN", now)
            update_score(2, "head_pitch", now)
        
        cv2.putText(frame, f"Yaw: {state.smoothed_yaw:.1f}", (w - 130, 90),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 1)
        cv2.putText(frame, f"Pitch: {state.smoothed_pitch:.1f}", (w - 130, 110),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 1)
        
        raw_gaze = detect_gaze(primary_face, h, w)
        is_gaze_active = raw_gaze in ("LEFT", "RIGHT", "HEAD_LEFT", "HEAD_RIGHT")
        gaze_duration = state.gaze_persist.update(is_gaze_active, now)
        
        if is_gaze_active:
            state.last_gaze_direction = raw_gaze
        
        if gaze_duration > CFG.GAZE_PERSIST_TIME:
            gaze_direction = state.last_gaze_direction
            set_alert(state.alerts_front, "gaze", f"GAZE: {gaze_direction}", now)
            update_score(2, "gaze", now)
        else:
            gaze_direction = "CENTER"
    
    smoothed_face = state.face_filter.update(new_face_box, now)
    
    if smoothed_face is not None:
        cv2.rectangle(frame, (smoothed_face.x1, smoothed_face.y1),
                     (smoothed_face.x2, smoothed_face.y2), (255, 0, 255), 2)
        cv2.putText(frame, "FACE", (smoothed_face.x1, smoothed_face.y2 + 15),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 255), 1)
    
    if face_count == 0:
        if state.face_missing_start is None:
            state.face_missing_start = now
        elapsed = now - state.face_missing_start
        if elapsed > CFG.FACE_MISSING_MAX:
            set_alert(state.alerts_front, "face_missing", "NO FACE DETECTED", now)
            update_score(2, "face_missing", now)
    else:
        state.face_missing_start = None
    
    if face_count >= 2:
        set_alert(state.alerts_front, "multi_face", "MULTIPLE FACES", now)
        update_score(5, "multiple_faces", now)
    
    return face_count, gaze_direction


# ═══════════════════════════════════════════════════════════════════════════════
# INTRUDER DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def detect_intruder(persons: List[BoundingBox], now: float) -> bool:
    if len(persons) == 0:
        if state.primary_person_last_seen is not None:
            if now - state.primary_person_last_seen > CFG.PRIMARY_PERSON_TIMEOUT:
                state.primary_person_box = None
                state.primary_person_last_seen = None
        state.intruder_history.update(False)
        return False
    
    state.primary_person_last_seen = now
    
    face_box = state.face_filter.state
    anchor = face_box if face_box is not None else state.primary_person_box
    
    if anchor is None:
        largest = max(persons, key=lambda p: p.area)
        state.primary_person_box = largest
        state.intruder_history.update(False)
        return False
    
    best_iou = 0.0
    best_person = None
    for p in persons:
        iou = anchor.iou(p) if face_box else p.iou(anchor)
        if face_box:
            face_center = face_box.center
            if p.contains_point(face_center[0], face_center[1]):
                iou = max(iou, 0.6)
        if iou > best_iou:
            best_iou = iou
            best_person = p
    
    if best_person is not None and best_iou > 0.3:
        if state.primary_person_box is None:
            state.primary_person_box = best_person
        else:
            state.primary_person_box = state.primary_person_box.smooth_update(
                best_person, CFG.FACE_BOX_SMOOTH_ALPHA)
    
    intruder_found = False
    if len(persons) > 1 and state.primary_person_box is not None:
        primary_area = state.primary_person_box.area
        
        for p in persons:
            if face_box and p.contains_point(*face_box.center):
                continue
            if state.primary_person_box.iou(p) > 0.3:
                continue
            
            p_area = p.area
            area_ratio = p_area / max(primary_area, 1)
            iou_with_primary = p.iou(state.primary_person_box)
            
            if area_ratio > CFG.INTRUDER_MIN_AREA_RATIO and iou_with_primary < CFG.INTRUDER_MAX_IOU:
                intruder_found = True
                break
    
    state.intruder_history.update(intruder_found)
    
    if state.intruder_history.is_confirmed():
        set_alert(state.alerts_front, "intruder", "INTRUDER DETECTED", now)
        update_score(4, "intruder", now)
        return True
    
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# HAND DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def detect_hands(frame: np.ndarray, hands_detector, now: float) -> List[BoundingBox]:
    h, w = frame.shape[:2]
    desk_zone_y = int(h * CFG.DESK_ZONE_Y_RATIO)
    
    cv2.line(frame, (0, desk_zone_y), (w, desk_zone_y), (100, 100, 100), 1)
    cv2.putText(frame, "DESK ZONE", (5, desk_zone_y + 15),
               cv2.FONT_HERSHEY_SIMPLEX, 0.4, (100, 100, 100), 1)
    
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = hands_detector.process(rgb)
    
    hand_boxes = []
    
    mp_hands = mp.solutions.hands
    mp_drawing = mp.solutions.drawing_utils
    mp_drawing_styles = mp.solutions.drawing_styles
    
    if results.multi_hand_landmarks:
        for idx, hand_lm in enumerate(results.multi_hand_landmarks):
            mp_drawing.draw_landmarks(
                frame, hand_lm, mp_hands.HAND_CONNECTIONS,
                mp_drawing_styles.get_default_hand_landmarks_style(),
                mp_drawing_styles.get_default_hand_connections_style()
            )
            
            xs = [lm.x * w for lm in hand_lm.landmark]
            ys = [lm.y * h for lm in hand_lm.landmark]
            
            box = BoundingBox(
                max(int(min(xs)) - CFG.HAND_BOX_PADDING, 0),
                max(int(min(ys)) - CFG.HAND_BOX_PADDING, 0),
                min(int(max(xs)) + CFG.HAND_BOX_PADDING, w),
                min(int(max(ys)) + CFG.HAND_BOX_PADDING, h)
            )
            hand_boxes.append(box)
            
            cv2.rectangle(frame, (box.x1, box.y1), (box.x2, box.y2), (255, 255, 0), 1)
            
            wrist = hand_lm.landmark[mp_hands.HandLandmark.WRIST]
            wrist_x, wrist_y = wrist.x * w, wrist.y * h
            
            is_above_desk = wrist_y < desk_zone_y
            
            if is_above_desk:
                state.hand_positions.append({"x": wrist_x, "y": wrist_y, "t": now})
                zone_label = "ACTIVE"
                zone_color = (0, 200, 255)
            else:
                zone_label = "DESK"
                zone_color = (100, 100, 100)
            
            handedness = "Hand"
            if results.multi_handedness and idx < len(results.multi_handedness):
                handedness = results.multi_handedness[idx].classification[0].label
            cv2.putText(frame, f"{handedness} ({zone_label})", (box.x1, box.y1 - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, zone_color, 1)
    
    # Analyze movement spikes
    cutoff = now - CFG.HAND_MOVEMENT_WINDOW
    while state.hand_positions and state.hand_positions[0]["t"] < cutoff:
        state.hand_positions.popleft()
    
    positions = list(state.hand_positions)
    if len(positions) >= 2:
        spike_count = 0
        for i in range(1, len(positions)):
            dx = positions[i]["x"] - positions[i-1]["x"]
            dy = positions[i]["y"] - positions[i-1]["y"]
            displacement = math.sqrt(dx*dx + dy*dy)
            
            if displacement > CFG.HAND_MOVEMENT_THRESHOLD:
                spike_count += 1
        
        if spike_count >= CFG.HAND_MOVEMENT_SPIKE_LIMIT:
            set_alert(state.alerts_side, "hand_move", "EXCESSIVE HAND MOVEMENT", now)
            update_score(2, "hand_movement", now)
    
    return hand_boxes


def get_hand_boxes_simple(frame: np.ndarray, hands_detector) -> List[BoundingBox]:
    """Get hand boxes without drawing or movement analysis."""
    h, w = frame.shape[:2]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = hands_detector.process(rgb)
    
    hand_boxes = []
    mp_hands = mp.solutions.hands
    
    if results.multi_hand_landmarks:
        for hand_lm in results.multi_hand_landmarks:
            xs = [lm.x * w for lm in hand_lm.landmark]
            ys = [lm.y * h for lm in hand_lm.landmark]
            
            box = BoundingBox(
                max(int(min(xs)) - CFG.HAND_BOX_PADDING, 0),
                max(int(min(ys)) - CFG.HAND_BOX_PADDING, 0),
                min(int(max(xs)) + CFG.HAND_BOX_PADDING, w),
                min(int(max(ys)) + CFG.HAND_BOX_PADDING, h)
            )
            hand_boxes.append(box)
    
    return hand_boxes


# ═══════════════════════════════════════════════════════════════════════════════
# PHONE IN HAND DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def check_phone_in_hand(
    hand_boxes: List[BoundingBox],
    phone_boxes: List[BoundingBox],
    frame: np.ndarray,
    now: float,
    camera: str = "side"
) -> bool:
    alerts = state.alerts_side if camera == "side" else state.alerts_front
    found = False
    
    for phone in phone_boxes:
        phone_cx, phone_cy = phone.center
        
        for hand in hand_boxes:
            iou = phone.iou(hand)
            inter_ratio = phone.intersection_over_self(hand)
            dist = phone.distance_to(hand)
            expanded = hand.expand(CFG.HAND_BOX_PADDING)
            inside = expanded.contains_point(phone_cx, phone_cy)
            
            match_method = None
            if iou > CFG.PHONE_HAND_OVERLAP_THRESH:
                match_method = f"IOU={iou:.2f}"
            elif inter_ratio > 0.15:
                match_method = f"INTER={inter_ratio:.2f}"
            elif dist < CFG.PHONE_NEAR_HAND_DIST:
                match_method = f"DIST={dist:.0f}"
            elif inside:
                match_method = "INSIDE"
            
            if match_method:
                found = True
                
                cv2.rectangle(frame, (hand.x1, hand.y1), (hand.x2, hand.y2),
                            (0, 0, 255), 3)
                cv2.rectangle(frame, (phone.x1, phone.y1), (phone.x2, phone.y2),
                            (0, 0, 255), 3)
                
                h_cx, h_cy = int(hand.center[0]), int(hand.center[1])
                p_cx, p_cy = int(phone_cx), int(phone_cy)
                cv2.line(frame, (h_cx, h_cy), (p_cx, p_cy), (0, 255, 255), 2)
                
                cv2.putText(frame, "PHONE IN HAND", (hand.x1, hand.y1 - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                cv2.putText(frame, f"[{match_method}]", (hand.x1, hand.y2 + 20),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
                
                set_alert(alerts, "phone_hand", "PHONE IN HAND", now)
                update_score(7, "phone_hand", now)
                break
        
        if found:
            break
    
    return found


def check_phone_near_person(
    persons: List[BoundingBox],
    phones: List[BoundingBox],
    frame: np.ndarray,
    now: float
) -> bool:
    for phone in phones:
        for person in persons:
            if phone.iou(person) > 0.05 or phone.distance_to(person) < 200:
                cv2.rectangle(frame, (phone.x1, phone.y1), (phone.x2, phone.y2),
                            (0, 100, 255), 2)
                cv2.putText(frame, "PHONE NEAR BODY", (phone.x1, phone.y1 - 8),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 100, 255), 2)
                set_alert(state.alerts_side, "phone_near", "PHONE NEAR BODY", now)
                update_score(5, "phone_side", now)
                return True
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# UI DRAWING
# ═══════════════════════════════════════════════════════════════════════════════

def draw_ui(frame: np.ndarray, camera: str, now: float):
    h, w = frame.shape[:2]
    alerts = state.alerts_front if camera == "front" else state.alerts_side
    
    # Top bar
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 50), (30, 30, 30), -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
    
    label = "FRONT CAMERA" if camera == "front" else "SIDE CAMERA"
    cv2.putText(frame, label, (10, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    
    is_cheating = state.cumulative_score >= CFG.CHEAT_THRESHOLD
    status = "CHEATING" if is_cheating else "NORMAL"
    color = (0, 0, 255) if is_cheating else (0, 255, 0)
    
    score_text = f"Score: {state.cumulative_score}"
    cv2.putText(frame, score_text, (w - 140, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    
    # Bottom bar
    overlay2 = frame.copy()
    cv2.rectangle(overlay2, (0, h - 35), (w, h), (30, 30, 30), -1)
    cv2.addWeighted(overlay2, 0.7, frame, 0.3, 0, frame)
    cv2.putText(frame, f"STATUS: {status}", (10, h - 10),
               cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    
    fps = state.fps_front if camera == "front" else state.fps_side
    cv2.putText(frame, f"FPS: {fps:.1f}", (w - 100, h - 10),
               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    
    # Stacked alerts
    active_alerts = get_active_alerts(alerts, now)
    y_offset = 70
    for msg in active_alerts[:5]:
        text_size = cv2.getTextSize(msg, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
        cv2.rectangle(frame, (8, y_offset - 18), (16 + text_size[0], y_offset + 4),
                     (0, 0, 180), -1)
        cv2.putText(frame, msg, (12, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        y_offset += 30


def draw_detections(
    frame: np.ndarray,
    persons: List[BoundingBox],
    phones: List[BoundingBox],
    books: List[BoundingBox],
    is_front: bool = True
):
    anchor = state.face_filter.state if is_front else None
    primary = state.primary_person_box
    
    for p in persons:
        is_primary = False
        if anchor and p.contains_point(*anchor.center):
            is_primary = True
        elif primary and p.iou(primary) > 0.3:
            is_primary = True
        
        color = (0, 255, 0) if is_primary else (0, 0, 255)
        label = "CANDIDATE" if is_primary else "PERSON"
        
        cv2.rectangle(frame, (p.x1, p.y1), (p.x2, p.y2), color, 2)
        cv2.putText(frame, label, (p.x1, p.y1 - 8),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
    
    for phone in phones:
        cv2.rectangle(frame, (phone.x1, phone.y1), (phone.x2, phone.y2), (0, 0, 255), 2)
        cv2.putText(frame, f"PHONE ({phone.confidence:.2f})", (phone.x1, phone.y1 - 8),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    
    for book in books:
        cv2.rectangle(frame, (book.x1, book.y1), (book.x2, book.y2), (0, 165, 255), 2)
        cv2.putText(frame, "BOOK", (book.x1, book.y1 - 8),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN APPLICATION
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    global state
    
    print("[INFO] Loading YOLO model...")
    yolo = YOLO("yolov8s.pt")
    
    print("[INFO] Initializing MediaPipe Face Mesh...")
    mp_face_mesh = mp.solutions.face_mesh
    face_mesh = mp_face_mesh.FaceMesh(
        static_image_mode=False,
        max_num_faces=3,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5
    )
    
    print("[INFO] Initializing MediaPipe Hands...")
    mp_hands = mp.solutions.hands
    hands_detector = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=2,
        min_detection_confidence=0.4,
        min_tracking_confidence=0.4
    )
    
    print("[INFO] Opening front camera...")
    front_cam = cv2.VideoCapture(0)
    front_cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    
    if not front_cam.isOpened():
        print("[ERROR] Front camera not available!")
        return
    
    print(f"[INFO] Opening side camera at {CFG.SIDE_CAM_URL}...")
    side_cam = IPCameraReader(CFG.SIDE_CAM_URL)
    side_cam_active = side_cam.isOpened()
    
    if not side_cam_active:
        print("[WARN] Side camera not available. Running front-only mode.")
    
    print("[INFO] ═══════════════════════════════════════════════")
    print("[INFO]   AI Exam Proctoring System Active")
    print("[INFO]   Press ESC to exit  |  R to reset")
    print("[INFO]   Phone debug output enabled")
    print("[INFO] ═══════════════════════════════════════════════")
    
    try:
        while True:
            ret1, front = front_cam.read()
            if not ret1:
                print("[ERROR] Front camera read failed")
                break
            
            if side_cam_active:
                ret2, side = side_cam.read()
                if not ret2 or side is None:
                    print("[WARN] Side camera disconnected")
                    side_cam_active = False
                    side = np.zeros((480, 640, 3), dtype=np.uint8)
                    cv2.putText(side, "SIDE CAMERA OFFLINE", (120, 240),
                               cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            else:
                side = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(side, "SIDE CAMERA OFFLINE", (120, 240),
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            
            now = time.time()
            state.frame_count += 1
            
            front = resize_frame(front, CFG.RESIZE_WIDTH_FRONT)
            side = resize_frame(side, CFG.RESIZE_WIDTH_SIDE)
            
            h_front, w_front = front.shape[:2]
            h_side, w_side = side.shape[:2]
            
            run_yolo = (state.frame_count % CFG.YOLO_INTERVAL == 0)
            
            # ══════════════════════════════════════════════════════════════
            # FRONT CAMERA PROCESSING
            # ══════════════════════════════════════════════════════════════
            
            # Camera obstruction
            blocked, block_reason, block_debug = detect_camera_block(front, "front", now)
            if blocked:
                set_alert(state.alerts_front, "camera_block", f"BLOCKED: {block_reason}", now)
                update_score(CFG.CAM_BLOCK_SCORE, "camera_block_front", now)
                
                overlay = front.copy()
                cv2.rectangle(overlay, (0, 0), (w_front, h_front), (0, 0, 255), -1)
                cv2.addWeighted(overlay, 0.3, front, 0.7, 0, front)
                cv2.putText(front, "CAMERA BLOCKED", (20, h_front // 2),
                           cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
            
            # Face detection
            face_count, gaze_dir = detect_face(front, face_mesh, now)
            
            # Get hand boxes for front camera
            front_hand_boxes = get_hand_boxes_simple(front, hands_detector)
            
            # YOLO detection
            if run_yolo:
                # Main detection
                persons, phones, books = detect_objects(front, yolo, "front")
                
                # FIX: Store raw phones before validation
                state.raw_front_phones = phones.copy()
                
                # Validate phones with relaxed rules
                validated_phones = validate_phones(
                    phones, persons, front_hand_boxes,
                    h_front, w_front, "front"
                )
                
                # FIX: Also run crop detection if no phones found but persons exist
                if len(validated_phones) == 0 and len(persons) > 0:
                    crop_phones = detect_phone_in_crop(front, persons, yolo, "front", "person")
                    if crop_phones:
                        # Validate crop phones too
                        crop_validated = validate_phones(
                            crop_phones, persons, front_hand_boxes,
                            h_front, w_front, "front"
                        )
                        validated_phones.extend(crop_validated)
                
                # FIX: Also check hand crops
                if len(validated_phones) == 0 and len(front_hand_boxes) > 0:
                    hand_crop_phones = detect_phone_in_crop(
                        front, front_hand_boxes, yolo, "front", "hand"
                    )
                    if hand_crop_phones:
                        crop_validated = validate_phones(
                            hand_crop_phones, persons, front_hand_boxes,
                            h_front, w_front, "front"
                        )
                        validated_phones.extend(crop_validated)
                
                # Update history
                phone_detected = len(validated_phones) > 0
                state.phone_history_front.update(phone_detected, state.frame_count)
                
                # Cache results
                state.cached_front_persons = persons
                state.cached_front_books = books
                
                # FIX: More lenient confirmation - if phone detected, show it
                if phone_detected or state.phone_history_front.is_confirmed():
                    state.cached_front_phones = validated_phones
                else:
                    state.cached_front_phones = []
            
            # Intruder detection
            detect_intruder(state.cached_front_persons, now)
            
            # Phone alert
            if len(state.cached_front_phones) > 0:
                set_alert(state.alerts_front, "phone", "PHONE DETECTED", now)
                update_score(5, "phone_front", now)
                
                # Also check phone in hand on front camera
                check_phone_in_hand(front_hand_boxes, state.cached_front_phones, front, now, "front")
            
            # Book alert
            if len(state.cached_front_books) > 0:
                set_alert(state.alerts_front, "book", "BOOK DETECTED", now)
            
            # Draw front camera
            draw_detections(front, state.cached_front_persons, state.cached_front_phones,
                          state.cached_front_books, is_front=True)
            
            # Draw hand boxes on front
            for hb in front_hand_boxes:
                cv2.rectangle(front, (hb.x1, hb.y1), (hb.x2, hb.y2), (255, 255, 0), 1)
            
            # ══════════════════════════════════════════════════════════════
            # SIDE CAMERA PROCESSING
            # ══════════════════════════════════════════════════════════════
            
            if side_cam_active:
                # Camera obstruction
                side_blocked, side_reason, _ = detect_camera_block(side, "side", now)
                if side_blocked:
                    set_alert(state.alerts_side, "camera_block", f"BLOCKED: {side_reason}", now)
                    update_score(CFG.CAM_BLOCK_SCORE, "camera_block_side", now)
                
                # Hand detection
                hand_boxes = detect_hands(side, hands_detector, now)
                
                # YOLO detection
                if run_yolo:
                    persons_side, phones_side, _ = detect_objects(side, yolo, "side")
                    
                    state.raw_side_phones = phones_side.copy()
                    
                    validated_side = validate_phones(
                        phones_side, persons_side, hand_boxes,
                        h_side, w_side, "side"
                    )
                    
                    # Crop detection for side camera
                    if len(validated_side) == 0 and len(hand_boxes) > 0:
                        hand_crop_phones = detect_phone_in_crop(
                            side, hand_boxes, yolo, "side", "hand"
                        )
                        if hand_crop_phones:
                            crop_validated = validate_phones(
                                hand_crop_phones, persons_side, hand_boxes,
                                h_side, w_side, "side"
                            )
                            validated_side.extend(crop_validated)
                    
                    if len(validated_side) == 0 and len(persons_side) > 0:
                        person_crop_phones = detect_phone_in_crop(
                            side, persons_side, yolo, "side", "person"
                        )
                        if person_crop_phones:
                            crop_validated = validate_phones(
                                person_crop_phones, persons_side, hand_boxes,
                                h_side, w_side, "side"
                            )
                            validated_side.extend(crop_validated)
                    
                    phone_detected = len(validated_side) > 0
                    state.phone_history_side.update(phone_detected, state.frame_count)
                    
                    state.cached_side_persons = persons_side
                    
                    if phone_detected or state.phone_history_side.is_confirmed():
                        state.cached_side_phones = validated_side
                    else:
                        state.cached_side_phones = []
                
                # Phone in hand check
                if len(state.cached_side_phones) > 0 and len(hand_boxes) > 0:
                    check_phone_in_hand(hand_boxes, state.cached_side_phones, side, now, "side")
                
                # Phone near person
                if len(state.cached_side_phones) > 0 and len(state.cached_side_persons) > 0:
                    check_phone_near_person(state.cached_side_persons, state.cached_side_phones, side, now)
                
                # Draw side camera
                draw_detections(side, state.cached_side_persons, state.cached_side_phones,
                              [], is_front=False)
            
            # ══════════════════════════════════════════════════════════════
            # SCORE AND UI
            # ══════════════════════════════════════════════════════════════
            
            apply_score_decay(now)
            
            # Update FPS
            state.fps_front_counter += 1
            if now - state.fps_front_timer >= 1.0:
                state.fps_front = state.fps_front_counter / (now - state.fps_front_timer)
                state.fps_front_counter = 0
                state.fps_front_timer = now
            
            if side_cam_active:
                state.fps_side_counter += 1
                if now - state.fps_side_timer >= 1.0:
                    state.fps_side = state.fps_side_counter / (now - state.fps_side_timer)
                    state.fps_side_counter = 0
                    state.fps_side_timer = now
            
            # Draw UI
            draw_ui(front, "front", now)
            draw_ui(side, "side", now)
            
            # Debug: Show raw phone count
            if CFG.DEBUG_PHONE:
                cv2.putText(front, f"Raw phones: {len(state.raw_front_phones)}", (10, h_front - 50),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
                cv2.putText(front, f"Valid phones: {len(state.cached_front_phones)}", (10, h_front - 70),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            
            # Display
            cv2.imshow("Front Camera", front)
            cv2.imshow("Side Camera", side)
            
            # Keyboard
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                print("[INFO] Exiting...")
                break
            elif key == ord('r'):
                state.reset()
                print("[INFO] System reset")
            elif key == ord('d'):
                CFG.DEBUG_PHONE = not CFG.DEBUG_PHONE
                print(f"[INFO] Phone debug: {CFG.DEBUG_PHONE}")
    
    except KeyboardInterrupt:
        print("[INFO] Interrupted")
    
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        print("[INFO] Releasing resources...")
        front_cam.release()
        if side_cam_active:
            side_cam.release()
        face_mesh.close()
        hands_detector.close()
        cv2.destroyAllWindows()
        print("[INFO] Session ended")


if __name__ == "__main__":
    main()