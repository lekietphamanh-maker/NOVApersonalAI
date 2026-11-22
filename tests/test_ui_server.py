"""HUD server: token and loopback Host required, the page gets a snapshot then live events, actions reach Nova."""
from __future__ import annotations

import http.client
import json
import threading
import unittest

from ui_server import UiServer


class UiServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.actions: list[tuple[str, dict]] = []
        self.server = UiServer(on_action=lambda name, args: self.actions.append((name, args)) or {"ok": True, "echo": name},
                               snapshot=lambda: {"state": {"busy": False}, "chat": []})
        self.server.start(port=0)
        self.port = int(self.server.url.split(":")[2].split("/")[0])

    def tearDown(self) -> None:
        self.server.stop()

    def request(self, method: str, path: str, body: dict | None = None, token: str | None = None,
                host: str | None = None) -> tuple[int, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": host or f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
        if token is not None:
            headers["X-Nova-Token"] = token
        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        response = connection.getresponse()
        return response.status, response.read()

    def test_actions_need_the_token_and_a_loopback_host(self) -> None:
        # A wrong token with a body, several times over: answering 401 without reading the body
        # used to reset the connection on Windows, so the client saw an aborted connection.
        for _ in range(10):
            self.assertEqual(self.request("POST", "/api/action", {"name": "send"}, token="wrong")[0], 401)
        self.assertEqual(self.request("POST", "/api/action", {"name": "send"})[0], 401)
        self.assertEqual(self.request("POST", "/api/action", {"name": "send"}, self.server.token, host="evil.example:80")[0], 403)
        self.assertEqual(self.actions, [])
        status, body = self.request("POST", "/api/action", {"name": "send", "args": {"text": "hi"}}, self.server.token)
        self.assertEqual((status, json.loads(body)), (200, {"ok": True, "echo": "send"}))
        self.assertEqual(self.actions, [("send", {"text": "hi"})])

    def test_the_server_queues_a_cold_browsers_burst_of_requests(self) -> None:
        # A cold browser asks for the page, its CSS, fonts and scripts all at once; the default
        # listen backlog of 5 turns some of those connections away before the server sees them.
        self.assertGreaterEqual(self.server._httpd.request_queue_size, 32)

    def test_page_is_served_with_a_content_security_policy(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("GET", "/", headers={"Host": f"127.0.0.1:{self.port}"})
        response = connection.getresponse()
        self.assertIn(b"<title>Nova</title>", response.read())
        self.assertIn("script-src", response.headers["Content-Security-Policy"].replace("default-src 'self'", "script-src"))
        self.assertEqual(self.request("GET", "/../ui_server.py")[0], 404)
        self.assertEqual(self.request("GET", "/api/events?token=wrong")[0], 401)

    def test_event_stream_starts_with_a_snapshot_then_live_events(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("GET", f"/api/events?token={self.server.token}", headers={"Host": f"127.0.0.1:{self.port}"})
        response = connection.getresponse()
        self.assertEqual(response.headers["Content-Type"], "text/event-stream")

        def next_event() -> dict:
            while True:
                line = response.fp.readline().decode()
                if line.startswith("data: "):
                    return json.loads(line[6:])

        self.assertEqual(next_event(), {"type": "snapshot", "state": {"busy": False}, "chat": []})
        self.assertTrue(self.server.ever_connected.is_set())
        threading.Timer(0.2, lambda: self.server.emit({"type": "state", "patch": {"busy": True}})).start()
        self.assertEqual(next_event(), {"type": "state", "patch": {"busy": True}})
        self.assertEqual(self.server.clients, 1)
        connection.close()

    def test_a_newer_build_can_replace_this_one_but_a_web_form_cannot(self) -> None:
        replaced = []
        self.server.on_replace = lambda: replaced.append(True)
        status, body = self.request("GET", "/api/show")
        self.assertEqual(status, 200)
        self.assertIn("build", json.loads(body))
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("POST", "/api/replace", body="x", headers={"Host": f"127.0.0.1:{self.port}", "Content-Type": "text/plain"})
        connection.getresponse().read()
        self.assertEqual(replaced, [])
        self.assertEqual(self.request("POST", "/api/replace", {})[0], 200)
        self.assertEqual(replaced, [True])


if __name__ == "__main__":
    unittest.main()
