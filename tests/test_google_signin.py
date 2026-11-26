"""Google sign-in's page back on this PC tells the truth: a refusal says it didn't finish, and a stray request (a
favicon, another program) doesn't end the wait for Google's real answer."""
from __future__ import annotations

import threading
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

import gmail_tools


class SignInPageTests(unittest.TestCase):
    def sign_in(self, visits) -> tuple[list[object], str]:
        """Runs connect() with a stand-in browser that opens `visits(state)` on Nova's loopback page, in order."""
        pages: list[object] = []
        visitors: list[threading.Thread] = []

        def browser(url: str) -> bool:
            query = parse_qs(urlsplit(url).query)
            redirect, state = query["redirect_uri"][0], query["state"][0]

            def visit() -> None:
                for path in visits(state):
                    try:
                        with urlopen(redirect + path, timeout=5) as response:
                            pages.append(response.read().decode())
                    except HTTPError as error:
                        pages.append(error.code)
            visitors.append(threading.Thread(target=visit, daemon=True))
            visitors[-1].start()
            return True

        with mock.patch.object(gmail_tools, "_client", return_value={"client_id": "id"}), \
                mock.patch.object(gmail_tools.webbrowser, "open", browser), \
                mock.patch.object(gmail_tools, "_post_form", return_value={}):
            with self.assertRaises(RuntimeError) as raised:
                gmail_tools.connect(timeout=10)
        for visitor in visitors:
            visitor.join(10)  # the browser reads the page after Nova has already moved on
        return pages, str(raised.exception)

    def test_saying_no_is_not_called_connected(self) -> None:
        pages, error = self.sign_in(lambda state: [f"/?error=access_denied&state={state}"])
        self.assertIn("cancelled", error)
        self.assertIn("didn't finish", pages[0])

    def test_a_stray_request_does_not_end_the_wait(self) -> None:
        pages, error = self.sign_in(lambda state: ["/favicon.ico", f"/?state={state}&code=abc"])
        self.assertEqual(pages[0], 404)
        self.assertIn("Google said yes", pages[1])
        self.assertIn("refresh token", error)  # the code was taken and exchanged (the stand-in sends no token back)


if __name__ == "__main__":
    unittest.main()
