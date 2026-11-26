"""Separate apps for Advance mode: tools that run on their own instead of inside Nova's window.

- "window": one of Nova's own screens (Rea, Shannon) in its own window, beside the HUD.
- "docker": a self-hosted app Nova starts and stops in Docker (OpenProject), then opens in the browser.
- "download" / "web": a desktop app to install, or a site; Nova opens its page, and the app itself once it's there.
- the owner's own apps: a name and an address or a program, saved in settings.

The repos with AGPL code (Cap, VoiceStudio, AppFlowy) only ever run as these separate apps: none of their code is in Nova.
"""
from __future__ import annotations

import re
import secrets
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

DOCKER_PAGE = "https://www.docker.com/products/docker-desktop/"
MAX_OWN_APPS = 24


@dataclass(frozen=True)
class App:
    id: str
    name: str
    what: str
    kind: str                        # window | docker | download | web
    page: str = ""                   # where to get it, or the site
    runs_on: str = ""                # which brain does its AI work
    image: str = ""                  # docker
    port: int = 0                    # docker: the port on this PC
    inner_port: int = 80
    env: tuple[tuple[str, str], ...] = ()
    volumes: tuple[tuple[str, str], ...] = ()
    secret_env: str = ""             # an environment variable Nova fills with a random secret, kept sealed
    open_url: str = ""               # what Open shows once it runs (docker / self-hosted)
    mac_app: str = ""                # download: the app's name for `open -a`
    windows_exe: tuple[str, ...] = ()  # download: where the installer puts it, under %LOCALAPPDATA% or Program Files
    licence: str = ""


CATALOG: tuple[App, ...] = (
    App("rea", "Rea", "How an app is built, as a blueprint you can turn around.", "window",
        runs_on="Claude Code (your Claude plan)", licence="Nova's own screen"),
    App("shannon", "Shannon", "Break into your own app before someone else does: weak spots on a shield.", "window",
        runs_on="Claude (Anthropic API key), in Docker", licence="Nova's own screen"),
    App("workplace", "Workplace", "Notes, sketches, pictures and files on one board, with Nova explaining.", "window",
        runs_on="whichever brain answers you", licence="Nova's own screen"),
    App("openproject", "OpenProject", "Projects, boards, Gantt charts and time tracking, on this PC.", "docker",
        "https://www.openproject.org/docs/installation-and-operations/installation/docker/",
        image="openproject/openproject:15", port=8080, inner_port=80,
        env=(("OPENPROJECT_HOST__NAME", "localhost:8080"), ("OPENPROJECT_HTTPS", "false")),
        volumes=(("nova-openproject-pgdata", "/var/openproject/pgdata"),
                 ("nova-openproject-assets", "/var/openproject/assets")),
        secret_env="OPENPROJECT_SECRET_KEY_BASE", open_url="http://localhost:8080", licence="GPL-3.0"),
    App("voicestudio", "VoiceStudio", "Voice cloning and text to speech studio (self-hosted, port 3900).", "web",
        "https://github.com/debpalash/VoiceStudio", runs_on="its own local voice models", open_url="http://localhost:3900",
        licence="AGPL-3.0"),
    App("appflowy", "AppFlowy", "Notes, docs and boards like Notion, on this PC.", "download",
        "https://appflowy.com/download", mac_app="AppFlowy", windows_exe=("AppFlowy/AppFlowy.exe",), licence="AGPL-3.0"),
    App("cap", "Cap", "Screen recorder with editing and sharing (Nova's own recording is built in).", "download",
        "https://cap.so/download", mac_app="Cap", windows_exe=("Programs/Cap/Cap.exe", "Cap/Cap.exe"), licence="AGPL-3.0"),
    App("openwhispr", "OpenWhispr", "Dictation app (Nova's own dictation key is built in).", "download",
        "https://github.com/OpenWhispr/openwhispr/releases", mac_app="OpenWhispr",
        windows_exe=("Programs/OpenWhispr/OpenWhispr.exe",), licence="MIT"),
    App("chatwoot", "Chatwoot", "Customer chat inbox for a business (website chat, email, social).", "web",
        "https://www.chatwoot.com/docs/self-hosted", open_url="https://app.chatwoot.com", licence="MIT"),
    App("open-generative-ai", "Open Generative AI", "Image and video studio over many models (Nova makes pictures "
        "with your API brain).", "web", "https://github.com/Anil-matcha/Open-Generative-AI", licence="MIT"),
    App("cal", "Cal.diy", "Booking pages people pick a time from (Nova finds free time in your calendar).", "web",
        "https://github.com/calcom/cal.diy", open_url="https://cal.com", licence="MIT"),
    App("open-seo", "open-seo", "Full SEO suite with keyword data (Nova's SEO check is built in).", "web",
        "https://github.com/every-app/open-seo", licence="MIT"),
)


def find(app_id: str) -> App | None:
    return next((app for app in CATALOG if app.id == app_id), None)


@dataclass
class OwnApp:
    id: str
    name: str
    target: str  # a web address or a program / file on this PC

    @staticmethod
    def new(name: str, target: str) -> "OwnApp":
        name, target = " ".join(str(name).split())[:40], str(target).strip().strip('"')[:400]
        if not name:
            raise ValueError("give the app a name")
        if not target:
            raise ValueError("give its web address, or the program it starts")
        if not re.match(r"^https?://", target) and not Path(target).expanduser().exists():
            raise ValueError(f"“{target[:80]}” isn't a web address (https://…) or a file on this PC")
        return OwnApp(secrets.token_hex(4), name, target)

    def as_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "target": self.target}


def own_apps(saved: Any) -> list[OwnApp]:
    found = []
    for item in saved if isinstance(saved, list) else []:
        if isinstance(item, dict) and item.get("id") and item.get("name") and item.get("target"):
            found.append(OwnApp(str(item["id"]), str(item["name"]), str(item["target"])))
    return found[:MAX_OWN_APPS]


# ---------- Docker ----------

def docker_path() -> str | None:
    found = shutil.which("docker")
    if found:
        return found
    candidates = [Path("C:/Program Files/Docker/Docker/resources/bin/docker.exe")] if sys.platform == "win32" else \
        [Path("/usr/local/bin/docker"), Path("/opt/homebrew/bin/docker"), Path("/Applications/Docker.app/Contents/Resources/bin/docker")]
    return next((str(path) for path in candidates if path.exists()), None)


def container(app: App) -> str:
    return f"nova-{app.id}"


def run_arguments(docker: str, app: App, secret: str) -> list[str]:
    arguments = [docker, "run", "-d", "--name", container(app), "--restart", "unless-stopped",
                 "-p", f"127.0.0.1:{app.port}:{app.inner_port}"]
    for name, value in app.env:
        arguments += ["-e", f"{name}={value}"]
    if app.secret_env:
        arguments += ["-e", f"{app.secret_env}={secret}"]
    for volume, path in app.volumes:
        arguments += ["-v", f"{volume}:{path}"]
    return arguments + [app.image]


class Docker:
    """Starts, stops and checks Nova's containers. run: subprocess.run (replaced in tests)."""

    def __init__(self, run: Callable[..., Any] = subprocess.run, locate: Callable[[], str | None] = docker_path) -> None:
        self._run, self._locate = run, locate

    def _call(self, arguments: list[str], timeout: float) -> Any:
        flags = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if sys.platform == "win32" else {}
        return self._run(arguments, capture_output=True, text=True, timeout=timeout, check=False, **flags)

    def problem(self) -> str:
        docker = self._locate()
        if docker is None:
            return "Docker Desktop isn't installed"
        try:
            answer = self._call([docker, "info", "--format", "{{.ServerVersion}}"], 15)
        except (OSError, subprocess.TimeoutExpired):
            return "Docker doesn't answer"
        return "" if answer.returncode == 0 else "Docker Desktop isn't running (start it, then try again)"

    def status(self, app: App) -> str:
        """running | stopped | absent | "" (Docker isn't here)."""
        docker = self._locate()
        if docker is None:
            return ""
        try:
            answer = self._call([docker, "ps", "-a", "--filter", f"name=^{container(app)}$", "--format", "{{.State}}"], 10)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if answer.returncode != 0:
            return ""
        state = answer.stdout.strip().splitlines()[0] if answer.stdout.strip() else ""
        return "running" if state == "running" else "stopped" if state else "absent"

    def start(self, app: App, secret: Callable[[], str]) -> str:
        problem = self.problem()
        if problem:
            raise RuntimeError(problem)
        docker = self._locate()
        state = self.status(app)
        if state == "running":
            return f"{app.name} is already running: {app.open_url}"
        if state == "stopped":
            answer = self._call([docker, "start", container(app)], 120)
        else:  # the first start pulls the image: a few minutes
            answer = self._call(run_arguments(docker, app, secret() if app.secret_env else ""), 1800)
        if answer.returncode != 0:
            lines = (answer.stderr or answer.stdout or "").strip().splitlines()
            raise RuntimeError((lines[-1] if lines else "Docker said no")[:200])
        return f"{app.name} is starting at {app.open_url} (the first start takes a few minutes)."

    def stop(self, app: App) -> str:
        docker = self._locate()
        if docker is None or self.status(app) != "running":
            return f"{app.name} isn't running."
        answer = self._call([docker, "stop", container(app)], 120)
        if answer.returncode != 0:
            raise RuntimeError((answer.stderr or "Docker said no").strip()[:200])
        return f"Stopped {app.name}. Its data stays for next time."


# ---------- installed desktop apps ----------

def installed_path(app: App, platform: str = sys.platform, environ: dict[str, str] | None = None) -> str | None:
    import os
    environ = os.environ if environ is None else environ
    if platform == "darwin" and app.mac_app:
        for folder in ("/Applications", str(Path.home() / "Applications")):
            if Path(folder, f"{app.mac_app}.app").exists():
                return str(Path(folder, f"{app.mac_app}.app"))
    if platform == "win32":
        roots = [environ.get(name, "") for name in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)")]
        for root in filter(None, roots):
            for relative in app.windows_exe:
                if Path(root, relative).exists():
                    return str(Path(root, relative))
    return None


def is_web(target: str) -> bool:
    return urlsplit(target).scheme in ("http", "https")
