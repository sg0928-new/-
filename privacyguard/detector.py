"""Face detection and the "someone else is looking" decision.

Detection runs on a downscaled grayscale copy of the newest camera frame; the
decision layer turns a stream of counts into a debounced trigger so a single
misfire or a person walking past the door does not flash the screen.

Why Haar and not a DNN: it ships with opencv (no model download, no 200 MB
runtime), costs ~5 ms per frame at 320 px, and this product only needs "is there
more than one face in front of the laptop".
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import cv2

_CASCADE_DIR = cv2.data.haarcascades


@dataclass
class FaceBox:
    x: int
    y: int
    w: int
    h: int
    score: float = 0.0

    @property
    def area(self) -> int:
        return self.w * self.h

    def iou(self, other: "FaceBox") -> float:
        x1, y1 = max(self.x, other.x), max(self.y, other.y)
        x2 = min(self.x + self.w, other.x + other.w)
        y2 = min(self.y + self.h, other.y + other.h)
        if x2 <= x1 or y2 <= y1:
            return 0.0
        inter = (x2 - x1) * (y2 - y1)
        return inter / float(self.area + other.area - inter)


@dataclass
class Detection:
    boxes: list[FaceBox] = field(default_factory=list)
    owner: int = -1              # index of the largest face (assumed "you")
    others: int = 0              # faces that are not the owner
    ms: float = 0.0
    frame_w: int = 0
    frame_h: int = 0

    @property
    def count(self) -> int:
        return len(self.boxes)


class FaceDetector:
    def __init__(self, detect_width: int = 320, scale_factor: float = 1.15,
                 min_neighbors: int = 5, min_face_px: int = 28,
                 profiles: bool = True):
        self.detect_width = int(detect_width)
        self.scale_factor = float(scale_factor)
        self.min_neighbors = int(min_neighbors)
        self.min_face_px = int(min_face_px)
        self.profiles = bool(profiles)
        self._front = self._load("haarcascade_frontalface_default.xml")
        self._profile = self._load("haarcascade_profileface.xml") if profiles else None
        self.configure(detect_width, scale_factor, min_neighbors, min_face_px, profiles)

    @staticmethod
    def _load(name: str):
        path = os.path.join(_CASCADE_DIR, name)
        clf = cv2.CascadeClassifier(path)
        return None if clf.empty() else clf

    def configure(self, detect_width=None, scale_factor=None, min_neighbors=None,
                  min_face_px=None, profiles=None) -> None:
        if detect_width is not None:
            self.detect_width = int(detect_width)
        if scale_factor is not None:
            self.scale_factor = max(1.02, float(scale_factor))
        if min_neighbors is not None:
            self.min_neighbors = int(min_neighbors)
        if min_face_px is not None:
            self.min_face_px = int(min_face_px)
        if profiles is not None and bool(profiles) != self.profiles:
            self.profiles = bool(profiles)
            self._profile = self._load("haarcascade_profileface.xml") if self.profiles else None

    # ---------------------------------------------------------------- detect
    def detect(self, frame_bgr) -> Detection:
        import time
        t0 = time.perf_counter()
        if frame_bgr is None:
            return Detection(ms=0.0)
        h, w = frame_bgr.shape[:2]
        scale = self.detect_width / float(w) if w > self.detect_width else 1.0
        if scale != 1.0:
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (int(w * scale), int(h * scale)),
                              interpolation=cv2.INTER_AREA)
        else:
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        # minSize is in working pixels, so it must scale with the downscale
        min_size = max(12, int(self.min_face_px * scale))
        boxes: list[FaceBox] = []
        if self._front is not None:
            for x, y, bw, bh in self._front.detectMultiScale(
                    gray, scaleFactor=self.scale_factor, minNeighbors=self.min_neighbors,
                    minSize=(min_size, min_size), flags=cv2.CASCADE_SCALE_IMAGE):
                boxes.append(FaceBox(int(x), int(y), int(bw), int(bh), 1.0))
        if self._profile is not None:
            for x, y, bw, bh in self._profile.detectMultiScale(
                    gray, scaleFactor=self.scale_factor, minNeighbors=self.min_neighbors,
                    minSize=(min_size, min_size)):
                boxes.append(FaceBox(int(x), int(y), int(bw), int(bh), 0.7))
            flipped = cv2.flip(gray, 1)
            for x, y, bw, bh in self._profile.detectMultiScale(
                    flipped, scaleFactor=self.scale_factor, minNeighbors=self.min_neighbors,
                    minSize=(min_size, min_size)):
                boxes.append(FaceBox(int(gray.shape[1] - x - bw), int(y), int(bw), int(bh), 0.7))
        boxes = self._nms(boxes)
        det = Detection(boxes=boxes, ms=(time.perf_counter() - t0) * 1000.0,
                        frame_w=w, frame_h=h)
        det.owner = max(range(len(boxes)), key=lambda i: boxes[i].area, default=-1)
        det.others = sum(1 for i, b in enumerate(boxes)
                         if i != det.owner and b.iou(boxes[det.owner]) < 0.35) if boxes else 0
        return det

    @staticmethod
    def _nms(boxes: list[FaceBox], thresh: float = 0.35) -> list[FaceBox]:
        """Keep the higher score / bigger box when two detections overlap."""
        out: list[FaceBox] = []
        for b in sorted(boxes, key=lambda x: (x.score, x.area), reverse=True):
            if all(b.iou(o) < thresh for o in out):
                out.append(b)
        return out


class IntruderLogic:
    """Debounced "more than N faces in front of me" state machine."""

    def __init__(self, allowed_own_faces: int = 1, confirm_frames: int = 4,
                 cooldown_s: float = 12.0, release_s: float = 2.0):
        self.allowed_own_faces = int(allowed_own_faces)
        self.confirm_frames = int(confirm_frames)
        self.cooldown_s = float(cooldown_s)
        self.release_s = float(release_s)
        self._hit = 0
        self._miss = 0
        self._last_alert = 0.0
        self.active = False
        self.peak = 0

    def configure(self, **kw) -> None:
        for k, v in kw.items():
            if hasattr(self, k) and v is not None:
                setattr(self, k, v)

    def update(self, det: Detection, now: float | None = None) -> str | None:
        """Return 'trigger' / 'release' / None."""
        import time
        now = time.time() if now is None else now
        risky = det.count > self.allowed_own_faces
        if risky:
            self._hit += 1
            self._miss = 0
            self.peak = max(self.peak, det.count)
        else:
            self._miss += 1
            if self._miss >= 2:
                self._hit = 0

        if not self.active:
            if self._hit >= self.confirm_frames and (now - self._last_alert) >= self.cooldown_s:
                self.active = True
                self._last_alert = now
                self._hit = 0
                return "trigger"
            return None

        # already active: end when the room is clear for release_s
        if not risky and self._miss * 1.0 >= 1:
            if getattr(self, "_clear_since", None) is None:
                self._clear_since = now
            if now - self._clear_since >= self.release_s:
                self.active = False
                self._clear_since = None
                self.peak = 0
                return "release"
        else:
            self._clear_since = None
        return None
