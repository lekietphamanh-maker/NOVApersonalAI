"""Claude on the owner's Claude plan: Nova's online brain through Claude Code (`claude -p`) instead of an API key.

No API credit is spent: Claude Code runs on the subscription the owner already pays for, and counts toward its usage
limits. Nova's tools reach Claude through nova_mcp (a local MCP server inside Nova), so Claude can still set timers,
search the web, add reminders and the rest. Claude Code's own tools are switched off except web search and fetch: it
can't read files, edit them or run commands here. The answer streams back as Claude writes it, so Nova speaks while it
thinks, like with the API.

One Claude Code session stays open between questions (started ahead of the first one), so a question doesn't wait for
Claude Code and Nova's tools to start: it remembers the conversation itself and gets only what's new. A new session
starts when Nova's instructions or tools change, after 30 questions, or when it stopped.

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
from dataclasses import dataclass
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
MAX_SESSION_TURNS = 30  # then a fresh session, so the conversation Claude carries doesn't keep growing
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


class _Stale(Exception):
    """A kept session had ended by itself before this question."""


@dataclass
class _Session:
    process: Any
    lines: queue.Queue
    errors: list[str]
    key: tuple
    mcp_file: Path
    token: str
    turns: int = 0
    stderr_reader: threading.Thread | None = None

    def alive(self) -> bool:
        return self.process.poll() is None


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
        self._session: _Session | None = None
        self._runner: Callable[[str, dict[str, Any]], str] | None = None  # the current question's tools, or None
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return f"{MODELS[self.model]} (Claude plan)"

    def arguments(self, command: str, system_file: Path, mcp_file: Path) -> list[str]:
        start = [command, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                 "--include-partial-messages",
                 "--model", self.model, "--effort", self.effort,
                 "--system-prompt-file", str(system_file), "--mcp-config", str(mcp_file)]
        if not self.connectors:
            return [*start, "--strict-mcp-config", "--tools", BUILT_IN_TOOLS, "--allowedTools", ALLOWED_TOOLS]
        # claude.ai connectors only load without --strict-mcp-config; any other MCP server the owner set up in Claude Code
        # loads too but can't be used here, because only the tools named in --allowedTools run in -p.
        return [*start, "--tools", BUILT_IN_TOOLS, "--allowedTools", f"{ALLOWED_TOOLS},{CONNECTORS}",
                "--disallowedTools", CONNECTOR_DENIED]

    def _key(self, command: str, system: str, tools: list[dict[str, Any]]) -> tuple:
        """What a session was started with: when any of it changes, a new session starts."""
        return (command, system, tuple(sorted(tool["function"]["name"] for tool in tools)))

    def _dispatch(self, name: str, arguments: dict[str, Any]) -> str:
        run = self._runner
        return run(name, arguments) if run is not None else "Nova isn't answering a question right now."

    def _open(self, command: str, system: str, tools: list[dict[str, Any]]) -> _Session:
        """Starts Claude Code once; it then answers question after question without starting again."""
        if self.tools is None:
            self.tools = ToolServer()
        token = self.tools.open(tools, self._dispatch)
        system_file, mcp_file = self.folder / "system.md", self.folder / "mcp.json"
        system_file.write_text(system, encoding="utf-8")
        mcp_file.write_text(json.dumps({"mcpServers": {SERVER_NAME: {
            "type": "http", "url": self.tools.url, "headers": {"Authorization": f"Bearer {token}"}}}}), encoding="utf-8")
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
        on_the_plan = {name: value for name, value in os.environ.items() if name not in API_KEY_VARIABLES}
        try:
            process = self.start(self.arguments(command, system_file, mcp_file), stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                 errors="replace", cwd=str(self.folder), env=on_the_plan, **flags)
        except OSError as exc:
            self.tools.close(token)
            mcp_file.unlink(missing_ok=True)
            raise Unavailable(f"Claude Code couldn't start ({exc})") from exc
        session = _Session(process, queue.Queue(), [], self._key(command, system, tools), mcp_file, token)
        threading.Thread(target=self._read, args=(process.stdout, session.lines), daemon=True).start()
        session.stderr_reader = threading.Thread(target=lambda: session.errors.extend(process.stderr), daemon=True)
        session.stderr_reader.start()
        return session

    def _end(self) -> None:
        session, self._session = self._session, None
        if session is None:
            return
        _stop(session.process)
        session.mcp_file.unlink(missing_ok=True)
        if self.tools is not None:
            self.tools.close(session.token)

    def warm(self, system: str, tools: list[dict[str, Any]]) -> None:
        """Starts the session ahead of the first question (in the background), so that one is quick too."""
        command = self.command()
        if command is None:
            return

        def start() -> None:
            with self._lock:
                if self._session is None or self._session.key != self._key(command, system, tools) or not self._session.alive():
                    self._end()
                    try:
                        self._session = self._open(command, system, tools)
                    except Unavailable:
                        pass
        threading.Thread(target=start, name="NovaPlanWarm", daemon=True).start()

    def turn(self, system: str, prompt: str, tools: list[dict[str, Any]], run: Callable[[str, dict[str, Any]], str],
             on_text: Callable[[str], None], cancel: Any = None, followup: str | None = None) -> str | None:
        """One whole turn: Claude answers `prompt`, using `tools` (run by `run`) as often as it needs. Returns the
        final answer, or None when cancelled. Raises Unavailable when Claude Code couldn't answer.
        followup: the same request without the earlier conversation, for a session that has already seen it."""
        command = self.command()
        if command is None:
            raise Unavailable("Claude Code isn't installed on this PC")
        with self._lock:
            for attempt in range(2):
                session = self._session
                if (session is None or session.key != self._key(command, system, tools) or not session.alive()
                        or session.turns >= MAX_SESSION_TURNS):
                    self._end()
                    session = self._session = self._open(command, system, tools)
                text = followup if followup is not None and session.turns > 0 else prompt
                self._runner = run
                try:
                    return self._ask(session, text, on_text, cancel)
                except _Stale:
                    self._end()  # it had stopped while waiting (asleep, signed out): one fresh start
                    if attempt:
                        raise Unavailable("Claude Code stopped") from None
                finally:
                    self._runner = None
        return None

    def _ask(self, session: _Session, text: str, on_text: Callable[[str], None], cancel: Any) -> str | None:
        try:
            session.process.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n")
            session.process.stdin.flush()  # through stdin: never on a command line cmd.exe would read
        except (OSError, ValueError):
            raise _Stale() from None
        said: list[str] = []
        streamed = False
        deadline = time.monotonic() + TURN_TIMEOUT_SECONDS
        while True:
            if cancel is not None and cancel.is_set():
                self._end()
                return None
            if time.monotonic() > deadline:
                self._end()
                raise Unavailable("Claude Code took more than 10 minutes")
            try:
                line = session.lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:  # Claude Code ended
                session.process.wait(timeout=10)
                if session.stderr_reader is not None:
                    session.stderr_reader.join(timeout=2)  # what it said on the way out, before deciding why
                if not said and session.turns > 0 and not session.errors:
                    raise _Stale()
                self._end()
                raise why_it_failed("".join(session.errors) or "no answer")
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "system" and event.get("subtype") == "init":
                session.mcp_file.unlink(missing_ok=True)  # read by now: the key in it isn't left lying around
            streamed = streamed or event.get("type") == "stream_event"
            for piece in text_pieces(event, streamed):
                if piece:
                    said.append(piece)
                    on_text(piece)
            if event.get("type") == "result":
                session.turns += 1
                if event.get("is_error"):
                    raise why_it_failed(str(event.get("result") or "") or "no answer")
                return "".join(said) or str(event.get("result") or "")

    @staticmethod
    def _read(stream: Any, lines: queue.Queue) -> None:
        for line in stream:
            lines.put(line)
        lines.put(None)

    def close(self) -> None:
        with self._lock:
            self._end()
        shutil.rmtree(self.folder, ignore_errors=True)
