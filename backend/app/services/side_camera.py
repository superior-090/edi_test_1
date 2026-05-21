from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

import cv2

_readers: dict[str, "_SideCameraReader"] = {}
_readers_lock = threading.Lock()
_fresh_frame_seconds = 2.5


def normalize_side_camera_url(raw_url: str) -> str:
    value = raw_url.strip()
    if not value:
        raise ValueError("Side camera IP is required")

    if "://" not in value:
        value = f"http://{value}"

    parsed = urlparse(value)
    if not parsed.hostname or not parsed.port:
        raise ValueError("Enter the side camera as IP:PORT, for example 192.168.0.103:8080")

    if parsed.path in ("", "/"):
        value = value.rstrip("/") + "/video"

    return value


class _SideCameraReader:
    def __init__(self, url: str):
        self.url = url
        self._lock = threading.Lock()
        self._frame = None
        self._last_frame_at = 0.0
        self._capture = None
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def read_fresh_frame(self):
        with self._lock:
            age = time.monotonic() - self._last_frame_at
            if self._frame is None or age > _fresh_frame_seconds:
                return False, None
            return True, self._frame.copy()

    def _read_loop(self):
        while self._running:
            capture = self._open_capture()
            if capture is None:
                time.sleep(0.25)
                continue

            with self._lock:
                self._capture = capture

            misses = 0
            while self._running:
                try:
                    ok, frame = capture.read()
                except Exception:
                    ok, frame = False, None
                if ok and frame is not None:
                    misses = 0
                    with self._lock:
                        self._frame = frame
                        self._last_frame_at = time.monotonic()
                    continue

                misses += 1
                time.sleep(0.1)
                if misses >= 5:
                    break

            capture.release()
            with self._lock:
                if self._capture is capture:
                    self._capture = None

    def _open_capture(self):
        capture = cv2.VideoCapture(self.url)
        if not capture.isOpened():
            capture.release()
            return None
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return capture


def read_side_camera_frame(url: str, timeout_seconds: float = 4.0):
    reader = _get_reader(url)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        ok, frame = reader.read_fresh_frame()
        if ok:
            return True, frame
        time.sleep(0.05)
    return False, None


def _get_reader(url: str) -> _SideCameraReader:
    with _readers_lock:
        reader = _readers.get(url)
        if reader is None:
            reader = _SideCameraReader(url)
            _readers[url] = reader
        return reader


def get_latest_side_camera_frame(url: str):
    return _get_reader(url).read_fresh_frame()


def validate_side_camera_url(raw_url: str):
    url = normalize_side_camera_url(raw_url)
    ok, frame = read_side_camera_frame(url)
    if not ok:
        raise ValueError("Side camera is not reachable or not streaming")
    return url, frame
