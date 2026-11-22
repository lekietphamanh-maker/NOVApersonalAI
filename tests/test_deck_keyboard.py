"""The deck's keyboard: which keys exist, what one press does, text in any language, and (on Windows) real typing."""
from __future__ import annotations

import ctypes
import sys
import unittest
from unittest.mock import patch

import deck_keyboard
from deck_keyboard import KEYS, MODIFIERS, key_events, press, text_units, type_text


class KeyTests(unittest.TestCase):
    def test_a_press_holds_its_modifiers_around_the_key(self) -> None:
        self.assertEqual(key_events("c", ["ctrl"]), [(0xA2, True), (0x43, True), (0x43, False), (0xA2, False)])
        self.assertEqual(key_events("t", ["ctrl", "shift", "ctrl"]),  # each modifier once, let go in reverse
                         [(0xA2, True), (0xA0, True), (0x54, True), (0x54, False), (0xA0, False), (0xA2, False)])
        self.assertEqual(key_events("win", ["win"]), [(0x5B, True), (0x5B, False)])  # Start menu
        self.assertEqual(key_events("f5"), [(0x74, True), (0x74, False)])

    def test_only_the_decks_keys_exist(self) -> None:
        for key in ("a", "z", "0", "9", "f1", "f12", "esc", "enter", "backspace", "left", "pagedown", "`", "/", "\\"):
            self.assertIn(key, KEYS)
        for bad in ("A", "f13", "volume_up", "", "ctrl"):
            with self.subTest(bad), self.assertRaises(ValueError):
                key_events(bad)
        with self.assertRaises(ValueError):
            key_events("a", ["hyper"])
        self.assertEqual(set(MODIFIERS), {"ctrl", "shift", "alt", "win"})

    def test_nothing_is_pressed_unless_every_key_is_good(self) -> None:
        with patch.object(deck_keyboard, "_send") as send:
            with self.assertRaises(ValueError):
                press([{"key": "a", "mods": []}, {"key": "nope", "mods": []}])
            with self.assertRaises(ValueError):
                press([{"key": "a", "mods": "ctrl"}])
            with self.assertRaises(ValueError):
                press([{"key": "a"}] * 65)
            with self.assertRaises(ValueError):
                press([])
            send.assert_not_called()
            press([{"key": "h", "mods": ["shift"]}, {"key": "i"}])
            self.assertEqual(len(send.call_args[0][0]), 6)

    def test_text_goes_in_as_written(self) -> None:
        units = text_units("Xin chào\nđi 👍")
        self.assertIn(("char", ord("à")), units)
        self.assertIn(("char", ord("đ")), units)
        self.assertIn(("key", KEYS["enter"]), units)
        self.assertEqual(units[-2:], [("char", 0xD83D), ("char", 0xDC4D)])  # an emoji is two UTF-16 units
        self.assertEqual(text_units("a\r\nb"), [("char", 97), ("key", KEYS["enter"]), ("char", 98)])
        self.assertEqual(len(text_units("x" * 5000)), deck_keyboard.MAX_TEXT)
        with patch.object(deck_keyboard, "_send") as send:
            type_text("hi")
            self.assertEqual(len(send.call_args[0][0]), 4)  # each character down and up

    def test_windows_gets_the_input_layout_it_expects(self) -> None:
        self.assertEqual(ctypes.sizeof(deck_keyboard._Input), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
        arrow = deck_keyboard._key(KEYS["left"], False)
        self.assertEqual(arrow.u.ki.dwFlags, deck_keyboard.KEYEVENTF_EXTENDEDKEY | deck_keyboard.KEYEVENTF_KEYUP)
        self.assertEqual(deck_keyboard._key(KEYS["a"], True).u.ki.dwFlags, 0)


# Runs in its own process: if anything in it stalls (a window caught in a modal loop), the test fails after a minute
# instead of holding up the whole run.
TYPING_SCRIPT = r"""
import ctypes, json, sys, time, tkinter as tk
import deck_keyboard
user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
root = tk.Tk()
root.title("Nova deck keyboard test")
entry = tk.Entry(root, width=40)
entry.pack(padx=20, pady=20)
root.attributes("-topmost", True)
root.update()
hwnd = int(root.wm_frame(), 16)

def settle():
    for _ in range(30):
        root.update()
        time.sleep(0.02)

def in_front():
    # sharing input with the window in front lets this process bring its own window forward (no Alt-key trick:
    # a lone Alt puts a window in menu mode)
    front = user32.GetForegroundWindow()
    theirs, mine = user32.GetWindowThreadProcessId(front, None), kernel32.GetCurrentThreadId()
    if front and theirs and theirs != mine:
        user32.AttachThreadInput(theirs, mine, True)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    if front and theirs and theirs != mine:
        user32.AttachThreadInput(theirs, mine, False)
    root.focus_force()
    entry.focus_set()
    settle()
    return user32.GetForegroundWindow() == hwnd

if not any(in_front() for _ in range(10)):
    print("NO-FOREGROUND")
    sys.exit(0)
deck_keyboard.press([{"key": "h", "mods": ["shift"]}, {"key": "i", "mods": []}, {"key": "1", "mods": ["shift"]}])
deck_keyboard.type_text(" Xin chào")
settle()
typed = entry.get()
if user32.GetForegroundWindow() == hwnd:
    deck_keyboard.press([{"key": "home", "mods": ["shift"]}, {"key": "backspace", "mods": []}])  # select to the start, delete
    settle()
print(json.dumps([typed, entry.get()]))
root.destroy()
"""


@unittest.skipUnless(sys.platform == "win32", "needs a Windows desktop")
class TypingOnWindowsTests(unittest.TestCase):
    def test_keys_and_text_reach_the_window_in_front(self) -> None:
        import json
        import subprocess
        from pathlib import Path
        result = subprocess.run([sys.executable, "-c", TYPING_SCRIPT], capture_output=True, text=True, timeout=60,
                                cwd=Path(__file__).resolve().parent.parent)
        lines = result.stdout.strip().splitlines()
        self.assertEqual(result.returncode, 0, result.stderr)
        if lines and lines[-1] == "NO-FOREGROUND":
            self.skipTest("this desktop doesn't let the test window come to the front")
        self.assertEqual(json.loads(lines[-1]), ["Hi! Xin chào", ""])  # Shift, plain keys, Unicode text, Shift+Home


if __name__ == "__main__":
    unittest.main()
