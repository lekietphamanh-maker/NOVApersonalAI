"""The Cloud brain: AI agents the owner signs in to with an account (a subscription, no API key). Claude Code on the
Claude plan is the full one: it runs Nova's tools over MCP (plan_brain.PlanBrain). Codex (a ChatGPT account) and Gemini
CLI (a Google account) answer through their own command line: they can search the web themselves but don't use Nova's
tools, so actions on this PC stay with Claude Code or the AI on this PC.

Each agent installs with npm (Node.js) and connects by its own sign-in, which Nova opens in a terminal window.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Callable

from cloud_brain import Unavailable

TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class Agent:
    key: str
    label: str
    account: str
    command: str
    package: str
    login: tuple[str, ...]      # the sign-in, run in a terminal window the owner sees
    ask: tuple[str, ...]        # one answer, non-interactive; the request goes in on standard input
    full: bool = False          # runs Nova's tools (only Claude Code, through MCP)


AGENTS: tuple[Agent, ...] = (
    Agent("claude-code", "Claude Code", "your Claude plan (Pro or Max)", "claude", "@anthropic-ai/claude-code",
          ("claude",), (), full=True),
    Agent("codex", "Codex", "your ChatGPT plan", "codex", "@openai/codex", ("codex", "login"),
          ("exec", "--skip-git-repo-check", "-")),
    Agent("gemini", "Gemini CLI", "your Google account", "gemini", "@google/gemini-cli", ("gemini",),
          ("-p", "Answer the request that came in on standard input.")),
)


def agent(key: str) -> Agent:
    return next((item for item in AGENTS if item.key == key), AGENTS[0])


def find(item: Agent) -> str | None:
    """The agent's command, if it's installed (PATH read again, so one installed while Nova runs is found)."""
    if item.key == "claude-code":
        import claude_code
        return claude_code.find()  # also where Claude Code's own installer puts it
    import node_runtime
    node_runtime.refresh_path()
    return shutil.which(item.command) or shutil.which(f"{item.command}.cmd")


def _quiet() -> dict[str, Any]:
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if sys.platform == "win32" else {}


def install(item: Agent, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> str:
    """npm install -g <package>: needs Node.js (which Nova's setup installs)."""
    import node_runtime
    node = node_runtime.find()
    if node is None:
        raise RuntimeError("Node.js isn't on this PC yet (SETTINGS → Downloads, or Set up everything)")
    node_runtime.use(node)
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm is None:
        raise RuntimeError("npm wasn't found next to Node.js")
    result = run([npm, "install", "-g", item.package], capture_output=True, text=True, timeout=900, **_quiet())
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "npm failed").strip().splitlines()[-1][:200])
    return f"{item.label} is installed. Next: Connect account."


def connect(item: Agent, popen: Callable[..., Any] = subprocess.Popen) -> None:
    """Opens a terminal window running the agent's own sign-in (the owner signs in there; Nova never sees it)."""
    command = find(item)
    if command is None:
        raise RuntimeError(f"{item.label} isn't installed yet: press Install first")
    line = [command, *item.login[1:]]
    if sys.platform == "win32":
        popen(["cmd", "/c", "start", f"Connect {item.label}", "cmd", "/k", *line])
    elif sys.platform == "darwin":
        import mac
        import shlex
        mac.osascript(f'tell application "Terminal" to do script "{" ".join(shlex.quote(part) for part in line)}"')
    else:
        popen(["x-terminal-emulator", "-e", *line])


class CliBrain:
    """A Cloud brain agent that answers one turn through its command line (no Nova tools)."""
    plan = True          # the agent hands it a whole turn (agent._ask_plan)
    sees_screen = False

    def __init__(self, item: Agent, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
        self.item, self._run = item, run

    @property
    def name(self) -> str:
        return self.item.label

    def turn(self, system: str, prompt: str, tools: list[dict[str, Any]], run_tool: Callable[[str, dict[str, Any]], str],
             on_text: Callable[[str], None], cancel: Any = None, followup: str | None = None) -> str:
        command = find(self.item)
        if command is None:
            raise Unavailable(f"{self.item.label} isn't installed (SETTINGS → Cloud brain)")
        request = (f"{system}\n\nYou can't use Nova's tools in this mode: answer in words, and if the owner wants something "
                   f"done on their PC, say it needs Claude Code or the AI on their PC.\n\n{prompt}")
        environment = {name: value for name, value in os.environ.items()
                       if name not in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")}  # the account, not a key
        try:
            result = self._run([command, *self.item.ask], input=request, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=TIMEOUT_SECONDS, cwd=tempfile.gettempdir(), env=environment,
                               **_quiet())
        except subprocess.TimeoutExpired as exc:
            raise Unavailable(f"{self.item.label} took too long") from exc
        except OSError as exc:
            raise Unavailable(f"{self.item.label} couldn't start ({exc})") from exc
        answer = (result.stdout or "").strip()
        if result.returncode != 0 or not answer:
            last = ((result.stderr or "").strip().splitlines() or ["no answer"])[-1][:200]
            signed_out = re.search(r"log ?in|logged|sign ?in|signed|auth|credential", last, re.IGNORECASE) is not None
            raise Unavailable(f"{self.item.label} isn't connected to {self.item.account}: SETTINGS → Cloud brain → Connect "
                              "account" if signed_out else f"{self.item.label} stopped: {last}")
        on_text(answer)
        return answer
