"""Screenshot each panel tab, so the GUI can be reviewed without a human at the desk.

    python tests/shot_panel.py          # all four tabs -> outputs/_panel_tab*.png
    python tests/shot_panel.py 1        # only tab 1
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import ImageGrab

from privacyguard import config as cfgmod
from privacyguard.app import GuardService
from privacyguard.panel import Panel

OUT = Path(__file__).resolve().parents[1] / "outputs"


def shoot(panel: Panel, index: int, name: str, scroll: bool = False) -> None:
    panel.root.deiconify()
    panel.root.lift()
    panel.root.attributes("-topmost", True)
    try:
        panel.root.focus_force()
    except Exception:
        pass
    panel.nb.select(index)
    for _ in range(14):
        panel.root.update()
        time.sleep(0.06)
    if scroll:
        panel._canvases[index].yview_moveto(1.0)
        for _ in range(14):
            panel.root.update()
            time.sleep(0.06)
    x, y = panel.root.winfo_rootx(), panel.root.winfo_rooty()
    w, h = panel.root.winfo_width(), panel.root.winfo_height()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    OUT.mkdir(exist_ok=True)
    path = OUT / f"_panel_{name}.png"
    img.save(path)
    print("saved", path, img.size)


def main() -> int:
    svc = GuardService(cfgmod.load())
    svc.overlay.start()
    panel = Panel(svc)
    idx = sys.argv[1] if len(sys.argv) > 1 else None
    tabs = [(0, "monitor"), (1, "effects"), (2, "sound"), (3, "general")]
    for i, name in tabs:
        if idx is not None and str(i) != str(idx):
            continue
        shoot(panel, i, name)
        if i == 1:
            shoot(panel, i, "effects_preview", scroll=True)
    panel.root.destroy()
    svc.overlay.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
