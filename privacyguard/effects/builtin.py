"""The built-in screen effects.

Each entry is a pure function of (size, time, params) — no global state — so the
control panel can preview one at a time and the overlay can cross-fade between
them without bookkeeping.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .base import Ctx, Effect
from .draw import (band_alpha, composite, ease_pulse, edge_alpha, glow_layer,
                   glow_sprite, hsv_gradient, layer_from_alpha, make_noise,
                   parse_color, radial_alpha, rect_path, smoothstep)


class PulseFrame(Effect):
    key = "pulse_frame"
    label_zh = "脉冲红框"
    label_en = "Pulse frame"
    hint = "边框按心跳节奏发光，四角带柔光。最克制，干扰最小。"

    def render(self, ctx: Ctx) -> Image.Image:
        w, h = ctx.w, ctx.h
        beat = 0.55 + 0.45 * ease_pulse(ctx.t, 1.05 * ctx.speed)
        thick = (0.018 + 0.012 * beat) * min(w, h)
        a = edge_alpha(w, h, falloff=0.11) * (0.35 + 0.65 * beat) * ctx.intensity
        img = layer_from_alpha(a, ctx.color, ctx.opacity)

        def corners(draw, w, h, color):
            r = int(min(w, h) * 0.22)
            for cx, cy in ((0, 0), (w, 0), (0, h), (w, h)):
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*color, int(150 * beat)))

        img = composite(img, glow_layer((w, h), corners,
                                        blur=max(6, min(w, h) * 0.035),
                                        color=ctx.color, opacity=0.55 * ctx.opacity))
        return img


class VignetteFocus(Effect):
    key = "vignette_focus"
    label_zh = "暗角聚焦"
    label_en = "Vignette focus"
    hint = "四周压暗、中央提亮，把注意力收回到屏幕正中。"

    def render(self, ctx: Ctx) -> Image.Image:
        w, h = ctx.w, ctx.h
        breathe = 0.85 + 0.15 * math.sin(ctx.t * 2.0 * ctx.speed)
        dark = radial_alpha(w, h, 0.5, 0.5, 0.62 * breathe, 0.62 * breathe, power=2.0,
                            inner=0.0, outer=1.0) * 0.85 * ctx.intensity
        img = layer_from_alpha(dark, (0, 0, 0), ctx.opacity * 0.95)
        # tinted rim so the effect is legible on an already-dark desktop
        rim = edge_alpha(w, h, falloff=0.18) ** 2 * ctx.intensity
        img = composite(img, layer_from_alpha(rim, ctx.color, ctx.opacity * 0.55))
        core = radial_alpha(w, h, 0.5, 0.5, 0.34, 0.34, power=2.0, inner=0.35, outer=0.0)
        img = composite(img, layer_from_alpha(core, ctx.secondary, 0.18 * ctx.opacity))
        return img


class Frost(Effect):
    key = "frost"
    label_zh = "磨砂霜化"
    label_en = "Frosted glass"
    hint = "冷色磨砂 + 冰晶颗粒。强度拉满时可当作“挡内容”的隐私护盾。"

    hides_content = True

    def render(self, ctx: Ctx) -> Image.Image:
        w, h = ctx.w, ctx.h
        base_a = 0.30 + 0.08 * math.sin(ctx.t * 0.9 * ctx.speed)
        a = np.full((h, w), base_a * ctx.intensity, dtype=np.float32)
        a *= 0.55 + 0.45 * edge_alpha(w, h, falloff=0.55)      # thicker at the rim
        img = layer_from_alpha(a, (118, 176, 232), ctx.opacity)

        noise = make_noise(w, h, ctx.rng, scale=0.5)
        grain = layer_from_alpha(np.clip(noise * 0.55 * ctx.intensity, 0, 1), (255, 255, 255),
                                 ctx.opacity * 0.7)
        img = composite(img, grain)

        def veins(draw, w, h, color):
            for _ in range(34):
                x, y = int(ctx.rng.integers(0, w)), int(ctx.rng.integers(0, h))
                ln = min(w, h) * ctx.rng.uniform(0.04, 0.16)
                ang = ctx.rng.uniform(0, math.tau)
                draw.line([x, y, x + ln * math.cos(ang), y + ln * math.sin(ang)],
                          fill=(*color, 230), width=max(1, int(min(w, h) / 320)))

        img = composite(img, glow_layer((w, h), veins, blur=1.2, color=(245, 252, 255),
                                        opacity=0.75 * ctx.opacity))
        # cold rim light so it reads as glass, not a gray rectangle
        rim = edge_alpha(w, h, falloff=0.1) * 0.7 * ctx.intensity
        return composite(img, layer_from_alpha(rim, ctx.color, ctx.opacity * 0.45))


class Curtain(Effect):
    key = "curtain"
    label_zh = "隐私幕帘"
    label_en = "Privacy curtain"
    hint = "上下幕帘合拢，边缘发光。护盾模式的经典做法。"

    hides_content = True

    def render(self, ctx: Ctx) -> Image.Image:
        w, h = ctx.w, ctx.h
        close = smoothstep(min(1.0, ctx.t / 0.6)) * (0.42 + 0.18 * ctx.intensity)
        bar = int(h * close)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        alpha = int(255 * ctx.opacity * 0.92)
        draw.rectangle([0, 0, w, bar], fill=(6, 8, 12, alpha))
        draw.rectangle([0, h - bar, w, h], fill=(6, 8, 12, alpha))
        glow = int(220 * ctx.opacity)
        draw.line([0, bar, w, bar], fill=(*ctx.color, glow), width=max(2, h // 260))
        draw.line([0, h - bar, w, h - bar], fill=(*ctx.color, glow), width=max(2, h // 260))

        def halo(draw, w, h, color):
            draw.rectangle([0, bar - 6, w, bar + 6], fill=(*color, 140))
            draw.rectangle([0, h - bar - 6, w, h - bar + 6], fill=(*color, 140))

        return composite(img, glow_layer((w, h), halo, blur=max(4, h // 60),
                                         color=ctx.color, opacity=ctx.opacity * 0.8))


class Scanlines(Effect):
    key = "scanlines"
    label_zh = "CRT 扫描线"
    label_en = "CRT scanlines"
    hint = "细密扫描线 + 缓慢下移的亮带，复古监视器质感。"

    def render(self, ctx: Ctx) -> Image.Image:
        w, h = ctx.w, ctx.h
        period = max(3, int(h / max(1, ctx.intensity * 200)))
        a = np.zeros((h, w), dtype=np.float32)
        a[::period, :] = 0.75 * ctx.intensity
        band_y = int((ctx.t * 0.35 * ctx.speed % 1.0) * h)
        band_h = max(4, int(h * 0.07))
        ys = np.arange(h, dtype=np.float32)
        d = np.abs(((ys - band_y + h) % h) - h / 2)
        band = np.clip(1.0 - d / (band_h / 2), 0, 1) ** 2
        a = np.clip(a * 0.8 + band[:, None] * 0.55 * ctx.intensity, 0, 1)
        img = layer_from_alpha(a, (0, 0, 0), ctx.opacity * 0.9)
        img = composite(img, layer_from_alpha(a, ctx.color, ctx.opacity * 0.55))

        def beam(draw, w, h, color):
            draw.rectangle([0, band_y - band_h / 4, w, band_y + band_h / 4], fill=(*color, 210))

        return composite(img, glow_layer((w, h), beam, blur=max(3, h // 70),
                                         color=ctx.color, opacity=0.85 * ctx.opacity))


class Glitch(Effect):
    key = "glitch"
    label_zh = "故障撕裂"
    label_en = "Glitch tear"
    hint = "横向条带错位 + RGB 分离 + 雪花，赛博警报感最强。"

    def render(self, ctx: Ctx) -> Image.Image:
        w, h = ctx.w, ctx.h
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        rng = ctx.rng
        n_band = int(6 + 14 * ctx.intensity)
        for _ in range(n_band):
            y = int(rng.integers(0, h))
            bh = int(rng.integers(max(2, h // 120), max(4, h // 22)))
            col = ctx.color if rng.random() < 0.6 else ctx.secondary
            a = int(rng.integers(60, 200) * ctx.opacity * ctx.intensity)
            dx = int(rng.normal(0, w * 0.02))
            img.paste(Image.new("RGBA", (w, bh), (*col, a)), (dx, y))
            if rng.random() < 0.5:
                img.paste(Image.new("RGBA", (w, bh // 2), (255, 255, 255, a // 2)),
                          (-dx, y + bh // 2))
        noise = make_noise(w, h, rng, scale=0.35)
        img = composite(img, layer_from_alpha(np.clip(noise * 0.5 * ctx.intensity, 0, 1),
                                             (255, 255, 255), ctx.opacity * 0.35))
        # scan tear line
        y = int((ctx.t * 1.4 * ctx.speed % 1.0) * h)
        tear = (np.abs(np.arange(h, dtype=np.float32) - y) < max(1, h // 300))
        tear = np.repeat(tear[:, None].astype(np.float32) * 0.9, w, axis=1)
        img = composite(img, layer_from_alpha(np.clip(tear, 0, 1), ctx.secondary, ctx.opacity * 0.8))
        return img


class MatrixRain(Effect):
    key = "matrix_rain"
    label_zh = "数字雨"
    label_en = "Digital rain"
    hint = "纵向坠落的数据流，尾迹渐变。"

    def render(self, ctx: Ctx) -> Image.Image:
        w, h = ctx.w, ctx.h
        rng = ctx.rng
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        cols = max(24, int(w / 18))
        cw = w / cols
        t = ctx.t * ctx.speed
        trail = max(20, int(h * 0.42))
        for i in range(cols):
            for lane in range(2):
                speed = 0.35 + 0.55 * ((i * 7 + lane * 13) % 11) / 11.0
                phase = (t * speed + (i * 3 + lane * 5) % 17 / 17.0) % 1.0
                head = int(phase * (h + trail)) - trail
                for k in range(0, trail, 3):
                    y = head + k
                    if not (0 <= y < h):
                        continue
                    fall = 1.0 - k / trail
                    a = int(235 * (fall ** 1.4) * ctx.opacity * ctx.intensity)
                    if a < 4:
                        continue
                    x0 = i * cw + lane * cw * 0.4
                    draw.line([x0, y, x0 + cw * 0.45, y], fill=(*ctx.color, a), width=max(1, int(cw * 0.3)))
                hy = head + trail
                if 0 <= hy < h:
                    r = max(1, int(cw * 0.18))
                    draw.ellipse([i * cw + lane * cw * 0.4 - r, hy - r - 1,
                                  i * cw + lane * cw * 0.4 + cw * 0.45 + r, hy + r + 1],
                                 fill=(235, 255, 245, int(230 * ctx.opacity)))
        veil = np.full((h, w), 0.10 * ctx.intensity, dtype=np.float32)
        return composite(img, layer_from_alpha(veil, (0, 0, 0), ctx.opacity * 0.9))


class Particles(Effect):
    key = "particles"
    label_zh = "粒子汇聚"
    label_en = "Particle swarm"
    hint = "光点从四角汇聚到中央并爆开，循环呼吸。"

    def render(self, ctx: Ctx) -> Image.Image:
        w, h = ctx.w, ctx.h
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sprite = glow_sprite(max(6, int(min(w, h) * 0.035)), ctx.color, softness=1.6)
        n = int(90 * ctx.intensity) + 20
        t = ctx.t * ctx.speed
        for i in range(n):
            ph = (t * 0.8 + i / n * 3.0) % 1.0
            ang = i * 2.399963
            r = (1.0 - ph) * min(w, h) * 0.62
            cx = w / 2 + math.cos(ang) * r * 1.35
            cy = h / 2 + math.sin(ang) * r
            s = sprite.copy()
            a = int(255 * (ph ** 0.6) * ctx.opacity)
            s.putalpha(s.getchannel("A").point(lambda v, a=a: int(v * a / 255)))
            img.alpha_composite(s, (int(cx - sprite.width / 2), int(cy - sprite.height / 2)))
        core = radial_alpha(w, h, 0.5, 0.5, 0.12, 0.12, power=2.0, inner=1.0, outer=0.0)
        return composite(img, layer_from_alpha(core * (0.3 + 0.3 * ease_pulse(t, 2.0)),
                                               ctx.secondary, ctx.opacity))


class Radar(Effect):
    key = "radar"
    label_zh = "雷达扫掠"
    label_en = "Radar sweep"
    hint = "同心圆 + 旋转扇形 + 随机光点，像在被搜索。"

    def render(self, ctx: Ctx) -> Image.Image:
        w, h = ctx.w, ctx.h
        cx, cy = w / 2, h / 2
        rmax = min(w, h) * 0.55
        span = 55.0
        ang = (ctx.t * 1.1 * ctx.speed * 360) % 360
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)

        def wedge(draw, color, alpha_scale):
            steps = 22
            for k in range(steps):
                a0 = ang - span * k / steps
                a1 = ang - span * (k + 1) / steps
                al = int(alpha_scale * (1 - k / steps) ** 1.6)
                if al <= 2:
                    continue
                draw.polygon([(cx, cy),
                              (cx + rmax * math.cos(math.radians(a0)), cy + rmax * math.sin(math.radians(a0))),
                              (cx + rmax * math.cos(math.radians(a1)), cy + rmax * math.sin(math.radians(a1)))],
                             fill=(*color, al))

        wedge(d, ctx.color, int(150 * ctx.opacity * ctx.intensity))
        img = composite(img, layer)

        rings = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        rd = ImageDraw.Draw(rings)
        for k in range(1, 5):
            rr = rmax * k / 4
            rd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=(*ctx.color, 90), width=1)
        rd.line([cx, cy - rmax, cx, cy + rmax], fill=(*ctx.color, 60), width=1)
        rd.line([cx - rmax, cy, cx + rmax, cy], fill=(*ctx.color, 60), width=1)
        img = composite(img, rings)

        for _ in range(4 + int(6 * ctx.intensity)):
            ra = ctx.rng.uniform(0, math.tau)
            rr = rmax * ctx.rng.uniform(0.15, 0.95)
            p = (ra, rr)
            # blip stays lit for a moment after the sweep passes it
            phase = ((ang - math.degrees(ra)) % 360) / 360.0
            lit = max(0.0, 1.0 - phase * 3.0)
            if lit <= 0.05:
                continue
            dot = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            dd = ImageDraw.Draw(dot)
            x, y = cx + rr * math.cos(ra), cy + rr * math.sin(ra)
            rr2 = max(3, min(w, h) * 0.012)
            dd.ellipse([x - rr2, y - rr2, x + rr2, y + rr2],
                       fill=(*ctx.secondary, int(230 * lit * ctx.opacity)))
            img = composite(img, dot)
        return img


class HexGrid(Effect):
    key = "hexgrid"
    label_zh = "六边形脉冲"
    label_en = "Hex pulse"
    hint = "蜂窝网格从中心向外扩散的呼吸脉冲。"

    def render(self, ctx: Ctx) -> Image.Image:
        w, h = ctx.w, ctx.h
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        size = max(14, min(w, h) * 0.05)
        dx = size * math.sqrt(3)
        dy = size * 1.5
        rows = int(h / dy) + 2
        cols = int(w / dx) + 2
        cx, cy = w / 2, h / 2
        t = ctx.t * ctx.speed
        for r in range(rows):
            for c in range(cols):
                x = c * dx + (dx / 2 if r % 2 else 0) - dx / 2
                y = r * dy - dy / 2
                rho = math.hypot(x - cx, y - cy) / (min(w, h) * 0.6)
                pulse = 0.5 + 0.5 * math.sin(t * 2.2 - rho * 7.0)
                a = int(235 * pulse * ctx.intensity * max(0.0, 1.0 - rho * 0.55) * ctx.opacity)
                if a < 10:
                    continue
                pts = []
                for k in range(6):
                    th = math.pi / 3 * k + math.pi / 6
                    pts.append((x + size * math.cos(th), y + size * math.sin(th)))
                line_col = ctx.secondary if (r // 3) % 2 == 0 else ctx.color
                draw.polygon(pts, outline=(*line_col, a), width=max(1, int(size * 0.07)))
                if pulse > 0.78:
                    draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(*ctx.color, a))
        return img


class WatchEye(Effect):
    key = "watch_eye"
    label_zh = "凝视之眼"
    label_en = "Watching eye"
    hint = "屏幕中央一只眼睛睁开、虹膜左右扫视。心理压迫感强，遮挡少。"

    def render(self, ctx: Ctx) -> Image.Image:
        w, h = ctx.w, ctx.h
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        cx, cy = w / 2, h / 2
        ew = min(w, h) * 0.34
        eh = ew * 0.42
        open_ratio = 0.45 + 0.45 * min(1.0, ctx.t / 0.4) * (0.9 + 0.1 * math.sin(ctx.t * 1.6))
        lid = eh * open_ratio
        # eyelids as two arcs
        for sign in (-1, 1):
            pts = []
            for k in range(31):
                u = k / 30
                x = cx - ew + 2 * ew * u
                y = cy + sign * lid * math.sin(math.pi * u) * 0.9
                pts.append((x, y))
            draw.line(pts, fill=(*ctx.color, int(200 * ctx.opacity)), width=max(2, int(ew * 0.02)))
        # iris
        look = math.sin(ctx.t * 0.9 * ctx.speed) * ew * 0.38
        ir = lid * 0.85
        for k in range(6):
            rr = ir * (1 - k / 8)
            a = int(150 * ctx.opacity * (1 - k / 6))
            draw.ellipse([cx + look - rr, cy - rr, cx + look + rr, cy + rr],
                         outline=(*ctx.secondary, a))
        draw.ellipse([cx + look - ir * 0.35, cy - ir * 0.35, cx + look + ir * 0.35, cy + ir * 0.35],
                     fill=(*ctx.secondary, int(220 * ctx.opacity)))

        def halo(draw_, w_, h_, color):
            draw_.ellipse([cx - ew * 1.05, cy - lid * 1.4, cx + ew * 1.05, cy + lid * 1.4],
                          fill=(*color, 40))

        img = composite(img, glow_layer((w, h), halo, blur=max(4, ew * 0.12),
                                        color=ctx.color, opacity=ctx.opacity))
        # faint vignette so the eye reads as the only bright thing
        vig = radial_alpha(w, h, 0.5, 0.5, 0.55, 0.55, power=2.0, inner=0.0, outer=0.55)
        return composite(img, layer_from_alpha(vig * ctx.intensity, (0, 0, 0), ctx.opacity))


class RainbowWash(Effect):
    key = "rainbow_wash"
    label_zh = "流光溢彩"
    label_en = "Rainbow wash"
    hint = "全屏流动色相 + 柔和压暗，视觉讨好、不刺眼。"

    def render(self, ctx: Ctx) -> Image.Image:
        w, h = ctx.w, ctx.h
        rgb = hsv_gradient(w, h, ctx.t * ctx.speed * 0.6, angle=math.radians(30))
        a = radial_alpha(w, h, 0.5, 0.5, 0.85, 0.85, power=1.6, inner=1.0, outer=0.35)
        alpha = (a * 0.24 * ctx.intensity * ctx.opacity * 255).astype(np.uint8)
        rgba = np.dstack([(rgb * 255).astype(np.uint8), alpha])
        return Image.fromarray(rgba, "RGBA")


class Marquee(Effect):
    key = "marquee"
    label_zh = "跑马灯边框"
    label_en = "Marquee border"
    hint = "虚线绕屏幕一圈流动，像警戒线。"

    def render(self, ctx: Ctx) -> Image.Image:
        w, h = ctx.w, ctx.h
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        th = max(3, int(min(w, h) * 0.012))
        dash = max(18, int(min(w, h) * 0.07))
        gap = max(8, int(dash * 0.6))
        per = 2 * (w + h)
        offset = (ctx.t * 160 * ctx.speed) % (dash + gap)
        a = int(235 * ctx.opacity)
        k = 0
        while k * (dash + gap) < per:
            u0 = k * (dash + gap) + offset
            n = max(2, int(dash / 6))
            pts = [rect_path(u0 + dash * i / (n - 1), w, h) for i in range(n)]
            draw.line(pts, fill=(*ctx.color, a), width=th * 2)
            k += 1
        # second, dimmer ring just inside the edge for depth
        inset = th * 6
        draw.rectangle([inset, inset, w - inset - 1, h - inset - 1],
                       outline=(*ctx.secondary, int(90 * ctx.opacity)), width=max(1, th // 2))
        return img


class Sunburst(Effect):
    key = "sunburst"
    label_zh = "放射脉冲"
    label_en = "Sunburst"
    hint = "旋转光线从中心射出，周期性鼓起。"

    def render(self, ctx: Ctx) -> Image.Image:
        w, h = ctx.w, ctx.h
        cx, cy = w / 2, h / 2
        rmax = math.hypot(w, h) * 0.62
        beat = 0.6 + 0.4 * ease_pulse(ctx.t, 1.4 * ctx.speed)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        n = 28
        rot = ctx.t * 0.5 * ctx.speed
        for k in range(n):
            a0 = math.tau * k / n + rot
            wide = math.tau / n * 0.35
            al = int((60 + 90 * beat) * ctx.opacity * ctx.intensity * (0.5 + 0.5 * math.cos(k * 1.7)))
            if al < 8:
                continue
            draw.polygon([(cx, cy),
                          (cx + rmax * math.cos(a0 - wide), cy + rmax * math.sin(a0 - wide)),
                          (cx + rmax * math.cos(a0 + wide), cy + rmax * math.sin(a0 + wide))],
                         fill=(*ctx.color, al))
        mask = radial_alpha(w, h, 0.5, 0.5, 0.8, 0.8, power=1.4, inner=1.0, outer=0.0)
        arr = np.array(img, dtype=np.float32)
        arr[..., 3] *= mask
        img = Image.fromarray(arr.astype(np.uint8), "RGBA")

        core = radial_alpha(w, h, 0.5, 0.5, 0.1, 0.1, power=2.0, inner=1.0, outer=0.0)
        return composite(img, layer_from_alpha(core * beat * 0.7, ctx.secondary, ctx.opacity))


class NoiseStatic(Effect):
    key = "noise_static"
    label_zh = "雪花噪点"
    label_en = "Static noise"
    hint = "电视雪花 + 色块闪烁，干扰感强、几乎不遮挡画面结构。"

    def render(self, ctx: Ctx) -> Image.Image:
        w, h = ctx.w, ctx.h
        noise = make_noise(w, h, ctx.rng, scale=1.0)
        flick = 0.35 + 0.25 * ctx.rng.random()
        a = np.clip(noise * flick * ctx.intensity, 0, 1)
        img = layer_from_alpha(a, (235, 240, 255), ctx.opacity * 0.42)

        def blocks(draw, w, h, color):
            for _ in range(int(3 + 6 * ctx.intensity)):
                bw = int(ctx.rng.integers(w // 12, w // 3))
                bh = int(ctx.rng.integers(h // 40, h // 12))
                x = int(ctx.rng.integers(0, max(1, w - bw)))
                y = int(ctx.rng.integers(0, max(1, h - bh)))
                col = parse_color(ctx.color) if ctx.rng.random() < 0.5 else parse_color(ctx.secondary)
                draw.rectangle([x, y, x + bw, y + bh], fill=(*col, int(70 * ctx.opacity)))

        img = composite(img, glow_layer((w, h), blocks, blur=0, color=ctx.color,
                                        opacity=0.8))
        # rolling sync bar
        y = int((ctx.t * 0.6 * ctx.speed % 1.0) * h)
        band = np.zeros((h, w), dtype=np.float32)
        band[max(0, y - 4):y + 4, :] = 0.6
        return composite(img, layer_from_alpha(band, (255, 255, 255), ctx.opacity * 0.4))


class Aperture(Effect):
    key = "aperture"
    label_zh = "光圈收拢"
    label_en = "Iris aperture"
    hint = "六叶光圈慢慢闭合，中间视野收窄，像镜头眨眼。护盾型特效。"

    hides_content = True

    def render(self, ctx: Ctx) -> Image.Image:
        w, h = ctx.w, ctx.h
        cx, cy = w / 2, h / 2
        close = smoothstep(min(1.0, ctx.t / 1.1))
        # the iris never seals completely: it breathes around a small hole, so the
        # screen is obscured but the alert keeps moving instead of going black
        breath = 0.5 + 0.5 * math.sin(ctx.t * 1.35 * ctx.speed)
        hole = 0.13 + 0.15 * breath
        r = min(w, h) * (0.80 - (0.80 - hole) * close * (0.55 + 0.45 * ctx.intensity))
        rot = ctx.t * 0.12 * ctx.speed
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        far = min(w, h) * 3.0
        a_fill = int(226 * ctx.opacity)
        for i in range(6):
            a0 = rot + math.pi / 3 * i
            a1 = rot + math.pi / 3 * (i + 1)
            p0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
            p1 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
            q0 = (cx + far * math.cos(a0), cy + far * math.sin(a0))
            q1 = (cx + far * math.cos(a1), cy + far * math.sin(a1))
            draw.polygon([p0, q0, q1, p1], fill=(5, 7, 10, a_fill))
        # blade seams pick up the alert colour so the shutter reads as deliberate
        edge = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ed = ImageDraw.Draw(edge)
        pts = [(cx + r * math.cos(rot + math.pi / 3 * i),
                cy + r * math.sin(rot + math.pi / 3 * i)) for i in range(6)]
        ed.line(pts + [pts[0]], fill=(*ctx.color, int(240 * ctx.opacity)),
                width=max(2, int(min(w, h) * 0.006)))
        for i in range(6):
            a0 = rot + math.pi / 3 * i
            ed.line([(cx + r * math.cos(a0), cy + r * math.sin(a0)),
                     (cx + (r + min(w, h) * 0.42) * math.cos(a0),
                      cy + (r + min(w, h) * 0.42) * math.sin(a0))],
                    fill=(*ctx.secondary, int(70 * ctx.opacity)),
                    width=max(1, int(min(w, h) * 0.003)))
        img = composite(img, edge.filter(ImageFilter.GaussianBlur(6)))
        img = composite(img, edge)
        # warm glow just outside the hole, like light leaking past the blades
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        rr = r * 1.35
        gd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                   outline=(*ctx.color, int(120 * ctx.opacity * ctx.intensity)),
                   width=max(2, int(min(w, h) * 0.02)))
        img = composite(img, glow.filter(ImageFilter.GaussianBlur(14)))
        return img


BUILTIN: list[Effect] = [
    PulseFrame(), VignetteFocus(), Frost(), Curtain(), Scanlines(), Glitch(),
    MatrixRain(), Particles(), Radar(), HexGrid(), WatchEye(), RainbowWash(),
    Marquee(), Sunburst(), NoiseStatic(), Aperture(),
]
