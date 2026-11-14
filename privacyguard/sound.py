"""Procedural alert sounds (no asset files) + async playback via winsound.

The WAVs are synthesised once per session into memory, so the repository carries
no binaries and the panel can audition any of them instantly.
"""

from __future__ import annotations

import io
import threading
import time
import wave

import numpy as np

try:
    import winsound
except ImportError:                     # pragma: no cover - non-Windows
    winsound = None

SR = 44100


def _envelope(n: int, attack: float = 0.01, release: float = 0.12) -> np.ndarray:
    a = max(1, int(n * attack))
    r = max(1, int(n * release))
    env = np.ones(n, dtype=np.float32)
    env[:a] = np.linspace(0, 1, a) ** 1.5
    env[-r:] = np.linspace(1, 0, r) ** 1.5
    return env


def _tone(freq: float, dur: float, wave_type: str = "sine", detune: float = 0.0) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n, dtype=np.float32) / SR
    if wave_type == "square":
        s = np.sign(np.sin(2 * np.pi * freq * t)) * 0.6
    elif wave_type == "saw":
        s = 2.0 * ((t * freq) % 1.0) - 1.0
    elif wave_type == "tri":
        s = 2.0 * np.abs(2.0 * ((t * freq) % 1.0) - 1.0) - 1.0
    else:
        s = np.sin(2 * np.pi * freq * t)
        if detune:
            s = 0.6 * s + 0.4 * np.sin(2 * np.pi * (freq * (1 + detune)) * t)
    return s * _envelope(n)


def _noise(dur: float, lowpass: float = 0.15) -> np.ndarray:
    n = int(SR * dur)
    rng = np.random.default_rng(4)
    raw = rng.standard_normal(n).astype(np.float32)
    # cheap one-pole low pass, then a sweep envelope for "whoosh"
    out = np.empty_like(raw)
    acc = 0.0
    k = lowpass
    for i in range(n):
        acc += k * (raw[i] - acc)
        out[i] = acc
    out *= _envelope(n, 0.15, 0.5)
    return out / (np.abs(out).max() + 1e-6)


def _mix(*parts: np.ndarray) -> np.ndarray:
    n = max(p.size for p in parts)
    out = np.zeros(n, dtype=np.float32)
    for p in parts:
        out[:p.size] += p
    return np.clip(out * 0.7, -1.0, 1.0)


def _build(name: str) -> np.ndarray:
    if name == "alarm_two_tone":
        return _mix(_tone(880, 0.22, "square"), np.concatenate([
            np.zeros(int(SR * 0.26)), _tone(622, 0.30, "square")]))
    if name == "soft_chime":
        return _mix(_tone(523.25, 1.1, "sine", 0.004), _tone(659.25, 0.9, "sine", 0.004),
                    _tone(783.99, 0.7, "sine", 0.004))
    if name == "heartbeat":
        thump = _tone(62, 0.16, "tri") * 1.2
        return np.concatenate([thump, np.zeros(int(SR * 0.12)),
                               thump * 0.75, np.zeros(int(SR * 0.45)),
                               thump, np.zeros(int(SR * 0.12)), thump * 0.7])
    if name == "whoosh":
        return _noise(0.9, 0.10)
    if name == "digital_beep":
        beep = _tone(1244, 0.09, "square")
        gap = np.zeros(int(SR * 0.07), dtype=np.float32)
        return np.concatenate([beep, gap, beep, gap, beep])
    if name == "riser":
        n = int(SR * 1.0)
        t = np.arange(n, dtype=np.float32) / SR
        f = 300 + 1200 * (t / t[-1]) ** 2
        phase = 2 * np.pi * np.cumsum(f) / SR
        return (np.sin(phase) * _envelope(n, 0.2, 0.15)).astype(np.float32)
    return _tone(880, 0.3, "square")


WAV_CACHE: dict[str, bytes] = {}


def wav_bytes(name: str, volume: float = 1.0) -> bytes:
    key = f"{name}:{volume:.2f}"
    if key in WAV_CACHE:
        return WAV_CACHE[key]
    pcm = _build(name)
    pcm = np.clip(pcm * float(volume), -1.0, 1.0)
    data = (pcm * 32767).astype(np.int16).tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data)
    out = buf.getvalue()
    WAV_CACHE[key] = out
    return out


def duration(name: str) -> float:
    return _build(name).size / SR


SOUNDS: list[dict] = [
    {"key": "alarm_two_tone", "zh": "双音警报", "en": "Two-tone alarm"},
    {"key": "soft_chime", "zh": "柔和铃音", "en": "Soft chime"},
    {"key": "heartbeat", "zh": "心跳", "en": "Heartbeat"},
    {"key": "whoosh", "zh": "呼啸", "en": "Whoosh"},
    {"key": "digital_beep", "zh": "数字蜂鸣", "en": "Digital beeps"},
    {"key": "riser", "zh": "升调警报", "en": "Riser"},
]


class SoundPlayer:
    """Plays a synthesised cue ``repeat`` times without blocking the caller."""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.last_error: str | None = None

    def play(self, name: str, volume: float = 0.7, repeat: int = 1, delay_ms: int = 0) -> None:
        if winsound is None:
            self.last_error = "winsound unavailable (Windows only)"
            return
        self.stop()
        self._stop.clear()
        data = wav_bytes(name, volume)

        def run():
            try:
                if delay_ms:
                    if self._stop.wait(delay_ms / 1000.0):
                        return
                for _ in range(max(1, int(repeat))):
                    if self._stop.is_set():
                        return
                    winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_ASYNC)
                    if self._stop.wait(duration(name) + 0.08):
                        return
            except Exception as exc:                     # keep the guard alive
                self.last_error = str(exc)

        self._thread = threading.Thread(target=run, name="sound", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if winsound is not None:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=0.3)
        self._thread = None
