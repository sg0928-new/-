"""Overlay smoke test: push a solid half-transparent frame for a few seconds.

Run it, look at the screen (it should turn red-ish, get darker, and still let you
click/drag through to the desktop), then read the printed diagnostics.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image

from privacyguard.overlay import ScreenOverlay, premultiply_bgra


def main() -> int:
    ov = ScreenOverlay(multi_monitor=True)
    print("start:", ov.start(), "geometry:", ov.geometry, "err:", ov._error)
    w, h = ov.size
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., 0] = 255          # red
    rgba[..., 3] = 120
    frame = premultiply_bgra(Image.fromarray(rgba, "RGBA"))
    t0 = time.time()
    pushed = 0
    while time.time() - t0 < 4.0:
        ov.push(frame, (w, h))
        pushed += 1
        time.sleep(0.05)
    print(f"pushed {pushed} frames, visible={ov.visible}, err={ov._error}")
    ov.stop()
    print("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
