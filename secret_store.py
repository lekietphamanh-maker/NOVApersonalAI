"""Small secrets (API keys) kept on this PC only, sealed for this user: Windows DPAPI, a Keychain key on the Mac, and a
file only this user can read elsewhere (tests, Linux)."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Callable


def _folder() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Alfred" / "secrets"


def _path(name: str) -> Path:
    if not re.fullmatch(r"[a-z0-9_-]{1,60}", name):
        raise ValueError("bad secret name")
    return _folder() / f"{name}.bin"


def _seal(data: bytes) -> bytes:
    if sys.platform == "win32":
        import win32crypt
        return win32crypt.CryptProtectData(data, "Nova", None, None, None, 0)
    if sys.platform == "darwin":
        import mac
        return mac.protect(data)
    return data


def _open(data: bytes) -> bytes:
    if sys.platform == "win32":
        import win32crypt
        return win32crypt.CryptUnprotectData(data, None, None, None, 0)[1]
    if sys.platform == "darwin":
        import mac
        return mac.unprotect(data)
    return data


def save(name: str, value: str) -> None:
    path = _path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_seal(value.strip().encode()))
    if sys.platform not in ("win32", "darwin"):
        path.chmod(0o600)


def load(name: str) -> str | None:
    try:
        return _open(_path(name).read_bytes()).decode() or None
    except (OSError, ValueError):
        return None
    except Exception:  # sealed for another user or PC: as good as missing
        return None


def forget(name: str) -> None:
    _path(name).unlink(missing_ok=True)


def load_or_move(name: str, read_plain: "Callable[[], str | None]", plain: Path) -> str | None:
    """A secret from the sealed store. One an earlier build left in a plain file (read by `read_plain`) is sealed once
    and the plain file removed; when the store can't take it, the plain file keeps working as before."""
    value = load(name)
    if value is not None:
        return value
    value = read_plain()
    if not value:
        return None
    try:
        save(name, value)
    except OSError:
        return value
    plain.unlink(missing_ok=True)
    return value
