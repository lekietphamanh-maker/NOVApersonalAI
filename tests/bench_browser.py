"""Shared by the browser tests of the circuit bench and Building mode: Edge (Windows) or a Chromium with software WebGL,
serving Nova's ui/ folder and a few test pages from memory (no server, no ports)."""
from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path
from typing import Any, Iterator
import unittest

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
TYPES = {".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".woff2": "font/woff2", ".svg": "image/svg+xml",
         ".json": "application/json"}
GL_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
ORIGIN = "http://nova.test"


@contextlib.contextmanager
def browser_page(pages: dict[str, str], held: list[Any] | None = None, hold: dict[str, Any] | None = None) -> Iterator[tuple[Any, list[str]]]:
    """A page serving ui/ and `pages` ({"/name.html": html}); a request for hold["path"] is kept back in `held` while
    hold["on"] is set (so a test can decide when it finishes)."""
    from playwright.sync_api import sync_playwright

    if sys.platform != "win32" and not os.environ.get("NOVA_BROWSER"):
        os.environ["NOVA_BROWSER"] = "/opt/pw-browsers/chromium"

    def answer(route: Any) -> None:
        path = route.request.url.split("nova.test", 1)[1].split("?")[0].split("#")[0]
        if path in pages:
            route.fulfill(body=pages[path], content_type="text/html")
            return
        if hold and held is not None and hold.get("on") and path == hold.get("path"):
            held.append(route)
            return
        target = (UI / path.lstrip("/")).resolve()
        if UI.resolve() in target.parents and target.is_file():
            route.fulfill(body=target.read_bytes(), content_type=TYPES.get(target.suffix, "application/octet-stream"))
        else:
            route.fulfill(status=404)

    with sync_playwright() as playwright:
        path = os.environ.get("NOVA_BROWSER")
        browser = (playwright.chromium.launch(executable_path=path, headless=True, args=GL_ARGS) if path
                   else playwright.chromium.launch(channel="msedge", headless=True, args=GL_ARGS))
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            problems: list[str] = []
            page.on("pageerror", lambda error: problems.append(f"pageerror: {error}"))
            page.on("console", lambda message: problems.append(message.text) if message.type == "error" else None)
            page.set_default_timeout(60000)  # 3D scenes drawn in software on a busy machine
            page.route(f"{ORIGIN}/**", answer)
            yield page, problems
        finally:
            browser.close()


def skip_without_webgl(test: unittest.TestCase, page: Any) -> None:
    if not page.evaluate("!!document.createElement('canvas').getContext('webgl2')"):
        test.skipTest("this browser has no WebGL")
