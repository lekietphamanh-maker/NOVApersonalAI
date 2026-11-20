"""Mini Nova in the corner: every state draws, Nova's state picks the right one, and on Windows the window shows
without taking the keyboard, stays out of screenshots, and the takeover banner appears while Nova acts."""
from __future__ import annotations

import sys
import time
import unittest

import mini_orb


class MiniOrbDrawingTests(unittest.TestCase):
    def test_every_state_draws_a_frame(self) -> None:
        for mode in mini_orb.MODES:
            frame = mini_orb.render(mode, 1.2, level=0.5)
            self.assertEqual((frame.size, frame.mode), ((mini_orb.SIZE, mini_orb.SIZE), "RGBA"), mode)
            self.assertGreater(frame.getbbox()[2], 0, mode)
            corner = frame.getpixel((0, 0))
            self.assertEqual(corner[3], 0, f"{mode}: the corners must stay see-through")

    def test_taking_over_glows_much_more(self) -> None:
        def glow(mode: str) -> int:
            return sum(pixel[3] for pixel in mini_orb.render(mode, 0.4).getdata())
        self.assertGreater(glow("act"), glow("armed") * 1.4)

    def test_the_banner_draws(self) -> None:
        banner = mini_orb.render_banner()
        self.assertEqual(banner.mode, "RGBA")
        self.assertGreater(banner.width, 300)
        self.assertEqual(banner.getpixel((0, 0))[3], 0, "the banner's corners must stay see-through")

    def test_the_state_picks_the_look(self) -> None:
        base = {"switches": {"mic": False}, "voice": {"tone": "idle"}, "busy": False, "speaking": False}
        self.assertEqual(mini_orb.mode_for(base, acting=False), "asleep")
        self.assertEqual(mini_orb.mode_for({**base, "switches": {"mic": True}}, acting=False), "armed")
        self.assertEqual(mini_orb.mode_for({**base, "voice": {"tone": "listen"}}, acting=False), "listen")
        self.assertEqual(mini_orb.mode_for({**base, "busy": True}, acting=False), "think")
        self.assertEqual(mini_orb.mode_for({**base, "busy": True, "speaking": True}, acting=False), "speak")
        self.assertEqual(mini_orb.mode_for({**base, "busy": True}, acting=True), "act")


@unittest.skipUnless(sys.platform == "win32", "needs a Windows desktop")
class MiniOrbWindowTests(unittest.TestCase):
    def test_shows_without_focus_opens_on_click_and_warns_while_nova_acts(self) -> None:
        import ctypes
        import tkinter as tk
        from ctypes import wintypes
        api = mini_orb._api()
        user32 = api.user32
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        root = tk.Tk()
        root.withdraw()
        look = {"mode": "armed"}
        opened: list[int] = []
        orb = mini_orb.MiniOrb(root, lambda: (look["mode"], 0.3, (255, 176, 64), True), on_open=lambda: opened.append(1),
                               on_right_click=lambda: None)
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

        def describe(hwnd) -> str:
            name, kind, process = ctypes.create_unicode_buffer(128), ctypes.create_unicode_buffer(128), wintypes.DWORD()
            user32.GetWindowTextW(hwnd, name, 128)
            user32.GetClassNameW(hwnd, kind, 128)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process))
            return f"{hwnd} {kind.value!r} {name.value!r} pid {process.value}"

        def assert_never_ours(when: str) -> None:
            """What matters: neither of Nova's windows is ever the one taking your keyboard."""
            active = user32.GetForegroundWindow()
            print(f"{when}: foreground is {describe(active)}")
            self.assertNotIn(active, (orb.window.hwnd, orb.banner.hwnd), f"{when}: Nova's window took the focus")

        def run(seconds: float) -> None:
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                root.update()
                time.sleep(0.01)
        try:
            orb.start()
            run(1.5)
            self.assertIsNotNone(orb.window, "the mini orb could not be created")
            self.assertTrue(user32.IsWindowVisible(orb.window.hwnd), "the mini orb never appeared")
            self.assertGreater(orb.frames, 5)
            assert_never_ours("after showing")
            style = user32.GetWindowLongW(orb.window.hwnd, mini_orb.GWL_EXSTYLE)
            self.assertTrue(style & mini_orb.WS_EX_NOACTIVATE, "it could take the keyboard")
            self.assertTrue(style & mini_orb.WS_EX_TOPMOST)
            self.assertFalse(style & mini_orb.WS_EX_TRANSPARENT, "it must be clickable when Nova isn't acting")
            affinity = wintypes.DWORD()
            user32.GetWindowDisplayAffinity(orb.window.hwnd, ctypes.byref(affinity))
            self.assertEqual(affinity.value, mini_orb.WDA_EXCLUDEFROMCAPTURE)
            left, _top, _right, bottom = mini_orb.work_area()
            self.assertLess(orb.window.x - left, 60)
            self.assertLess(bottom - (orb.window.y + mini_orb.SIZE), 60)

            user32.PostMessageW(orb.window.hwnd, mini_orb.WM_LBUTTONDOWN, 1, 0)
            user32.PostMessageW(orb.window.hwnd, mini_orb.WM_LBUTTONUP, 0, 0)
            run(0.3)
            self.assertEqual(opened, [1], "a click didn't open Nova")
            assert_never_ours("after a click")

            look["mode"] = "act"
            run(0.6)
            self.assertTrue(user32.IsWindowVisible(orb.banner.hwnd), "no takeover banner while Nova acts")
            for window in (orb.window, orb.banner):
                style = user32.GetWindowLongW(window.hwnd, mini_orb.GWL_EXSTYLE)
                self.assertTrue(style & mini_orb.WS_EX_TRANSPARENT, "Nova's own clicks must pass through it")
            look["mode"] = "think"
            run(0.6)
            self.assertFalse(user32.IsWindowVisible(orb.banner.hwnd))
            assert_never_ours("after the takeover")
        finally:
            orb.stop()
            root.destroy()


if __name__ == "__main__":
    unittest.main()
