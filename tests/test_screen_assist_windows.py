"""End to end on a real Windows desktop: snapshot, highlight, type with read-back, click through an overlay.

Set ALFRED_ASSIST_COMMAND to a JSON list (for example ["dist/Nova/Nova.exe", "--screen-assist"])
to test a packaged helper instead of the source one.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from screen_assist import ScreenAssist, ScreenSession


@unittest.skipUnless(sys.platform == "win32", "needs a Windows desktop")
class ScreenAssistOnWindowsTests(unittest.TestCase):
    def test_observe_point_type_and_click(self) -> None:
        import ctypes
        user32 = ctypes.windll.user32
        saved = Path(tempfile.mkdtemp()) / "saved.txt"
        fixture = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                    str(Path(__file__).with_name("fixture_form.ps1")), "-OutFile", str(saved)])
        command = json.loads(os.environ["ALFRED_ASSIST_COMMAND"]) if os.environ.get("ALFRED_ASSIST_COMMAND") else None
        assist = ScreenAssist(command)
        try:
            hwnd = 0
            for _attempt in range(100):
                hwnd = user32.FindWindowW(None, "Nova Test Fixture")
                if hwnd:
                    break
                time.sleep(0.2)
            self.assertTrue(hwnd, "fixture window never appeared")
            time.sleep(0.5)

            session = ScreenSession(assist, lambda: hwnd, threading.Event())
            listing = session.observe()
            print(listing)
            save = next(item for item in session.context.elements if item.role == "button" and item.name == "Save")
            field = next(item for item in session.context.elements if item.role == "edit")

            foreground = user32.GetForegroundWindow()
            self.assertIn("Pointed at", session.point_at(save, "Save"))
            time.sleep(0.5)
            self.assertEqual(user32.GetForegroundWindow(), foreground, "an overlay took focus")

            self.assertIn("Pointed at", session.point_at(field, "Type here", "arrow"))
            self.assertIn("Pointed at", session.point_at(save, "", "ring"))
            text = session.read_text()
            print(text)
            self.assertIn("Question 1: What is 6 times 7?", text)
            self.assertEqual(text.count("Question 1"), 1)  # paging down found nothing new: read once

            self.assertIn("Scrolled down 1", session.scroll(None, "down", 1))  # the wheel over the window's middle
            self.assertIn("Scrolled up 1", session.scroll(field, "up", 1))
            import base64
            picture = session.screenshot()  # what Claude sees: the window with every control's number drawn on it
            self.assertTrue(picture and base64.b64decode(picture)[:2] == b"\xff\xd8", "no JPEG screenshot")
            refused = session.open_target("nova-no-such-program-xyz")  # the helper's "open" answers, and says no
            print(refused.split("\n\n")[0])
            self.assertTrue(refused.startswith("Not done:"), refused)

            typed = session.type_text(field, "hello alfred")
            print(typed)
            self.assertIn("now contains: 'hello alfred'", typed)

            # The 12-second highlight still covers the button: the click must pass through it.
            clicked = session.click(session.element(save.element_id))
            print(clicked.split("\n\n")[0])
            for _attempt in range(50):
                if saved.exists():
                    break
                time.sleep(0.1)
            self.assertEqual(saved.read_text(encoding="utf-8-sig"), "hello alfred")

            # The takeover banner promises that Esc stops Nova: a long answer stops part of the way through.
            def press_escape() -> None:
                time.sleep(0.8)
                user32.keybd_event(0x1B, 0, 0, 0)
                time.sleep(0.05)
                user32.keybd_event(0x1B, 0, 2, 0)  # KEYEVENTF_KEYUP
            threading.Thread(target=press_escape, daemon=True).start()
            started = time.monotonic()
            stopped = session.type_text(field, "x" * 600)
            print(stopped.split("\n\n")[0], f"({time.monotonic() - started:.1f} s)")
            self.assertIn("Stopped: the user pressed Esc", stopped)
        finally:
            assist.close()
            fixture.kill()

    def test_walkthrough_follows_the_user(self) -> None:
        import base64
        import ctypes
        from walkthrough import Walkthrough
        saved = Path(tempfile.mkdtemp()) / "saved.txt"
        fixture = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                    str(Path(__file__).with_name("fixture_form.ps1")), "-OutFile", str(saved)])
        command = json.loads(os.environ["ALFRED_ASSIST_COMMAND"]) if os.environ.get("ALFRED_ASSIST_COMMAND") else None
        assist = ScreenAssist(command)
        updates: list[tuple] = []
        changed = threading.Condition()

        def on_update(index, status, pointed):
            with changed:
                updates.append((index, status, pointed))
                changed.notify_all()

        def wait_for(count: int) -> None:
            with changed:
                self.assertTrue(changed.wait_for(lambda: len(updates) >= count, timeout=30), updates)
        try:
            hwnd = 0
            for _attempt in range(100):
                hwnd = ctypes.windll.user32.FindWindowW(None, "Nova Test Fixture")
                if hwnd:
                    break
                time.sleep(0.2)
            self.assertTrue(hwnd, "fixture window never appeared")
            time.sleep(0.5)
            glance = assist.request({"cmd": "glance", "hwnd": hwnd})
            self.assertEqual(len(base64.b64decode(glance["glance"])), 160 * 100)

            guide = Walkthrough(assist, hwnd, ['Type a message in "Message"', 'Click "Save"'], on_update)
            guide.start()
            wait_for(1)
            self.assertEqual(updates[0], (0, "step", "Message"))
            # The user types: the walkthrough must notice and move on to Save by itself.
            session = ScreenSession(assist, lambda: hwnd, threading.Event())
            session.observe()
            field = next(item for item in session.context.elements if item.role == "edit")
            session.type_text(field, "hello alfred, this is the walkthrough test")
            wait_for(2)
            print("walkthrough:", updates)
            self.assertEqual(updates[1], (1, "step", "Save"))
            guide.next()  # the user presses Next in the HUD
            wait_for(3)
            self.assertEqual(updates[2], (2, "done", ""))
        finally:
            assist.close()
            fixture.kill()


if __name__ == "__main__":
    unittest.main()
