"""Verify the overlay actually composites: put a plain white window on screen,
cover it with only the red overlay layer, and save a GDI screenshot of that area.
"""

from __future__ import annotations

import ctypes
import sys
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageGrab

from privacyguard.overlay import ScreenOverlay, premultiply_bgra


def main() -> int:
    root = tk.Tk()
    root.geometry("420x300+80+80")
    root.attributes("-topmost", True)
    tk.Label(root, text="底图 / base window", bg="white", fg="black",
             font=("Segoe UI", 20)).pack(fill="both", expand=True)
    root.update()

    ov = ScreenOverlay(multi_monitor=False)
    ov.start()
    w, h = ov.size
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., 0] = 255              # red, 140/255 alpha
    rgba[..., 3] = 140
    frame = premultiply_bgra(Image.fromarray(rgba, "RGBA"))
    for _ in range(40):
        ov.push(frame, (w, h))
        root.update()
        time.sleep(0.03)

    shot = ImageGrab.grab(bbox=(80, 80, 500, 380), all_screens=True)
    out = Path(__file__).resolve().parents[1] / "outputs" / "_overlay_proof.png"
    out.parent.mkdir(exist_ok=True)
    shot.save(out)
    print("visible:", ov.visible, "err:", ov._error, "saved:", out)
    ov.stop()
    root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
