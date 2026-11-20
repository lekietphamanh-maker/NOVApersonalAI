"""Serves Nova's HUD (ui/) on loopback, streams state to it (server-sent events) and takes its actions.

Every API call needs this run's random token, and the Host header must be loopback, so web pages
open in the user's browser cannot drive Nova (no CSRF, no DNS rebinding).
"""
from __future__ import annotations

import hmac
import collections
import json
import queue
import secrets
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

PREFERRED_PORT = 8770
PING_SECONDS = 2.0
MAX_ACTION_BYTES = 4_000_000  # an action can carry a photo slid onto the TV (up to 3 MB as a data URL)


def ui_folder() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "ui"


class _Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript", ".css": "text/css",
                      ".html": "text/html", ".woff2": "font/woff2", ".svg": "image/svg+xml", ".png": "image/png"}

    def __init__(self, *args, server_state: "UiServer", **kwargs) -> None:
        self.server_state = server_state
        super().__init__(*args, **kwargs)

    def log_message(self, *_args) -> None:
        pass  # the windowed app has no console

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.path.split("?")[0] in ("/", "/index.html"):
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                             "frame-src http://127.0.0.1:*; connect-src 'self'; object-src 'none'; base-uri 'none'")
        super().end_headers()

    def _loopback_host(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _json(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        self.server_state.requests.append(self.path.split("?")[0].split("#")[0][:60])  # the smoke test says what came
        if not self._loopback_host():
            self.send_error(403)
            return
        url = urlsplit(self.path)
        if url.path == "/api/show":
            # A second Nova start asks this one to show its window instead (harmless, so no token).
            if self.server_state.on_show is not None:
                self.server_state.on_show()
            from build_info import BUILD
            self._json(200, {"ok": True, "app": "alfred", "build": BUILD})
            return
        if url.path == "/api/events":
            token = parse_qs(url.query).get("token", [""])[0]
            if not hmac.compare_digest(token, self.server_state.token):
                self._json(401, {"error": "not paired"})
                return
            self._stream()
            return
        if url.path.startswith("/api/"):
            self.send_error(404)
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if (urlsplit(self.path).path == "/api/replace" and self._loopback_host()
                and self.headers.get("Content-Type") == "application/json"):
            # A newer Nova is starting: this one quits so the new one takes over. JSON only, so a web page
            # elsewhere can't trigger it without a CORS preflight (never answered).
            if self.server_state.on_replace is not None:
                self.server_state.on_replace()  # before answering: the new Nova waits for the port to free up
            self._json(200, {"ok": True})
            return
        if not self._loopback_host() or urlsplit(self.path).path != "/api/action":
            self.send_error(403)
            return
        if not hmac.compare_digest(self.headers.get("X-Nova-Token", ""), self.server_state.token):
            self._json(401, {"error": "not paired"})
            return
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), MAX_ACTION_BYTES)))
            name, args = str(body["name"]), body.get("args") or {}
            if not isinstance(args, dict):
                raise ValueError("args must be an object")
        except (ValueError, KeyError, TypeError):
            self._json(400, {"error": "bad request"})
            return
        try:
            self._json(200, self.server_state.on_action(name, args) or {"ok": True})
        except Exception as exc:  # report it to the page instead of dropping the connection
            self._json(200, {"ok": False, "error": str(exc)})

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        client = self.server_state.add_client()
        try:
            while True:
                try:
                    event = client.get(timeout=PING_SECONDS)
                    data = f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    data = ": ping\n\n"  # also how a closed window is noticed: the write fails
                self.wfile.write(data.encode())
                self.wfile.flush()
        except OSError:
            pass
        finally:
            self.server_state.remove_client(client)


class UiServer:
    def __init__(self, on_action: Callable[[str, dict[str, Any]], dict[str, Any] | None],
                 snapshot: Callable[[], dict[str, Any]], lock: threading.RLock | None = None) -> None:
        self.on_action = on_action
        self.snapshot = snapshot
        self.token = secrets.token_urlsafe(24)
        self._clients: list[queue.Queue] = []
        # Shared with the owner of the state, so a change and its event can't interleave with a snapshot.
        self._lock = lock or threading.RLock()
        self._httpd: ThreadingHTTPServer | None = None
        self.ever_connected = threading.Event()
        self.requests: collections.deque[str] = collections.deque(maxlen=40)
        self.on_replace: Callable[[], None] | None = None
        self.on_show: Callable[[], None] | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._httpd.server_address[1]}/#token={self.token}"

    @property
    def clients(self) -> int:
        with self._lock:
            return len(self._clients)

    def start(self, port: int = PREFERRED_PORT) -> str:
        if self._httpd is None:
            handler = partial(_Handler, directory=str(ui_folder()), server_state=self)
            try:
                self._httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
            except OSError:
                self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            self._httpd.daemon_threads = True
            threading.Thread(target=self._httpd.serve_forever, name="AlfredUi", daemon=True).start()
        return self.url

    def add_client(self) -> queue.Queue:
        client: queue.Queue = queue.Queue(maxsize=2000)
        with self._lock:  # the snapshot and later events reach the page in order
            client.put({"type": "snapshot", **self.snapshot()})
            self._clients.append(client)
        self.ever_connected.set()
        return client

    def remove_client(self, client: queue.Queue) -> None:
        with self._lock:
            if client in self._clients:
                self._clients.remove(client)

    def emit(self, event: dict[str, Any]) -> None:
        with self._lock:
            for client in self._clients:
                try:
                    client.put_nowait(event)
                except queue.Full:
                    pass  # a stuck page; it gets a fresh snapshot when it reconnects

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
