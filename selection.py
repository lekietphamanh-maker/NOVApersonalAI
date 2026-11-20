"""Highlighted text to the second brain: press the keep-hotkey with text selected, and Nova copies it with Ctrl+C,
reads it from the clipboard and puts the owner's own clipboard text back. Everything that touches Windows comes in as
a function, so the logic is tested anywhere."""
from __future__ import annotations

import ctypes
import time
from typing import Callable

MAX_SELECTION = 20_000  # characters kept from one highlight


def grab_selection(copy: Callable[[], None], sequence: Callable[[], int], read: Callable[[], str | None],
                   write: Callable[[str], None], wait: float = 1.0, sleep: Callable[[float], None] = time.sleep) -> str:
    """The text highlighted in the app in front, or "" when nothing was highlighted.

    `sequence` is the clipboard's change counter: a Ctrl+C that copied nothing leaves it alone, which tells "nothing
    selected" apart from "selected the same text that is already on the clipboard"."""
    before_text, before = read(), sequence()
    copy()
    waited = 0.0
    while sequence() == before and waited < wait:
        sleep(0.05)
        waited += 0.05
    if sequence() == before:
        return ""
    copied = read() or ""
    if before_text is not None:
        write(before_text)  # the owner's clipboard is theirs: put it back
    return copied.strip()[:MAX_SELECTION]


# ---------- Windows ----------

CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002
VK_CONTROL, VK_C, KEYEVENTF_KEYUP = 0x11, 0x43, 0x0002


def _user32():
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes, user32.OpenClipboard.restype = [wintypes.HWND], wintypes.BOOL
    user32.GetClipboardData.argtypes, user32.GetClipboardData.restype = [wintypes.UINT], wintypes.HANDLE
    user32.SetClipboardData.argtypes, user32.SetClipboardData.restype = [wintypes.UINT, wintypes.HANDLE], wintypes.HANDLE
    user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    kernel32.GlobalAlloc.argtypes, kernel32.GlobalAlloc.restype = [wintypes.UINT, ctypes.c_size_t], wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes, kernel32.GlobalLock.restype = [wintypes.HGLOBAL], ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    return user32, kernel32


def _open_clipboard(user32) -> bool:
    for _attempt in range(25):  # another program may hold the clipboard for a moment
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False


def clipboard_sequence() -> int:
    return int(_user32()[0].GetClipboardSequenceNumber())


def read_clipboard_text() -> str | None:
    """The clipboard's text, or None when it holds something else (a picture, files) or can't be opened."""
    user32, kernel32 = _user32()
    if not _open_clipboard(user32):
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def write_clipboard_text(text: str) -> None:
    user32, kernel32 = _user32()
    if not _open_clipboard(user32):
        return
    try:
        user32.EmptyClipboard()
        data = (text + "\0").encode("utf-16-le")
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        pointer = kernel32.GlobalLock(handle)
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        user32.SetClipboardData(CF_UNICODETEXT, handle)  # the clipboard owns the memory now
    finally:
        user32.CloseClipboard()


def press_ctrl_c() -> None:
    user32 = ctypes.windll.user32
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_C, 0, 0, 0)
    user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def grab_windows_selection() -> str:
    return grab_selection(press_ctrl_c, clipboard_sequence, read_clipboard_text, write_clipboard_text)
