"""特效预览图生成：把每个特效渲染成 PNG 并拼成图集。

用途：README 效果展示 + 视觉回归核对（改特效后比对图片差异）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageDraw

from privacyguard import effects
from privacyguard.config import load


def render_all(out_dir: Path, width: int = 640, height: int = 400,
               at: tuple[float, ...] = (0.35, 1.1), bg: tuple[int, int, int] = (24, 26, 34)) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = load()
    written: list[Path] = []
    for key in effects.ORDER:
        eff = effects.get(key)
        panels = []
        for t in at:
            cfg["effect"]["names"] = [key]
            seq = effects.EffectSequencer(cfg)
            rng = np.random.default_rng(3)
            frame = effects.render_frame(cfg, (width, height), seq, t, rng)
            base = Image.new("RGBA", (width, height), (*bg, 255))
            # a fake desktop behind the effect so the alpha is legible
            d = ImageDraw.Draw(base)
            for i in range(0, height, 28):
                d.line([0, i, width, i], fill=(44, 48, 60, 255))
            d.rectangle([width * 0.12, height * 0.2, width * 0.88, height * 0.8],
                        outline=(90, 96, 112, 255), width=2)
            d.text((width * 0.14, height * 0.22), eff.label_zh, fill=(180, 186, 200, 255))
            panels.append(Image.alpha_composite(base, frame).convert("RGB"))
        row = Image.new("RGB", (width * len(panels) + 8 * (len(panels) - 1), height), bg)
        for i, p in enumerate(panels):
            row.paste(p, (i * (width + 8), 0))
        path = out_dir / f"{key}.png"
        row.save(path)
        written.append(path)
    return written


def contact_sheet(files: list[Path], out_path: Path, cols: int = 3) -> Path:
    thumbs = [Image.open(f).convert("RGB").resize((480, 300), Image.LANCZOS) for f in files]
    rows = (len(thumbs) + cols - 1) // cols
    pad = 10
    W = cols * 480 + pad * (cols + 1)
    H = rows * 300 + pad * (rows + 1) + 34
    sheet = Image.new("RGB", (W, H), (18, 20, 26))
    d = ImageDraw.Draw(sheet)
    d.text((pad + 2, 10), "PrivacyGuard — built-in screen effects / 内置特效一览",
           fill=(215, 220, 232))
    for i, th in enumerate(thumbs):
        r, c = divmod(i, cols)
        sheet.paste(th, (pad + c * (480 + pad), 34 + pad + r * (300 + pad)))
    sheet.save(out_path)
    return out_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="render effect previews")
    ap.add_argument("--out", default="docs/effects")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=400)
    args = ap.parse_args(argv)
    out = Path(args.out)
    files = render_all(out, args.width, args.height)
    sheet = contact_sheet(files, out / "_contact_sheet.png")
    print(f"{len(files)} effect previews -> {out}  (sheet: {sheet.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
