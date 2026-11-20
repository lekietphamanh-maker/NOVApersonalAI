"""The deck's keyboard: keys tapped on the iPad (or a touch screen) become real key presses on this PC.

Only the keys drawn on the deck exist here. A press holds its modifiers, presses the key and lets go of everything.
Text from the deck's type box goes in as Unicode characters, so Vietnamese and emoji arrive exactly as written
(the PC's keyboard layout and input method don't touch them). Windows doesn't let any app type into a window that
runs as administrator unless that app does too.
"""
from __future__ import annotations

import ctypes
import threading

MODIFIERS = {"ctrl": 0xA2, "shift": 0xA0, "alt": 0xA4, "win": 0x5B}  # the left-hand ones
KEYS: dict[str, int] = {
    **{chr(code): code - 32 for code in range(ord("a"), ord("z") + 1)},  # 'a' -> 0x41
    **{str(digit): 0x30 + digit for digit in range(10)},
    **{f"f{number}": 0x6F + number for number in range(1, 13)},
    "esc": 0x1B, "tab": 0x09, "capslock": 0x14, "enter": 0x0D, "backspace": 0x08, "space": 0x20,
    "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "printscreen": 0x2C, "win": 0x5B, "menu": 0x5D,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA, "'": 0xDE,
    ",": 0xBC, ".": 0xBE, "/": 0xBF,
}
EXTENDED = {0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28, 0x5B, 0x5D, 0x2C}  # arrows, Ins/Del, Win...
MAX_KEYS = 64  # per request: what piled up while the previous request was on its way
MAX_TEXT = 1000
INPUT_KEYBOARD, KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 1, 0x1, 0x2, 0x4


# Windows' INPUT, with fixed-width fields so the size is right (40 bytes on 64-bit, 28 on 32-bit).
class _KeyboardInput(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16), ("dwFlags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class _MouseInput(ctypes.Structure):  # only here so the union is as big as Windows expects
    _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32), ("mouseData", ctypes.c_uint32),
                ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class _Union(ctypes.Union):
    _fields_ = [("ki", _KeyboardInput), ("mi", _MouseInput)]


class _Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("u", _Union)]


_typing = threading.Lock()  # two requests never mix their keys


def key_events(key: str, mods: list[str] | tuple[str, ...] = ()) -> list[tuple[int, bool]]:
    """(virtual key, down?) for one press: the modifiers down, the key down and up, the modifiers up."""
    if key not in KEYS:
        raise ValueError(f"No {key!r} key on the deck.")
    held: list[int] = []
    for mod in mods:
        if mod not in MODIFIERS:
            raise ValueError(f"No {mod!r} modifier on the deck.")
        if MODIFIERS[mod] not in held and MODIFIERS[mod] != KEYS[key]:
            held.append(MODIFIERS[mod])
    vk = KEYS[key]
    return [(code, True) for code in held] + [(vk, True), (vk, False)] + [(code, False) for code in reversed(held)]


def text_units(text: str) -> list[tuple[str, int]]:
    """('char', UTF-16 code unit) per character (an emoji is two), ('key', VK) for a new line or a tab."""
    units: list[tuple[str, int]] = []
    for char in str(text)[:MAX_TEXT]:
        if char == "\r":
            continue
        if char in "\n\t":
            units.append(("key", KEYS["enter" if char == "\n" else "tab"]))
            continue
        encoded = char.encode("utf-16-le")
        units.extend(("char", int.from_bytes(encoded[i:i + 2], "little")) for i in range(0, len(encoded), 2))
    return units


def press(keys: object) -> None:
    """Press each {'key': ..., 'mods': [...]} in order on this PC. All are checked before any is pressed."""
    if not isinstance(keys, list) or not 0 < len(keys) <= MAX_KEYS:
        raise ValueError("Send between 1 and 64 keys at a time.")
    events: list[tuple[int, bool]] = []
    for item in keys:
        if not isinstance(item, dict) or not isinstance(item.get("mods", []), list):
            raise ValueError("A key is {key, mods}.")
        events.extend(key_events(str(item.get("key", "")), [str(mod) for mod in item.get("mods", [])]))
    _send([_key(vk, down) for vk, down in events])


def type_text(text: str) -> None:
    """Type the text on this PC as it is written: any language, emoji, new lines."""
    inputs = []
    for kind, value in text_units(text):
        if kind == "key":
            inputs += [_key(value, True), _key(value, False)]
        else:
            inputs += [_unicode(value, KEYEVENTF_UNICODE), _unicode(value, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
    _send(inputs)


def _key(vk: int, down: bool) -> _Input:
    flags = (0 if down else KEYEVENTF_KEYUP) | (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED else 0)
    scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0) if hasattr(ctypes, "windll") else 0  # some apps read scan codes
    return _Input(type=INPUT_KEYBOARD, u=_Union(ki=_KeyboardInput(wVk=vk, wScan=scan, dwFlags=flags)))


def _unicode(unit: int, flags: int) -> _Input:
    return _Input(type=INPUT_KEYBOARD, u=_Union(ki=_KeyboardInput(wVk=0, wScan=unit, dwFlags=flags)))


def _send(inputs: list[_Input]) -> None:
    if not inputs:
        return
    batch = (_Input * len(inputs))(*inputs)
    with _typing:
        sent = ctypes.windll.user32.SendInput(len(inputs), batch, ctypes.sizeof(_Input))
    if sent != len(inputs):
        raise OSError("Windows didn't take the keys: the window in front may be running as administrator.")
