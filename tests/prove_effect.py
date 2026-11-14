"""End-to-end proof: real effect engine -> overlay window -> actual screen pixels.

Puts a plain white window on screen, fires the guard for one effect, and grabs
that area so the composited result can be eyeballed or committed as a screenshot.
"""

from __future__ import annotations

import sys
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import ImageGrab

from privacyguard import config as cfgmod
from privacyguard.app import GuardService

OUT = Path(__file__).resolve().parents[1] / "outputs"
BOX = (0, 0, 860, 560)


def main() -> int:
    keys = sys.argv[1:] or ["pulse_frame", "scanlines", "aperture", "radar"]
    root = tk.Tk()
    root.geometry("860x560+0+0")
    root.attributes("-topmost", True)
    root.overrideredirect(True)
    tk.Label(root, text="PrivacyGuard 特效验证底图（模拟深色桌面）", bg="#12161c", fg="#dfe5ee",
             font=("Microsoft YaHei UI", 20)).pack(fill="both", expand=True)
    root.update()
    time.sleep(0.4)

    cfg = cfgmod.deep_merge(cfgmod.DEFAULTS, cfgmod.load())
    cfg["effect"]["quality"] = 0.55
    cfg["effect"]["fade_s"] = 0.2
    cfg["sound"]["enabled"] = False
    svc = GuardService(cfg)
    svc.overlay.start()
    svc._det = __import__("privacyguard.detector", fromlist=["FaceDetector"]).FaceDetector()

    OUT.mkdir(exist_ok=True)
    for key in keys:
        cfg["effect"]["names"] = [key]
        cfg["effect"]["duration_s"] = 3.0
        svc.apply_config(cfg)
        svc.trigger(source="proof")
        for _ in range(30):
            root.update()
            time.sleep(0.04)
        img = ImageGrab.grab(bbox=BOX, all_screens=True)
        path = OUT / f"_fx_{key}.png"
        img.save(path)
        print("saved", path, "visible:", svc.overlay.visible, "err:", svc.overlay._error)
        svc.stop_alert()
        time.sleep(0.4)
        root.update()

    svc.overlay.stop()
    root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
