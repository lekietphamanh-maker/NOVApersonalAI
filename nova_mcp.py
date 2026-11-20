"""Nova's tools for Claude Code: a tiny MCP server (streamable HTTP, JSON answers) on 127.0.0.1.

While Claude answers on the owner's Claude plan (plan_brain), `claude -p` reaches Nova's tools here, inside Nova's own
process, so they run with Nova's live state (timers, reminders, the second brain, approvals) and no extra program has to
start for each question. Only this PC can connect, and each turn opens with a fresh random token: a request without it
is refused, and when the turn ends the token is gone.
"""
from __future__ import annotations

import hmac
import json
import secrets
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

SERVER_NAME = "nova"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_REQUEST_BYTES = 1_000_000


@dataclass(frozen=True)
class Turn:
    token: str
    tools: list[dict[str, Any]]  # Nova's tool definitions (Ollama's format) offered this turn
    run: Callable[[str, dict[str, Any]], str]


def mcp_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"name": tool["function"]["name"], "description": tool["function"]["description"],
             "inputSchema": tool["function"]["parameters"]} for tool in tools]


def answer(turn: Turn, request: dict[str, Any], name: str = SERVER_NAME) -> dict[str, Any] | None:
    """The JSON-RPC answer to one request, or None for a notification."""
    method, params, request_id = request.get("method"), request.get("params") or {}, request.get("id")
    if request_id is None:
        return None

    def ok(result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    if method == "initialize":
        asked = params.get("protocolVersion")
        return ok({"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": name, "version": "1"}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": mcp_tools(turn.tools)})
    if method == "tools/call":
        name, arguments = str(params.get("name", "")), params.get("arguments") or {}
        offered = {tool["function"]["name"] for tool in turn.tools}
        if name not in offered or not isinstance(arguments, dict):
            text, failed = f"There is no tool called {name}. The tools are: {', '.join(sorted(offered))}.", True
        else:
            try:
                text, failed = str(turn.run(name, arguments)), False
            except Exception as exc:  # a tool's failure goes back to Claude as text, like it does for the API brain
                text, failed = f"Not done: {type(exc).__name__}: {exc}", True
        return ok({"content": [{"type": "text", "text": text}], "isError": failed})
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Unknown method {method}"}}


class _Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets another program bind the same port beside Nova (and hear its requests); off there.
    allow_reuse_address = sys.platform != "win32"


class ToolServer:
    """One per Nova. `open(tools, run)` starts a turn and returns its token; `close()` ends it."""

    def __init__(self, port: int = 0, name: str = SERVER_NAME) -> None:
        self._turn: Turn | None = None
        self.name = name
        self._lock = threading.Lock()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:
                pass

            def _send(self, status: int, body: Any = None) -> None:
                data = json.dumps(body, ensure_ascii=False).encode() if body is not None else b""
                self.send_response(status)
                if body is not None:
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # no server-to-client stream: everything is answered on its POST
                self._send(405)

            def do_DELETE(self) -> None:
                self._send(405)

            def do_POST(self) -> None:
                turn = server.current(self.headers.get("Authorization", ""))
                if turn is None:
                    self._send(401, {"error": "Nova isn't expecting Claude right now."})
                    return
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > MAX_REQUEST_BYTES:
                    self._send(413 if length else 400)
                    return
                try:
                    message = json.loads(self.rfile.read(length))
                except ValueError:
                    self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
                    return
                if isinstance(message, list):
                    answers = [reply for item in message
                               if isinstance(item, dict) and (reply := answer(turn, item, server.name))]
                    self._send(200, answers) if answers else self._send(202)
                    return
                reply = answer(turn, message, server.name) if isinstance(message, dict) else None
                self._send(200, reply) if reply else self._send(202)

        self._http = _Server(("127.0.0.1", port), Handler)
        self._http.daemon_threads = True
        self.url = f"http://127.0.0.1:{self._http.server_address[1]}/mcp"
        threading.Thread(target=self._http.serve_forever, name="NovaToolServer", daemon=True).start()

    def current(self, authorization: str) -> Turn | None:
        with self._lock:
            turn = self._turn
        if turn is None or not hmac.compare_digest(authorization.encode(), f"Bearer {turn.token}".encode()):
            return None
        return turn

    def open(self, tools: list[dict[str, Any]], run: Callable[[str, dict[str, Any]], str], token: str = "") -> str:
        token = token or secrets.token_urlsafe(32)
        with self._lock:
            self._turn = Turn(token, list(tools), run)
        return token

    def close(self, token: str = "") -> None:
        """Ends the turn (with a token: only if it is still that one's, so an older session can't end a newer one)."""
        with self._lock:
            if not token or (self._turn is not None and self._turn.token == token):
                self._turn = None

    def shutdown(self) -> None:
        self.close()
        self._http.shutdown()
        self._http.server_close()
