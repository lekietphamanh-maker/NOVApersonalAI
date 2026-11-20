"""Nova's screen helper process (Windows): UI Automation snapshots, click-through overlays, input.

It runs as its own per-monitor-DPI-aware process, so every rectangle, overlay position and cursor
coordinate is a physical desktop pixel on every monitor. The dashboard talks to it through
screen_assist.ScreenAssist: one JSON request per stdin line, one JSON response per stdout line.
Start it with `python assist_helper.py` or `Nova.exe --screen-assist`.
"""
from __future__ import annotations

import ctypes
import json
import queue
import sys
import threading
import time

TRANSPARENT = "#010203"
CYAN = "#ffb040"  # Nova gold (name kept: used throughout this file)
NOTE_BACKGROUND = "#ffe08a"
GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80000, 0x20, 0x80, 0x08000000
WDA_EXCLUDEFROMCAPTURE = 0x11
GA_ROOT = 2
PER_MONITOR_AWARE_V2 = -4


def _snapshot(hwnd: int) -> dict:
    """Every enabled, on-screen control of one window, in one cached UI Automation call."""
    from pywinauto.uia_defines import IUIA
    uia = IUIA()
    automation, ids = uia.iuia, uia.UIA_dll
    cache = automation.CreateCacheRequest()
    for property_id in (ids.UIA_NamePropertyId, ids.UIA_ControlTypePropertyId, ids.UIA_BoundingRectanglePropertyId,
                        ids.UIA_IsEnabledPropertyId, ids.UIA_IsOffscreenPropertyId, ids.UIA_IsPasswordPropertyId):
        cache.AddProperty(property_id)
    window = automation.ElementFromHandle(hwnd)
    found = window.FindAllBuildCache(ids.TreeScope_Descendants, automation.CreateTrueCondition(), cache)
    elements = []
    for index in range(found.Length):
        element = found.GetElement(index)
        # Password fields are left out entirely, so the model can never target one.
        if element.CachedIsOffscreen or not element.CachedIsEnabled or element.CachedIsPassword:
            continue
        rect = element.CachedBoundingRectangle
        elements.append({
            "role": uia.known_control_type_ids.get(element.CachedControlType, ""),
            "name": element.CachedName or "",
            "rect": [rect.left, rect.top, rect.right, rect.bottom],
        })
    return {"window_title": window.CurrentName or "", "elements": elements}


def _text(hwnd: int, limit: int = 6000) -> dict:  # limit: characters per read; Nova scrolls for the rest
    """The visible static text of one window (problem statements, labels, paragraphs)."""
    from pywinauto.uia_defines import IUIA
    uia = IUIA()
    automation, ids = uia.iuia, uia.UIA_dll
    cache = automation.CreateCacheRequest()
    for property_id in (ids.UIA_NamePropertyId, ids.UIA_IsOffscreenPropertyId):
        cache.AddProperty(property_id)
    is_text = automation.CreatePropertyCondition(ids.UIA_ControlTypePropertyId, ids.UIA_TextControlTypeId)
    window = automation.ElementFromHandle(hwnd)
    found = window.FindAllBuildCache(ids.TreeScope_Descendants, is_text, cache)
    lines: list[str] = []
    for index in range(found.Length):
        element = found.GetElement(index)
        name = " ".join((element.CachedName or "").split())
        if name and not element.CachedIsOffscreen and name not in lines:
            lines.append(name)
            if sum(map(len, lines)) > limit:
                break
    return {"window_title": window.CurrentName or "", "text": "\n".join(lines)[:limit]}


def _glance(hwnd: int) -> dict:
    """A small gray thumbnail of one window, so a walkthrough notices when the user did a step."""
    import base64
    import ctypes.wintypes
    import mss
    from PIL import Image
    rect = ctypes.wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ValueError("the window is gone")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width < 8 or height < 8:
        raise ValueError("the window is not visible")
    with mss.mss() as screen:  # Nova's overlays are excluded from capture, so they never count as a change
        shot = screen.grab({"left": rect.left, "top": rect.top, "width": width, "height": height})
    image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX").convert("L").resize((160, 100), Image.Resampling.BILINEAR)
    return {"glance": base64.b64encode(image.tobytes()).decode(), "rect": [rect.left, rect.top, rect.right, rect.bottom]}


SHOT_LONG_SIDE = 1568  # Claude reads images up to about this size without shrinking them itself
MARK_COLOR = (255, 45, 150)


def _shot(hwnd: int, marks: list) -> dict:
    """A color screenshot of one window with each control's number drawn on it (Set-of-Marks, as in Clicky), as a
    JPEG, so a model that can see matches the picture to the SCREEN list. Nova's overlays aren't in it."""
    import base64
    import ctypes.wintypes
    import io
    import mss
    from PIL import Image, ImageDraw, ImageFont
    rect = ctypes.wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ValueError("the window is gone")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width < 8 or height < 8:
        raise ValueError("the window is not visible")
    with mss.mss() as screen:
        shot = screen.grab({"left": rect.left, "top": rect.top, "width": width, "height": height})
    image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arialbd.ttf", 15)
    except OSError:
        font = ImageFont.load_default()
    for number, (left, top, right, bottom) in marks:
        box = (left - rect.left, top - rect.top, right - rect.left, bottom - rect.top)
        draw.rectangle(box, outline=MARK_COLOR, width=2)
        label = draw.textbbox((box[0] + 3, box[1] + 1), str(number), font=font)
        draw.rectangle((label[0] - 3, label[1] - 1, label[2] + 3, label[3] + 1), fill=MARK_COLOR)
        draw.text((box[0] + 3, box[1] + 1), str(number), fill=(255, 255, 255), font=font)
    scale = min(1.0, SHOT_LONG_SIDE / max(image.size))
    if scale < 1.0:
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=80)
    return {"image": base64.b64encode(buffer.getvalue()).decode(), "size": list(image.size)}


def _focus(hwnd: int | None) -> None:
    if not hwnd:
        return
    from pywinauto.controls.hwndwrapper import HwndWrapper
    try:
        HwndWrapper(hwnd).set_focus()
    except Exception:
        pass  # The click itself still focuses the control.


class StoppedByUser(Exception):
    """The user pressed Esc while Nova was moving the mouse or typing."""


STOP_KEYS = [0x1B]  # the stop hotkey (SETTINGS → Hotkeys); Esc unless the owner changed it


def _escape_pressed() -> bool:
    """The stop hotkey from the user. Nova's own text never contains it, and a step that presses Esc itself isn't
    checked."""
    held = [bool(ctypes.windll.user32.GetAsyncKeyState(key) & 0x8001) for key in STOP_KEYS]
    return bool(held) and all(held)


def _glide_and_click(hwnd: int, x: int, y: int, button: str = "left") -> None:
    """Move the real cursor visibly so the user can follow, then click (left, right or double). Esc stops it before the click."""
    import ctypes.wintypes
    from pywinauto import mouse
    _escape_pressed()  # clears an old "was pressed" note, so only a fresh Esc counts
    _focus(hwnd)
    start = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(start))
    for step in range(1, 15):
        progress = step / 14
        eased = progress * progress * (3 - 2 * progress)
        ctypes.windll.user32.SetCursorPos(int(start.x + (x - start.x) * eased), int(start.y + (y - start.y) * eased))
        time.sleep(0.016)
        if _escape_pressed():
            raise StoppedByUser("the user pressed Esc; nothing was clicked")
    if button == "double":
        mouse.double_click(coords=(x, y))
    else:
        mouse.click(button=button, coords=(x, y))


def _scroll(hwnd: int, x: int | None, y: int | None, clicks: int) -> None:
    """The mouse wheel over a point (the window's middle when none is given); clicks > 0 scrolls up."""
    import ctypes.wintypes
    from pywinauto import mouse
    _focus(hwnd)
    if x is None or y is None:
        rect = ctypes.wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise ValueError("the window is gone")
        x, y = (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    mouse.scroll(coords=(int(x), int(y)), wheel_dist=int(clicks))


def _open(target: str) -> None:
    """Open a program, a web address, a file or a folder the way Start > Run would."""
    if not target.strip() or len(target) > 300 or any(ord(character) < 32 for character in target):
        raise ValueError("that is not something Windows can open")
    if ctypes.windll.shell32.ShellExecuteW(None, "open", target.strip(), None, None, 1) <= 32:
        raise ValueError(f"Windows could not open {target.strip()[:80]}")


def _type(hwnd: int, x: int, y: int, text: str) -> dict:
    from pywinauto import keyboard
    from pywinauto.uia_defines import IUIA
    _glide_and_click(hwnd, x, y)
    time.sleep(0.15)
    keys = ["{%s}" % character if character in "+^%~(){}[]" else character for character in text]
    stopped = False
    for start in range(0, len(keys), 6):  # a few characters at a time, so Esc can stop a long answer halfway
        if _escape_pressed():
            stopped = True
            break
        keyboard.send_keys("".join(keys[start:start + 6]), pause=0.01, with_spaces=True, with_tabs=True,
                           with_newlines=True)
    time.sleep(0.2)
    uia = IUIA()
    value = uia.iuia.GetFocusedElement().GetCurrentPropertyValue(uia.UIA_dll.UIA_ValueValuePropertyId)
    return {"value": value if isinstance(value, str) else None, "stopped": stopped}


def _keys(hwnd: int | None, spec: str) -> None:
    from pywinauto import keyboard
    if "{ESC}" not in spec and _escape_pressed():
        raise StoppedByUser("the user pressed Esc; no keys were pressed")
    _focus(hwnd)
    keyboard.send_keys(spec, pause=0.02)


class Overlays:
    """Topmost, click-through, never-activated windows that only draw."""

    def __init__(self, root) -> None:
        self.root = root
        self.windows: list = []

    def _show(self, geometry: str, build):
        import tkinter as tk
        user32 = ctypes.windll.user32
        window = tk.Toplevel(self.root, bg=TRANSPARENT)
        window.overrideredirect(True)
        window.attributes("-topmost", True, "-transparentcolor", TRANSPARENT, "-alpha", 0.96)
        build(window)
        window.geometry(geometry)
        window.update_idletasks()
        hwnd = user32.GetAncestor(window.winfo_id(), GA_ROOT)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                              | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        # Keeps overlays out of Nova's own screenshots (Windows 10 2004+; ignored elsewhere).
        user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        self.windows.append(window)
        return window

    def _expire(self, window, seconds: float | None) -> None:
        if seconds:
            self.root.after(int(seconds * 1000), lambda: self._close(window))

    def _close(self, window) -> None:
        if window in self.windows:
            self.windows.remove(window)
            window.destroy()

    def highlight(self, rect: list[int], label: str, seconds: float | None, style: str = "box") -> None:
        if style == "arrow":
            return self._arrow(rect, label, seconds)
        import tkinter as tk
        left, top, right, bottom = (int(value) for value in rect)
        pad, strip = 4, 22
        if style == "ring":
            # A circle around the target: grow the box to a square around its center.
            center_x, center_y = (left + right) // 2, (top + bottom) // 2
            radius = max(right - left, bottom - top) // 2 + 10
            left, top, right, bottom = center_x - radius, center_y - radius, center_x + radius, center_y + radius
        width, height = right - left + 2 * pad, bottom - top + 2 * pad + strip

        def build(window) -> None:
            canvas = tk.Canvas(window, bg=TRANSPARENT, highlightthickness=0, width=width, height=height)
            canvas.pack()
            if style == "ring":
                canvas.create_oval(3, strip + 3, width - 3, height - 3, outline=CYAN, width=4)
            else:
                canvas.create_rectangle(2, strip + 2, width - 2, height - 2, outline=CYAN, width=3)
            if label:
                # shortcut: a label wider than the target is clipped; fine for 2-4 word labels.
                text = canvas.create_text(8, strip // 2, text=label[:60], anchor="w", fill="#04121a",
                                          font=("Segoe UI", 9, "bold"))
                x1, y1, x2, y2 = canvas.bbox(text)
                canvas.create_rectangle(x1 - 5, y1 - 2, x2 + 5, y2 + 2, fill=CYAN, outline=CYAN)
                canvas.tag_raise(text)

        self._expire(self._show(f"{width}x{height}+{left - pad}+{top - pad - strip}", build), seconds)

    def _arrow(self, rect: list[int], label: str, seconds: float | None) -> None:
        """A thick arrow coming from the left, tip touching the target's left edge."""
        import tkinter as tk
        left, top, _right, bottom = (int(value) for value in rect)
        width, height = 170, 56
        tip_y = height // 2

        def build(window) -> None:
            canvas = tk.Canvas(window, bg=TRANSPARENT, highlightthickness=0, width=width, height=height)
            canvas.pack()
            canvas.create_line(8, tip_y, width - 6, tip_y, fill=CYAN, width=6, arrow="last", arrowshape=(18, 22, 8))
            if label:
                canvas.create_text(10, 10, text=label[:24], anchor="w", fill=CYAN, font=("Segoe UI", 9, "bold"))

        # shortcut: always drawn on the left; a target at the far left of a monitor gets a clipped arrow.
        self._expire(self._show(f"{width}x{height}+{left - width}+{(top + bottom) // 2 - tip_y}", build), seconds)

    def note(self, rect: list[int], text: str, seconds: float | None) -> None:
        import tkinter as tk
        left, top, right, _bottom = (int(value) for value in rect)

        def build(window) -> None:
            tk.Label(window, text=text[:300], bg=NOTE_BACKGROUND, fg="#1d1d1f", font=("Segoe UI", 10),
                     wraplength=260, justify="left", padx=10, pady=8).pack()

        # shortcut: placed right of the target without clamping to the monitor edge.
        self._expire(self._show(f"+{right + 10}+{top}", build), seconds)

    def clear(self) -> None:
        for window in list(self.windows):
            self._close(window)


def _handle(request: dict, overlays: Overlays) -> dict:
    command = request.get("cmd")
    if command == "snapshot":
        return _snapshot(int(request["hwnd"]))
    if command == "text":
        return _text(int(request["hwnd"]), int(request.get("limit") or 6000))
    if command == "glance":
        return _glance(int(request["hwnd"]))
    if command == "shot":
        return _shot(int(request["hwnd"]), request.get("marks") or [])
    if command == "highlight":
        overlays.highlight(request["rect"], str(request.get("label", "")), request.get("seconds"), str(request.get("style", "box")))
    elif command == "note":
        overlays.note(request["rect"], str(request["text"]), request.get("seconds"))
    elif command == "clear":
        overlays.clear()
    elif command == "click":
        _glide_and_click(int(request["hwnd"]), int(request["x"]), int(request["y"]), str(request.get("button", "left")))
    elif command == "scroll":
        _scroll(int(request["hwnd"]), request.get("x"), request.get("y"), int(request["clicks"]))
    elif command == "open":
        _open(str(request["target"]))
    elif command == "type":
        return _type(int(request["hwnd"]), int(request["x"]), int(request["y"]), str(request["text"]))
    elif command == "keys":
        _keys(request.get("hwnd"), str(request["keys"]))
    else:
        raise ValueError(f"unknown command {command!r}")
    return {}


def serve() -> int:
    # Must run before any window or UI Automation call so all coordinates are physical pixels.
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(PER_MONITOR_AWARE_V2))
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    overlays = Overlays(root)
    requests: queue.Queue[str | None] = queue.Queue()

    def read_requests() -> None:
        for line in sys.stdin:
            requests.put(line)
        requests.put(None)  # The dashboard closed the pipe: exit.

    def pump() -> None:
        while True:
            try:
                line = requests.get_nowait()
            except queue.Empty:
                break
            if line is None:
                root.destroy()
                return
            if not line.strip():
                continue
            try:
                response = {"ok": True, **_handle(json.loads(line), overlays)}
            except Exception as exc:
                response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            # ASCII-only JSON, so the pipe's code page never matters.
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        root.after(15, pump)

    threading.Thread(target=read_requests, name="AlfredAssistStdin", daemon=True).start()
    root.after(15, pump)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
