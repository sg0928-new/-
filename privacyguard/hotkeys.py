"""Global hotkeys through RegisterHotKey (no keyboard hook, no extra package)."""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
WM_QUIT_HOTKEYS = 0x0400 + 1

NAMED_VK = {
    "space": 0x20, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "enter": 0x0D,
    "backspace": 0x08, "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}


def parse_combo(text: str) -> tuple[int, int] | None:
    """'ctrl+alt+p' -> (modifiers, virtual-key). Returns None if unparsable."""
    if not text:
        return None
    mods = 0
    key = None
    for part in str(text).lower().replace(" ", "").split("+"):
        if part in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif part == "alt":
            mods |= MOD_ALT
        elif part == "shift":
            mods |= MOD_SHIFT
        elif part in ("win", "meta", "super"):
            mods |= MOD_WIN
        elif part:
            if part in NAMED_VK:
                key = NAMED_VK[part]
            elif len(part) == 1 and part.isalpha():
                key = ord(part.upper())
            elif part.isdigit():
                key = ord(part)
    if key is None:
        return None
    return mods, key


class HotkeyManager:
    """Registers a set of hotkeys on a message-only thread.

    ``RegisterHotKey`` fails when another app already owns the combo — that is
    reported per-hotkey instead of crashing the guard.
    """

    def __init__(self, bindings: dict[str, str], on_press):
        self.bindings = dict(bindings)
        self.on_press = on_press
        self._thread: threading.Thread | None = None
        self._run = False
        self._thread_id = 0
        self.errors: dict[str, str] = {}
        self.active: list[str] = []

    def start(self) -> bool:
        if self._thread is not None:
            return True
        self._run = True
        self._thread = threading.Thread(target=self._main, name="hotkeys", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._run = False
        if self._thread_id:
            try:
                user32.PostThreadMessageW(self._thread_id, WM_QUIT_HOTKEYS, 0, 0)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _main(self) -> None:
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        ids: dict[int, str] = {}
        for i, (action, combo) in enumerate(self.bindings.items(), start=1):
            parsed = parse_combo(combo)
            if not parsed:
                self.errors[action] = f"无法解析热键 / cannot parse: {combo}"
                continue
            mods, vk = parsed
            if user32.RegisterHotKey(None, i, mods, vk):
                ids[i] = action
                self.active.append(action)
            else:
                self.errors[action] = f"热键被占用 / already taken: {combo}"
        msg = wintypes.MSG()
        while self._run and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                action = ids.get(int(msg.wParam))
                if action:
                    try:
                        self.on_press(action)
                    except Exception:
                        pass
        for i in ids:
            user32.UnregisterHotKey(None, i)
