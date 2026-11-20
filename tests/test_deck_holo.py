"""The deck's Holo look in a real browser: it rests with only Nova's orb and the widget dial (the keyboard hidden, so
nothing types on the PC); half a drag along the bar slides back; a swipe brings the 60% keyboard in; the dial works
either way; fn reaches F-keys and arrows; Classic shows the full keyboard at once. (Edge on Windows, Chromium elsewhere.)"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

from tests.test_web_tasks import _browser_available

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(_browser_available(), "needs Playwright and Edge (Windows) or a Chromium")
class HoloKeyboardTests(unittest.TestCase):
    def test_swipe_to_unlock_then_type_and_use_the_dial(self) -> None:
        from playwright.sync_api import sync_playwright

        from web_tasks import launch
        if sys.platform != "win32" and not os.environ.get("NOVA_BROWSER"):
            os.environ["NOVA_BROWSER"] = "/opt/pw-browsers/chromium"
        sent: list[dict] = []

        def serve(route) -> None:
            path = route.request.url.split("deck.test", 1)[1].split("?")[0].split("#")[0]
            if path == "/deck.html":
                route.fulfill(body=(ROOT / "phone" / "deck.html").read_bytes(), content_type="text/html")
            elif path == "/api/deck":
                sent.append(json.loads(route.request.post_data))
                route.fulfill(json={"message": ""})
            elif path == "/api/screen":
                route.fulfill(json={"mode": "asleep", "timers": [], "reminders": []})
            else:
                route.fulfill(status=404)

        def press(page, selector: str, pointer: int) -> None:
            page.locator(selector).dispatch_event("pointerdown", {"pointerId": pointer})
            page.locator(selector).dispatch_event("pointerup", {"pointerId": pointer})

        def swipe(page, share: float) -> None:
            box = page.locator("#lock-track").bounding_box()
            y = box["y"] + box["height"] / 2
            page.mouse.move(box["x"] + 30, y)
            page.mouse.down()
            page.mouse.move(box["x"] + box["width"] * share, y, steps=8)
            page.mouse.up()
            page.wait_for_timeout(400)

        with sync_playwright() as playwright:
            browser = launch(playwright)
            page = browser.new_page(viewport={"width": 1180, "height": 820})
            page.route("http://deck.test/**", serve)
            page.goto("http://deck.test/deck.html#token=abc")
            page.wait_for_timeout(500)
            locked = lambda: page.evaluate("document.body.classList.contains('keys-hidden')")  # noqa: E731
            self.assertTrue(locked())  # Holo is the default: orb and widgets only
            self.assertFalse(page.locator("#keyboard").is_visible())
            press(page, '.key[aria-label="A"]', 1)
            page.wait_for_timeout(200)
            self.assertEqual(sent, [])  # hidden keys type nothing
            press(page, '.dial-part[aria-label="Copy"]', 2)
            page.wait_for_timeout(300)
            self.assertEqual(sent, [{"action": "copy"}])  # the dial works with the keys hidden
            swipe(page, 0.4)
            self.assertTrue(locked())  # half a drag along the bar slides back
            dial = page.locator("#dial").bounding_box()
            page.mouse.move(dial["x"] + dial["width"] * 0.85, dial["y"] + 30)
            page.mouse.down()
            page.mouse.move(dial["x"] + dial["width"] * 0.35, dial["y"] + 30, steps=6)  # a swipe over the dial
            page.mouse.up()
            page.wait_for_timeout(600)
            self.assertFalse(locked())
            self.assertTrue(page.locator("#keyboard").is_visible())
            sent.clear()
            press(page, '.key[aria-label="A"]', 3)
            page.wait_for_timeout(400)
            self.assertIn({"keys": [{"key": "a", "mods": []}]}, sent)
            # 60%: no F-key row and no arrow keys; fn reaches them (tap fn, then the key)
            self.assertEqual(page.locator('.key[aria-label="F1"]').count(), 0)
            self.assertEqual(page.locator('.key[aria-label="▲"]').count(), 0)
            sent.clear()
            press(page, '.key[aria-label="fn"]', 6)
            press(page, '.key[aria-label="1"]', 7)
            press(page, '.key[aria-label="fn"]', 8)
            press(page, '.key[aria-label="I"]', 9)
            page.wait_for_timeout(400)
            typed = [key["key"] for batch in sent for key in batch.get("keys", [])]
            self.assertEqual(typed, ["f1", "up"])
            page.click("#lock-now")
            self.assertTrue(locked())
            page.click("#skin")  # Classic: no lock, the keys work at once
            self.assertFalse(page.evaluate("document.body.classList.contains('holo')"))
            sent.clear()
            press(page, '.key[aria-label="B"]', 5)
            page.wait_for_timeout(400)
            self.assertEqual(sent, [{"keys": [{"key": "b", "mods": []}]}])
            self.assertEqual(page.locator('.key[aria-label="F1"]').count(), 1)  # Classic keeps the full keyboard
            browser.close()


if __name__ == "__main__":
    unittest.main()
