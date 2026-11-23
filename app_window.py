"""Nova's window: the HUD page in a browser app window (own profile, no browser bars), plus Win32 helpers.

Windows uses Edge, which is always there. On the Mac it's Chrome, Edge, Brave or Chromium if one is installed (else
the default browser); the Win32 window helpers do nothing there.
"""
from __future__ import annotations

import ctypes
import contextlib
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Iterator
from ctypes import wintypes
from pathlib import Path

WINDOW_TITLE = "Nova"  # the HUD page's <title>; an app window shows exactly that
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x1, 0x2, 0x10, 0x40
SW_MINIMIZE, SW_SHOWNOACTIVATE, SW_RESTORE = 6, 4, 9


def find_edge() -> Path | None:
    """The browser for Nova's own window: Edge on Windows, a Chromium browser on the Mac."""
    if sys.platform == "darwin":
        import mac
        return mac.find_browser()
    paths = [Path(os.environ.get(variable, "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
             for variable in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    return next((path for path in paths if path.is_file()), None)


def open_window(url: str, profile_dir: Path) -> subprocess.Popen | None:
    """Edge with its own profile keeps camera permission for the HUD and never mixes with the user's tabs."""
    edge = find_edge()
    if edge is None:
        webbrowser.open(url)
        return None
    profile_dir.mkdir(parents=True, exist_ok=True)
    # This profile only ever loads Nova's own loopback pages (links open in the user's browser),
    # so the camera prompt for creative mode is answered here once and for all.
    proc = subprocess.Popen([str(edge), f"--app={url}", f"--user-data-dir={profile_dir}", "--no-first-run",
                             "--no-default-browser-check", "--window-size=1360,880", "--disable-features=Translate",
                             "--use-fake-ui-for-media-stream"])
    # Nova's own window must not open behind whatever the owner was doing.
    bring_window_titled_to_front(WINDOW_TITLE)
    return proc


_USER32 = None
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM) if hasattr(ctypes, "WINFUNCTYPE") else None


def _user32():
    """Our own user32 handle with 64-bit-safe argument types (HWND_TOPMOST is -1 as a pointer)."""
    global _USER32
    if _USER32 is None and hasattr(ctypes, "WinDLL"):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = [wintypes.HWND]
        for name in ("IsWindow", "IsWindowVisible", "IsIconic"):
            getattr(user32, name).argtypes = hwnd
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, wintypes.UINT]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        _USER32 = user32
    return _USER32


def find_window(title: str = WINDOW_TITLE) -> int | None:
    user32 = _user32()
    if user32 is None:
        return None
    found: list[int] = []

    @WNDENUMPROC
    def check(hwnd, _param):
        if not user32.IsWindowVisible(hwnd):
            return True
        text = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, text, 256)
        kind = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, kind, 64)
        if text.value == title and kind.value.startswith("Chrome_WidgetWin"):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(check, 0)
    return found[0] if found else None


def close_window(hwnd: int | None) -> None:
    """Ask a window to close, as its own close button would."""
    user32 = _user32()
    if user32 is not None and hwnd:
        user32.PostMessageW(wintypes.HWND(hwnd), 0x0010, 0, 0)  # WM_CLOSE


def is_window(hwnd: int | None) -> bool:
    user32 = _user32()
    return bool(hwnd and user32 and user32.IsWindow(hwnd))


def keep_on_top(hwnd: int | None, on_top: bool) -> None:
    """Show the window above the app the user is in without taking the keyboard focus from it."""
    user32 = _user32()
    if not is_window(hwnd):
        return
    if on_top and user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    user32.SetWindowPos(hwnd, HWND_TOPMOST if on_top else HWND_NOTOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | (SWP_SHOWWINDOW if on_top else 0))


@contextlib.contextmanager
def dialog_on_top(root: object | None, hwnd: int | None = None) -> Iterator[None]:
    """While a native file window Nova opens is up, keep it above the HUD.

    Tk's root is hidden, so a dialog parented to it can open behind Nova's window on Windows.
    Lifting the root to the topmost band while the dialog is up lifts the dialog with it, and
    Nova's own window drops its always-on-top first so it can't cover the dialog. Everything
    is put back afterwards. A missing root (or no Win32 here) is a plain no-op, so a dialog
    still opens — this never raises.
    """
    lifted = False
    try:
        keep_on_top(hwnd, False)
        if root is not None:
            root.attributes("-topmost", True)  # type: ignore[attr-defined]
            lifted = True
    except Exception:  # noqa: BLE001 - a dialog must still open even if the lift fails
        pass
    try:
        yield
    finally:
        if lifted:
            try:
                root.attributes("-topmost", False)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - the dialog already closed; the flag is cosmetic
                pass


def minimize(hwnd: int | None) -> None:
    if is_window(hwnd):
        _user32().ShowWindow(hwnd, SW_MINIMIZE)


def restore(hwnd: int | None) -> None:
    """Un-minimize (back to maximized if it was); a window that is already showing is left alone."""
    if is_window(hwnd) and _user32().IsIconic(hwnd):
        _user32().ShowWindow(hwnd, SW_RESTORE)


def is_topmost(hwnd: int | None) -> bool:
    WS_EX_TOPMOST, GWL_EXSTYLE = 0x8, -20
    return is_window(hwnd) and bool(_user32().GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)


def bring_to_front(hwnd: int | None) -> bool:
    """Lift a window above Nova's (and every other) window, without leaving it always-on-top.

    A window Nova launches can open behind the HUD: Nova's own process usually isn't the
    foreground one, so Windows won't hand the new window the focus, and the HUD sits in front
    of it. The reliable move is the old topmost-then-not-topmost trick — pin it topmost for one
    SetWindowPos, which puts it at the top of the normal z-order, then unpin it so it behaves
    like any other window afterwards. A window that is already topmost (an approval has Nova's
    window lifted, or the smoke test is checking it) is left exactly as it is, so this never
    fights a deliberate topmost. Returns False when there is no window to lift (or no Win32
    here); never raises.
    """
    user32 = _user32()
    if not is_window(hwnd):
        return False
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        if is_topmost(hwnd):
            return True
        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
        try:
            user32.SetForegroundWindow(hwnd)  # best effort: the foreground rules may refuse it
        except Exception:  # noqa: BLE001 - focus is a bonus; being on top is the point
            pass
        return True
    except Exception:  # noqa: BLE001 - lifting a window must never break the action that opened it
        return False


def _titled(hwnd: int) -> bool:
    """A visible window with a real title (not a helper window with an empty one)."""
    user32 = _user32()
    if user32 is None:
        return False
    text = ctypes.create_unicode_buffer(256)
    return user32.GetWindowTextW(hwnd, text, 256) > 0 and bool(text.value.strip())


def snapshot_windows() -> set[int]:
    """The visible top-level windows right now (their handles), so a launch can tell what is new."""
    user32 = _user32()
    if user32 is None:
        return set()
    found: list[int] = []

    @WNDENUMPROC
    def check(hwnd, _param):
        if user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(check, 0)
    return set(found)


def new_windows(before: set[int], after: set[int], exclude: set[int] | None = None) -> list[int]:
    """Handles in `after` that weren't in `before` (and aren't excluded): the windows a launch just opened."""
    excluded = exclude or set()
    return [hwnd for hwnd in after if hwnd not in before and hwnd not in excluded]


def bring_new_window_to_front(before: set[int], exclude: set[int] | None = None,
                              timeout: float = 3.0, poll: float = 0.1) -> None:
    """In a background thread: wait for a window that wasn't there before the launch, and lift it above Nova.

    A new window takes a moment to appear, and the launch itself must not wait for it — so the watch
    runs in a daemon thread and stops at the first titled new window (or when the timeout runs out).
    Nova's own window is never a candidate. Does nothing where there is no Win32.
    """
    user32 = _user32()
    if user32 is None:
        return
    own = find_window()
    excluded = set(exclude or set()) | ({own} if own else set())

    def watch() -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for hwnd in new_windows(before, snapshot_windows(), excluded):
                if _titled(hwnd) and bring_to_front(hwnd):
                    return
            time.sleep(poll)

    threading.Thread(target=watch, name="NovaBringToFront", daemon=True).start()


def bring_window_titled_to_front(title: str, timeout: float = 5.0, poll: float = 0.1) -> None:
    """In a background thread: wait for the window with this exact title, and lift it above Nova.

    For windows Nova opens itself and knows by title (its own HUD, the creative window). Does
    nothing where there is no Win32.
    """
    if _user32() is None:
        return

    def watch() -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            hwnd = find_window(title)
            if hwnd and bring_to_front(hwnd):
                return
            time.sleep(poll)

    threading.Thread(target=watch, name="NovaBringToFront", daemon=True).start()


def open_browser(url: str) -> None:
    """Open a link in the user's own browser (not the HUD window) and lift the browser above Nova."""
    before = snapshot_windows()
    webbrowser.open(url)
    bring_new_window_to_front(before)


def open_path(target: str | Path) -> None:
    """Open a file, folder or link (obsidian://…) the way double-clicking it would."""
    before = snapshot_windows()
    if sys.platform == "win32":
        os.startfile(str(target))  # noqa: S606 - Nova's own files, the owner's folders and fixed apps
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])  # noqa: S603,S607
    else:
        subprocess.Popen(["xdg-open", str(target)])  # noqa: S603,S607
    # A launched app can open behind the HUD; lift its window once it appears.
    bring_new_window_to_front(before)


def obsidian_installed() -> bool:
    if sys.platform == "win32":
        import winreg
        try:
            winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "obsidian").Close()
            return True
        except OSError:
            return False
    if sys.platform == "darwin":
        return any((base / "Obsidian.app").exists() for base in (Path("/Applications"), Path.home() / "Applications"))
    return shutil.which("obsidian") is not None
