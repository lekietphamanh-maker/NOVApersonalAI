"""Nova's hotkeys, all changeable in SETTINGS → Hotkeys: hold-to-talk (Ctrl+Alt), stop (Esc), keep what you
highlighted (F9), and yes (F8) / no (F10) to answer a question Nova asks. Keys are Windows virtual-key
codes, read by polling (no keyboard hook), so they are never swallowed from the app you are using. On the Mac the
same codes are read through Quartz (mac.py), and Ctrl, Alt and Win are Control, Option and Command."""
from __future__ import annotations

import sys

DEFAULTS = {"talk": [0x11, 0x12], "stop": [0x1B], "clip": [0x78], "yes": [0x77], "no": [0x79],
            "dictate": [0x11, 0x5B]}  # Ctrl+Win (Control+Command on a Mac): hold, speak, and it's typed where you are
MODIFIERS = {0x10: "Shift", 0x11: "Ctrl", 0x12: "Alt", 0x5B: "Win", 0x5C: "Win"}
_NAMED = {0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pause", 0x14: "Caps Lock", 0x1B: "Esc", 0x20: "Space",
          0x21: "Page Up", 0x22: "Page Down", 0x23: "End", 0x24: "Home", 0x25: "Left", 0x26: "Up", 0x27: "Right",
          0x28: "Down", 0x2C: "Print Screen", 0x2D: "Insert", 0x2E: "Delete", 0x91: "Scroll Lock", 0xC0: "`",
          0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'"}
# Keys you type with: alone (or with just Shift) they would fire while you write, so hold-to-talk needs more.
_TYPING = set(range(0x30, 0x3A)) | set(range(0x41, 0x5B)) | {0x08, 0x09, 0x0D, 0x20, 0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF,
                                                              0xC0, 0xDB, 0xDC, 0xDD, 0xDE}


MAC_NAMES = {0x11: "Control", 0x12: "Option", 0x5B: "Command", 0x5C: "Command", 0x08: "Delete", 0x0D: "Return"}


def held(code: int, platform: str | None = None) -> bool:
    """Whether the key is down right now, whichever app is in front."""
    if (platform or sys.platform) == "darwin":
        import mac
        return mac.key_held(code)
    import ctypes
    return bool(ctypes.windll.user32.GetAsyncKeyState(code) & 0x8000)


def key_name(code: int, platform: str | None = None) -> str:
    if (platform or sys.platform) == "darwin" and code in MAC_NAMES:
        return MAC_NAMES[code]
    if code in MODIFIERS:
        return MODIFIERS[code]
    if code in _NAMED:
        return _NAMED[code]
    if 0x30 <= code <= 0x39 or 0x41 <= code <= 0x5A:
        return chr(code)
    if 0x70 <= code <= 0x87:
        return f"F{code - 0x6F}"
    if 0x60 <= code <= 0x69:
        return f"Num {code - 0x60}"
    return f"Key {code}"


def label(keys: list[int]) -> str:
    """'Ctrl+Alt', 'Ctrl+Shift+Space', 'F8': modifiers first, in the usual order."""
    order = {0x11: 0, 0x5B: 1, 0x5C: 1, 0x12: 2, 0x10: 3}
    return "+".join(key_name(code) for code in sorted(keys, key=lambda code: (order.get(code, 9), code)))


def check(which: str, keys: object, others: list[list[int]]) -> tuple[list[int], str]:
    """(the keys to save, '') or ([], why not). `others`: the keys of every other hotkey."""
    if which not in DEFAULTS:
        return [], "Unknown hotkey."
    if not isinstance(keys, list) or not 1 <= len(keys) <= 3 or not all(isinstance(code, int) and 1 <= code <= 254 for code in keys):
        return [], "Press one to three keys together."
    keys = sorted(set(keys))
    for taken in others:
        if sorted(taken) == keys:
            return [], f"{label(keys)} is already another hotkey."
    for taken in others:
        if set(taken) < set(keys):
            return [], f"{label(keys)} includes {label(taken)}, which would fire too."
    if which != "stop":  # Esc alone is fine for stop; every other key must not fire while you type
        plain = [code for code in keys if code not in MODIFIERS]
        if keys == [0x10] or (plain and all(code in _TYPING for code in plain)
                              and not any(code in (0x11, 0x12, 0x5B, 0x5C) for code in keys)):
            return [], (f"{label(keys)} would fire while you type. Add Ctrl, Alt or Win, or use a key like F8 or "
                        "Scroll Lock.")
    return keys, ""
