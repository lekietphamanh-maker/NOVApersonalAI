"""Nova on other screens: a TV pairs with a code the owner allows and can then only read what Nova shows; the deck
needs Nova Lite's pairing and only has its fixed buttons."""
from __future__ import annotations

import json
import os
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import screens
from phone_bridge import PhoneBridge


def call(url: str, method: str = "GET", token: str = "", body: dict | None = None, context=None) -> tuple[int, dict | str]:
    request = Request(url, data=json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None),
                      method=method, headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urlopen(request, timeout=10, context=context) as response:
            text = response.read().decode()
            return response.status, (json.loads(text) if response.headers.get("Content-Type", "").startswith("application/json") else text)
    except HTTPError as error:
        return error.code, {}


class PairingTests(unittest.TestCase):
    def test_a_tv_gets_a_token_only_after_the_owner_allows_its_code(self) -> None:
        path = Path(tempfile.mkdtemp()) / "screens.json"
        asked: list[str] = []
        pairing = screens.ScreenPairing(path, on_request=asked.append)
        hello = pairing.hello()
        self.assertEqual(asked, [hello["code"]])
        self.assertEqual(pairing.status(hello["session"]), {"approved": False})
        self.assertFalse(pairing.allow("0000" if hello["code"] != "0000" else "1111"))
        self.assertTrue(pairing.allow(hello["code"]))
        answer = pairing.status(hello["session"])
        self.assertTrue(answer["approved"])
        self.assertTrue(screens.ScreenPairing(path).allowed(answer["token"]))  # kept across restarts
        self.assertEqual(pairing.status(hello["session"])["approved"], False)  # the token is handed over once
        pairing.forget_all()
        self.assertFalse(pairing.allowed(answer["token"]))
        self.assertFalse(pairing.allowed(""))

    def test_slides_and_deck_buttons_are_checked(self) -> None:
        slide = screens.slide_payload("script", "  A   title ", "body", "javascript:alert(1)")
        self.assertEqual((slide["kind"], slide["title"], slide["image"]), ("text", "A title", ""))
        self.assertTrue(screens.slide_payload("image", image="data:image/png;base64,AAAA")["image"])
        from screen_assist import send_keys_spec
        for action, (kind, what) in screens.DECK_ACTIONS.items():
            self.assertIn(kind, ("media", "keys", "app", "nova"), action)
            if kind == "keys":
                self.assertTrue(send_keys_spec(what), action)


class ScreenServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = patch.dict(os.environ, {"ALFRED_DATA_DIR": tempfile.mkdtemp()})
        self.data.start()
        self.pressed: list[str] = []
        self.pairing = screens.ScreenPairing(Path(tempfile.mkdtemp()) / "screens.json")
        self.bridge = PhoneBridge(lambda text, approve: "ok", lambda action: "", screens=self.pairing,
                                  screen_state=lambda music, slide: {"mode": "speak", "caption": "Hello", "known": [music, slide]},
                                  deck=lambda action: self.pressed.append(action) or "done")
        self.bridge.start(host="127.0.0.1", port=0, setup_port=0)
        self.tv = self.bridge.tv_url().rsplit("/tv", 1)[0]
        self.app = self.bridge.app_url().split("/#")[0]
        from local_tls import folder
        self.tls = ssl.create_default_context(cafile=str(folder() / "ca.crt"))

    def tearDown(self) -> None:
        self.bridge.stop()
        self.data.stop()

    def test_the_tv_page_pairs_and_then_reads_only_the_screen(self) -> None:
        status, page = call(f"{self.tv}/tv")
        self.assertEqual(status, 200)
        self.assertIn("Nova · TV", page)
        self.assertEqual(call(f"{self.tv}/api/screen")[0], 401)
        _, hello = call(f"{self.tv}/api/tv/hello", "POST")
        self.assertEqual(call(f"{self.tv}/api/tv/status?session={hello['session']}")[1], {"approved": False})
        self.pairing.allow(hello["code"])
        _, answer = call(f"{self.tv}/api/tv/status?session={hello['session']}")
        status, screen = call(f"{self.tv}/api/screen?music=song&slide=s1", token=answer["token"])
        self.assertEqual((status, screen["caption"], screen["known"]), (200, "Hello", ["song", "s1"]))
        # The TV's code is read-only: it can't chat with Nova or press keys on the PC.
        self.assertEqual(call(f"{self.app}/api/chat", "POST", answer["token"], {"text": "hi"}, self.tls)[0], 401)
        self.assertEqual(call(f"{self.app}/api/deck", "POST", answer["token"], {"action": "copy"}, self.tls)[0], 401)
        self.assertEqual(self.pressed, [])

    def test_the_deck_needs_nova_lites_pairing(self) -> None:
        status, page = call(f"{self.app}/deck", context=self.tls)
        self.assertEqual(status, 200)
        self.assertIn("Nova Deck", page)
        self.assertEqual(call(f"{self.app}/api/deck", "POST", "", {"action": "copy"}, self.tls)[0], 401)
        status, answer = call(f"{self.app}/api/deck", "POST", self.bridge.token, {"action": "copy"}, self.tls)
        self.assertEqual((status, answer["message"], self.pressed), (200, "done", ["copy"]))


if __name__ == "__main__":
    unittest.main()
