"""Effect protocol."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from .draw import Color


@dataclass
class Ctx:
    w: int
    h: int
    t: float                      # seconds since the alert started
    color: Color
    secondary: Color
    intensity: float              # 0.1 .. 1.0
    opacity: float                # global alpha multiplier
    speed: float
    rng: np.random.Generator
    dark: bool = False            # content-hiding effects raise this


class Effect:
    """A screen-space effect.

    ``render`` must return a full-size RGBA image for the alert geometry; the
    overlay upscales it and alpha-blends it over the desktop.
    """

    key: str = ""
    label_zh: str = ""
    label_en: str = ""
    hint: str = ""
    hides_content: bool = False

    def render(self, ctx: Ctx) -> Image.Image:      # pragma: no cover - abstract
        raise NotImplementedError

    # helpers ---------------------------------------------------------------
    @staticmethod
    def blank(w: int, h: int) -> Image.Image:
        return Image.new("RGBA", (w, h), (0, 0, 0, 0))

    @staticmethod
    def a(base: Image.Image, layer: Image.Image | None) -> Image.Image:
        return base if layer is None else Image.alpha_composite(base, layer)
