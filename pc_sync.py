"""The owner's PCs (a desktop and a laptop) sharing Nova's memory through one folder they sync themselves.

No cloud: a sync tool such as Syncthing copies the folder device to device. Nova's part is making that safe:
each PC writes only its own files here, so the sync tool never sees two PCs changing the same file.

- Remembered facts and tasks: each change is appended to this PC's log, <folder>/.nova/memory/<pc>.jsonl.
  Every PC reads all the logs and, per fact, the newest event (remember or forget) wins, so the PCs agree
  whatever order the logs arrive in.
- Every few minutes each PC writes <folder>/.nova/pcs/<pc>.json, so the other one can tell when it last saw it.
"""
from __future__ import annotations

import json
import os
import platform
import re
import threading
import time
from pathlib import Path

MAX_TEXT = 240


def this_pc() -> str:
    """This PC's name, safe in a file name: Windows' computer name (DESKTOP-7Q2ABC, MY-LAPTOP)."""
    name = os.environ.get("COMPUTERNAME") or platform.node() or "PC"
    return re.sub(r"[^\w.-]+", "-", name).strip("-.")[:40] or "PC"


def last_seen(folder: Path, pc: str) -> float:
    """When `pc` last said it was here (epoch seconds), 0 if never."""
    try:
        return float(json.loads((Path(folder) / ".nova" / "pcs" / f"{pc}.json").read_text(encoding="utf-8"))["seen"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0.0


class SharedMemory:
    def __init__(self, folder: Path, pc: str) -> None:
        self.folder = Path(folder)
        self.pc = pc
        self._lock = threading.Lock()

    @property
    def logs(self) -> Path:
        return self.folder / ".nova" / "memory"

    def record(self, kind: str, op: str, text: str, at: float | None = None) -> None:
        """Add one change ('fact' or 'task', 'remember' or 'forget') to this PC's log; only this PC writes it."""
        event = {"kind": kind, "op": op, "text": " ".join(str(text).split())[:MAX_TEXT],
                 "at": round(time.time() if at is None else at, 3), "pc": self.pc}
        with self._lock:
            self.logs.mkdir(parents=True, exist_ok=True)
            with (self.logs / f"{self.pc}.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps(event, ensure_ascii=False) + "\n")

    def newest(self, kind: str) -> dict[str, tuple[str, str]]:
        """{casefolded text: (op, text)} of each fact's (or task's) newest event on any PC."""
        newest: dict[str, tuple[tuple[float, str], str, str]] = {}
        for path in sorted(self.logs.glob("*.jsonl")):
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue  # the sync tool is replacing it right now: next time
            for line in lines:
                try:
                    event = json.loads(line)
                    stamp = (float(event["at"]), str(event.get("pc", "")))
                except (ValueError, TypeError, KeyError):
                    continue  # a line that is still arriving
                if not isinstance(event, dict) or event.get("kind") != kind or event.get("op") not in ("remember", "forget"):
                    continue
                text = " ".join(str(event.get("text", "")).split())[:MAX_TEXT]
                key = text.casefold()
                if key and (key not in newest or stamp >= newest[key][0]):
                    newest[key] = (stamp, event["op"], text)
        return {key: (op, text) for key, (_stamp, op, text) in newest.items()}

    def beat(self) -> None:
        """'This PC was here just now', for the other PC's Settings (and for who writes the wiki)."""
        path = self.folder / ".nova" / "pcs" / f"{self.pc}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"pc": self.pc, "seen": round(time.time())}), encoding="utf-8")

    def others(self) -> list[dict]:
        """The other PCs sharing this folder, most recently seen first: [{'pc', 'seen'}]."""
        found = []
        for path in (self.folder / ".nova" / "pcs").glob("*.json"):
            if path.stem != self.pc:
                found.append({"pc": path.stem, "seen": last_seen(self.folder, path.stem)})
        return sorted(found, key=lambda other: -other["seen"])


def ago(seconds: float) -> str:
    """'just now', '5 min ago', '3 h ago', '2 days ago'."""
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{round(seconds / 60)} min ago"
    if seconds < 172_800:
        return f"{round(seconds / 3600)} h ago"
    return f"{round(seconds / 86_400)} days ago"
