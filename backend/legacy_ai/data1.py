"""
╔══════════════════════════════════════════════════════════════╗
║         TRAINING DATA COLLECTOR — Exam Cheat Detector        ║
╠══════════════════════════════════════════════════════════════╣
║  This script helps you collect labelled images to train a    ║
║  custom AI model that knows YOUR specific exam room setup.   ║
║                                                              ║
║  HOW TO USE:                                                 ║
║  1. Run this script                                          ║
║  2. Press keys to save frames with the correct label:        ║
║       E  →  Save as "examinee"  (normal, only student)       ║
║       I  →  Save as "intruder"  (another person visible)     ║
║       P  →  Save as "phone"     (phone visible)              ║
║       N  →  Save as "normal"    (clean, nothing suspicious)  ║
║       ESC → Quit                                             ║
║                                                              ║
║  TIPS FOR GOOD DATA:                                         ║
║  • Collect at least 200 images per label                     ║
║  • Vary lighting (day, night, lamp on/off)                   ║
║  • Vary angles (sit straight, lean, reach forward)           ║
║  • For intruder: have someone put hand/arm in from the side  ║
║  • Run this across multiple exam sessions                    ║
║                                                              ║
║  NEXT STEP AFTER COLLECTING:                                 ║
║  Upload the 'training_data/' folder to https://roboflow.com  ║
║  (free account) — it will auto-annotate and let you          ║
║  export a fine-tuned YOLOv8 model.                           ║
╚══════════════════════════════════════════════════════════════╝
"""

import cv2
import os
import time
import json
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
SIDE_CAM_URL = "https://192.0.0.2:8080/video"   # Same as your main script
OUTPUT_DIR   = "training_data"

LABELS = {
    ord('e'): "examinee",   # E key
    ord('i'): "intruder",   # I key
    ord('p'): "phone",      # P key
    ord('n'): "normal",     # N key
}

# Create folders for each label
for label in LABELS.values():
    os.makedirs(os.path.join(OUTPUT_DIR, label, "front"), exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, label, "side"),  exist_ok=True)

# ─────────────────────────────────────────────
# CAMERAS
# ─────────────────────────────────────────────
print("[INFO] Connecting cameras...")
front_cam = cv2.VideoCapture(0)
side_cam  = cv2.VideoCapture(SIDE_CAM_URL)

if not front_cam.isOpened():
    print("[ERROR] Front camera not available.")
    exit()

if not side_cam.isOpened():
    print(f"[WARNING] Side camera not reachable. Using front cam for both.")
    side_cam = cv2.VideoCapture(0)

# ─────────────────────────────────────────────
# STATS TRACKING
# ─────────────────────────────────────────────
counts = {label: 0 for label in LABELS.values()}
session_log = []

def save_pair(front, side, label):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    front_path = os.path.join(OUTPUT_DIR, label, "front", f"{ts}.jpg")
    side_path  = os.path.join(OUTPUT_DIR, label, "side",  f"{ts}.jpg")
    cv2.imwrite(front_path, front)
    cv2.imwrite(side_path,  side)
    counts[label] += 1
    session_log.append({"time": ts, "label": label})
    print(f"  ✓ Saved [{label}] — Total {label}: {counts[label]}")


def draw_ui(frame, label="FRONT"):
    h, w = frame.shape[:2]

    # Dark bar at top
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 130), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, frame)

    cv2.putText(frame, f"DATA COLLECTOR  [{label}]", (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 220, 255), 2)

    # Show key guide
    guide = "  E=examinee   I=intruder   P=phone   N=normal   ESC=quit"
    cv2.putText(frame, guide, (10, 58),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

    # Show counts
    count_str = "  Saved:  " + "   ".join(
        [f"{lbl}={counts[lbl]}" for lbl in LABELS.values()]
    )
    cv2.putText(frame, count_str, (10, 90),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100, 255, 100), 1)

    # Minimum target progress bar
    target = 200
    total  = sum(counts.values())
    pct    = min(total / (target * len(counts)), 1.0)
    bar_w  = int(pct * (w - 40))
    bar_col = (0, 200, 0) if pct >= 1.0 else (0, 165, 255)
    cv2.rectangle(frame, (20, 105), (20 + bar_w, 120), bar_col, -1)
    cv2.rectangle(frame, (20, 105), (w - 20,    120), (150, 150, 150), 1)
    cv2.putText(frame, f"Progress to 200/label: {int(pct*100)}%", (10, 130),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 180, 180), 1)


print("\n[INFO] Data collector ready.")
print("       Press E / I / P / N to save labelled frame pairs.")
print("       Press ESC to quit.\n")

# Flash banner on first frame
flash_msg   = ""
flash_until = 0.0

while True:
    ret1, front = front_cam.read()
    ret2, side  = side_cam.read()

    if not ret1 or front is None:
        print("[ERROR] Front camera lost.")
        break
    if not ret2 or side is None:
        side = front.copy()

    # Draw UI on copies so saved images are clean
    display_front = front.copy()
    display_side  = side.copy()
    draw_ui(display_front, "FRONT")
    draw_ui(display_side,  "SIDE")

    # Flash confirmation message
    now = time.time()
    if now < flash_until:
        cv2.putText(display_front, flash_msg, (20, 170),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 3)
        cv2.putText(display_side,  flash_msg, (20, 170),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 3)

    cv2.imshow("Front Camera — Data Collector", display_front)
    cv2.imshow("Side Camera  — Data Collector", display_side)

    key = cv2.waitKey(1) & 0xFF

    if key == 27:   # ESC
        break

    if key in LABELS:
        label = LABELS[key]
        save_pair(front, side, label)   # Save RAW frames (no UI overlay)
        flash_msg   = f"SAVED: {label.upper()}"
        flash_until = time.time() + 0.6

# ─────────────────────────────────────────────
# SAVE SESSION SUMMARY
# ─────────────────────────────────────────────
front_cam.release()
side_cam.release()
cv2.destroyAllWindows()

summary = {
    "total_saved" : sum(counts.values()),
    "per_label"   : counts,
    "log"         : session_log
}
summary_path = os.path.join(OUTPUT_DIR, "session_summary.json")
with open(summary_path, "w") as f:
    json.dump(summary, f, indent=2)

print("\n" + "="*55)
print("         DATA COLLECTION SESSION COMPLETE")
print("="*55)
for label, count in counts.items():
    status = "✓ GOOD" if count >= 200 else f"⚠ need {200 - count} more"
    print(f"  {label:<12} : {count:>4} images   {status}")
print(f"\n  All images saved to:  {OUTPUT_DIR}/")
print(f"  Summary saved to:     {summary_path}")
print("\n  NEXT STEP:")
print("  1. Go to https://roboflow.com (free)")
print("  2. Create a new project → 'Object Detection'")
print(f"  3. Upload the '{OUTPUT_DIR}/' folder")
print("  4. Use Auto-Label, then export as 'YOLOv8'")
print("  5. Run:  yolo train data=data.yaml model=yolov8n.pt epochs=50")
print("="*55)
