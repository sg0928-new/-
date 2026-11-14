"""Drawing primitives shared by the effects.

Everything here works on numpy arrays or PIL images and is sized to the effect
render resolution (a fraction of the real screen), then upscaled once by the
overlay. That split is what keeps a full-screen effect at 30 fps on a laptop
CPU: the expensive per-pixel maths happens on ~0.5 M pixels, not on 8 M.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

Color = tuple[int, int, int]


def parse_color(value, fallback: Color = (255, 59, 48)) -> Color:
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        return tuple(int(max(0, min(255, c))) for c in value[:3])
    if isinstance(value, str):
        s = value.strip().lstrip("#")
        if len(s) == 3:
            s = "".join(ch * 2 for ch in s)
        if len(s) == 6:
            try:
                return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                return fallback
    return fallback


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def ease_pulse(t: float, freq: float = 1.0, lo: float = 0.0, hi: float = 1.0) -> float:
    """Smooth 0..1 oscillation."""
    return lo + (hi - lo) * (0.5 - 0.5 * np.cos(2 * np.pi * freq * t))


def smoothstep(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


# ---------------------------------------------------------------- alpha maps
def radial_alpha(w: int, h: int, cx: float = 0.5, cy: float = 0.5,
                 rx: float = 0.5, ry: float = 0.5, power: float = 2.0,
                 inner: float = 0.0, outer: float = 1.0) -> np.ndarray:
    """Normalised elliptical falloff, ``inner`` at the centre, ``outer`` at the rim."""
    ys = (np.arange(h, dtype=np.float32) / max(1, h - 1) - cy) / max(1e-6, ry)
    xs = (np.arange(w, dtype=np.float32) / max(1, w - 1) - cx) / max(1e-6, rx)
    r = np.sqrt(xs[None, :] ** 2 + ys[:, None] ** 2)
    r = np.clip(r, 0.0, 1.0)
    return inner + (outer - inner) * (r ** power)


def edge_alpha(w: int, h: int, falloff: float = 0.22) -> np.ndarray:
    """1 at the border, 0 once inside ``falloff`` of the half-size — the reverse
    of a vignette, used to paint frames and glows that hug the screen edge."""
    ys = np.minimum(np.arange(h, dtype=np.float32), np.arange(h - 1, -1, -1, dtype=np.float32))
    xs = np.minimum(np.arange(w, dtype=np.float32), np.arange(w - 1, -1, -1, dtype=np.float32))
    d = np.minimum(ys[:, None], xs[None, :])
    band = max(1.0, falloff * min(w, h))
    return np.clip(1.0 - d / band, 0.0, 1.0) ** 1.5


def band_alpha(w: int, h: int, thickness: float, softness: float = 1.0) -> np.ndarray:
    ys = np.minimum(np.arange(h, dtype=np.float32), np.arange(h - 1, -1, -1, dtype=np.float32))
    xs = np.minimum(np.arange(w, dtype=np.float32), np.arange(w - 1, -1, -1, dtype=np.float32))
    d = np.minimum(ys[:, None], xs[None, :])
    k = max(1.0, thickness)
    return np.clip(1.0 - (d - k) / (softness * k + 1e-6), 0.0, 1.0) if thickness > 0 else np.zeros((h, w))


# ---------------------------------------------------------------- compositing
def layer_from_alpha(alpha: np.ndarray, color: Color, opacity: float = 1.0) -> Image.Image:
    a = np.clip(alpha * opacity, 0.0, 1.0)
    rgba = np.empty((alpha.shape[0], alpha.shape[1], 4), dtype=np.uint8)
    rgba[..., 0] = color[0]
    rgba[..., 1] = color[1]
    rgba[..., 2] = color[2]
    rgba[..., 3] = (a * 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def glow_layer(size: tuple[int, int], draw_fn, blur: float = 6.0,
               color: Color = (255, 255, 255), opacity: float = 1.0) -> Image.Image:
    """Draw with ``draw_fn(draw, w, h)`` on a transparent canvas, then blur it."""
    w, h = size
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw_fn(draw, w, h, color)
    if blur > 0:
        canvas = canvas.filter(ImageFilter.GaussianBlur(blur))
    if opacity != 1.0:
        alpha = canvas.getchannel("A").point(lambda v: int(v * opacity))
        canvas.putalpha(alpha)
    return canvas


def composite(base: Image.Image, layer: Image.Image) -> Image.Image:
    if layer is None:
        return base
    return Image.alpha_composite(base, layer)


def make_noise(w: int, h: int, rng: np.random.Generator, scale: float = 1.0) -> np.ndarray:
    """Cheap grain: one random buffer, reused for every channel offset."""
    if scale != 1.0:
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        small = rng.random((nh, nw), dtype=np.float32)
        return np.array(Image.fromarray((small * 255).astype(np.uint8)).resize((w, h),
                        Image.BILINEAR), dtype=np.float32) / 255.0
    return rng.random((h, w), dtype=np.float32)


def glow_sprite(radius: int, color: Color, softness: float = 2.0) -> Image.Image:
    """Small radial sprite pasted repeatedly for particles (cheaper than per-particle blur)."""
    d = radius * 2
    a = radial_alpha(d, d, 0.5, 0.5, 0.5, 0.5, power=softness, inner=1.0, outer=0.0)
    return layer_from_alpha(a, color, 1.0)


_CJK_FONTS = ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc",
              "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc")


def font(size: int = 16, bold: bool = False):
    """A TrueType face that can render Chinese, falling back to PIL's bitmap font."""
    from PIL import ImageFont
    for path in _CJK_FONTS[1:] if bold else _CJK_FONTS:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def rect_path(u: float, w: int, h: int) -> tuple[float, float]:
    """Map a distance along the screen perimeter to an (x, y) point."""
    per = 2 * (w + h)
    u = u % per
    if u < w:
        return u, 0.0
    u -= w
    if u < h:
        return float(w - 1), u
    u -= h
    if u < w:
        return float(w - 1 - u), float(h - 1)
    u -= w
    return 0.0, float(h - 1 - u)


def hsv_gradient(w: int, h: int, t: float, angle: float = 0.0) -> np.ndarray:
    """Animated hue gradient as an RGB float array — used by the rainbow wash.

    Built from three phase-shifted cosine waves instead of an HSV lookup table:
    the table version allocated a 6*h*w*3 float array (≈80 MB at 0.45 MP and the
    slowest effect in the benchmark), this one stays at 3*h*w floats.
    """
    xs = np.arange(w, dtype=np.float32) / max(1, w)
    ys = np.arange(h, dtype=np.float32)[:, None] / max(1, h)
    ph = (np.cos(angle) * xs[None, :] + np.sin(angle) * ys + t * 0.25) % 1.0
    tau = 2.0 * np.pi
    rgb = np.empty((h, w, 3), dtype=np.float32)
    for k in range(3):
        rgb[..., k] = 0.5 + 0.5 * np.cos(tau * (ph + k / 3.0))
    return rgb


def _hsv_gradient_table(w: int, h: int, t: float, angle: float = 0.0) -> np.ndarray:
    ys = np.arange(h, dtype=np.float32)[:, None] / max(1, h)
    xs = np.arange(w, dtype=np.float32)[None, :] / max(1, w)
    ph = (np.cos(angle) * xs + np.sin(angle) * ys + t * 0.25) % 1.0
    hue = ph * 6.0
    i = np.floor(hue).astype(np.int32) % 6
    f = hue - np.floor(hue)
    p, q, r = 1.0 - f, 1.0 - f, f          # only used through the table below
    one = np.ones_like(f)
    zero = np.zeros_like(f)
    table = np.stack([
        np.stack([one, r, zero], -1),
        np.stack([q, one, zero], -1),
        np.stack([zero, one, p], -1),
        np.stack([zero, q, one], -1),
        np.stack([r, zero, one], -1),
        np.stack([one, zero, q], -1),
    ], axis=0)
    rgb = np.take_along_axis(table, i[None, ..., None], axis=0)[0]
    return rgb
