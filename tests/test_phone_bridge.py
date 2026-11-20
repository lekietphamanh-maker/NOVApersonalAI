"""Nova Lite's server: pairing token required, chat, approvals answered on the phone, buttons."""
from __future__ import annotations

import io
import json
import os
import ssl
import tempfile
import wave
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from phone_bridge import PhoneBridge


class PhoneBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = patch.dict(os.environ, {"ALFRED_DATA_DIR": tempfile.mkdtemp()})
        self.data.start()
        self.approvals: list[bool] = []

        def ask(text: str, approve) -> str:
            if text == "save a task":
                self.approvals.append(approve("add_task", {"task": "Buy milk"}))
                return "Saved." if self.approvals[-1] else "Not saved."
            return f"You said: {text}"

        self.controls: list[str] = []
        self.heard: list[bytes] = []
        self.screen_asks: list[tuple[str, str]] = []
        self.typed: list[dict] = []

        def keyboard(request: dict) -> str:
            if request.get("keys") == "boom":
                raise ValueError("No 'boom' key on the deck.")
            self.typed.append(request)
            return ""
        self.bridge = PhoneBridge(ask, lambda action: self.controls.append(action) or "",
                                  transcribe=lambda pcm: self.heard.append(pcm) or "what time is it",
                                  screen_state=lambda music, slide: self.screen_asks.append((music, slide)) or {"mode": "speak"},
                                  keyboard=keyboard)
        self.setup_url = self.bridge.start(host="127.0.0.1", port=0, setup_port=0)
        self.base = self.bridge.app_url().split("/#")[0]
        # Only Nova's own authority is trusted: this proves the phone can verify the connection.
        from local_tls import folder
        self.tls = ssl.create_default_context(cafile=str(folder() / "ca.crt"))

    def tearDown(self) -> None:
        self.bridge.stop()
        self.data.stop()

    def call(self, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
        request = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                          headers={"Authorization": f"Bearer {self.bridge.token if token is None else token}",
                                   "Content-Type": "application/json"}, method="POST" if body is not None else "GET")
        try:
            with urlopen(request, timeout=10, context=self.tls) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_everything_needs_the_pairing_token(self) -> None:
        self.assertEqual(self.call("/api/hello", token="wrong")[0], 401)
        self.assertEqual(self.call("/api/chat", {"text": "hi"}, token="")[0], 401)
        self.assertEqual(self.call("/api/control", {"action": "next"}, token="wrong")[0], 401)
        self.assertEqual(self.controls, [])
        self.assertEqual(self.call("/api/hello"), (200, {"ok": True}))

    def test_pairing_link_carries_the_token_in_the_fragment(self) -> None:
        self.assertTrue(self.bridge.app_url().startswith("https://127.0.0.1:"))
        self.assertTrue(self.bridge.app_url().endswith(f"/#token={self.bridge.token}"))
        self.assertIn(f"/setup#token={self.bridge.token}&app=", self.bridge.pairing_url())
        old = self.bridge.token
        self.bridge.new_pairing()
        self.assertNotEqual(self.bridge.token, old)
        self.assertEqual(self.call("/api/hello", token=old)[0], 401)

    def test_chat_and_buttons(self) -> None:
        self.assertEqual(self.call("/api/chat", {"text": "hello"}), (200, {"reply": "You said: hello"}))
        self.call("/api/control", {"action": "next"})
        self.assertEqual(self.controls, ["next"])

    def test_approval_is_answered_on_the_phone(self) -> None:
        replies: list = []
        worker = threading.Thread(target=lambda: replies.append(self.call("/api/chat", {"text": "save a task"})))
        worker.start()
        for _ in range(50):
            status, pending = self.call("/api/pending")
            if pending:
                break
            time.sleep(0.1)
        self.assertEqual(pending["summary"], "Save this task?\n\nBuy milk")
        self.call("/api/answer", {"id": "not-the-id", "approved": True})  # ignored
        self.call("/api/answer", {"id": pending["id"], "approved": True})
        worker.join(timeout=10)
        self.assertEqual(replies, [(200, {"reply": "Saved."})])
        self.assertEqual(self.approvals, [True])
        self.assertEqual(self.call("/api/pending"), (200, {}))

    def test_the_app_page_is_served_without_the_token(self) -> None:
        with urlopen(self.base + "/", timeout=10, context=self.tls) as response:
            self.assertIn(b"<title>Nova Lite</title>", response.read())
        with urlopen(self.base + "/icon.png", timeout=10, context=self.tls) as response:
            self.assertEqual(response.headers["Content-Type"], "image/png")
        with self.assertRaises(HTTPError):
            urlopen(self.base + "/../phone_bridge.py", timeout=10, context=self.tls)

    def test_the_hud_orb_and_its_fonts_reach_the_other_screens_and_nothing_else(self) -> None:
        with urlopen(self.base + "/core.js", timeout=10, context=self.tls) as response:
            self.assertEqual(response.headers["Content-Type"], "text/javascript")
            self.assertIn(b"export function createCore", response.read())
        setup = self.setup_url.split("/setup")[0]  # the TV's plain-HTTP server
        with urlopen(setup + "/core.js", timeout=10) as response:
            self.assertIn(b"createCore", response.read())
        with urlopen(setup + "/fonts/rajdhani-latin-600-normal.woff2", timeout=10) as response:
            self.assertEqual(response.headers["Content-Type"], "font/woff2")
        for other in ("/app.js", "/index.html", "/fonts/../core.js", "/fonts/OFL-Rajdhani.txt"):
            with self.subTest(other), self.assertRaises(HTTPError):
                urlopen(setup + other, timeout=10)

    def test_the_deck_keyboard_types_only_for_the_paired_device(self) -> None:
        self.assertEqual(self.call("/api/deck", {"keys": [{"key": "a", "mods": []}]}, token="wrong")[0], 401)
        self.assertEqual(self.call("/api/deck", {"keys": [{"key": "c", "mods": ["ctrl"]}]}), (200, {"message": ""}))
        self.assertEqual(self.call("/api/deck", {"text": "Xin chào"}), (200, {"message": ""}))
        self.assertEqual(self.typed, [{"keys": [{"key": "c", "mods": ["ctrl"]}]}, {"text": "Xin chào"}])
        self.assertEqual(self.call("/api/deck", {"keys": "boom"}), (200, {"message": "No 'boom' key on the deck."}))

    def test_home_screen_shows_what_the_tv_shows(self) -> None:
        self.assertEqual(self.call("/api/screen?music=abc", token="wrong")[0], 401)
        self.assertEqual(self.call("/api/screen?music=abc&slide=s1"), (200, {"mode": "speak"}))
        self.assertEqual(self.call("/api/screen"), (200, {"mode": "speak"}))
        self.assertEqual(self.screen_asks, [("abc", "s1"), ("", "")])

    def test_setup_page_and_certificate_over_plain_http(self) -> None:
        setup = self.setup_url.split("/setup")[0]
        with urlopen(setup + "/setup", timeout=10) as response:
            self.assertIn(b"Download certificate", response.read())
        with urlopen(setup + "/alfred-ca.crt", timeout=10) as response:
            self.assertEqual(response.headers["Content-Type"], "application/x-x509-ca-cert")
            from cryptography import x509
            ca = x509.load_der_x509_certificate(response.read())
        constraints = ca.extensions.get_extension_for_class(x509.NameConstraints)
        self.assertTrue(constraints.critical)  # it can only vouch for home-network addresses
        with self.assertRaises(HTTPError):
            urlopen(setup + "/index.html", timeout=10)  # the app itself is only served over HTTPS

    def test_voice_from_the_phone(self) -> None:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as recording:
            recording.setnchannels(1)
            recording.setsampwidth(2)
            recording.setframerate(16_000)
            recording.writeframes(b"\x01\x00" * 16_000)
        request = Request(self.base + "/api/voice", data=buffer.getvalue(), method="POST",
                          headers={"Authorization": f"Bearer {self.bridge.token}", "Content-Type": "audio/wav"})
        with urlopen(request, timeout=10, context=self.tls) as response:
            self.assertEqual(json.load(response), {"text": "what time is it"})
        self.assertEqual(len(self.heard[0]), 32_000)
        wrong = Request(self.base + "/api/voice", data=buffer.getvalue(), method="POST",
                        headers={"Authorization": "Bearer nope", "Content-Type": "audio/wav"})
        with self.assertRaises(HTTPError):
            urlopen(wrong, timeout=10, context=self.tls)


if __name__ == "__main__":
    unittest.main()
