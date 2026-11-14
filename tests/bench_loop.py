"""Measure what the product actually does: trigger the real guard, then sample
``status`` while the render thread is the only producer.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from privacyguard import config as cfgmod
from privacyguard.app import GuardService


def main() -> int:
    keys = sys.argv[1:] or ["pulse_frame", "matrix_rain", "frost", "rainbow_wash"]
    cfg = cfgmod.deep_merge(cfgmod.DEFAULTS, cfgmod.load())
    cfg["sound"]["enabled"] = False
    svc = GuardService(cfg)
    svc.overlay.start()
    print(f"virtual screen {svc.overlay.geometry[2]}x{svc.overlay.geometry[3]}, "
          f"quality {cfg['effect']['quality']}")
    for key in keys:
        svc.cfg["effect"]["names"] = [key]
        svc.cfg["effect"]["duration_s"] = 12.0
        svc.apply_config(svc.cfg)
        svc.trigger(source="bench")
        time.sleep(9.0)
        st = svc.status
        print(f"{key:14s} fx {st['render_fps']:5.1f} fps  q {st.get('quality_now', 0):.2f}  "
              f"cpu {st['cpu']:5.1f}%  stages(render,pre,up) {st.get('fx_ms')}")
        svc.stop_alert()
        time.sleep(0.4)
    svc.overlay.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
