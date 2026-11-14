"""Full-screen, click-through, always-on-top layered window (Win32 via ctypes).

Design notes
------------
* One layered window covering the *virtual* screen (all monitors at once when
  ``multi_monitor`` is on) — cheaper than one window per display and it keeps
  effects aligned across a mixed-DPI setup.
* ``WS_EX_TRANSPARENT`` + ``HTTRANSPARENT`` means clicks, drags and scrolls go
  straight through to whatever is underneath; the guard never steals focus.
* ``UpdateLayeredWindow`` takes premultiplied BGRA, so the premultiply happens
  once in numpy on the producer thread and this thread only memmoves bytes.
"""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

import numpy as np

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
HWND_TOPMOST = -1
SWP_NOACTIVATE = 0x0010
DIB_RGB_COLORS = 0
BI_RGB = 0
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
SM_CXSCREEN, SM_CYSCREEN = 0, 1
WM_DESTROY, WM_NCHITTEST, WM_ERASEBKGND, WM_PAINT, WM_DISPLAYCHANGE = 0x0002, 0x0084, 0x0014, 0x000F, 0x007E
PM_REMOVE = 0x0001
HTTRANSPARENT = -1


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", wintypes.BYTE), ("BlendFlags", wintypes.BYTE),
                ("SourceConstantAlpha", wintypes.BYTE), ("AlphaFormat", wintypes.BYTE)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD), ("pt", POINT)]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


def enable_dpi_awareness() -> None:
    """Per-monitor DPI v2 so the overlay matches physical pixels on scaled screens."""
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


# explicit signatures: without these ctypes truncates the 64-bit LPARAM that the
# window procedure receives and every message raises OverflowError
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_longlong
user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND, wintypes.HDC, ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
    wintypes.HDC, ctypes.POINTER(POINT), wintypes.DWORD,
    ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
user32.UpdateLayeredWindow.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.CreateWindowExW.restype = wintypes.HWND
user32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT,
                                wintypes.UINT, wintypes.UINT]


def virtual_screen(multi_monitor: bool = True) -> tuple[int, int, int, int]:
    if multi_monitor:
        x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    else:
        x = y = 0
        w = user32.GetSystemMetrics(SM_CXSCREEN)
        h = user32.GetSystemMetrics(SM_CYSCREEN)
    return int(x), int(y), max(1, int(w)), max(1, int(h))


class ScreenOverlay:
    """Owns one layered window; ``push`` hands it premultiplied BGRA frames."""

    def __init__(self, multi_monitor: bool = True):
        self.multi_monitor = multi_monitor
        self._thread: threading.Thread | None = None
        self._hwnd = None
        self._run = False
        self._frame: bytes | np.ndarray | None = None
        self._frame_size: tuple[int, int] | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._visible = False
        self._last_push = 0.0
        self._resize = True
        self.geometry = virtual_screen(multi_monitor)
        self._hdc_screen = None
        self._hbitmap = None
        self._hdc_mem = None
        self._bits_ptr = None
        self._buf_hw = None
        self._class_atom = None
        self._wndproc = WNDPROC(self._wnd_proc)
        self._error: str | None = None

    # ------------------------------------------------------------------ api
    @property
    def size(self) -> tuple[int, int]:
        return self.geometry[2], self.geometry[3]

    def start(self) -> bool:
        if self._run:
            return True
        enable_dpi_awareness()
        self._run = True
        self._thread = threading.Thread(target=self._main, name="overlay", daemon=True)
        self._thread.start()
        self._thread.join(timeout=0.2)
        return self._hwnd is not None if not self._thread.is_alive() else True

    def stop(self) -> None:
        self._run = False
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def push(self, frame: np.ndarray, size: tuple[int, int]) -> None:
        """``frame`` is (h, w, 4) uint8 premultiplied BGRA to fill the whole geometry."""
        with self._lock:
            self._frame = frame
            self._frame_size = size
            self._last_push = time.monotonic()
        self._wake.set()

    def hide(self) -> None:
        with self._lock:
            self._frame = None
            self._last_push = 0.0
        self._wake.set()
        if self._hwnd:
            self._visible = False

    @property
    def visible(self) -> bool:
        return self._visible

    # -------------------------------------------------------------- internals
    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_NCHITTEST:
            return HTTRANSPARENT            # never receive mouse input
        if msg in (WM_ERASEBKGND, WM_PAINT):
            return 0
        if msg == WM_DISPLAYCHANGE:
            self._resize = True
            return 0
        if msg == WM_DESTROY:
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _register_class(self):
        hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
        cls = WNDCLASS()
        cls.lpfnWndProc = self._wndproc
        cls.hInstance = hinst
        cls.lpszClassName = "PrivacyGuardOverlay"
        cls.hCursor = None
        cls.hbrBackground = None
        atom = user32.RegisterClassW(ctypes.byref(cls))
        if not atom:
            err = ctypes.get_last_error()
            if err not in (0, 1410):        # 1410 = class already exists
                self._error = f"RegisterClass failed {err}"
        self._class_atom = atom or "PrivacyGuardOverlay"

    def _create_window(self):
        x, y, w, h = self.geometry
        hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
        ex = (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST |
              WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        self._hwnd = user32.CreateWindowExW(ex, "PrivacyGuardOverlay", "PrivacyGuard",
                                            WS_POPUP, x, y, w, h, None, None, hinst, None)
        if not self._hwnd:
            self._error = f"CreateWindowEx failed {ctypes.get_last_error()}"
            return False
        hdc_screen = user32.GetDC(None)
        self._hdc_screen = hdc_screen
        self._create_backbuffer(w, h)
        return True

    def _create_backbuffer(self, w: int, h: int):
        self._destroy_backbuffer()
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h            # top-down rows, matches numpy
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        bits = ctypes.c_void_p()
        self._hbitmap = gdi32.CreateDIBSection(self._hdc_screen, ctypes.byref(bmi),
                                              DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
        self._bits_ptr = bits
        self._hdc_mem = gdi32.CreateCompatibleDC(self._hdc_screen)
        gdi32.SelectObject(self._hdc_mem, self._hbitmap)
        self._buf_size = w * h * 4
        self._buf_hw = (w, h)

    def _destroy_backbuffer(self):
        if self._hdc_mem:
            gdi32.DeleteDC(self._hdc_mem)
            self._hdc_mem = None
        if self._hbitmap:
            gdi32.DeleteObject(self._hbitmap)
            self._hbitmap = None
        self._buf_hw = None

    def _upload(self, frame: np.ndarray, dest: tuple[int, int]):
        """``frame`` must be (h, w, 4) premultiplied BGRA matching ``dest``.

        Scaling inside UpdateLayeredWindow drops the per-pixel alpha channel, so
        the producer always hands over a full-resolution buffer; the thread only
        memmoves bytes.
        """
        w, h = int(dest[0]), int(dest[1])
        if self._resize or self._hbitmap is None or self._hdc_mem is None or self._buf_hw != (w, h):
            self._create_backbuffer(w, h)
            self._resize = False
        if frame.shape[1] != w or frame.shape[0] != h:
            self._error = f"frame {frame.shape[1]}x{frame.shape[0]} != window {w}x{h}"
            return
        # copying here would hold the GIL for a 7 MB memcpy on this thread and
        # starve the render thread, so only copy when the buffer is not usable
        src = frame if (frame.flags.c_contiguous and frame.dtype == np.uint8) \
            else np.ascontiguousarray(frame, dtype=np.uint8)
        ctypes.memmove(self._bits_ptr, src.ctypes.data, self._buf_size)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        pos = POINT(self.geometry[0], self.geometry[1])
        size = SIZE(w, h)
        src_pt = POINT(0, 0)
        ok = user32.UpdateLayeredWindow(self._hwnd, self._hdc_screen, ctypes.byref(pos),
                                        ctypes.byref(size), self._hdc_mem, ctypes.byref(src_pt),
                                        0, ctypes.byref(blend), ULW_ALPHA)
        if not ok and self._error is None:
            self._error = f"UpdateLayeredWindow failed {ctypes.get_last_error()}"

    def _show(self):
        if self._hwnd and not self._visible:
            user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
            user32.SetWindowPos(self._hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                SWP_NOACTIVATE | 0x0001 | 0x0002)   # NOSIZE | NOMOVE
            self._visible = True

    def _hide_window(self):
        if self._hwnd and self._visible:
            user32.ShowWindow(self._hwnd, SW_HIDE)
            self._visible = False

    def _pump(self) -> None:
        msg = MSG()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _main(self) -> None:
        self._register_class()
        if not self._create_window():
            self._run = False
            return
        self._hide_window()
        while self._run:
            self._pump()
            with self._lock:
                frame = self._frame
                size = self._frame_size
                last_push = self._last_push
                self._frame = None
            if frame is not None and size is not None:
                self._upload(frame, size)
                self._show()
            elif last_push == 0.0 or (time.monotonic() - last_push) > 0.20:
                # the last uploaded frame stays on screen; hide only when the
                # producer stops feeding us or explicitly asks to hide
                self._hide_window()
            self._wake.wait(timeout=0.008)
            self._wake.clear()
        self._hide_window()
        self._destroy_backbuffer()
        if self._hdc_screen:
            user32.ReleaseDC(None, self._hdc_screen)
            self._hdc_screen = None
        if self._hwnd:
            user32.DestroyWindow(self._hwnd)
            self._hwnd = None


def premultiply_bgra(img) -> np.ndarray:
    """PIL RGBA -> premultiplied BGRA uint8, in one vectorised pass.

    Kept as a single uint16 multiply/divide per channel instead of promoting the
    whole 4-channel buffer, which is several times faster on a 0.45 MP canvas.
    """
    a = np.asarray(img.convert("RGBA"), dtype=np.uint8)
    alpha = a[..., 3].astype(np.uint16)[..., None]
    rgb = (a[..., :3].astype(np.uint16) * alpha) // 255     # premultiply
    out = np.empty_like(a)
    out[..., 0] = rgb[..., 2]
    out[..., 1] = rgb[..., 1]
    out[..., 2] = rgb[..., 0]
    out[..., 3] = a[..., 3]
    return out
