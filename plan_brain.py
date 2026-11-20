"""Claude on the owner's Claude plan: Nova's online brain through Claude Code (`claude -p`) instead of an API key.

No API credit is spent: Claude Code runs on the subscription the owner already pays for, and counts toward its usage
limits. Nova's tools reach Claude through nova_mcp (a local MCP server inside Nova), so Claude can still set timers,
search the web, add reminders and the rest. Claude Code's own tools are switched off except web search and fetch: it
can't read files, edit them or run commands here. The answer streams back as Claude writes it, so Nova speaks while it
thinks, like with the API.

Every failure becomes cloud_brain.Unavailable, so the AI on this PC answers instead (plan limit reached, not signed in,
offline, Claude Code missing).
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from claude_code import API_KEY_VARIABLES, find
from cloud_brain import DEFAULT_EFFORT, DEFAULT_MODEL, EFFORTS, MODELS, Unavailable
from nova_mcp import SERVER_NAME, ToolServer

# Claude Code's own tools: only web search and fetch exist in the session (--tools), whatever the owner's own settings say.
BUILT_IN_TOOLS = "WebSearch,WebFetch"
ALLOWED_TOOLS = f"mcp__{SERVER_NAME},{BUILT_IN_TOOLS}"
# The owner's claude.ai connectors (Settings → Claude): read and draft, never send, share, change or delete.
CONNECTORS = "mcp__claude_ai_Gmail,mcp__claude_ai_Google_Drive"
CONNECTOR_DENIED = ",".join(
    f"mcp__claude_ai_{server}__{tool}" for server, names in (
        ("Gmail", ("send_message", "send_email", "send_draft", "gmail_send_message", "gmail_send_draft", "delete_message",
                   "trash_message", "gmail_delete_message", "gmail_trash_message", "modify_labels", "gmail_modify_labels")),
        ("Google_Drive", ("create_file", "update_file", "copy_file", "trash_file", "delete_file", "share_file",
                          "request_access", "create_shared_drive", "update_shared_drive")))
    for tool in names)
TURN_TIMEOUT_SECONDS = 10 * 60
LIMIT_WORDS = ("usage limit", "limit reached", "rate limit", "rate_limit", "overloaded", "too many requests", "429")
SIGN_IN_WORDS = ("not logged in", "/login", "log in", "login", "authenticat", "invalid api key", "credential")
OFFLINE_WORDS = ("enotfound", "econnrefused", "econnreset", "etimedout", "network", "getaddrinfo", "unable to connect",
                 "connection error", "fetch failed")


def why_it_failed(text: str) -> Unavailable:
    """Claude Code's error, said the way the owner needs to hear it."""
    lowered = text.lower()
    if any(word in lowered for word in LIMIT_WORDS):
        return Unavailable("your Claude plan's limit is reached for now")
    if any(word in lowered for word in SIGN_IN_WORDS):
        return Unavailable("Claude Code isn't signed in (open a terminal, run claude, and log in once)")
    if any(word in lowered for word in OFFLINE_WORDS):
        return Unavailable("this PC is offline", offline=True)
    last = text.strip().splitlines()[-1:] or ["no answer"]
    return Unavailable(f"Claude Code stopped ({last[0][:160]})")


def text_pieces(event: dict[str, Any], streamed: bool) -> Iterable[str]:
    """The text in one stream-json line. Pieces arrive as partial deltas; whole assistant messages only count when
    no deltas came (an older Claude Code)."""
    kind = event.get("type")
    if kind == "stream_event":
        inner = event.get("event") or {}
        delta = inner.get("delta") or {}
        if inner.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
            yield str(delta.get("text", ""))
    elif kind == "assistant" and not streamed:
        for block in (event.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                yield str(block.get("text", ""))


def _stop(process: subprocess.Popen) -> None:
    """Ends Claude Code and whatever it started (on Windows a .cmd shim starts node, which kill() alone would leave)."""
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        process.kill()


class PlanBrain:
    plan = True  # the agent hands this one a whole turn: Claude Code runs the tool loop itself
    sees_screen = False  # screenshots stay with the API brain or the AI on this PC

    def __init__(self, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT, tools: ToolServer | None = None,
                 command: Callable[[], str | None] = find,
                 start: Callable[..., subprocess.Popen] = subprocess.Popen, connectors: bool = False) -> None:
        self.model = model if model in MODELS else DEFAULT_MODEL
        self.connectors = connectors  # also the owner's claude.ai Gmail and Google Drive (read and draft only)
        self.effort = effort if effort in EFFORTS else DEFAULT_EFFORT
        self.tools = tools
        self.command, self.start = command, start
        self.folder = Path(tempfile.mkdtemp(prefix="nova-plan-"))  # Claude Code's working folder: empty, private

    @property
    def name(self) -> str:
        return f"{MODELS[self.model]} (Claude plan)"

    def arguments(self, command: str, system_file: Path, mcp_file: Path) -> list[str]:
        start = [command, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                 "--model", self.model, "--effort", self.effort,
                 "--system-prompt-file", str(system_file), "--mcp-config", str(mcp_file)]
        if not self.connectors:
            return [*start, "--strict-mcp-config", "--tools", BUILT_IN_TOOLS, "--allowedTools", ALLOWED_TOOLS]
        # claude.ai connectors only load without --strict-mcp-config; any other MCP server the owner set up in Claude Code
        # loads too but can't be used here, because only the tools named in --allowedTools run in -p.
        return [*start, "--tools", BUILT_IN_TOOLS, "--allowedTools", f"{ALLOWED_TOOLS},{CONNECTORS}",
                "--disallowedTools", CONNECTOR_DENIED]

    def turn(self, system: str, prompt: str, tools: list[dict[str, Any]], run: Callable[[str, dict[str, Any]], str],
             on_text: Callable[[str], None], cancel: Any = None) -> str | None:
        """One whole turn: Claude answers `prompt`, using `tools` (run by `run`) as often as it needs. Returns the
        final answer, or None when cancelled. Raises Unavailable when Claude Code couldn't answer."""
        command = self.command()
        if command is None:
            raise Unavailable("Claude Code isn't installed on this PC")
        if self.tools is None:
            self.tools = ToolServer()
        token = self.tools.open(tools, run)
        system_file, mcp_file = self.folder / "system.md", self.folder / "mcp.json"
        system_file.write_text(system, encoding="utf-8")
        mcp_file.write_text(json.dumps({"mcpServers": {SERVER_NAME: {
            "type": "http", "url": self.tools.url, "headers": {"Authorization": f"Bearer {token}"}}}}), encoding="utf-8")
        try:
            return self._run(command, system_file, mcp_file, prompt, on_text, cancel)
        finally:
            self.tools.close()
            mcp_file.unlink(missing_ok=True)

    def _run(self, command: str, system_file: Path, mcp_file: Path, prompt: str, on_text: Callable[[str], None],
             cancel: Any) -> str | None:
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
        on_the_plan = {name: value for name, value in os.environ.items() if name not in API_KEY_VARIABLES}
        try:
            process = self.start(self.arguments(command, system_file, mcp_file), stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                 errors="replace", cwd=str(self.folder), env=on_the_plan, **flags)
        except OSError as exc:
            raise Unavailable(f"Claude Code couldn't start ({exc})") from exc
        lines: queue.Queue[str | None] = queue.Queue()
        errors: list[str] = []
        threading.Thread(target=self._read, args=(process.stdout, lines), daemon=True).start()
        threading.Thread(target=lambda: errors.extend(process.stderr), daemon=True).start()
        try:
            process.stdin.write(prompt)  # through stdin: never on a command line cmd.exe would read
            process.stdin.close()
        except OSError:
            pass
        said: list[str] = []
        result: dict[str, Any] = {}
        streamed = False
        deadline = time.monotonic() + TURN_TIMEOUT_SECONDS
        while True:
            if cancel is not None and cancel.is_set():
                _stop(process)
                return None
            if time.monotonic() > deadline:
                _stop(process)
                raise Unavailable("Claude Code took more than 10 minutes")
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                break
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            streamed = streamed or event.get("type") == "stream_event"
            if event.get("type") == "result":
                result = event
            for piece in text_pieces(event, streamed):
                if piece:
                    said.append(piece)
                    on_text(piece)
        process.wait(timeout=10)
        if result.get("is_error") or (process.returncode and not said):
            raise why_it_failed(" ".join(filter(None, [str(result.get("result") or ""), "".join(errors)])) or "no answer")
        return "".join(said) or str(result.get("result") or "")

    @staticmethod
    def _read(stream: Any, lines: queue.Queue) -> None:
        for line in stream:
            lines.put(line)
        lines.put(None)

    def close(self) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)
