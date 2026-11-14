"""Diagnose why the layered window does not appear."""

from __future__ import annotations

import ctypes
import sys
import threading
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image

from privacyguard.overlay import ScreenOverlay, premultiply_bgra, user32


def main() -> int:
    ov = ScreenOverlay(multi_monitor=True)
    print("start ->", ov.start())
    time.sleep(0.6)
    print("thread alive:", ov._thread.is_alive() if ov._thread else None)
    print("hwnd:", ov._hwnd, "class atom:", ov._class_atom, "err:", ov._error)
    print("visible:", ov.visible, "run:", ov._run)

    w, h = ov.size
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., 0] = 255
    rgba[..., 3] = 140
    frame = premultiply_bgra(Image.fromarray(rgba, "RGBA"))
    ov.push(frame, (w, h))
    time.sleep(0.6)
    print("after push: visible:", ov.visible, "err:", ov._error)
    hwnd = ov._hwnd
    if hwnd:
        print("IsWindowVisible:", bool(user32.IsWindowVisible(hwnd)))
        rect = (ctypes.c_long * 4)()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        print("rect:", list(rect))
        print("exstyle:", hex(user32.GetWindowLongW(hwnd, -20) & 0xFFFFFFFF))
        print("parent/owner:", user32.GetWindow(hwnd, 4))   # GW_OWNER
    # dump the overlay thread stack if it is stuck
    if ov._thread and ov._thread.is_alive():
        frames = sys._current_frames()
        for tid, frame_ in frames.items():
            if tid == ov._thread.ident:
                traceback.print_stack(frame_)
    ov.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
