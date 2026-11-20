"""Finding Node.js on this PC (REA and Claude Desktop's bridge need it).

Nova only knew the PATH it started with, so Node installed while Nova was running, or Nova started by its installer
or updater, looked missing. Now PATH is read again from Windows' registry each time, then the usual install places
are tried (the official installer, nvm, fnm, Volta, Scoop, Chocolatey), and the owner can point at node.exe
themselves (an unzipped Node that was never installed). The Node found is put first on PATH, so npx and Claude Code
started from Nova find it too.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

NODE = "node.exe" if sys.platform == "win32" else "node"


def registry_path() -> list[str]:
    """PATH as Windows has it now (the machine's, then this user's), with %VARIABLES% filled in."""
    if sys.platform != "win32":
        return []
    import winreg
    parts: list[str] = []
    for root, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                      (winreg.HKEY_CURRENT_USER, "Environment")):
        try:
            with winreg.OpenKey(root, key) as handle:
                value, _kind = winreg.QueryValueEx(handle, "Path")
        except OSError:
            continue
        parts += [os.path.expandvars(part) for part in str(value).split(os.pathsep) if part.strip()]
    return parts


def refresh_path(environ: dict[str, str] | None = None, fresh: Callable[[], list[str]] = registry_path) -> None:
    """Adds the folders Windows' PATH has gained since Nova started (nothing is removed or reordered)."""
    environ = os.environ if environ is None else environ
    current = environ.get("PATH", "").split(os.pathsep)
    known = {part.rstrip("\\/").lower() for part in current if part}
    added = [part for part in fresh() if part.rstrip("\\/").lower() not in known]
    if added:
        environ["PATH"] = os.pathsep.join([*filter(None, current), *added])


def _newest(pattern_root: Path, pattern: str) -> list[Path]:
    try:
        return sorted(pattern_root.glob(pattern), key=lambda path: str(path), reverse=True)
    except OSError:
        return []


def candidates(environ: dict[str, str] | None = None) -> list[Path]:
    """Where Node is usually installed on Windows, most likely first."""
    environ = os.environ if environ is None else environ
    home = Path(environ.get("USERPROFILE") or Path.home())
    local = Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    roaming = Path(environ.get("APPDATA") or home / "AppData" / "Roaming")
    places = [Path(environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / NODE,
              Path(environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "nodejs" / NODE,
              local / "Programs" / "nodejs" / NODE]
    if environ.get("NVM_SYMLINK"):
        places.append(Path(environ["NVM_SYMLINK"]) / NODE)
    places += _newest(Path(environ.get("NVM_HOME") or roaming / "nvm"), f"v*/{NODE}")
    places += _newest(roaming / "fnm" / "node-versions", f"*/installation/{NODE}")
    places += [Path(environ.get("ProgramFiles", r"C:\Program Files")) / "Volta" / NODE, local / "Volta" / "bin" / NODE,
               home / "scoop" / "apps" / "nodejs" / "current" / NODE,
               home / "scoop" / "apps" / "nodejs-lts" / "current" / NODE,
               Path(environ.get("ProgramData", r"C:\ProgramData")) / "chocolatey" / "bin" / NODE]
    return places


def chosen(path: str) -> Path | None:
    """The owner's own choice: node.exe itself or the folder it's in."""
    if not path:
        return None
    given = Path(os.path.expandvars(path.strip().strip('"')))
    for option in (given, given / NODE):
        if option.is_file() and option.name.lower() == NODE:
            return option
    return None


def find(choice: str = "", fresh: Callable[[], list[str]] = registry_path) -> Path | None:
    own = chosen(choice)
    if own is not None:
        return own
    refresh_path(fresh=fresh)
    on_path = shutil.which("node")
    if on_path:
        return Path(on_path)
    return next((place for place in candidates() if place.is_file()), None)


def use(node: Path) -> None:
    """Node's folder first on PATH, so npx (beside node.exe) and anything Nova starts find this Node."""
    folder = str(node.parent)
    parts = os.environ.get("PATH", "").split(os.pathsep)
    if not parts or parts[0].rstrip("\\/").lower() != folder.rstrip("\\/").lower():
        os.environ["PATH"] = os.pathsep.join([folder, *[part for part in parts if part]])


def version(node: Path, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> tuple[int, int, int] | None:
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    try:
        text = run([str(node), "--version"], capture_output=True, text=True, timeout=10, **flags).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = re.match(r"v(\d+)\.(\d+)\.(\d+)", (text or "").strip())
    return tuple(int(part) for part in found.groups()) if found else None  # type: ignore[return-value]
