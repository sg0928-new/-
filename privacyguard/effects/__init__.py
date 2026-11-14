"""Effect registry and the frame producer used by the overlay."""

from __future__ import annotations

import time

import numpy as np
from PIL import Image

from .base import Ctx, Effect
from .builtin import BUILTIN
from .draw import parse_color

EFFECTS: dict[str, Effect] = {e.key: e for e in BUILTIN}
ORDER: list[str] = [e.key for e in BUILTIN]


def get(key: str) -> Effect:
    return EFFECTS.get(key, BUILTIN[0])


def describe() -> list[dict]:
    return [{"key": e.key, "zh": e.label_zh, "en": e.label_en, "hint": e.hint,
             "hides_content": e.hides_content} for e in BUILTIN]


def make_ctx(w: int, h: int, t: float, cfg: dict, rng: np.random.Generator,
             opacity_scale: float = 1.0) -> Ctx:
    eff = cfg.get("effect", cfg)
    return Ctx(
        w=w, h=h, t=t,
        color=parse_color(eff.get("color", "#FF3B30")),
        secondary=parse_color(eff.get("secondary", "#00E5FF")),
        intensity=float(eff.get("intensity", 0.9)),
        opacity=float(eff.get("opacity", 0.85)) * opacity_scale,
        speed=float(eff.get("speed", 1.0)),
        rng=rng,
    )


class EffectSequencer:
    """Chooses which effect is on screen at time ``t``.

    With ``random_mode`` the selected list is played as a randomised rotation
    every ``cycle_s`` seconds, so a long alert never looks static.
    """

    def __init__(self, cfg: dict, seed: int = 7):
        self.names: list[str] = []
        self.random_mode = False
        self.cycle_s = 2.5
        self.rng = np.random.default_rng(seed)
        self.configure(cfg)

    def configure(self, cfg: dict) -> None:
        eff = cfg.get("effect", {})
        names = [n for n in (eff.get("names") or []) if n in EFFECTS]
        self.names = names or ["pulse_frame"]
        self.random_mode = bool(eff.get("random_mode", False))
        self.cycle_s = max(1.0, float(eff.get("cycle_s", 2.5)))
        self._bag = list(self.names)

    def current(self, t: float) -> str:
        if not self.random_mode or len(self.names) == 1:
            return self.names[0] if len(self.names) == 1 else self.names[int(t / self.cycle_s) % len(self.names)]
        if not self._bag:
            self._bag = list(self.names)
        # deterministic per cycle index so re-renders agree
        idx = int(t / self.cycle_s)
        return self.names[idx % len(self.names)]


def render_frame(cfg: dict, size: tuple[int, int], seq: EffectSequencer, t: float,
                 rng: np.random.Generator, opacity_scale: float = 1.0) -> Image.Image:
    key = seq.current(t)
    ctx = make_ctx(size[0], size[1], t, cfg, rng, opacity_scale)
    img = get(key).render(ctx)
    if img.size != size:
        img = img.resize(size, Image.BILINEAR)
    return img
