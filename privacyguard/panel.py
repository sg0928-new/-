"""Control panel (tkinter): every knob the guard exposes, plus a live preview."""

from __future__ import annotations

import os
import time
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageTk
import numpy as np

from . import app as appmod
from . import config as cfgmod
from . import effects
from .camera import list_cameras
from .sound import SOUNDS, SoundPlayer

BG = "#12141a"
CARD = "#1b1e26"
FG = "#e6e9f0"
MUTED = "#98a0b3"
ACCENT = "#ff3b30"
OK = "#34c759"


class Panel:
    def __init__(self, service: appmod.GuardService):
        self.service = service
        self.cfg = service.cfg
        self.root = tk.Tk()
        self.root.title("PrivacyGuard · 摄像头看护的屏幕隐私守护")
        self.root.configure(bg=BG)
        self.root.geometry("1080x720")
        self.root.minsize(980, 660)
        self._preview_t = 0.0
        self._tick_n = 0
        self._effect_vars: dict[str, tk.BooleanVar] = {}
        self._slider_labels: list[tuple[tk.DoubleVar, tk.Label, str]] = []
        self._canvases: list[tk.Canvas] = []
        self._img_ref = None
        self._effect_ref = None
        self._build_style()
        self._build()
        self._load_from_config(self.cfg)
        service.on_panel_request = lambda: self.root.after(0, self._raise)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(60, self._tick)

    # ------------------------------------------------------------------ style
    def _build_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=FG, font=("Microsoft YaHei UI", 9))
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("Card.TLabel", background=CARD, foreground=FG)
        style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED)
        style.configure("TButton", background=CARD, foreground=FG, borderwidth=0, focusthickness=0)
        style.map("TButton", background=[("active", "#2a2f3b")])
        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#ff5a4f")])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=CARD, foreground=MUTED, padding=(14, 7))
        style.map("TNotebook.Tab", background=[("selected", "#2a2f3b")],
                  foreground=[("selected", FG)])
        style.configure("TCheckbutton", background=BG, foreground=FG)
        style.configure("Card.TCheckbutton", background=CARD, foreground=FG)
        style.configure("TScale", background=BG, troughcolor="#2a2f3b")
        style.configure("TCombobox", fieldbackground=CARD, background=CARD, foreground=FG,
                        arrowcolor=FG, bordercolor="#2a2f3b")
        style.map("TCombobox",
                  fieldbackground=[("readonly", CARD), ("disabled", "#232732")],
                  foreground=[("readonly", FG)],
                  selectbackground=[("readonly", CARD)],
                  selectforeground=[("readonly", FG)])
        style.configure("TSpinbox", fieldbackground=CARD, background=CARD, foreground=FG,
                        arrowcolor=FG, bordercolor="#2a2f3b")
        style.configure("TEntry", fieldbackground=CARD, foreground=FG, insertcolor=FG)
        style.configure("TScrollbar", background="#2a2f3b", troughcolor=BG, arrowcolor=MUTED)

    # ------------------------------------------------------------------- build
    def _build(self):
        top = tk.Frame(self.root, bg=CARD, height=64)
        top.pack(fill="x", padx=0, pady=0)
        tk.Label(top, text="PrivacyGuard", bg=CARD, fg=FG,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(side="left", padx=16, pady=12)
        self.badge = tk.Label(top, text="待机", bg="#2a2f3b", fg=FG, padx=10, pady=4,
                              font=("Microsoft YaHei UI", 9, "bold"))
        self.badge.pack(side="left", padx=6)
        self.status_lbl = tk.Label(top, text="", bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9))
        self.status_lbl.pack(side="left", padx=10)
        self.metrics = tk.Label(top, text="", bg=CARD, fg=MUTED, font=("Consolas", 9))
        self.metrics.pack(side="right", padx=14)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=(10, 0))

        left = tk.Frame(body, bg=BG, width=248)
        left.pack(side="left", fill="y", padx=(0, 12))
        left.pack_propagate(False)
        tk.Label(left, text="实时画面", bg=BG, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        self.cam_canvas = tk.Canvas(left, width=240, height=180, bg="#0a0c10",
                                    highlightthickness=1, highlightbackground="#2a2f3b")
        self.cam_canvas.pack(pady=(4, 10))
        self.cam_info = tk.Label(left, text="", bg=BG, fg=MUTED, justify="left",
                                 font=("Consolas", 9))
        self.cam_info.pack(anchor="w")

        tk.Frame(left, bg="#2a2f3b", height=1).pack(fill="x", pady=12)
        tk.Label(left, text="快捷键", bg=BG, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        self.hotkey_lbl = tk.Label(left, text="", bg=BG, fg=MUTED, justify="left",
                                   font=("Consolas", 9))
        self.hotkey_lbl.pack(anchor="w", pady=(4, 10))

        ttk.Button(left, text="立即测试特效", style="Accent.TButton",
                   command=self._test).pack(fill="x", pady=4)
        self.toggle_btn = ttk.Button(left, text="暂停守护", command=self._toggle)
        self.toggle_btn.pack(fill="x", pady=4)
        ttk.Button(left, text="保存设置", command=self._save).pack(fill="x", pady=4)
        ttk.Button(left, text="完全退出", command=self._on_quit).pack(fill="x", pady=(18, 4))

        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        self.nb = ttk.Notebook(right)
        self.nb.pack(fill="both", expand=True)
        self._tab_monitor()
        self._tab_effects()
        self._tab_sound()
        self._tab_general()

    def _scrollable(self, parent) -> tk.Frame:
        outer = tk.Frame(parent, bg=BG)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        bar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        outer.pack(fill="both", expand=True, padx=14, pady=12)
        self._canvases.append(canvas)
        return inner

    def _card(self, parent, title: str) -> tk.Frame:
        card = tk.Frame(parent, bg=CARD)
        card.pack(fill="x", pady=(0, 10))
        tk.Label(card, text=title, bg=CARD, fg=FG, font=("Microsoft YaHei UI", 10, "bold")
                 ).pack(anchor="w", padx=12, pady=(10, 2))
        return card

    def _slider(self, parent, label, var, lo, hi, step=1, fmt="{:.0f}", width=210):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=12, pady=2)
        tk.Label(row, text=label, bg=CARD, fg=MUTED, width=14, anchor="w").pack(side="left")
        val = tk.Label(row, text=fmt.format(float(var.get())), bg=CARD, fg=FG, width=7,
                       anchor="e", font=("Consolas", 9))
        val.pack(side="right", padx=(0, 6))
        s = ttk.Scale(row, from_=lo, to=hi, orient="horizontal", length=width, variable=var,
                      command=lambda v: val.configure(text=fmt.format(float(var.get())))
                      )
        s.pack(side="left")
        self._slider_labels.append((var, val, fmt))
        return s

    def _spin(self, parent, label, var, lo, hi, inc=1):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=12, pady=2)
        tk.Label(row, text=label, bg=CARD, fg=MUTED, width=14, anchor="w").pack(side="left")
        ttk.Spinbox(row, from_=lo, to=hi, increment=inc, textvariable=var, width=8).pack(side="left")

    # ------------------------------------------------------------------ tabs
    def _tab_monitor(self):
        tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(tab, text="检测")
        inner = self._scrollable(tab)

        c1 = self._card(inner, "摄像头与性能")
        r0 = tk.Frame(c1, bg=CARD)
        r0.pack(fill="x", padx=12, pady=2)
        self.v_enabled = tk.BooleanVar()
        ttk.Checkbutton(r0, text="启用监控", variable=self.v_enabled,
                        style="Card.TCheckbutton").pack(side="left")
        tk.Label(r0, text="摄像头", bg=CARD, fg=MUTED).pack(side="left", padx=(16, 4))
        self.v_cam = tk.StringVar()
        self.cam_combo = ttk.Combobox(r0, textvariable=self.v_cam, width=6, state="readonly")
        self.cam_combo.pack(side="left")
        ttk.Button(r0, text="重新扫描", command=self._scan_cams).pack(side="left", padx=6)
        self.v_res = tk.StringVar()
        tk.Label(r0, text="采集分辨率", bg=CARD, fg=MUTED).pack(side="left", padx=(12, 4))
        ttk.Combobox(r0, textvariable=self.v_res, width=10, state="readonly",
                     values=["640x480", "1280x720", "960x540", "320x240"]).pack(side="left")

        self.v_dw = tk.DoubleVar()
        self._slider(c1, "检测分辨率", self.v_dw, 160, 640, width=200)
        self.v_interval = tk.DoubleVar()
        self._slider(c1, "检测间隔(ms)", self.v_interval, 30, 500, width=200)

        c2 = self._card(inner, "灵敏度（越灵敏越容易触发）")
        self.v_scale = tk.DoubleVar()
        self._slider(c2, "级联缩放步长", self.v_scale, 1.03, 1.40, fmt="{:.2f}", width=200)
        self.v_neigh = tk.DoubleVar()
        self._slider(c2, "最小邻域数", self.v_neigh, 2, 12, width=200)
        self.v_facepx = tk.DoubleVar()
        self._slider(c2, "最小人脸像素", self.v_facepx, 16, 120, width=200)
        r1 = tk.Frame(c2, bg=CARD)
        r1.pack(fill="x", padx=12, pady=(4, 10))
        self.v_profiles = tk.BooleanVar()
        ttk.Checkbutton(r1, text="同时检测侧脸（慢约 40%）", variable=self.v_profiles,
                        style="Card.TCheckbutton").pack(side="left")

        c3 = self._card(inner, "触发判定")
        self.v_own = tk.IntVar()
        self._spin(c3, "允许本人面部数", self.v_own, 0, 3)
        self.v_confirm = tk.IntVar()
        self._spin(c3, "确认帧数", self.v_confirm, 1, 12)
        self.v_cooldown = tk.DoubleVar()
        self._spin(c3, "冷却(秒)", self.v_cooldown, 2, 60, inc=1)
        self.v_release = tk.DoubleVar()
        self._spin(c3, "恢复(秒)", self.v_release, 0.5, 8, inc=0.5)
        tk.Label(c3, text="说明：画面中人数超过「允许本人面部数」并持续「确认帧数」帧才会触发；\n"
                          "触发后若房间恢复安静并持续「恢复秒数」，特效自动收尾。",
                 bg=CARD, fg=MUTED, justify="left").pack(anchor="w", padx=12, pady=(4, 10))

    def _tab_effects(self):
        tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(tab, text="特效")
        inner = self._scrollable(tab)

        c0 = self._card(inner, "风格预设")
        grid = tk.Frame(c0, bg=CARD)
        grid.pack(fill="x", padx=12, pady=(2, 10))
        for i, (key, preset) in enumerate(cfgmod.PRESETS.items()):
            ttk.Button(grid, text=preset["label"], width=14,
                       command=lambda k=key: self._apply_preset(k)
                       ).grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 8), pady=3)

        c1 = self._card(inner, "选择特效（可多选，勾选后按顺序播放）")
        grid = tk.Frame(c1, bg=CARD)
        grid.pack(fill="x", padx=12, pady=(2, 6))
        for i, d in enumerate(effects.describe()):
            var = tk.BooleanVar()
            self._effect_vars[d["key"]] = var
            cell = tk.Frame(grid, bg=CARD)
            cell.grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 18), pady=2)
            ttk.Checkbutton(cell, text=f"{d['zh']}", variable=var,
                            style="Card.TCheckbutton").pack(side="left")
            tk.Label(cell, text="遮" if d["hides_content"] else "", bg=CARD, fg=ACCENT,
                     font=("Microsoft YaHei UI", 7)).pack(side="left", padx=2)
        tk.Label(c1, text="标「遮」的特效会明显遮挡屏幕内容，适合当隐私护盾。", bg=CARD,
                 fg=MUTED).pack(anchor="w", padx=12, pady=(0, 8))

        c2 = self._card(inner, "外观")
        r = tk.Frame(c2, bg=CARD)
        r.pack(fill="x", padx=12, pady=(2, 4))
        self.v_color = tk.StringVar()
        self.v_secondary = tk.StringVar()
        self.color_btn = tk.Button(r, text="主色", bg=ACCENT, fg="#fff", width=6,
                                   command=lambda: self._pick_color(self.v_color, self.color_btn))
        self.color_btn.pack(side="left")
        self.sec_btn = tk.Button(r, text="辅色", bg="#00e5ff", fg="#000", width=6,
                                 command=lambda: self._pick_color(self.v_secondary, self.sec_btn))
        self.sec_btn.pack(side="left", padx=8)
        for name, c in (("警示红", "#FF3B30"), ("青蓝", "#00E5FF"), ("紫", "#7C4DFF"),
                        ("绿", "#00FF88"), ("琥珀", "#FFB020"), ("白", "#FFFFFF")):
            b = tk.Button(r, text="", bg=c, width=2, relief="flat",
                          command=lambda c=c: (self.v_color.set(c), self.color_btn.configure(bg=c)))
            b.pack(side="left", padx=2)

        self.v_intensity = tk.DoubleVar()
        self._slider(c2, "强度", self.v_intensity, 0.1, 1.0, fmt="{:.2f}", width=200)
        self.v_opacity = tk.DoubleVar()
        self._slider(c2, "透明度", self.v_opacity, 0.05, 1.0, fmt="{:.2f}", width=200)
        self.v_speed = tk.DoubleVar()
        self._slider(c2, "速度", self.v_speed, 0.2, 4.0, fmt="{:.2f}", width=200)
        self.v_duration = tk.DoubleVar()
        self._slider(c2, "持续(秒)", self.v_duration, 1, 30, width=200)
        self.v_fade = tk.DoubleVar()
        self._slider(c2, "淡入淡出(秒)", self.v_fade, 0, 2, fmt="{:.2f}", width=200)
        self.v_quality = tk.DoubleVar()
        self._slider(c2, "渲染质量", self.v_quality, 0.2, 1.0, fmt="{:.2f}", width=200)
        r2 = tk.Frame(c2, bg=CARD)
        r2.pack(fill="x", padx=12, pady=(2, 10))
        self.v_random = tk.BooleanVar()
        ttk.Checkbutton(r2, text="随机轮播", variable=self.v_random,
                        style="Card.TCheckbutton").pack(side="left")
        self.v_cycle = tk.DoubleVar()
        tk.Label(r2, text="轮播间隔(秒)", bg=CARD, fg=MUTED).pack(side="left", padx=(14, 4))
        ttk.Spinbox(r2, from_=1, to=20, increment=0.5, textvariable=self.v_cycle,
                    width=6).pack(side="left")
        self.v_multi = tk.BooleanVar()
        ttk.Checkbutton(r2, text="覆盖全部显示器", variable=self.v_multi,
                        style="Card.TCheckbutton").pack(side="left", padx=(14, 0))

        c3 = self._card(inner, "预览（当前参数 · 实时）")
        self.fx_canvas = tk.Canvas(c3, width=520, height=260, bg="#0a0c10",
                                   highlightthickness=1, highlightbackground="#2a2f3b")
        self.fx_canvas.pack(padx=12, pady=(2, 12))

    def _tab_sound(self):
        tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(tab, text="声音")
        inner = self._scrollable(tab)
        c = self._card(inner, "触发音效")
        self.v_sound = tk.BooleanVar()
        ttk.Checkbutton(c, text="启用音效", variable=self.v_sound,
                        style="Card.TCheckbutton").pack(anchor="w", padx=12, pady=4)
        r = tk.Frame(c, bg=CARD)
        r.pack(fill="x", padx=12, pady=4)
        tk.Label(r, text="音效", bg=CARD, fg=MUTED).pack(side="left")
        self.v_sound_name = tk.StringVar()
        combo = ttk.Combobox(r, textvariable=self.v_sound_name, width=18, state="readonly",
                             values=[f"{s['zh']}|{s['key']}" for s in SOUNDS])
        combo.pack(side="left", padx=6)
        ttk.Button(r, text="试听", command=self._audition).pack(side="left")
        self.v_volume = tk.DoubleVar()
        self._slider(c, "音量", self.v_volume, 0.0, 1.0, fmt="{:.2f}", width=200)
        self.v_repeat = tk.IntVar()
        self._spin(c, "重复次数", self.v_repeat, 1, 8)
        self.v_delay = tk.IntVar()
        self._spin(c, "延迟(ms)", self.v_delay, 0, 3000, inc=100)
        tk.Label(c, text="音效全部由程序合成（正弦/方波/噪声），不需要任何音频文件。",
                 bg=CARD, fg=MUTED).pack(anchor="w", padx=12, pady=(4, 10))

    def _tab_general(self):
        tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(tab, text="通用")
        inner = self._scrollable(tab)
        c = self._card(inner, "全局热键")
        for action, label in (("panel", "打开面板"), ("test", "手动触发"), ("toggle", "暂停/恢复")):
            r = tk.Frame(c, bg=CARD)
            r.pack(fill="x", padx=12, pady=2)
            tk.Label(r, text=label, bg=CARD, fg=MUTED, width=10, anchor="w").pack(side="left")
            var = tk.StringVar()
            setattr(self, f"v_hk_{action}", var)
            ttk.Entry(r, textvariable=var, width=18).pack(side="left")
        self.hk_status = tk.Label(c, text="", bg=CARD, fg=MUTED, justify="left")
        self.hk_status.pack(anchor="w", padx=12, pady=(4, 10))

        c2 = self._card(inner, "启动与维护")
        self.v_autostart = tk.BooleanVar()
        ttk.Checkbutton(c2, text="开机自动后台启动（注册表 HKCU Run）",
                        variable=self.v_autostart,
                        style="Card.TCheckbutton").pack(anchor="w", padx=12, pady=4)
        self.v_startmin = tk.BooleanVar()
        ttk.Checkbutton(c2, text="启动时最小化面板", variable=self.v_startmin,
                        style="Card.TCheckbutton").pack(anchor="w", padx=12, pady=4)
        r = tk.Frame(c2, bg=CARD)
        r.pack(fill="x", padx=12, pady=(4, 10))
        ttk.Button(r, text="打开配置目录", command=self._open_config_dir).pack(side="left")
        ttk.Button(r, text="恢复默认", command=self._reset).pack(side="left", padx=8)
        tk.Label(c2, text="配置文件：%APPDATA%\\PrivacyGuard\\config.json",
                 bg=CARD, fg=MUTED).pack(anchor="w", padx=12, pady=(0, 10))

    # ------------------------------------------------------------- config I/O
    def _load_from_config(self, cfg: dict):
        m, e, s, h, g = (cfg["monitor"], cfg["effect"], cfg["sound"], cfg["hotkeys"], cfg["general"])
        self.v_enabled.set(bool(m["enabled"]))
        self.v_cam.set(str(m["camera_index"]))
        self.v_res.set(f'{m["width"]}x{m["height"]}')
        self.v_dw.set(int(m["detect_width"]))
        self.v_interval.set(int(m["detect_interval_ms"]))
        self.v_scale.set(float(m["scale_factor"]))
        self.v_neigh.set(int(m["min_neighbors"]))
        self.v_facepx.set(int(m["min_face_px"]))
        self.v_profiles.set(bool(m["detect_profiles"]))
        self.v_own.set(int(m["allowed_own_faces"]))
        self.v_confirm.set(int(m["confirm_frames"]))
        self.v_cooldown.set(float(m["cooldown_s"]))
        self.v_release.set(float(m["release_s"]))

        for k, var in self._effect_vars.items():
            var.set(k in e["names"])
        self.v_color.set(e["color"])
        self.color_btn.configure(bg=e["color"])
        self.v_secondary.set(e["secondary"])
        self.sec_btn.configure(bg=e["secondary"])
        self.v_intensity.set(float(e["intensity"]))
        self.v_opacity.set(float(e["opacity"]))
        self.v_speed.set(float(e["speed"]))
        self.v_duration.set(float(e["duration_s"]))
        self.v_fade.set(float(e["fade_s"]))
        self.v_quality.set(float(e["quality"]))
        self.v_random.set(bool(e["random_mode"]))
        self.v_cycle.set(float(e["cycle_s"]))
        self.v_multi.set(bool(e["multi_monitor"]))

        self.v_sound.set(bool(s["enabled"]))
        label = next((f"{x['zh']}|{x['key']}" for x in SOUNDS if x["key"] == s["name"]), SOUNDS[0]["zh"] + "|" + SOUNDS[0]["key"])
        self.v_sound_name.set(label)
        self.v_volume.set(float(s["volume"]))
        self.v_repeat.set(int(s["repeat"]))
        self.v_delay.set(int(s["delay_ms"]))

        self.v_hk_panel.set(h["panel"])
        self.v_hk_test.set(h["test"])
        self.v_hk_toggle.set(h["toggle"])
        self.v_autostart.set(appmod.autostart_enabled())
        self.v_startmin.set(bool(g["start_minimized"]))
        self._scan_cams(select=m["camera_index"])
        for var, lbl, fmt in self._slider_labels:
            lbl.configure(text=fmt.format(float(var.get())))

    def _collect(self) -> dict:
        names = [k for k, v in self._effect_vars.items() if v.get()] or ["pulse_frame"]
        res = str(self.v_res.get()).lower().replace(" ", "")
        w, h = (int(x) for x in res.split("x")) if "x" in res else (640, 480)
        return cfgmod.clamp_values({
            "monitor": {
                "enabled": bool(self.v_enabled.get()),
                "camera_index": int(float(self.v_cam.get() or 0)),
                "width": w, "height": h,
                "detect_width": int(self.v_dw.get()),
                "detect_interval_ms": int(self.v_interval.get()),
                "scale_factor": float(self.v_scale.get()),
                "min_neighbors": int(self.v_neigh.get()),
                "min_face_px": int(self.v_facepx.get()),
                "allowed_own_faces": int(self.v_own.get()),
                "confirm_frames": int(self.v_confirm.get()),
                "cooldown_s": float(self.v_cooldown.get()),
                "release_s": float(self.v_release.get()),
                "detect_profiles": bool(self.v_profiles.get()),
            },
            "effect": {
                "names": names,
                "random_mode": bool(self.v_random.get()),
                "cycle_s": float(self.v_cycle.get()),
                "color": self.v_color.get(),
                "secondary": self.v_secondary.get(),
                "intensity": float(self.v_intensity.get()),
                "opacity": float(self.v_opacity.get()),
                "speed": float(self.v_speed.get()),
                "duration_s": float(self.v_duration.get()),
                "fade_s": float(self.v_fade.get()),
                "quality": float(self.v_quality.get()),
                "multi_monitor": bool(self.v_multi.get()),
            },
            "sound": {
                "enabled": bool(self.v_sound.get()),
                "name": self.v_sound_name.get().split("|")[-1],
                "volume": float(self.v_volume.get()),
                "repeat": int(self.v_repeat.get()),
                "delay_ms": int(self.v_delay.get()),
            },
            "hotkeys": {
                "panel": self.v_hk_panel.get(), "test": self.v_hk_test.get(),
                "toggle": self.v_hk_toggle.get(),
            },
            "general": {
                "autostart": bool(self.v_autostart.get()),
                "start_minimized": bool(self.v_startmin.get()),
                "log": True,
            },
        })

    # ---------------------------------------------------------------- actions
    def _scan_cams(self, select=None):
        ids = list_cameras(4)
        if not ids:
            ids = [0]
        self.cam_combo.configure(values=[str(i) for i in ids])
        if select is not None:
            self.v_cam.set(str(select))
        elif self.v_cam.get() not in [str(i) for i in ids]:
            self.v_cam.set(str(ids[0]))

    def _apply_preset(self, key: str):
        preset = cfgmod.PRESETS.get(key)
        if not preset:
            return
        self.cfg = cfgmod.apply_preset(self._collect(), key)
        self._load_from_config(self.cfg)
        self.service.apply_config(self.cfg)
        self._flash(f"已应用预设：{preset['label']}")

    def _pick_color(self, var: tk.StringVar, btn: tk.Button):
        color = colorchooser.askcolor(color=var.get(), parent=self.root)[1]
        if color:
            var.set(color)
            btn.configure(bg=color)

    def _audition(self):
        key = self.v_sound_name.get().split("|")[-1]
        SoundPlayer().play(key, float(self.v_volume.get()), 1, 0)

    def _test(self):
        self.service.apply_config(self._collect())
        self.service.trigger(source="panel")

    def _toggle(self):
        if self.service.monitoring:
            self.service.stop_monitoring_only()
            self.toggle_btn.configure(text="开始守护")
        else:
            self.service.apply_config(self._collect())
            if self.service.start_monitoring():
                self.toggle_btn.configure(text="暂停守护")
            else:
                self._flash("摄像头不可用：" + (self.service.status.get("message") or ""))

    def _save(self):
        cfg = self._collect()
        self.service.apply_config(cfg)
        self.service.save_config()
        try:
            appmod.set_autostart(bool(cfg["general"]["autostart"]))
        except Exception as exc:
            self._flash(f"开机自启设置失败：{exc}")
        self._flash("设置已保存 ✓")

    def _reset(self):
        if messagebox.askyesno("恢复默认", "把所有设置恢复为默认值？", parent=self.root):
            self._load_from_config(cfgmod.DEFAULTS)
            self.service.apply_config(cfgmod.DEFAULTS)
            self._flash("已恢复默认")

    def _open_config_dir(self):
        p = cfgmod.config_dir()
        p.mkdir(parents=True, exist_ok=True)
        os.startfile(p)          # noqa: S606 - opening the user's own config folder

    def _flash(self, text: str, ms: int = 2200):
        self.status_lbl.configure(text=text, fg=OK)
        self.root.after(ms, lambda: self.status_lbl.configure(text="", fg=MUTED))

    def _raise(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(1200, lambda: self.root.attributes("-topmost", False))

    def _on_close(self):
        self.root.iconify()
        self._flash("面板已最小化，守护继续运行（热键可呼出）")

    def _on_quit(self):
        try:
            self.service.stop()
        finally:
            self.root.destroy()

    # ------------------------------------------------------------------- tick
    def _tick(self):
        st = self.service.status
        state = "警报中" if st["alert"] else ("守护中" if self.service.monitoring else "已暂停")
        color = ACCENT if st["alert"] else (OK if self.service.monitoring else "#8e8e93")
        self.badge.configure(text=state, bg=color,
                             fg="#fff" if color != OK else "#06210f")
        msg = st.get("message") or ""
        self.status_lbl.configure(text=msg[:60], fg=MUTED)
        self.metrics.configure(text=f"faces {st['faces']} · cam {st['cam_fps']:.0f}fps · "
                                     f"detect {st['detect_ms']:.1f}ms · fx {st['render_fps']:.0f}fps "
                                     f"@{st.get('quality_now', 0):.2f} · cpu {st['cpu']:.0f}%")
        hk = st.get("hotkey_errors") or ""
        self.hk_status.configure(text=("注册失败：" + hk) if hk else "热键已注册")
        self.hotkey_lbl.configure(
            text=f"{self.v_hk_panel.get()}  面板\n{self.v_hk_test.get()}  测试\n"
                 f"{self.v_hk_toggle.get()}  暂停")
        self._tick_n += 1
        if self._tick_n % 3 == 0:
            self._draw_camera(st)
        if self.nb.index(self.nb.select()) == 1:
            self._draw_effect()
        self.root.after(90, self._tick)

    def _draw_camera(self, st: dict):
        cam = self.service.cam
        frame = None
        if cam is not None:
            frame, _, _ = cam.read()
        if frame is None:
            self.cam_canvas.delete("all")
            self.cam_canvas.create_text(120, 90, text="无画面 / no signal", fill=MUTED)
            self.cam_info.configure(text="摄像头未就绪")
            return
        h, w = frame.shape[:2]
        from PIL import ImageDraw
        img = Image.fromarray(frame[:, :, ::-1])        # BGR -> RGB
        img = img.resize((240, int(240 * h / max(1, w))), Image.BILINEAR)
        draw = ImageDraw.Draw(img)
        sc = 240.0 / max(1, w)
        for (bx, by, bw, bh, is_owner) in st.get("boxes") or []:
            draw.rectangle([bx * sc, by * sc, (bx + bw) * sc, (by + bh) * sc],
                           outline=(0, 230, 120) if is_owner else (255, 60, 48), width=2)
        self._img_ref = ImageTk.PhotoImage(img)
        self.cam_canvas.delete("all")
        self.cam_canvas.create_image(0, 0, anchor="nw", image=self._img_ref)
        self.cam_info.configure(
            text=f"{w}x{h} · 均值 {st.get('frame_mean', 0):.0f}\n"
                 f"人脸 {st['faces']}（本人 {st['owner']} / 他人 {st['others']}）")

    def _draw_effect(self):
        w, h = 520, 260
        cfg = self._collect()
        self._preview_t += 0.09
        rng = np.random.default_rng(5)
        seq = effects.EffectSequencer(cfg, seed=5)
        small = (max(80, w // 2), max(60, h // 2))
        frame = effects.render_frame(cfg, small, seq, self._preview_t, rng).resize((w, h), Image.BILINEAR)
        bg = Image.new("RGBA", (w, h), (10, 12, 16, 255))
        from PIL import ImageDraw
        d = ImageDraw.Draw(bg)
        for i in range(0, h, 20):
            d.line([0, i, w, i], fill=(30, 34, 44, 255))
        d.rectangle([w * 0.15, h * 0.2, w * 0.85, h * 0.8], outline=(70, 76, 92, 255))
        comp = Image.alpha_composite(bg, frame).convert("RGB")
        self._effect_ref = ImageTk.PhotoImage(comp)
        self.fx_canvas.delete("all")
        self.fx_canvas.create_image(0, 0, anchor="nw", image=self._effect_ref)

    def run(self):
        if self.cfg["general"].get("start_minimized"):
            self.root.iconify()
        self.root.mainloop()
