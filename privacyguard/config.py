"""Configuration model: defaults, presets, load/save with clamping.

Everything the control panel edits lives in one JSON document under
``%APPDATA%\\PrivacyGuard\\config.json`` so the exe/python entry point can be
started from any directory.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

APP_NAME = "PrivacyGuard"

DEFAULTS: dict = {
    "version": 1,
    "monitor": {
        "enabled": True,
        "camera_index": 0,
        "width": 640,
        "height": 480,
        "detect_width": 320,
        "detect_interval_ms": 100,
        "scale_factor": 1.15,
        "min_neighbors": 5,
        "min_face_px": 28,
        "allowed_own_faces": 1,
        "confirm_frames": 4,
        "cooldown_s": 12.0,
        "release_s": 2.0,
        "detect_profiles": True,
    },
    "effect": {
        "names": ["pulse_frame"],
        "random_mode": False,
        "cycle_s": 2.5,
        "color": "#FF3B30",
        "secondary": "#00E5FF",
        "intensity": 0.9,
        "opacity": 0.85,
        "speed": 1.0,
        "duration_s": 8.0,
        "fade_s": 0.35,
        "quality": 0.5,
        "multi_monitor": True,
    },
    "sound": {
        "enabled": True,
        "name": "alarm_two_tone",
        "volume": 0.7,
        "repeat": 2,
        "delay_ms": 0,
    },
    "hotkeys": {"panel": "ctrl+alt+p", "test": "ctrl+alt+t", "toggle": "ctrl+alt+space"},
    "general": {"autostart": False, "start_minimized": False, "log": True},
}

PRESETS: dict[str, dict] = {
    "red_frame": {
        "label": "极简红框",
        "effect": {"names": ["pulse_frame"], "color": "#FF3B30", "opacity": 0.7,
                   "intensity": 0.8, "speed": 1.0, "random_mode": False},
    },
    "cyber_glitch": {
        "label": "赛博故障",
        "effect": {"names": ["glitch", "scanlines", "noise_static"], "random_mode": True,
                   "cycle_s": 1.8, "color": "#00E5FF", "secondary": "#FF00A8",
                   "opacity": 0.9, "intensity": 1.0, "speed": 1.6},
    },
    "soft_guard": {
        "label": "柔光守护",
        "effect": {"names": ["vignette_focus", "rainbow_wash"], "random_mode": True,
                   "cycle_s": 4.0, "color": "#7C4DFF", "opacity": 0.55,
                   "intensity": 0.7, "speed": 0.7},
    },
    "matrix": {
        "label": "数字雨",
        "effect": {"names": ["matrix_rain", "scanlines"], "random_mode": False,
                   "color": "#00FF88", "opacity": 0.8, "speed": 1.0},
    },
    "radar": {
        "label": "雷达侦察",
        "effect": {"names": ["radar", "marquee"], "random_mode": True, "cycle_s": 3.0,
                   "color": "#00E5FF", "opacity": 0.75, "speed": 1.2},
    },
    "max_shield": {
        "label": "隐私护盾（挡内容）",
        "effect": {"names": ["frost", "curtain"], "random_mode": False,
                   "color": "#0A84FF", "opacity": 0.95, "intensity": 1.0, "speed": 0.9},
        "sound": {"enabled": True, "name": "alarm_two_tone", "volume": 0.85, "repeat": 3},
    },
}

# numeric clamps: (min, max) applied on load so a hand-edited file cannot
# produce a frozen UI or a 0-size overlay
CLAMP: dict[tuple[str, str], tuple[float, float]] = {
    ("monitor", "camera_index"): (0, 8),
    ("monitor", "width"): (160, 1920),
    ("monitor", "height"): (120, 1080),
    ("monitor", "detect_width"): (160, 640),
    ("monitor", "detect_interval_ms"): (30, 1000),
    ("monitor", "scale_factor"): (1.02, 1.6),
    ("monitor", "min_neighbors"): (2, 12),
    ("monitor", "min_face_px"): (16, 160),
    ("monitor", "allowed_own_faces"): (0, 4),
    ("monitor", "confirm_frames"): (1, 20),
    ("monitor", "cooldown_s"): (2.0, 120.0),
    ("monitor", "release_s"): (0.5, 10.0),
    ("effect", "cycle_s"): (1.0, 30.0),
    ("effect", "intensity"): (0.1, 1.0),
    ("effect", "opacity"): (0.05, 1.0),
    ("effect", "speed"): (0.2, 4.0),
    ("effect", "duration_s"): (1.0, 60.0),
    ("effect", "fade_s"): (0.0, 2.0),
    ("effect", "quality"): (0.2, 1.0),
    ("sound", "volume"): (0.0, 1.0),
    ("sound", "repeat"): (1, 8),
    ("sound", "delay_ms"): (0, 5000),
}


def config_dir() -> Path:
    root = os.environ.get("APPDATA") or str(Path.home())
    return Path(root) / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def clamp_values(cfg: dict) -> dict:
    for (section, key), (lo, hi) in CLAMP.items():
        sec = cfg.get(section)
        if not isinstance(sec, dict) or key not in sec:
            continue
        try:
            val = float(sec[key])
        except (TypeError, ValueError):
            continue
        sec[key] = type(DEFAULTS[section][key])(max(lo, min(hi, val)))
    names = cfg.get("effect", {}).get("names") or []
    if not isinstance(names, list):
        cfg["effect"]["names"] = list(DEFAULTS["effect"]["names"])
    return cfg


def load(path: Path | str | None = None) -> dict:
    p = Path(path) if path else config_path()
    cfg = copy.deepcopy(DEFAULTS)
    if p.exists():
        try:
            cfg = deep_merge(DEFAULTS, json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            cfg = copy.deepcopy(DEFAULTS)   # corrupt file: fall back, keep running
    return clamp_values(cfg)


def save(cfg: dict, path: Path | str | None = None) -> Path:
    p = Path(path) if path else config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(clamp_values(copy.deepcopy(cfg)), indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(p)
    return p


def apply_preset(cfg: dict, key: str) -> dict:
    preset = PRESETS.get(key)
    if not preset:
        return cfg
    out = deep_merge(cfg, {k: v for k, v in preset.items() if k != "label"})
    return clamp_values(out)
