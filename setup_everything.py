"""Set up everything: after install, Nova downloads and turns on what every feature needs, one step after another,
without the owner going round Settings. It starts by itself on the first run (the owner can stop it) and again from
SETTINGS → Downloads → Set up everything.

Each step says whether it's done already, how big it is, and how to do it. A step that fails is reported and the next
one runs; a step that doesn't fit on the disk is skipped. What can't be automatic (Docker and WSL need an administrator
and a restart; accounts need the owner to sign in) is listed at the end instead of half-done.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

OLLAMA_SETUP = "https://ollama.com/download/OllamaSetup.exe"
SPARE_DISK_MB = 2048  # left free after a step, so the PC never fills up
MANUAL = (
    ("Docker Desktop", "Shannon and the Docker apps need it. It installs with an administrator prompt and a restart: "
                       "docker.com/products/docker-desktop"),
    ("Accounts", "Claude, ChatGPT, Gemini, Google mail and calendar ask you to sign in once: SETTINGS → Model and "
                 "SETTINGS → Google"),
)

Progress = Callable[[str], None]


@dataclass
class Step:
    id: str
    name: str
    why: str
    size_mb: int
    done: Callable[[], bool]
    run: Callable[[Progress], None]
    after: Callable[[], None] = lambda: None   # turns the feature on once it's here


def _quiet() -> dict[str, Any]:
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if sys.platform == "win32" else {}


def _command(arguments: list[str], progress: Progress, what: str, timeout: float = 1800,
             run: Callable[..., Any] = subprocess.run) -> None:
    progress(what)
    result = run(arguments, capture_output=True, text=True, timeout=timeout, check=False, **_quiet())
    if result.returncode != 0:
        lines = (result.stderr or result.stdout or "").strip().splitlines()
        raise RuntimeError(lines[-1][:200] if lines else f"{arguments[0]} stopped with code {result.returncode}")


def brew() -> str | None:
    return shutil.which("brew") or next((path for path in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew") if Path(path).exists()), None)


def winget() -> str | None:
    return shutil.which("winget")


def winget_install(package: str, progress: Progress, what: str, run: Callable[..., Any] = subprocess.run) -> None:
    _command([winget() or "winget", "install", "-e", "--id", package, "--silent", "--accept-package-agreements",
              "--accept-source-agreements", "--disable-interactivity"], progress, what, run=run)


def install_ollama(progress: Progress, run: Callable[..., Any] = subprocess.run, opener: Callable[..., Any] = urlopen,
                   platform: str = sys.platform) -> None:
    """Ollama for this user (no administrator prompt on Windows): winget, or Ollama's own installer, silently."""
    if platform == "darwin":
        if brew() is None:
            raise RuntimeError("install Homebrew (brew.sh) or get Ollama from ollama.com/download")
        _command([brew(), "install", "ollama"], progress, "Installing Ollama with Homebrew", run=run)
        _command([brew(), "services", "start", "ollama"], progress, "Starting Ollama", run=run)
        return
    if platform != "win32":
        raise RuntimeError("install Ollama with: curl -fsSL https://ollama.com/install.sh | sh")
    if winget():
        winget_install("Ollama.Ollama", progress, "Installing Ollama", run)
        return
    progress("Downloading Ollama (about 700 MB)")
    with tempfile.TemporaryDirectory() as scratch:
        setup = Path(scratch) / "OllamaSetup.exe"
        with opener(Request(OLLAMA_SETUP, headers={"User-Agent": "Nova"}), timeout=1800) as response, setup.open("wb") as file:
            shutil.copyfileobj(response, file)
        _command([str(setup), "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"], progress, "Installing Ollama", run=run)


def install_node(progress: Progress, run: Callable[..., Any] = subprocess.run, platform: str = sys.platform) -> None:
    if platform == "darwin":
        if brew() is None:
            raise RuntimeError("install Homebrew (brew.sh) or Node.js from nodejs.org")
        _command([brew(), "install", "node"], progress, "Installing Node.js with Homebrew", run=run)
    elif platform == "win32" and winget():
        winget_install("OpenJS.NodeJS.LTS", progress, "Installing Node.js (Windows may ask for permission)", run)
    else:
        raise RuntimeError("get Node.js LTS from nodejs.org/en/download")
    import node_runtime
    node_runtime.refresh_path()


def wait_for(check: Callable[[], bool], seconds: float = 90, sleep: Callable[[float], None] = time.sleep) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        sleep(2)
    return check()


def free_mb(folder: Path | None = None) -> float:
    return shutil.disk_usage(folder or Path.home()).free / 1024 ** 2


class Setup:
    """Runs the steps on a worker thread. report(state) is called after every change; stop() ends it between steps."""

    def __init__(self, report: Callable[[dict[str, Any]], None], disk_mb: Callable[[], float] = free_mb) -> None:
        self._report, self._disk_mb = report, disk_mb
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.steps: list[dict[str, Any]] = []
        self.current = ""
        self._working = False  # the last report comes from the worker itself, so is_alive() would still say yes

    @property
    def running(self) -> bool:
        return self._working

    def state(self) -> dict[str, Any]:
        return {"running": self.running, "current": self.current, "steps": [dict(item) for item in self.steps],
                "manual": [{"name": name, "why": why} for name, why in MANUAL]}

    def start(self, steps: list[Step]) -> bool:
        if self.running:
            return False
        self._stop.clear()
        self._working = True
        self.steps = [{"id": step.id, "name": step.name, "why": step.why, "size_mb": step.size_mb, "status": "waiting",
                       "note": ""} for step in steps]
        self._thread = threading.Thread(target=self._work, args=(steps,), name="NovaSetup", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _mark(self, index: int, status: str, note: str = "") -> None:
        self.steps[index].update(status=status, note=note)
        self._report(self.state())

    def _work(self, steps: list[Step]) -> None:
        for index, step in enumerate(steps):
            if self._stop.is_set():
                self._mark(index, "stopped")
                continue
            try:
                if step.done():
                    step.after()
                    self._mark(index, "done", "already here")
                    continue
            except Exception:
                pass  # couldn't tell: try to set it up
            if step.size_mb and self._disk_mb() < step.size_mb + SPARE_DISK_MB:
                self._mark(index, "skipped", f"needs {step.size_mb / 1024:.1f} GB free on the disk")
                continue
            self.current = step.name
            self._mark(index, "running")
            try:
                step.run(lambda text, index=index: self._mark(index, "running", text))
                step.after()
                self._mark(index, "done")
            except Exception as exc:
                self._mark(index, "failed", str(exc)[:200])
        self.current = ""
        self._working = False
        self._report(self.state())

    def summary(self) -> str:
        counts = {status: sum(item["status"] == status for item in self.steps) for status in ("done", "failed", "skipped")}
        text = f"Set up everything: {counts['done']} ready"
        if counts["failed"]:
            text += f", {counts['failed']} didn't work (SETTINGS → Downloads says why)"
        if counts["skipped"]:
            text += f", {counts['skipped']} skipped for disk space"
        return text + "."
