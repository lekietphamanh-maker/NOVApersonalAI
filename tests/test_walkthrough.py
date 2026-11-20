"""Walkthroughs: steps parsed, each step's control found by name, a step counts as done when the screen
changed and settled (or the user pressed Next), and stopping ends it."""
from __future__ import annotations

import base64
import threading
import time
import unittest
from unittest.mock import patch

import walkthrough
from screen_elements import number_elements
from walkthrough import Walkthrough, difference, find_control, parse_steps, speakable_step, strong_pixels

BLANK, MENU, TYPED = bytes([200] * 16000), bytes([60] * 16000), bytes([200] * 15900 + [20] * 100)


class FakeAssist:
    def __init__(self, glances: list[bytes]):
        self.glances, self.drawn = glances, []
        self.menu_open = False

    def request(self, payload: dict, timeout: float = 10.0) -> dict:
        command = payload["cmd"]
        if command == "snapshot":
            elements = [{"role": "MenuItem", "name": "File", "rect": [10, 10, 60, 30]}]
            if self.menu_open:
                elements.append({"role": "MenuItem", "name": "Export To…", "rect": [10, 40, 120, 60]})
            return {"window_title": "Keynote", "elements": elements}
        if command == "glance":
            image = self.glances.pop(0) if len(self.glances) > 1 else self.glances[0]
            if image is MENU:
                self.menu_open = True
            return {"glance": base64.b64encode(image).decode(), "rect": [0, 0, 800, 600]}
        self.drawn.append(payload)
        return {}


class WalkthroughTests(unittest.TestCase):
    def test_parsing_and_finding(self):
        self.assertEqual(parse_steps('1. Click "File"\n\n- Click "Export To"\nStep 3: Choose "PDF"'),
                         ['Click "File"', 'Click "Export To"', 'Choose "PDF"'])
        elements = number_elements([{"role": "Button", "name": "Export To…", "rect": [0, 0, 50, 20]},
                                    {"role": "Button", "name": "Export", "rect": [0, 30, 50, 50]}])
        self.assertEqual(find_control(elements, 'Click "export"').name, "Export")
        self.assertEqual(find_control(elements, 'Click “Export To”').name, "Export To…")
        self.assertIsNone(find_control(elements, "Open the menu"))
        self.assertEqual(speakable_step('Click "File"'), "Click File")

    def test_change_rules(self):
        self.assertEqual(difference(BLANK, BLANK), 0)
        self.assertGreater(difference(BLANK, MENU), walkthrough.CHANGED)          # a menu opened
        self.assertLess(difference(BLANK, TYPED), walkthrough.CHANGED)            # typing: small mean...
        self.assertGreaterEqual(strong_pixels(BLANK, TYPED), walkthrough.STRONG_CHANGED)  # ...but strong pixels
        hover = bytes([200] * 15500 + [215] * 500)                                # a button hover tint
        self.assertLess(difference(BLANK, hover), walkthrough.CHANGED)
        self.assertEqual(strong_pixels(BLANK, hover), 0)

    def test_steps_advance_when_the_screen_changes_and_settles(self):
        updates = []
        done = threading.Event()
        assist = FakeAssist([BLANK, BLANK, MENU, MENU, MENU, MENU, TYPED, TYPED])

        def on_update(index, status, pointed):
            updates.append((index, status, pointed))
            if status != "step":
                done.set()

        with patch.object(walkthrough, "GLANCE_EVERY", 0.01):
            guide = Walkthrough(assist, 42, ['Click "File"', 'Click "Export To"'], on_update)
            guide.start()
            self.assertTrue(done.wait(5))
        self.assertEqual(updates, [(0, "step", "File"), (1, "step", "Export To…"), (2, "done", "")])
        notes = [item["text"] for item in assist.drawn if item["cmd"] == "note"]
        self.assertEqual(notes, ['Click "File"', 'Click "Export To"'])
        labels = [item["label"] for item in assist.drawn if item["cmd"] == "highlight"]
        self.assertEqual(labels, ["Step 1/2", "Step 2/2"])

    def test_next_and_stop(self):
        updates = []
        with patch.object(walkthrough, "GLANCE_EVERY", 0.01):
            guide = Walkthrough(FakeAssist([BLANK]), 42, ['Click "File"', 'Open "Recent"'], lambda *update: updates.append(update))
            guide.start()
            time.sleep(0.1)
            guide.next()  # nothing changed on screen, the user pressed Next
            time.sleep(0.1)
            guide.stop()
            guide.thread.join(2)
        self.assertEqual(updates, [(0, "step", "File"), (1, "step", "")])
        self.assertFalse(guide.thread.is_alive())


if __name__ == "__main__":
    unittest.main()
