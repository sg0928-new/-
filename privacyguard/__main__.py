"""Entry point.

    python -m privacyguard                 # panel + guard
    python -m privacyguard --no-panel      # background only (autostart uses this)
    python -m privacyguard --test 6        # start, then fire one alert for 6 s
    python -m privacyguard --camera 1      # override the configured camera
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

from . import config as cfgmod
from .app import GuardService


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="privacyguard",
                                 description="摄像头看护的屏幕隐私守护 / camera screen privacy guard")
    ap.add_argument("--no-panel", action="store_true", help="不带控制面板，纯后台运行")
    ap.add_argument("--test", type=float, default=0.0, metavar="SEC",
                    help="启动 SEC 秒后自动触发一次特效并持续 SEC 秒")
    ap.add_argument("--camera", type=int, default=None, help="覆盖配置中的摄像头序号")
    ap.add_argument("--config", default=None, help="使用指定的配置文件")
    ap.add_argument("--no-camera", action="store_true", help="不启动摄像头（只做特效/面板调试）")
    args = ap.parse_args(argv)

    cfg = cfgmod.load(args.config)
    if args.camera is not None:
        cfg["monitor"]["camera_index"] = args.camera

    service = GuardService(cfg)
    if service.overlay.start() is False and service.overlay._error:
        print("overlay:", service.overlay._error, file=sys.stderr)

    if args.no_camera:
        service.monitoring = False
        service._start_hotkeys()
        service.status["state"] = "no-camera"
    else:
        ok = service.start()
        if not ok:
            print("camera:", service.status.get("message") or "unavailable", file=sys.stderr)

    if args.test:
        threading.Timer(max(0.3, min(3.0, args.test / 2)),
                        lambda: service.trigger(source="cli-test")).start()

    if args.no_panel:
        print(f"PrivacyGuard {cfgmod.APP_NAME} running headless — Ctrl+C to stop", flush=True)
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            service.stop()
        return 0

    from .panel import Panel
    panel = Panel(service)
    try:
        panel.run()
    finally:
        service.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
