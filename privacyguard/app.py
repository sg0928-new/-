"""Background guard service: camera thread → detector thread → overlay frames.

Threads are deliberately split:

* ``detect``   — camera + Haar, ~12 Hz, ~5 ms per frame at 320 px
* ``render``   — only alive while an alert is on screen, ~30 fps
* ``overlay``  — Win32 message loop, memmoves frames and nothing else

When no alert is active the render thread does not exist and the overlay window
is hidden, which is why the idle cost is close to a camera capture loop.
"""

from __future__ import annotations

import threading
import time

import numpy as np
from PIL import Image

from . import config as cfgmod
from . import effects
from .camera import CameraStream
from .detector import FaceDetector, IntruderLogic
from .overlay import ScreenOverlay, premultiply_bgra, virtual_screen
from .sound import SoundPlayer
from .hotkeys import HotkeyManager


class GuardService:
    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg if cfg is not None else cfgmod.load()
        self.lock = threading.RLock()
        self.cam: CameraStream | None = None
        self._det: FaceDetector | None = None
        self.logic = IntruderLogic()
        self.overlay = ScreenOverlay(self.cfg["effect"].get("multi_monitor", True))
        self.sound = SoundPlayer()
        self.seq = effects.EffectSequencer(self.cfg)
        self.hotkeys: HotkeyManager | None = None

        self._stop = threading.Event()
        self._detect_thread: threading.Thread | None = None
        self._render_thread: threading.Thread | None = None
        self._render_stop: threading.Event | None = None
        self._alert_until = 0.0
        self._alert_start = 0.0
        self._render_fps = 0.0
        self._last_cpu = (time.process_time(), time.perf_counter(), 0.0)
        self._cfg_version = 0
        self._rng = np.random.default_rng(11)
        self.monitoring = False
        self.status: dict = {
            "state": "idle", "faces": 0, "owner": 0, "others": 0, "detect_ms": 0.0,
            "cam_fps": 0.0, "render_fps": 0.0, "alert": False, "effect": "",
            "cpu": 0.0, "message": "", "frame_mean": 0.0, "alerts": 0, "hotkey_errors": "",
            "quality_now": 0.0, "boxes": [], "fx_ms": (0.0, 0.0, 0.0),
        }
        self._apply(cfgmod.deep_merge(cfgmod.DEFAULTS, self.cfg))

    # ------------------------------------------------------------- lifecycle
    def start(self) -> bool:
        self.overlay.start()
        self._stop.clear()
        ok = self._start_camera()
        if ok:
            self._detect_thread = threading.Thread(target=self._detect_loop, name="detect", daemon=True)
            self._detect_thread.start()
        self._start_hotkeys()
        self.monitoring = ok
        return ok

    def stop(self) -> None:
        self._stop.set()
        self.stop_alert()
        if self._detect_thread is not None:
            self._detect_thread.join(timeout=2.0)
            self._detect_thread = None
        if self.cam is not None:
            self.cam.stop()
        if self.hotkeys is not None:
            self.hotkeys.stop()
        self.sound.stop()
        self.overlay.stop()
        self.monitoring = False
        self.status["state"] = "stopped"

    # ----------------------------------------------------------------- config
    def apply_config(self, cfg: dict) -> None:
        with self.lock:
            old_idx = self.cfg["monitor"].get("camera_index")
            was = self.monitoring
        self.cfg = cfgmod.clamp_values(cfgmod.deep_merge(cfgmod.DEFAULTS, cfg))
        self._apply(self.cfg)
        with self.lock:
            need_restart = (self.cfg["monitor"].get("camera_index") != old_idx) or was != self.cfg["monitor"]["enabled"]
        self.overlay.multi_monitor = self.cfg["effect"].get("multi_monitor", True)
        self.overlay.geometry = virtual_screen(self.overlay.multi_monitor)
        if need_restart:
            self.restart_monitoring()
        self._start_hotkeys()

    def save_config(self) -> None:
        with self.lock:
            cfgmod.save(self.cfg)

    def _apply(self, cfg: dict) -> None:
        m = cfg["monitor"]
        self._det = self._det or FaceDetector()
        self._det.configure(m["detect_width"], m["scale_factor"], m["min_neighbors"],
                            m["min_face_px"], m["detect_profiles"])
        self.logic.configure(allowed_own_faces=m["allowed_own_faces"],
                             confirm_frames=m["confirm_frames"],
                             cooldown_s=m["cooldown_s"], release_s=m["release_s"])
        self.seq.configure(cfg)
        self._cfg_version += 1

    def restart_monitoring(self) -> None:
        was = self.monitoring
        self.stop_monitoring_only()
        if self.cfg["monitor"]["enabled"] and was:
            self.start_monitoring()

    def start_monitoring(self) -> bool:
        if self.monitoring:
            return True
        ok = self._start_camera()
        self.monitoring = ok
        if ok and (self._detect_thread is None or not self._detect_thread.is_alive()):
            self._stop.clear()
            self._detect_thread = threading.Thread(target=self._detect_loop, name="detect", daemon=True)
            self._detect_thread.start()
        return ok

    def stop_monitoring_only(self) -> None:
        self._stop.set()
        if self._detect_thread is not None:
            self._detect_thread.join(timeout=2.0)
            self._detect_thread = None
        if self.cam is not None:
            self.cam.stop()
            self.cam = None
        self.monitoring = False
        self.stop_alert()

    def _start_camera(self) -> bool:
        m = self.cfg["monitor"]
        if self.cam is not None:
            self.cam.stop()
        self.cam = CameraStream(int(m["camera_index"]), int(m["width"]), int(m["height"]))
        ok = self.cam.start()
        if not ok:
            self.status["state"] = "camera-error"
            self.status["message"] = self.cam.error or "camera unavailable"
        else:
            self.status["state"] = "watch"
            self.status["message"] = ""
        return ok

    def _start_hotkeys(self) -> None:
        if self.hotkeys is not None:
            self.hotkeys.stop()
        self.hotkeys = HotkeyManager(self.cfg["hotkeys"], self._on_hotkey)
        self.hotkeys.start()
        errs = self.hotkeys.errors
        self.status["hotkey_errors"] = "; ".join(errs.values()) if errs else ""

    def _on_hotkey(self, action: str) -> None:
        if action == "test":
            self.trigger(source="hotkey")
        elif action == "toggle":
            if self.monitoring:
                self.stop_monitoring_only()
            else:
                self.start_monitoring()
        elif action == "panel":
            self.on_panel_request() if self.on_panel_request else None

    on_panel_request = None      # the panel attaches a callback here

    # ------------------------------------------------------------------ alert
    def trigger(self, source: str = "detector") -> None:
        e = self.cfg["effect"]
        now = time.time()
        duration = float(e["duration_s"])
        with self.lock:
            self._alert_start = now
            self._alert_until = max(self._alert_until, now + duration)
            self.status["alerts"] += 1
            self.status["alert"] = True
            self.status["state"] = "alert"
            self.status["message"] = f"trigger: {source}"
        s = self.cfg["sound"]
        if s.get("enabled"):
            self.sound.play(s["name"], s.get("volume", 0.7), s.get("repeat", 1), s.get("delay_ms", 0))
        self._ensure_render()

    def stop_alert(self) -> None:
        with self.lock:
            self._alert_until = 0.0
            self.status["alert"] = False
            if self.monitoring:
                self.status["state"] = "watch"
        if self._render_stop is not None:
            self._render_stop.set()
        if self._render_thread is not None:
            self._render_thread.join(timeout=1.5)
            self._render_thread = None
        self.overlay.hide()

    def _ensure_render(self) -> None:
        if self._render_thread is not None:
            if self._render_stop is not None and self._render_stop.is_set():
                self._render_thread.join(timeout=0.6)      # let the previous loop exit
            elif self._render_thread.is_alive():
                return
        self._render_stop = threading.Event()
        self._render_thread = threading.Thread(
            target=self._render_loop, args=(self._render_stop,), name="render", daemon=True)
        self._render_thread.start()

    # ------------------------------------------------------------------ loops
    def _detect_loop(self) -> None:
        interval = max(0.03, self.cfg["monitor"]["detect_interval_ms"] / 1000.0)
        last_seq = -1
        dark_frames = 0
        while not self._stop.is_set():
            t0 = time.perf_counter()
            cam = self.cam
            if cam is None:
                time.sleep(interval)
                continue
            frame, stamp, seq = cam.read()
            if frame is None or seq != last_seq:
                if frame is not None:
                    last_seq = seq
                    mean = float(frame.mean())
                    self.status["frame_mean"] = mean
                    dark_frames = dark_frames + 1 if mean < 4.0 else 0
                    if dark_frames > 40 and self.status["message"] == "":
                        self.status["message"] = "摄像头画面全黑（可能被遮挡或无权限）/ camera sees all black"
                det = self._det.detect(frame) if frame is not None else None
                if det is not None:
                    self.status["faces"] = det.count
                    self.status["owner"] = max(0, det.owner + 1)
                    self.status["others"] = det.others
                    self.status["detect_ms"] = det.ms
                    self.status["boxes"] = [(b.x, b.y, b.w, b.h, i == det.owner)
                                            for i, b in enumerate(det.boxes)]
                    event = self.logic.update(det)
                    if event == "trigger":
                        self.trigger(source="detector")
                    elif event == "release":
                        self.stop_alert()
            with self.lock:
                self.status["cam_fps"] = cam.fps if cam else 0.0
            # periodic alert expiry (effects also have their own fade-out)
            if self.status["alert"] and time.time() > self._alert_until:
                self.stop_alert()
            dt = time.perf_counter() - t0
            time.sleep(max(0.0, interval - dt))

    def _render_loop(self, stop: threading.Event) -> None:
        e = self.cfg["effect"]
        quality = float(e.get("quality", 0.5))
        q = quality
        fade = float(e.get("fade_s", 0.35))
        geo = self.overlay.geometry
        full = (geo[2], geo[3])
        work = (max(64, int(full[0] * q)), max(64, int(full[1] * q)))
        frames = 0
        t_fps = time.perf_counter()
        rng = np.random.default_rng(19)
        cfg_ver = -1
        ema = 16.0                     # exponential moving average of frame cost (ms)
        while not stop.is_set():
            t_frame = time.perf_counter()
            now = time.time()
            with self.lock:
                start = self._alert_start
                until = self._alert_until
                ver = self._cfg_version
            if ver != cfg_ver:
                self.seq.configure(self.cfg)
                cfg_ver = ver
            t = max(0.0, now - start)
            remain = until - now
            if remain <= -fade:
                break
            # envelope: fade in at the head, fade out at the tail
            env = 1.0
            if t < fade:
                env = t / max(1e-3, fade)
            if remain < fade:
                env = max(0.0, remain / max(1e-3, fade))
            a0 = time.perf_counter()
            frame = effects.render_frame(self.cfg, work, self.seq, t, rng, opacity_scale=env)
            a1 = time.perf_counter()
            # premultiply while the buffer is still small, then upscale: a linear
            # resize on premultiplied pixels stays consistent with the alpha channel
            bgra = premultiply_bgra(frame)
            a2 = time.perf_counter()
            if work != full:
                # bilinear when there is head-room, nearest when the frame budget is
                # tight — the difference is 17 ms vs 2 ms at 1707x1067
                mode = Image.BILINEAR if ema < 26.0 else Image.NEAREST
                bgra = np.asarray(Image.fromarray(bgra, "RGBA").resize(full, mode))
            a3 = time.perf_counter()
            self.overlay.push(bgra, full)
            with self.lock:
                self.status["effect"] = self.seq.current(t)
                self.status["fx_ms"] = (round(1000 * (a1 - a0), 1), round(1000 * (a2 - a1), 1),
                                        round(1000 * (a3 - a2), 1))
            frames += 1
            now2 = time.perf_counter()
            ema = 0.85 * ema + 0.15 * 1000.0 * (now2 - t_frame)
            # adaptive resolution: hold >= ~25 fps on weak machines, recover when idle
            if ema > 38.0 and q > 0.26:
                q = max(0.26, q * 0.88)
                work = (max(64, int(full[0] * q)), max(64, int(full[1] * q)))
            elif ema < 22.0 and q < quality:
                q = min(quality, q * 1.08)
                work = (max(64, int(full[0] * q)), max(64, int(full[1] * q)))
            self.status["quality_now"] = round(q, 2)
            if now2 - t_fps >= 1.0:
                self._render_fps = frames / (now2 - t_fps)
                self.status["render_fps"] = self._render_fps
                frames, t_fps = 0, now2
            cpu0, wall0, _ = self._last_cpu
            cpu1, wall1 = time.process_time(), time.perf_counter()
            self.status["cpu"] = 100.0 * (cpu1 - cpu0) / max(1e-6, wall1 - wall0)
            self._last_cpu = (cpu1, wall1, self.status["cpu"])
            # frame pacing towards 30 fps, measured from the start of the iteration
            spent = time.perf_counter() - t_frame
            if spent < 1.0 / 30.0:
                time.sleep(1.0 / 30.0 - spent)
        self.overlay.hide()
        with self.lock:
            self.status["alert"] = False
            if self.monitoring:
                self.status["state"] = "watch"


# ---------------------------------------------------------------- autostart
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "PrivacyGuard"


def set_autostart(enable: bool, no_panel: bool = True) -> bool:
    """Register/unregister this package under HKCU Run. Returns the final state."""
    import os
    import sys
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
    except OSError:
        return False
    try:
        if enable:
            exe = sys.executable
            if getattr(sys, "frozen", False):
                # packaged: sys.executable *is* PrivacyGuard.exe, there is no `-m`
                args = "--no-panel" if no_panel else ""
            else:
                if no_panel:
                    exe = exe.replace("python.exe", "pythonw.exe")
                args = "-m privacyguard --no-panel" if no_panel else "-m privacyguard"
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, f'"{exe}" {args}'.strip())
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass
        return enable
    finally:
        winreg.CloseKey(key)


def autostart_enabled() -> bool:
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ)
    except OSError:
        return False
    try:
        winreg.QueryValueEx(key, RUN_VALUE)
        return True
    except FileNotFoundError:
        return False
    finally:
        winreg.CloseKey(key)
