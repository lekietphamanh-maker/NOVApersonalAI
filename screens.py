"""Nova on other screens: a TV dashboard and a touch control deck (old iPad, touch laptop).

TV: open http://<this PC>:8767/tv once in the TV's browser. It shows a 4-digit code; click Allow in Nova and the
TV gets its own read-only screen code (kept in the TV's browser). Plain HTTP, because TVs can't install Nova's
certificate, so that code can only read what Nova shows on screen (captions, weather, music, timers, what you slid
onto the TV) and nothing else. Forget all TVs in SETTINGS.

Deck: Nova Lite's HTTPS app at /deck, with Nova Lite's pairing, because it presses keys on this PC. Only the fixed
actions below exist: no free typing, nothing that runs a program other than the few listed.
"""
from __future__ import annotations

import hmac
import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable

PAIRING_SECONDS = 300
MAX_PENDING = 4

# deck action -> (kind, what): keys are combos for screen_assist.send_keys_spec, media are media_keys actions.
DECK_ACTIONS: dict[str, tuple[str, str]] = {
    "previous": ("media", "previous"), "play_pause": ("media", "play_pause"), "next": ("media", "next"),
    "volume_up": ("media", "volume_up"), "volume_down": ("media", "volume_down"), "mute": ("media", "mute"),
    "copy": ("keys", "ctrl+c"), "paste": ("keys", "ctrl+v"), "cut": ("keys", "ctrl+x"), "undo": ("keys", "ctrl+z"),
    "redo": ("keys", "ctrl+y"), "select_all": ("keys", "ctrl+a"), "save": ("keys", "ctrl+s"), "find": ("keys", "ctrl+f"),
    "new_tab": ("keys", "ctrl+t"), "close_tab": ("keys", "ctrl+w"), "reopen_tab": ("keys", "ctrl+shift+t"),
    "switch_app": ("keys", "alt+tab"), "desktop": ("keys", "win+d"), "task_view": ("keys", "win+tab"),
    "snip": ("keys", "win+shift+s"), "page_up": ("keys", "pageup"), "page_down": ("keys", "pagedown"),
    "enter": ("keys", "enter"), "escape": ("keys", "esc"),
    "notepad": ("app", "notepad.exe"), "calculator": ("app", "calc.exe"), "explorer": ("app", "explorer.exe"),
    "browser": ("app", "https://www.google.com"), "spotify": ("app", "spotify:"),
    "nova_stop": ("nova", "stop"), "creative": ("nova", "creative"), "photo": ("nova", "photo"),
    "brain_now": ("nova", "brain_now"), "tv_clear": ("nova", "tv_clear"),
}


class ScreenPairing:
    """TVs that asked to show Nova (pending, with a code) and the ones allowed (a read-only token each)."""

    def __init__(self, path: Path, on_request: Callable[[str], None] = lambda _code: None) -> None:
        self.path = Path(path)
        self.on_request = on_request
        self._pending: dict[str, dict[str, Any]] = {}  # session -> {code, at, token}
        self._lock = threading.Lock()

    def _load(self) -> list[str]:
        try:
            return [str(token) for token in json.loads(self.path.read_text(encoding="utf-8")).get("tokens", [])]
        except (OSError, ValueError, AttributeError):
            return []

    def _save(self, tokens: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"tokens": tokens[-12:]}), encoding="utf-8")

    def hello(self) -> dict[str, str]:
        """A TV asks: a session for it to poll and a code to show (the owner allows that code in Nova)."""
        now = time.time()
        with self._lock:
            self._pending = {key: value for key, value in self._pending.items() if now - value["at"] < PAIRING_SECONDS}
            while len(self._pending) >= MAX_PENDING:
                self._pending.pop(next(iter(self._pending)))
            session, code = secrets.token_urlsafe(18), f"{secrets.randbelow(9000) + 1000}"
            self._pending[session] = {"code": code, "at": now, "token": ""}
        self.on_request(code)
        return {"session": session, "code": code}

    def status(self, session: str) -> dict[str, Any]:
        with self._lock:
            entry = self._pending.get(session)
            if entry is None or time.time() - entry["at"] > PAIRING_SECONDS:
                return {"approved": False, "expired": True}
            if not entry["token"]:
                return {"approved": False}
            self._pending.pop(session)
        return {"approved": True, "token": entry["token"]}

    def allow(self, code: str) -> bool:
        """The owner allowed the TV showing this code."""
        with self._lock:
            entry = next((value for value in self._pending.values() if hmac.compare_digest(value["code"], str(code))
                          and time.time() - value["at"] < PAIRING_SECONDS), None)
            if entry is None:
                return False
            entry["token"] = secrets.token_urlsafe(24)
            tokens = self._load()
            self._save(tokens + [entry["token"]])
        return True

    def allowed(self, token: str) -> bool:
        return bool(token) and any(hmac.compare_digest(token, known) for known in self._load())

    def forget_all(self) -> None:
        self._save([])

    @property
    def count(self) -> int:
        return len(self._load())


def slide_payload(kind: str, title: str = "", body: str = "", image: str = "") -> dict[str, Any]:
    """Something shown big on the TV: a reply, a note, the song, the weather, a picture (data URL)."""
    kind = kind if kind in ("text", "music", "weather", "image", "note") else "text"
    if image and not image.startswith("data:image/"):
        image = ""
    return {"id": secrets.token_hex(4), "kind": kind, "title": " ".join(str(title).split())[:120],
            "body": str(body).strip()[:4000], "image": image[:3_000_000], "at": time.time()}
