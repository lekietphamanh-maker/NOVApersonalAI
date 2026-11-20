"""Nova's own browser, out of sight: web addresses only, the tool's rules, and a real run (Edge on Windows CI, any
Chromium given in NOVA_BROWSER elsewhere) on a little local site: read, fill a form by its labels, submit, go back."""
from __future__ import annotations

import functools
import http.server
import importlib.util
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from tools import execute_tool
from web_tasks import WebBrowser, web_address

SITE = {
    "index.html": """<!doctype html><html><head><title>Shop Test</title></head><body>
<h1>Laptop deals</h1><p>The Aero 14 costs $899 this week.</p><a href="/second.html">More deals</a>
<form action="/thanks.html" method="get"><label for="q">Your email</label><input id="q" name="email">
<label for="size">Size</label><select id="size" name="size"><option>Small</option><option>Large</option></select>
<label><input type="checkbox" name="news"> Send me news</label><input type="password" name="pw" aria-label="Secret">
<button type="submit">Sign up</button></form>""" + "<p>filler line</p>" * 900 + "</body></html>",
    "second.html": "<!doctype html><title>Second</title><p>Second page: the Zen 16 is $1,199.</p>",
    "thanks.html": "<!doctype html><title>Thanks</title><p>Thanks! You are signed up.</p>",
}


class FakeWeb:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __getattr__(self, action: str):
        return lambda *args: self.calls.append((action, *args)) or f"page after {action}"


class RulesTests(unittest.TestCase):
    def test_only_web_pages_open(self) -> None:
        self.assertEqual(web_address("example.com/deals"), "https://example.com/deals")
        self.assertEqual(web_address("http://127.0.0.1:8765/a"), "http://127.0.0.1:8765/a")
        self.assertEqual(web_address("shop.example.com:8080/x"), "https://shop.example.com:8080/x")
        for bad in ("file:///C:/Windows/win.ini", "javascript:alert(1)", "ftp://x.org", "https://", "mailto:a@b.c",
                    "https://x.org:abc/"):
            with self.assertRaises(ValueError, msg=bad):
                web_address(bad)

    def test_the_tool_reads_freely_and_asks_through_approve_before_changing_a_page(self) -> None:
        web, asked = FakeWeb(), []
        run = lambda arguments, answer=True: execute_tool("web", arguments, None,  # noqa: E731
                                                          lambda name, details: asked.append(details["summary"]) or answer, web=web)
        self.assertEqual(run({"action": "open", "target": "example.com"}), "page after open")
        self.assertEqual(run({"action": "read", "part": 2}), "page after read")
        self.assertEqual(asked, [])  # reading never asks
        self.assertEqual(run({"action": "fill", "target": "Your email", "text": "me@example.com"}), "page after fill")
        self.assertIn("declined", run({"action": "click", "target": "Sign up"}, answer=False))
        self.assertEqual(asked, ["On a web page in Nova's own browser: put “me@example.com” in Your email",
                                 "On a web page in Nova's own browser: click Sign up"])
        self.assertIn("needs a target", run({"action": "open"}))
        self.assertIn("not done", run({"action": "open", "target": "file:///etc/passwd"}).lower())
        self.assertIn("needs Microsoft Edge", execute_tool("web", {"action": "back"}, None, lambda *_: True))


def _browser_available() -> bool:
    if importlib.util.find_spec("playwright") is None:
        return False
    return sys.platform == "win32" or bool(os.environ.get("NOVA_BROWSER")) or Path("/opt/pw-browsers/chromium").exists()


@unittest.skipUnless(_browser_available(), "needs Playwright and Edge (Windows) or a Chromium")
class RealBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if sys.platform != "win32" and not os.environ.get("NOVA_BROWSER"):
            os.environ["NOVA_BROWSER"] = "/opt/pw-browsers/chromium"
        folder = Path(tempfile.mkdtemp())
        for name, page in SITE.items():
            (folder / name).write_text(page, encoding="utf-8")
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(folder))
        http.server.SimpleHTTPRequestHandler.log_message = lambda *_args: None
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.site = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.web = WebBrowser()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.web.close()
        cls.server.shutdown()

    def test_read_fill_submit_go_back_and_follow_a_link(self) -> None:
        page = self.web.open(f"{self.site}/index.html")
        print(page[:400])
        self.assertIn('WEB PAGE "Shop Test"', page)
        self.assertIn("The Aero 14 costs $899", page)
        self.assertIn('[2] field "Your email"', page)
        self.assertIn('checkbox "Send me news"', page)
        self.assertNotIn("Secret", page)  # password fields are never offered
        self.assertIn("read part 2 for more", page)  # a long page comes in parts
        self.assertIn("(part 2 of", self.web.read(2))
        for target, text in (("Your email", "me@example.com"), ("Size", "Large"), ("Send me news", "yes")):
            self.assertTrue(self.web.fill(target, text).startswith("WEB PAGE"), target)
        done = self.web.click("Sign up")
        self.assertIn("Thanks! You are signed up.", done)
        self.assertIn("email=me%40example.com&size=Large&news=on", done)
        self.assertIn('"Shop Test"', self.web.back())
        self.assertIn("the Zen 16 is $1,199", self.web.click("1"))
        self.assertIn("Couldn't do that on the page", self.web.click("Nothing called this anywhere"))


if __name__ == "__main__":
    unittest.main()
