"""Nova's Gmail and Google Drive for the owner's own Claude apps (Claude Code, Claude Desktop) as an MCP server.

Off until the owner turns it on in Settings. Then Nova serves an MCP endpoint on this PC only (127.0.0.1, a fixed port
so the Claude apps' settings keep working) behind a long random key kept in Nova's folder. The tools are the same as
Nova's own: list and read unread mail, save drafts (never send), search, list and read Drive files (read-only). The
Claude app asks the owner before each tool call, so Nova doesn't ask again.

Claude Code connects straight to it (`claude mcp add --transport http`). Claude Desktop only starts local programs, so
it goes through mcp-remote (Node.js), pinned, with the key in a headers file rather than on the command line.
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Callable

from drive_tools import DRIVE_TOOL_NAMES, DRIVE_TOOLS, execute_drive_tool
from nova_mcp import ToolServer

SERVER_NAME = "nova-google"
PORT = 47821
MCP_REMOTE = "mcp-remote@0.16.0"  # pinned: Claude Desktop runs it with npx


def _folder() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Alfred"


def key_path() -> Path:
    return _folder() / "google_mcp_key"


def headers_path() -> Path:
    return _folder() / "google_mcp_headers.txt"


def key() -> str:
    """The key the Claude apps send; made once, so their settings keep working after Nova restarts."""
    path = key_path()
    try:
        secret = path.read_text(encoding="utf-8").strip()
    except OSError:
        secret = ""
    if len(secret) < 32:
        path.parent.mkdir(parents=True, exist_ok=True)
        secret = secrets.token_urlsafe(32)
        path.write_text(secret, encoding="utf-8")
    headers = f"Authorization: Bearer {secret}\n"
    if not headers_path().is_file() or headers_path().read_text(encoding="utf-8") != headers:
        headers_path().write_text(headers, encoding="utf-8")
    return secret


def new_key() -> str:
    """A new key: every Claude app set up with the old one is shut out until it gets the new one."""
    key_path().unlink(missing_ok=True)
    return key()


def url(port: int = PORT) -> str:
    return f"http://127.0.0.1:{port}/mcp"


def claude_code_command(secret: str, port: int = PORT) -> str:
    return (f'claude mcp add --transport http --scope user {SERVER_NAME} {url(port)} '
            f'--header "Authorization: Bearer {secret}"')


def claude_desktop_config(port: int = PORT) -> dict[str, Any]:
    """The entry for claude_desktop_config.json (the key stays in the headers file, out of the config)."""
    return {"mcpServers": {SERVER_NAME: {"command": "npx", "args": [
        "-y", MCP_REMOTE, url(port), "--header-file", str(headers_path())]}}}


def tools(gmail_tools: list[dict[str, Any]], gmail: bool, drive: bool) -> list[dict[str, Any]]:
    return [*(gmail_tools if gmail else []), *(DRIVE_TOOLS if drive else [])]


class GoogleMcp:
    """gmail() / drive() give the connected services (None when that part of Google isn't connected)."""

    def __init__(self, gmail: Callable[[], Any], drive: Callable[[], Any], port: int = PORT) -> None:
        self.gmail, self.drive, self.port = gmail, drive, port
        self.server: ToolServer | None = None

    @property
    def running(self) -> bool:
        return self.server is not None

    def start(self) -> None:
        """Raises OSError when the port is taken (another Nova, or another program)."""
        from tools import GMAIL_TOOLS
        if self.server is None:
            self.server = ToolServer(self.port, SERVER_NAME)
        offered = tools(GMAIL_TOOLS, self.gmail() is not None, self.drive() is not None)
        self.server.open(offered, self.run, key())

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server = None

    def run(self, name: str, arguments: dict[str, Any]) -> str:
        from tools import _invalid_arguments, execute_gmail_tool
        problem = _invalid_arguments(name, arguments)
        if problem:
            return problem
        if name in DRIVE_TOOL_NAMES:
            return execute_drive_tool(name, arguments, self.drive())
        return execute_gmail_tool(name, arguments, lambda *_: True, self.gmail())  # the Claude app asked the owner


def setup_text(secret: str, port: int = PORT) -> dict[str, str]:
    return {"url": url(port), "claude_code": claude_code_command(secret, port),
            "claude_desktop": json.dumps(claude_desktop_config(port), indent=2)}
