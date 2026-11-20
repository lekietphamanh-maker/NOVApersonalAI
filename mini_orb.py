"""Mini Nova: a small orb in the bottom-left corner of the screen while you work in other apps.

Same states as the big orb (asleep, waiting for "Hey Nova", listening, thinking, speaking). It never takes the
keyboard, stays out of screenshots, hides over full-screen video, and can be dragged. Click it to open Nova,
right-click to switch the mic. While Nova moves your mouse and types, it flares and a banner at the top of the
screen says not to touch the mouse and that Esc stops it.

Frames are drawn with Pillow (anti-aliased, soft glow) at twice the size and scaled down; render() is pure.
The windows are native layered windows (real per-pixel transparency): created as never-activating and shown
without activation, so the orb can never take the keyboard from the app you are using.
"""
from __future__ import annotations

import math
import sys
import time
from typing import Callable

SIZE = 168            # the window; the orb sits in the middle, the rest is see-through and click-through
WARNING = (255, 112, 48)
BANNER_TITLE = "NOVA IS USING YOUR MOUSE AND KEYBOARD"
BANNER_TEXT = "Please don't touch them.  Press Esc to stop."
MODES = ("asleep", "armed", "listen", "think", "speak", "act", "error", "music")


def mode_for(state: dict, acting: bool) -> str:
    """Which look the mini orb has, from Nova's state."""
    if acting:
        return "act"
    voice = state.get("voice") or {}
    if voice.get("tone") == "error":
        return "error"
    if voice.get("tone") in ("listen", "record"):
        return "listen"
    if state.get("speaking"):
        return "speak"
    if state.get("busy"):
        return "think"
    if (state.get("music") or {}).get("playing"):
        return "music"  # nothing else going on and music plays: the orb becomes a spinning disc
    return "armed" if (state.get("switches") or {}).get("mic") else "asleep"


def render_disc(t: float, accent: tuple[int, int, int], art=None, bands: list[float] | None = None):
    """Music playing: a vinyl disc spinning at 33 rpm with the album cover as its label, inside a ring of bars that
    move with the sound (mirrored left and right, low notes at the top)."""
    from PIL import Image, ImageDraw, ImageFilter
    scale = 2
    size = SIZE * scale
    center = size / 2
    radius = size * 0.26
    line = max(2, int(size * 0.012))
    frame = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow = Image.new("RGBA", (size // 4, size // 4), (0, 0, 0, 0))
    k = size // 4 / size
    ImageDraw.Draw(glow).ellipse((size / 8 - radius * 1.25 * k, size / 8 - radius * 1.25 * k,
                                  size / 8 + radius * 1.25 * k, size / 8 + radius * 1.25 * k), fill=(*accent, 70))
    frame = Image.alpha_composite(frame, glow.filter(ImageFilter.GaussianBlur(radius * 0.18 * k)).resize((size, size)))
    draw = ImageDraw.Draw(frame)
    levels = bands or []
    count = 48
    for index in range(count):
        mirrored = index if index <= count // 2 else count - index
        level = levels[min(len(levels) - 1, mirrored * len(levels) // (count // 2 + 1))] if levels else 0.0
        angle = -math.pi / 2 + 2 * math.pi * index / count
        inner, outer = radius * 1.1, radius * (1.16 + 0.55 * level)
        draw.line((center + math.cos(angle) * inner, center + math.sin(angle) * inner,
                   center + math.cos(angle) * outer, center + math.sin(angle) * outer),
                  fill=(*accent, int(150 + 105 * level)), width=line)
    draw.ellipse((center - radius, center - radius, center + radius, center + radius), fill=(9, 9, 13, 255),
                 outline=(*accent, 200), width=line)
    for groove in range(5):
        r = radius * (0.58 + 0.08 * groove)
        draw.ellipse((center - r, center - r, center + r, center + r), outline=(255, 255, 255, 22), width=1)
    label = int(radius * 1.04)
    if art is not None:
        cover = art.convert("RGBA").resize((label, label)).rotate(-(t * 200) % 360, resample=Image.BICUBIC)
    else:
        cover = Image.new("RGBA", (label, label), (*accent, 255))
        ImageDraw.Draw(cover).pieslice((0, 0, label, label), (-(t * 200)) % 360, (-(t * 200)) % 360 + 40,
                                       fill=(255, 255, 255, 90))
    mask = Image.new("L", (label, label), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, label - 1, label - 1), fill=255)
    frame.paste(cover, (int(center - label / 2), int(center - label / 2)), mask)
    spindle = radius * 0.07
    draw.ellipse((center - spindle, center - spindle, center + spindle, center + spindle), fill=(6, 6, 9, 255))
    # A sheen across the vinyl that stays still while the label turns: reads as spinning.
    draw.arc((center - radius * 0.9, center - radius * 0.9, center + radius * 0.9, center + radius * 0.9), 200, 250,
             fill=(255, 255, 255, 40), width=line * 2)
    return frame.resize((SIZE, SIZE), Image.LANCZOS)


def render(mode: str, t: float, level: float = 0.0, accent: tuple[int, int, int] = (255, 176, 64), music=None):
    """One frame (RGBA, SIZE x SIZE) of the mini orb. music: (cover image or None, sound bands) for the disc."""
    if mode == "music":
        art, bands = music or (None, None)
        return render_disc(t, accent, art, bands)
    from PIL import Image, ImageDraw, ImageFilter
    scale = 2
    size = SIZE * scale
    center = size / 2
    color = WARNING if mode == "act" else (255, 77, 106) if mode == "error" else accent
    acting = mode == "act"
    pulse = 0.5 + 0.5 * math.sin(t * (7 if acting else 2.2))
    radius = size * (0.30 if acting else 0.25)  # the disc grows when Nova takes over

    def circle(draw, r, **style):
        draw.ellipse((center - r, center - r, center + r, center + r), **style)

    def arc(draw, r, start, span, width, alpha):
        draw.arc((center - r, center - r, center + r, center + r), start, start + span, fill=(*color, alpha), width=width)

    def blurred_blob(r: float, alpha: int, blur: float):
        """A soft glow: drawn and blurred at a quarter of the size (much cheaper), then scaled up."""
        small = size // 4
        blob = Image.new("RGBA", (small, small), (0, 0, 0, 0))
        k = small / size
        ImageDraw.Draw(blob).ellipse((small / 2 - r * k, small / 2 - r * k, small / 2 + r * k, small / 2 + r * k),
                                     fill=(*color, alpha))
        return blob.filter(ImageFilter.GaussianBlur(blur * k)).resize((size, size), Image.BILINEAR)

    frame = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    # Aura outside the disc: only when Nova takes over (it "glows up"), or a faint one while speaking.
    if acting or mode == "speak":
        frame = Image.alpha_composite(frame, blurred_blob(radius * (1.18 + 0.12 * pulse),
                                                          int((150 + 90 * pulse) if acting else 50), size * 0.06))
    disc = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(disc)
    circle(draw, radius, fill=(7, 11, 18, 238))
    frame = Image.alpha_composite(frame, disc)

    # A soft light inside the disc.
    glow_strength = {"asleep": 40, "armed": 70, "listen": 120 + 120 * level, "think": 110, "speak": 130,
                     "act": 170 + 60 * pulse, "error": 110}[mode]
    frame = Image.alpha_composite(frame, blurred_blob(radius * 0.55, int(min(255, glow_strength)), radius * 0.35))

    shapes = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(shapes)
    line = max(2, int(size * 0.012))
    if mode == "asleep":  # the glowing line with one small orbit, like the big orb asleep
        draw.line((center - radius * 0.62, center, center + radius * 0.62, center), fill=(*color, 230), width=line + 1)
        angle = t * 0.9
        dot = (center + math.cos(angle) * radius * 0.62, center + math.sin(angle) * radius * 0.2)
        draw.ellipse((dot[0] - line * 1.6, dot[1] - line * 1.6, dot[0] + line * 1.6, dot[1] + line * 1.6), fill=(*color, 255))
    elif mode == "armed":  # waiting for "Hey Nova": a slow orbit, and now and then a wink
        wink = 1.0 if (t % 7.0) < 0.35 else 0.0
        circle(draw, radius * 0.42, outline=(*color, int(140 + 100 * wink)), width=line)
        arc(draw, radius * 0.62, (t * 70) % 360, 100, line, 210)
        circle(draw, radius * 0.13, fill=(*color, 200))
    elif mode == "listen":  # the core breathes with your voice
        core = radius * (0.2 + 0.32 * min(1.0, level * 1.6))
        circle(draw, core, fill=(*color, 245))
        circle(draw, core + radius * (0.1 + 0.06 * pulse), outline=(*color, 150), width=line)
        arc(draw, radius * 0.8, (t * 120) % 360, 70, line, 160)
    elif mode == "think":  # two arcs turning opposite ways
        arc(draw, radius * 0.62, (t * 240) % 360, 120, line + 1, 235)
        arc(draw, radius * 0.42, (-t * 300) % 360, 90, line + 1, 200)
        circle(draw, radius * 0.14, fill=(*color, 180))
    elif mode == "speak":  # ripples going out
        circle(draw, radius * 0.24, fill=(*color, 245))
        for k in range(3):
            phase = (t * 0.9 + k / 3) % 1.0
            circle(draw, radius * (0.28 + 0.55 * phase), outline=(*color, int(220 * (1 - phase))), width=line)
    elif mode == "act":  # taking over: bright core, fast double ring, pulsing rim
        circle(draw, radius * (0.26 + 0.05 * pulse), fill=(*color, 255))
        arc(draw, radius * 0.6, (t * 360) % 360, 140, line + 2, 255)
        arc(draw, radius * 0.6, (t * 360 + 180) % 360, 140, line + 2, 255)
    else:  # error
        circle(draw, radius * 0.5, outline=(*color, 230), width=line + 1)
        draw.line((center, center - radius * 0.28, center, center + radius * 0.06), fill=(*color, 255), width=line + 2)
        circle(draw, line * 1.3, fill=(*color, 255))
    rim_alpha = int(255 if acting else 150)
    circle(draw, radius - line, outline=(*color, rim_alpha), width=line + (2 if acting else 0))
    frame = Image.alpha_composite(frame, shapes)
    return frame.resize((SIZE, SIZE), Image.LANCZOS)


# ---------- the takeover banner (pure) ----------

def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    for name in (("segoeuib.ttf", "seguisb.ttf") if bold else ("segoeui.ttf",)) + ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def render_banner():
    """The banner at the top of the screen while Nova uses the mouse and keyboard (RGBA, with a soft glow)."""
    from PIL import Image, ImageDraw, ImageFilter
    title, text = _font(17, bold=True), _font(15)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    width = 64 + max(probe.textlength(BANNER_TITLE, font=title), probe.textlength(BANNER_TEXT, font=text)) + 34
    width, height, margin = int(width), 72, 16
    image = Image.new("RGBA", (width + 2 * margin, height + 2 * margin), (0, 0, 0, 0))
    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle((margin, margin, margin + width, margin + height), 14, fill=(*WARNING, 150))
    image = Image.alpha_composite(image, glow.filter(ImageFilter.GaussianBlur(9)))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((margin, margin, margin + width, margin + height), 14, fill=(11, 15, 22, 242),
                           outline=(*WARNING, 255), width=2)
    left, middle = margin + 20, margin + height / 2
    draw.polygon([(left + 14, middle - 14), (left + 29, middle + 12), (left - 1, middle + 12)], fill=(*WARNING, 255))
    draw.text((left + 14, middle + 1), "!", font=_font(17, bold=True), fill=(11, 15, 22, 255), anchor="mm")
    draw.text((margin + 64, margin + 14), BANNER_TITLE, font=title, fill=(255, 217, 184, 255))
    draw.text((margin + 64, margin + 40), BANNER_TEXT, font=text, fill=(225, 230, 238, 255))
    return image


# ---------- native windows (Windows) ----------

GWL_EXSTYLE = -20
WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x8, 0x20, 0x80
WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x80000, 0x8000000
WDA_EXCLUDEFROMCAPTURE = 0x11
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x4, 0x10
WM_MOUSEACTIVATE, WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONUP = 0x21, 0x200, 0x201, 0x202, 0x205
MA_NOACTIVATE = 3
_API = None


def _api():
    """user32 / gdi32 with exact argument types (handles are 64-bit)."""
    global _API
    if _API is not None:
        return _API
    import ctypes
    from ctypes import wintypes
    from types import SimpleNamespace
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HICON), ("hCursor", wintypes.HICON), ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte), ("SourceConstantAlpha", ctypes.c_ubyte),
                    ("AlphaFormat", ctypes.c_ubyte)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]

    def types(function, argtypes, restype=None):
        function.argtypes = argtypes
        if restype is not None:
            function.restype = restype

    HWND, HDC = wintypes.HWND, wintypes.HDC
    types(user32.DefWindowProcW, [HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], LRESULT)
    types(user32.RegisterClassExW, [ctypes.POINTER(WNDCLASSEXW)], wintypes.ATOM)
    types(user32.CreateWindowExW, [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, HWND, wintypes.HMENU, wintypes.HINSTANCE,
                                   wintypes.LPVOID], HWND)
    types(user32.DestroyWindow, [HWND], wintypes.BOOL)
    types(user32.ShowWindow, [HWND, ctypes.c_int], wintypes.BOOL)
    types(user32.IsWindowVisible, [HWND], wintypes.BOOL)
    types(user32.SetWindowPos, [HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT],
          wintypes.BOOL)
    types(user32.GetWindowLongW, [HWND, ctypes.c_int], wintypes.LONG)
    types(user32.SetWindowLongW, [HWND, ctypes.c_int, wintypes.LONG], wintypes.LONG)
    types(user32.SetWindowDisplayAffinity, [HWND, wintypes.DWORD], wintypes.BOOL)
    types(user32.GetDC, [HWND], HDC)
    types(user32.ReleaseDC, [HWND, HDC], ctypes.c_int)
    types(user32.UpdateLayeredWindow, [HWND, HDC, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(wintypes.SIZE), HDC,
                                       ctypes.POINTER(wintypes.POINT), wintypes.COLORREF, ctypes.POINTER(BLENDFUNCTION),
                                       wintypes.DWORD], wintypes.BOOL)
    types(user32.GetCursorPos, [ctypes.POINTER(wintypes.POINT)], wintypes.BOOL)
    types(user32.SetCapture, [HWND], HWND)
    types(user32.ReleaseCapture, [], wintypes.BOOL)
    types(user32.LoadCursorW, [wintypes.HINSTANCE, ctypes.c_void_p], wintypes.HICON)
    types(user32.GetForegroundWindow, [], HWND)
    types(user32.GetWindowTextW, [HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int)
    types(user32.GetWindowRect, [HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL)
    types(user32.MonitorFromWindow, [HWND, wintypes.DWORD], wintypes.HMONITOR)
    types(user32.GetMonitorInfoW, [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)], wintypes.BOOL)
    types(user32.SystemParametersInfoW, [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT], wintypes.BOOL)
    types(gdi32.CreateCompatibleDC, [HDC], HDC)
    types(gdi32.CreateDIBSection, [HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                   wintypes.HANDLE, wintypes.DWORD], wintypes.HBITMAP)
    types(gdi32.SelectObject, [HDC, wintypes.HGDIOBJ], wintypes.HGDIOBJ)
    types(gdi32.DeleteObject, [wintypes.HGDIOBJ], wintypes.BOOL)
    types(gdi32.DeleteDC, [HDC], wintypes.BOOL)
    types(kernel32.GetModuleHandleW, [wintypes.LPCWSTR], wintypes.HMODULE)
    _API = SimpleNamespace(ctypes=ctypes, wintypes=wintypes, user32=user32, gdi32=gdi32, kernel32=kernel32,
                           WNDPROC=WNDPROC, WNDCLASSEXW=WNDCLASSEXW, BLENDFUNCTION=BLENDFUNCTION, BITMAPINFO=BITMAPINFO,
                           BITMAPINFOHEADER=BITMAPINFOHEADER, MONITORINFO=MONITORINFO)
    return _API


def work_area() -> tuple[int, int, int, int]:
    """The primary screen without the taskbar: left, top, right, bottom."""
    api = _api()
    rect = api.wintypes.RECT()
    api.user32.SystemParametersInfoW(0x0030, 0, api.ctypes.byref(rect), 0)  # SPI_GETWORKAREA
    return rect.left, rect.top, rect.right, rect.bottom


def foreground() -> tuple[int | None, str, bool]:
    """The window you are using: its handle, its title, and whether it fills its whole monitor (video, games)."""
    api = _api()
    hwnd = api.user32.GetForegroundWindow()
    if not hwnd:
        return None, "", False
    title = api.ctypes.create_unicode_buffer(256)
    api.user32.GetWindowTextW(hwnd, title, 256)
    rect = api.wintypes.RECT()
    api.user32.GetWindowRect(hwnd, api.ctypes.byref(rect))
    info = api.MONITORINFO(cbSize=api.ctypes.sizeof(api.MONITORINFO))
    full = bool(api.user32.GetMonitorInfoW(api.user32.MonitorFromWindow(hwnd, 2), api.ctypes.byref(info))) and (
        rect.left <= info.rcMonitor.left and rect.top <= info.rcMonitor.top
        and rect.right >= info.rcMonitor.right and rect.bottom >= info.rcMonitor.bottom)
    return int(hwnd), title.value, full


class LayeredWindow:
    """A borderless, always-on-top window drawn from an RGBA image with real transparency. It is created as
    never-activating and only ever shown without activation, so it can't take the keyboard. Kept out of
    screenshots. Messages arrive through the thread's message loop (Tk's mainloop pumps them)."""

    _class_registered = False

    def __init__(self, name: str, on_message=None) -> None:
        api = _api()
        self.api, self.on_message = api, on_message
        instance = api.kernel32.GetModuleHandleW(None)
        self._wndproc = api.WNDPROC(self._window_procedure)  # kept: Windows calls it for the window's lifetime
        class_name = f"NovaLayered{id(self)}"
        window_class = api.WNDCLASSEXW(cbSize=api.ctypes.sizeof(api.WNDCLASSEXW), lpfnWndProc=self._wndproc,
                                       hInstance=instance, hCursor=api.user32.LoadCursorW(None, 32649),  # IDC_HAND
                                       lpszClassName=class_name)
        if not api.user32.RegisterClassExW(api.ctypes.byref(window_class)):
            raise OSError(f"RegisterClassExW failed ({api.ctypes.get_last_error()})")
        self.hwnd = api.user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, class_name, name, WS_POPUP,
            0, 0, 1, 1, None, None, instance, None)
        if not self.hwnd:
            raise OSError(f"CreateWindowExW failed ({api.ctypes.get_last_error()})")
        api.user32.SetWindowDisplayAffinity(self.hwnd, WDA_EXCLUDEFROMCAPTURE)  # Windows 10 2004+; else ignored
        self.x = self.y = 0
        self.visible = False
        self.click_through = False

    def _window_procedure(self, hwnd, message, wparam, lparam):
        if message == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE
        if self.on_message is not None and message in (WM_LBUTTONDOWN, WM_MOUSEMOVE, WM_LBUTTONUP, WM_RBUTTONUP):
            try:
                self.on_message(message)
            except Exception:
                pass  # never let a click break the message loop
            return 0
        return self.api.user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def set_click_through(self, on: bool) -> None:
        if on == self.click_through:
            return
        style = self.api.user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        style = style | WS_EX_TRANSPARENT if on else style & ~WS_EX_TRANSPARENT
        self.api.user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, style)
        self.click_through = on

    def show(self, on: bool) -> None:
        if on != self.visible:
            self.api.user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE if on else SW_HIDE)
            self.visible = on

    def move(self, x: int, y: int) -> None:
        self.x, self.y = x, y
        self.api.user32.SetWindowPos(self.hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)

    def draw(self, image) -> None:
        """Show an RGBA image (premultiplied for Windows) at the window's position."""
        from PIL import Image, ImageChops
        api, ctypes, wintypes = self.api, self.api.ctypes, self.api.wintypes
        red, green, blue, alpha = image.split()
        pixels = Image.merge("RGBA", (ImageChops.multiply(blue, alpha), ImageChops.multiply(green, alpha),
                                      ImageChops.multiply(red, alpha), alpha)).tobytes()  # BGRA, premultiplied
        width, height = image.size
        screen = api.user32.GetDC(None)
        memory = api.gdi32.CreateCompatibleDC(screen)
        info = api.BITMAPINFO()
        info.bmiHeader = api.BITMAPINFOHEADER(biSize=ctypes.sizeof(api.BITMAPINFOHEADER), biWidth=width,
                                              biHeight=-height, biPlanes=1, biBitCount=32, biCompression=0)
        bits = ctypes.c_void_p()
        bitmap = api.gdi32.CreateDIBSection(memory, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
        try:
            ctypes.memmove(bits, pixels, len(pixels))
            previous = api.gdi32.SelectObject(memory, bitmap)
            blend = api.BLENDFUNCTION(0, 0, 255, 1)  # AC_SRC_OVER, per-pixel alpha
            api.user32.UpdateLayeredWindow(self.hwnd, screen, ctypes.byref(wintypes.POINT(self.x, self.y)),
                                           ctypes.byref(wintypes.SIZE(width, height)), memory,
                                           ctypes.byref(wintypes.POINT(0, 0)), 0, ctypes.byref(blend), 2)  # ULW_ALPHA
            api.gdi32.SelectObject(memory, previous)
        finally:
            api.gdi32.DeleteObject(bitmap)
            api.gdi32.DeleteDC(memory)
            api.user32.ReleaseDC(None, screen)

    def destroy(self) -> None:
        if self.hwnd:
            self.api.user32.DestroyWindow(self.hwnd)
            self.hwnd = None


class MiniOrb:
    """state() -> (mode, mic level 0..1, accent rgb, should it show). Runs on the Tk thread via root.after;
    the windows' clicks arrive through Tk's message loop."""

    def __init__(self, root, state: Callable[[], tuple[str, float, tuple[int, int, int], bool]],
                 on_open: Callable[[], None], on_right_click: Callable[[], None],
                 position: tuple[int, int] | None = None, on_moved: Callable[[tuple[int, int]], None] | None = None,
                 music: Callable[[], tuple] | None = None) -> None:
        self.root, self.state, self.on_open, self.on_right_click = root, state, on_open, on_right_click
        self.music = music  # () -> (cover image or None, sound bands): for the disc while music plays
        self.on_moved = on_moved or (lambda _position: None)
        self.position = position
        self.window: LayeredWindow | None = None
        self.banner: LayeredWindow | None = None
        self.mode, self.level = "asleep", 0.0
        self.drag: dict | None = None
        self.started = time.monotonic()
        self.frames = 0
        self.stopped = False

    def start(self) -> None:
        if sys.platform != "win32":
            return
        try:
            self.window = LayeredWindow("Nova", self._on_mouse)
            self.banner = LayeredWindow("Nova is using your mouse")
            self.banner.set_click_through(True)  # Nova's own clicks go straight through it
            left, top, right, bottom = work_area()
            x, y = self.position or (left + 6, bottom - SIZE - 6)
            self.window.move(x, y)
            image = render_banner()
            self.banner.move(left + (right - left - image.width) // 2, top + 6)
            self.banner.draw(image)
        except Exception:
            self.stop()  # a decoration: without it Nova works the same
            return
        self.root.after(300, self._tick)

    def stop(self) -> None:
        self.stopped = True
        for window in (self.window, self.banner):
            if window is not None:
                window.destroy()
        self.window = self.banner = None

    # ---- mouse: click opens Nova, drag moves the orb, right-click switches the mic ----
    def _on_mouse(self, message: int) -> None:
        api = _api()
        point = api.wintypes.POINT()
        api.user32.GetCursorPos(api.ctypes.byref(point))
        if message == WM_LBUTTONDOWN:
            api.user32.SetCapture(self.window.hwnd)
            self.drag = {"x": point.x, "y": point.y, "left": self.window.x, "top": self.window.y, "moved": False}
        elif message == WM_MOUSEMOVE and self.drag:
            dx, dy = point.x - self.drag["x"], point.y - self.drag["y"]
            if self.drag["moved"] or abs(dx) + abs(dy) > 4:
                self.drag["moved"] = True
                self.window.move(self.drag["left"] + dx, self.drag["top"] + dy)
        elif message == WM_LBUTTONUP and self.drag:
            api.user32.ReleaseCapture()
            drag, self.drag = self.drag, None
            if drag["moved"]:
                self.position = (self.window.x, self.window.y)
                self.on_moved(self.position)
            else:
                self.on_open()
        elif message == WM_RBUTTONUP:
            self.on_right_click()

    # ---- frames ----
    def _tick(self) -> None:
        if self.stopped or self.window is None:
            return
        try:
            mode, level, accent, show = self.state()
            acting = mode == "act"
            self.banner.show(acting)
            self.window.set_click_through(acting)  # while Nova clicks, the orb must not catch a click
            visible = show or acting
            if visible:
                self.level += (level - self.level) * 0.35
                self.mode = mode
                extra = self.music() if mode == "music" and self.music else None
                self.window.draw(render(mode, time.monotonic() - self.started, self.level, accent, extra))
                self.frames += 1
            self.window.show(visible)
        except Exception:
            pass  # a decoration: never let it break Nova
        busy = self.window is not None and self.window.visible
        # Smooth while something happens, calmer otherwise, and only a cheap check while hidden.
        self.root.after(250 if not busy else 33 if self.mode in ("listen", "think", "speak", "act", "music") else 66, self._tick)
