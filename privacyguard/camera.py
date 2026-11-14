"""Threaded camera capture with a latest-frame slot.

The detector never waits on the camera: it always takes the newest frame, so a
slow detection pass can never build a backlog (the usual cause of webcam
watchdogs growing to seconds of latency).
"""

from __future__ import annotations

import threading
import time

import cv2


def list_cameras(max_index: int = 4) -> list[int]:
    """Probe camera indices 0..max_index-1, return the ones that deliver a frame."""
    found: list[int] = []
    for idx in range(max_index):
        for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY):
            cap = cv2.VideoCapture(idx, backend)
            try:
                if cap.isOpened() and cap.grab():
                    found.append(idx)
                    break
            finally:
                cap.release()
    return found


class CameraStream:
    def __init__(self, index: int = 0, width: int = 640, height: int = 480,
                 max_fps: float = 15.0):
        self.index = int(index)
        self.width = int(width)
        self.height = int(height)
        self.max_fps = max(1.0, float(max_fps))
        self._cap: cv2.VideoCapture | None = None
        self._lock = threading.Lock()
        self._frame = None
        self._stamp = 0.0
        self._seq = 0
        self._run = False
        self._thread: threading.Thread | None = None
        self._fps = 0.0
        self._fails = 0
        self.error: str | None = None

    # ------------------------------------------------------------------ api
    def open(self) -> bool:
        for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY):
            cap = cv2.VideoCapture(self.index, backend)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)      # drop stale frames
                cap.set(cv2.CAP_PROP_FPS, int(self.max_fps))
                ok = cap.grab()
                if ok:
                    self._cap = cap
                    self.error = None
                    return True
            cap.release()
        self.error = f"camera {self.index} not available"
        return False

    def start(self) -> bool:
        if self._run:
            return True
        if self._cap is None and not self.open():
            return False
        self._run = True
        self._thread = threading.Thread(target=self._loop, name="camera", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._run = False
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def read(self) -> tuple[object | None, float, int]:
        """Return (frame_bgr, timestamp, sequence) — the same tuple until a new frame lands."""
        with self._lock:
            return self._frame, self._stamp, self._seq

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def running(self) -> bool:
        return self._run

    # -------------------------------------------------------------- internal
    def _loop(self) -> None:
        t_fps = time.perf_counter()
        n = 0
        period = 1.0 / self.max_fps
        while self._run and self._cap is not None:
            t0 = time.perf_counter()
            ok, frame = self._cap.read()
            if not ok:
                self._fails += 1
                if self._fails > 30:                 # camera unplugged / busy
                    self.error = "frame read failed"
                    break
                time.sleep(0.02)
                continue
            self._fails = 0
            with self._lock:
                self._frame = frame
                self._stamp = time.time()
                self._seq += 1
            n += 1
            now = time.perf_counter()
            if now - t_fps >= 1.0:
                self._fps = n / (now - t_fps)
                n, t_fps = 0, now
            # pace the grab: the detector needs ~12 Hz, not the camera's 30
            spent = time.perf_counter() - t0
            if spent < period:
                time.sleep(period - spent)
        self._run = False
