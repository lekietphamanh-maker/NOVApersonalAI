"""Creative mode's real page in a real browser, served by Nova's own CreativeServer, with the browser's stand-in camera:
the page loads (one missing export stopped it for days in v2.15), the camera starts, and Nova's commands reach it.
(Edge on Windows, Chromium elsewhere.)"""
from __future__ import annotations

import os
import sys
import unittest

import creative_mode
from tests.bench_browser import GL_ARGS
from tests.test_web_tasks import _browser_available

CAMERA_ARGS = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"]


@unittest.skipUnless(_browser_available(), "needs Playwright and Edge (Windows) or a Chromium")
class CreativePageTests(unittest.TestCase):
    def test_the_page_loads_starts_the_camera_and_follows_nova(self) -> None:
        from playwright.sync_api import sync_playwright

        server = creative_mode.CreativeServer()
        self.addCleanup(server.stop)
        url = server.start()
        path = os.environ.get("NOVA_BROWSER") or (None if sys.platform == "win32" else "/opt/pw-browsers/chromium")
        with sync_playwright() as playwright:
            options = {"headless": True, "args": GL_ARGS + CAMERA_ARGS}
            browser = (playwright.chromium.launch(executable_path=path, **options) if path
                       else playwright.chromium.launch(channel="msedge", **options))
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 720})
                errors: list[str] = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.set_default_timeout(60000)  # three.js draws in software on a busy runner
                # No tracker models: in software they hold the page for minutes, and a stand-in camera has no hands to
                # find. Their failure must still leave a working page (the mouse moves the holograms).
                page.route("**/vendor/models/**", lambda route: route.abort())
                page.goto(url)
                self.assertEqual(errors, [])  # a module that fails to load says so before the load event
                page.wait_for_function("window.creative && document.getElementById('camera').videoWidth > 0")
                self.assertTrue(page.locator("#camera-error").is_hidden())
                page.wait_for_function("window.creative.trackingError !== null")
                before = page.evaluate("window.creative.objects.length")
                server.send({"action": "add", "shape": "cube"})
                page.wait_for_function(f"window.creative.objects.length > {before}")
                server.send({"action": "hand_music", "on": True})
                page.wait_for_function("!document.getElementById('handmusic-panel').hidden")
                self.assertTrue(server.active)
                self.assertEqual(errors, [])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
