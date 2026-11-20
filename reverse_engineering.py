"""Reverse engineering with REA (github.com/morluto/rea), through Claude Code on the owner's plan.

"Reverse engineer <app, site, file or project>" starts a background job: Claude Code gets REA as its only MCP server
(the npm package pinned to one version, run with npx; Node.js 22.23+ must be installed) and works out how the target
works. The report goes to outputs/ and a Library entry under "Reverse engineering" (target, date, a summary, where the
full report is), so it can be found again and turned into something with Discover's "Add to Nova".

REA reads files and can run or drive the target with the owner's permissions; only software and services the owner is
allowed to analyse. The switch in Settings is off until they read that and turn it on.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

import node_runtime
from claude_code import API_KEY_VARIABLES, find as find_claude

REA_PACKAGE = "rea-agents@6.9.0"  # pinned: a new REA version is a change to Nova, reviewed like any other
NODE_NEEDED = ((22, 23, 4), (24, 22, 1), (26, 12, 1))  # REA's engines: ^22.23.4 || ^24.22.1 || >=26.12.1
ALLOWED_TOOLS = "mcp__rea,Read,Glob,Grep,WebSearch,WebFetch"
TIMEOUT_SECONDS = 45 * 60
LIBRARY_TOPIC = "Reverse engineering"
INSTRUCTIONS = ("You are reverse engineering something for Nova's owner, who is allowed to analyse it. Use the rea tools "
                "to inspect it; prefer static analysis, and only run or drive it when that is needed to answer. Don't "
                "change, patch or bypass anything (no cracking, no licence or DRM circumvention). Answer in Markdown: "
                "a three-line summary first, then how it is built (stack, structure, main parts), how the part asked "
                "about works, with the evidence for each conclusion, and what you couldn't determine.\n\n")


def node_version(run: Callable[..., subprocess.CompletedProcess] = subprocess.run, choice: str = "") -> tuple[int, int, int] | None:
    """The version of the Node.js Nova finds (see node_runtime), which then goes first on PATH for npx."""
    node = node_runtime.find(choice)
    if node is None:
        return None
    found = node_runtime.version(node, run)
    if found is not None:
        node_runtime.use(node)
    return found


def node_ok(version: tuple[int, int, int] | None) -> bool:
    if version is None:
        return False
    major = version[0]
    return any(version >= floor for floor in NODE_NEEDED if floor[0] == major) or version >= NODE_NEEDED[-1]


def mcp_config(platform: str = sys.platform) -> dict:
    """REA as Claude Code's only MCP server (on Windows npx is a .cmd file, which needs cmd /c to start)."""
    command, args = ("cmd", ["/c", "npx", "-y", REA_PACKAGE, "mcp"]) if platform == "win32" else ("npx", ["-y", REA_PACKAGE, "mcp"])
    return {"mcpServers": {"rea": {"command": command, "args": args}}}


def target_name(target: str) -> str:
    text = " ".join(str(target).split())[:200]
    name = re.sub(r"^https?://", "", text).rstrip("/\\")
    return (re.split(r"[\\/]", name)[-1] or name)[:60] or "target"


def run(target: str, goal: str, folder: Path, command: str,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> str:
    """Claude Code's report, or RuntimeError saying what went wrong."""
    folder.mkdir(parents=True, exist_ok=True)
    config = folder / "rea-mcp.json"
    config.write_text(json.dumps(mcp_config()), encoding="utf-8")
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    on_the_plan = {name: value for name, value in os.environ.items() if name not in API_KEY_VARIABLES}
    task = f"Target: {target}\nWhat the owner wants to know: {goal or 'how it works, overall'}"
    try:
        result = runner([command, "-p", "--output-format", "text", "--mcp-config", str(config), "--strict-mcp-config",
                         "--allowedTools", ALLOWED_TOOLS], input=INSTRUCTIONS + task, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", cwd=str(folder), env=on_the_plan, timeout=TIMEOUT_SECONDS, **flags)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("the reverse engineering took more than 45 minutes") from exc
    except OSError as exc:
        raise RuntimeError(f"Claude Code couldn't start ({exc})") from exc
    report = (result.stdout or "").strip()
    if result.returncode != 0 or not report:
        problem = (result.stderr or result.stdout or "").strip().splitlines()[-1:] or ["no answer"]
        raise RuntimeError(f"Claude Code stopped: {problem[0][:200]}")
    return report


class ReverseEngineering:
    """save(title, text) -> Path keeps the report (outputs/); library(title, note) files it in the Library;
    done(title, result, ok) tells the owner."""

    def __init__(self, save: Callable[[str, str], Path], library: Callable[[str, str], None],
                 done: Callable[[str, str, bool], None], workspace: Path,
                 command: Callable[[], str | None] = find_claude,
                 node: Callable[[], tuple[int, int, int] | None] = node_version) -> None:
        self.save, self.library, self.done, self.workspace = save, library, done, Path(workspace)
        self.command, self.node = command, node
        self.running: list[str] = []

    def problem(self) -> str:
        """Why it can't run on this PC right now ("" when it can)."""
        if self.command() is None:
            return "Claude Code isn't installed on this PC (claude.com/product/claude-code)"
        found = self.node()
        if found is None:
            return ("Nova can't find Node.js (REA needs Node.js 22.23 or newer): install the LTS from nodejs.org, or "
                    "point Nova to node.exe in Settings → Need to → Reverse engineering")
        if not node_ok(found):
            return f"Node.js {'.'.join(map(str, found))} is too old for REA: it needs 22.23 or newer (the LTS from nodejs.org)"
        return ""

    def start(self, target: str, goal: str = "") -> str:
        problem = self.problem()
        if problem:
            return f"Can't reverse engineer here: {problem}. Say that in one sentence."
        name = target_name(target)
        title = f"Reverse engineering {name}"
        folder = self.workspace / f"{datetime.now():%Y-%m-%d %H%M} {re.sub(r'[^A-Za-z0-9._ -]', '_', name)}"
        self.running.append(title)
        threading.Thread(target=self._work, args=(title, name, str(target), str(goal), folder, self.command()),
                         name="NovaReverseEngineering", daemon=True).start()
        return (f"Started reverse engineering {name} with REA in the background (Claude Code on the owner's plan). "
                "The report goes to outputs/ and the Library under Reverse engineering. Tell the owner in one sentence.")

    def _work(self, title: str, name: str, target: str, goal: str, folder: Path, command: str) -> None:
        try:
            report = run(target, goal, folder, command)
            path = self.save(title, f"Target: {target}\n\n{report}")
            summary = "\n".join(report.splitlines()[:6])
            self.library(f"RE {name}", f"Target: {target}\nAsked: {goal or 'how it works'}\n"
                                       f"Full report: outputs/{path.name}\n\n{summary}")
            self.done(title, f"outputs/{path.name}", True)
        except Exception as exc:
            self.done(title, str(exc), False)
        finally:
            self.running.remove(title)
