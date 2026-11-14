"""Generate the application icon (and the tray-ish preview) with PIL only.

    python tools/make_icon.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "assets"


def draw(size: int) -> Image.Image:
    s = size * 4                                  # supersample for clean edges
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(s * 0.22)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=(18, 20, 26, 255))
    # red alert frame
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    inset = int(s * 0.10)
    gd.rounded_rectangle([inset, inset, s - inset, s - inset], radius=int(r * 0.7),
                         outline=(255, 59, 48, 255), width=max(2, int(s * 0.035)))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(int(s * 0.03))))
    img = Image.alpha_composite(img, glow)
    # watching eye
    eye = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ed = ImageDraw.Draw(eye)
    cx, cy = s / 2, s / 2
    ew, eh = s * 0.54, s * 0.30
    ed.ellipse([cx - ew / 2, cy - eh / 2, cx + ew / 2, cy + eh / 2],
               outline=(232, 237, 246, 255), width=max(2, int(s * 0.020)))
    ir = s * 0.075
    ed.ellipse([cx - ir * 1.7, cy - ir * 1.7, cx + ir * 1.7, cy + ir * 1.7],
               fill=(0, 229, 255, 255))
    ed.ellipse([cx - ir, cy - ir, cx + ir, cy + ir], fill=(10, 12, 16, 255))
    img = Image.alpha_composite(img, eye)
    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = draw(256)
    base.save(OUT / "icon.png")
    base.save(OUT / "icon.ico", sizes=[(s, s) for s in sizes])
    print("icon ->", OUT / "icon.ico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
