"""Real work on the owner's Claude Code plan: Nova hands a big job (an explainer, a research report) to `claude -p`,
which works on it in the background in the vault folder and answers in Markdown, saved in outputs/. It may only read
the vault and the web (Read, Glob, Grep, WebSearch, WebFetch): it can't change files or run commands. The task goes in
through stdin, never on a command line (claude may be a .cmd file, where cmd.exe would read & and | in it)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

ALLOWED_TOOLS = "Read,Glob,Grep,WebSearch,WebFetch"
# Build mode: write and edit files in the project's own folder, plus git. No other command: an interpreter or a package
# manager (python, node, npm, pip) can run anything at all, so allowing one would be allowing every command.
BUILD_TOOLS = ALLOWED_TOOLS + ",Write,Edit,Bash(git init),Bash(git add:*),Bash(git commit:*),Bash(git status)"
BUILD_INSTRUCTIONS = ("You are building something for Nova's owner in the current folder, their project folder. Write and "
                      "edit the files here only; you can't run commands other than git. Make it work as it is: a website as "
                      "plain HTML, CSS and JavaScript with index.html at the top (no build step), a script with a short "
                      "README saying how to run it. If the folder already has the project, change it as asked instead of "
                      "starting over. No questions back: decide sensibly. End with three lines: what you made, the file to "
                      "open first, and how to run it.\n\n")
# With one of these in its environment Claude Code bills that API key instead of the owner's Claude plan.
API_KEY_VARIABLES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
TIMEOUT_SECONDS = 30 * 60
INSTRUCTIONS = ("You are doing a piece of work for Nova's owner. The current folder is their Obsidian vault (raw/ "
                "sources, wiki/ topic pages, outputs/ earlier work): use it for context when it helps. Answer with the "
                "finished deliverable only, in Markdown, ready to save as a note. No questions back: decide sensibly.\n\n")


def find() -> str | None:
    """The claude command, if Claude Code is installed (npm or the native installer)."""
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    for candidate in (home / ".local" / "bin" / "claude.exe", Path(os.environ.get("APPDATA", home)) / "npm" / "claude.cmd"):
        if candidate.exists():
            return str(candidate)
    return None


def run(task: str, folder: Path, command: str, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        building: bool = False) -> str:
    """Claude Code's answer, or RuntimeError with what went wrong. building: it may write in `folder` (and use git)."""
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    on_the_plan = {name: value for name, value in os.environ.items() if name not in API_KEY_VARIABLES}
    try:
        mode = ["--allowedTools", BUILD_TOOLS, "--permission-mode", "acceptEdits"] if building else ["--allowedTools", ALLOWED_TOOLS]
        result = runner([command, "-p", "--output-format", "text", *mode],
                        input=(BUILD_INSTRUCTIONS if building else INSTRUCTIONS) + task, capture_output=True, text=True, encoding="utf-8", errors="replace",
                        cwd=str(folder), env=on_the_plan, timeout=TIMEOUT_SECONDS, **flags)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Claude Code took more than 30 minutes") from exc
    except OSError as exc:
        raise RuntimeError(f"Claude Code couldn't start ({exc})") from exc
    answer = (result.stdout or "").strip()
    if result.returncode != 0 or not answer:
        problem = (result.stderr or result.stdout or "").strip().splitlines()[-1:] or ["no answer"]
        raise RuntimeError(f"Claude Code stopped: {problem[0][:200]}")
    return answer


PROJECTS = Path.home() / "Documents" / "Nova Projects"


def project_folder(name: str, root: Path = PROJECTS) -> Path:
    """The project's own folder: the same name gives the same folder, so "change my portfolio site" goes on with it."""
    words = re.findall(r"[\w]+", str(name).lower())
    return root / ("-".join(words)[:60] or "project")


class DeepWork:
    """Background jobs for Claude Code. `save(title, text)` keeps the result (outputs/); `done(title, result, ok)`
    tells the owner; `built(name, folder, ok, message)` hears when a build is finished."""

    def __init__(self, folder: Callable[[], Path], save: Callable[[str, str], Path],
                 done: Callable[[str, str, bool], None], command: Callable[[], str | None] = find,
                 built: Callable[[str, Path, bool, str], None] | None = None, projects: Path = PROJECTS) -> None:
        self.folder, self.save, self.done, self.command = folder, save, done, command
        self.built, self.projects = built, projects
        self.running: list[str] = []

    @property
    def available(self) -> bool:
        return self.command() is not None

    def start(self, title: str, task: str) -> str:
        command = self.command()
        if command is None:
            return "Claude Code isn't installed on this PC, so Nova can't hand this off. Do it here instead."
        title = " ".join(str(title).split())[:80] or "Deep work"
        self.running.append(title)
        threading.Thread(target=self._work, args=(title, str(task), command), name="NovaDeepWork", daemon=True).start()
        return (f'Claude Code is working on "{title}" in the background. It will be saved in outputs/ and the owner will '
                "be told when it's ready. Tell them that in one sentence.")

    def build(self, name: str, task: str) -> str:
        command = self.command()
        if command is None:
            return "Claude Code isn't installed on this PC, so Nova can't build this. Say so in one sentence."
        folder = project_folder(name, self.projects)
        folder.mkdir(parents=True, exist_ok=True)
        label = f"Build: {folder.name}"
        self.running.append(label)
        threading.Thread(target=self._build, args=(label, folder, str(task), command), name="NovaBuild", daemon=True).start()
        return (f"Claude Code is building it in {folder} in the background; Nova opens it when it is done. Tell the owner "
                "that in one sentence.")

    def _build(self, label: str, folder: Path, task: str, command: str) -> None:
        try:
            summary = run(task, folder, command, building=True)
            self.save(label, f"Folder: {folder}\n\n{summary}")
            if self.built is not None:
                self.built(folder.name, folder, True, summary)
        except Exception as exc:
            if self.built is not None:
                self.built(folder.name, folder, False, str(exc))
        finally:
            self.running.remove(label)

    def _work(self, title: str, task: str, command: str) -> None:
        try:
            path = self.save(title, run(task, self.folder(), command))
            self.done(title, f"outputs/{path.name}", True)
        except Exception as exc:
            self.done(title, str(exc), False)
        finally:
            self.running.remove(title)
