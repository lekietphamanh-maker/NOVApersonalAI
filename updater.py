"""Nova updates herself from GitHub Releases.

On start and every few hours Nova asks GitHub for the newest release. A newer one is downloaded quietly (its
installer, Nova-Setup.exe), checked against the SHA-256 published with it, and kept until the owner says restart: then
the installer runs silently, closes Nova, replaces her and starts her again. A download that is cut off or doesn't
match its checksum is thrown away, never run, so a bad update can't leave Nova broken. The installer of the version
before stays available: "Install the previous version" downloads it the same way.

Only a copy installed by Nova-Setup.exe updates itself (it has install.ini next to Nova.exe). The zip editions are told
a new version is out, with the link. A copy run from source ("dev") never updates.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO = "lekietphamanh-maker/NOVApersonalAI"
API = f"https://api.github.com/repos/{REPO}"
INSTALLER, CHECKSUM = "Nova-Setup.exe", "Nova-Setup.exe.sha256"
CHECK_EVERY_HOURS = 6
KEPT_INSTALLERS = 2
CHUNK = 1 << 20
SILENT_INSTALL = ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]
VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


class UpdateError(RuntimeError):
    """Said to the owner as it is: no network, GitHub busy, a broken download."""


def version_key(text: str) -> tuple[int, int, int] | None:
    match = VERSION.match(str(text).strip())
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def is_newer(candidate: str, current: str) -> bool:
    new, now = version_key(candidate), version_key(current)
    return new is not None and now is not None and new > now


@dataclass(frozen=True)
class Release:
    version: str
    page: str
    installer: str  # download address of Nova-Setup.exe, "" when the release has none
    checksum: str
    notes: str = ""


def parse_release(data: dict[str, Any]) -> Release:
    assets = {asset.get("name"): asset.get("browser_download_url", "") for asset in data.get("assets") or []}
    return Release(str(data.get("tag_name", "")), str(data.get("html_url", "")), assets.get(INSTALLER, ""),
                   assets.get(CHECKSUM, ""), str(data.get("body") or "")[:3000])


def installed_by_setup(executable: str | None = None) -> bool:
    """Nova-Setup.exe put this copy here (it writes install.ini beside Nova.exe)."""
    if executable is None:
        if not getattr(sys, "frozen", False):
            return False
        executable = sys.executable
    return (Path(executable).resolve().parent / "install.ini").is_file()


class Updater:
    def __init__(self, current: str, folder: Path, opener: Callable[..., Any] = urlopen,
                 can_install: Callable[[], bool] = installed_by_setup,
                 run: Callable[[list[str]], Any] = lambda command: subprocess.Popen(command, close_fds=True)) -> None:
        self.current, self.folder, self._open, self.can_install, self._run = current, Path(folder), opener, can_install, run

    # ---------- asking GitHub ----------

    def _get(self, url: str, timeout: float = 20) -> Any:
        request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Nova-updater"})
        try:
            with self._open(request, timeout=timeout) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            if exc.code in (403, 429):
                raise UpdateError("GitHub is limiting requests right now; Nova will try again later") from None
            raise UpdateError(f"GitHub said {exc.code}") from None
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise UpdateError(f"couldn't reach GitHub ({type(exc).__name__})") from None

    def newest(self) -> Release | None:
        """The newest release if it is newer than this Nova, else None."""
        if version_key(self.current) is None:
            return None  # run from source: never updates itself
        release = parse_release(self._get(f"{API}/releases/latest"))
        return release if is_newer(release.version, self.current) else None

    def previous(self) -> Release | None:
        """The newest release older than this one that has an installer: what "go back" installs."""
        for data in self._get(f"{API}/releases?per_page=20"):
            release = parse_release(data)
            if is_newer(self.current, release.version) and release.installer and release.checksum:
                return release
        return None

    # ---------- downloading and installing ----------

    def path_for(self, release: Release) -> Path:
        return self.folder / f"Nova-Setup-{release.version}.exe"

    def download(self, release: Release, progress: Callable[[int], None] = lambda _percent: None) -> Path:
        """The verified installer for this release (downloaded once; a bad or cut-off download is deleted)."""
        if not release.installer or not release.checksum:
            raise UpdateError(f"{release.version} has no installer to update with; download it from {release.page}")
        target = self.path_for(release)
        expected = self._expected_hash(release)
        if target.exists() and _sha256(target) == expected:
            return target
        self.folder.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(".part")
        try:
            request = Request(release.installer, headers={"User-Agent": "Nova-updater"})
            with self._open(request, timeout=60) as response, partial.open("wb") as file:
                total, done, shown = int(response.headers.get("Content-Length") or 0), 0, -1
                while chunk := response.read(CHUNK):
                    file.write(chunk)
                    done += len(chunk)
                    percent = done * 100 // total if total else 0
                    if percent != shown:
                        shown = percent
                        progress(percent)
        except (URLError, TimeoutError, OSError) as exc:
            partial.unlink(missing_ok=True)
            raise UpdateError(f"the download stopped ({type(exc).__name__}); Nova will try again later") from None
        if _sha256(partial) != expected:
            partial.unlink(missing_ok=True)
            raise UpdateError(f"the {release.version} download was damaged (its checksum didn't match), so it wasn't kept")
        partial.replace(target)
        self._tidy(keep=target)
        return target

    def _expected_hash(self, release: Release) -> str:
        request = Request(release.checksum, headers={"User-Agent": "Nova-updater"})
        try:
            with self._open(request, timeout=20) as response:
                text = response.read().decode("utf-8", "replace")
        except (URLError, TimeoutError, OSError) as exc:
            raise UpdateError(f"couldn't get the checksum ({type(exc).__name__})") from None
        found = re.search(r"\b[0-9a-fA-F]{64}\b", text)
        if not found:
            raise UpdateError(f"{release.version}'s checksum file is unreadable, so it won't be installed")
        return found.group(0).lower()

    def _tidy(self, keep: Path) -> None:
        """Keeps the newest few installers (the one before is the way back) and drops the rest."""
        installers = sorted(self.folder.glob("Nova-Setup-v*.exe"), key=lambda path: version_key(
            path.stem.removeprefix("Nova-Setup-")) or (0, 0, 0), reverse=True)
        for old in installers[KEPT_INSTALLERS:]:
            if old != keep:
                old.unlink(missing_ok=True)

    def install(self, installer: Path) -> None:
        """Starts the silent install; it closes this Nova, replaces it and starts the new one."""
        if not self.can_install():
            raise UpdateError("this copy of Nova wasn't installed with Nova-Setup.exe, so it can't replace itself")
        if not installer.is_file():
            raise UpdateError("the downloaded update is gone; check again")
        self._run([str(installer), *SILENT_INSTALL])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def default_folder() -> Path:
    base = os.environ.get("ALFRED_DATA_DIR") or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Alfred" / "DesktopData"
    return Path(base) / "updates"
