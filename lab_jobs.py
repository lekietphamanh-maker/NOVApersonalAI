"""The jobs Rea and Shannon ran, newest first, so their screens can show past reports again (the reports themselves
are in outputs/ and the Library; this keeps what the screens draw: the blueprint, the findings, the stages)."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

KEEP = 40


class JobLog:
    def __init__(self, path: Path, keep: int = KEEP) -> None:
        self.path, self.keep = Path(path), keep
        self._lock = threading.Lock()
        try:
            self._jobs: list[dict[str, Any]] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._jobs = []
        for job in self._jobs:  # Nova closed while it ran: it isn't running any more
            if job.get("status") == "running":
                job.update(status="failed", error="Nova was closed while it ran")

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._jobs, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)

    def add(self, kind: str, **fields: Any) -> dict[str, Any]:
        job = {"id": uuid.uuid4().hex[:12], "kind": kind, "started": datetime.now().isoformat(timespec="seconds"),
               "status": "running", **fields}
        with self._lock:
            self._jobs = [job, *self._jobs][:self.keep]
            self._save()
        return dict(job)

    def update(self, job_id: str, **changes: Any) -> dict[str, Any] | None:
        with self._lock:
            for index, job in enumerate(self._jobs):
                if job["id"] == job_id:
                    self._jobs[index] = {**job, **changes}
                    self._save()
                    return dict(self._jobs[index])
        return None

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            return next((dict(job) for job in self._jobs if job["id"] == job_id), None)

    def recent(self, kind: str) -> list[dict[str, Any]]:
        """This kind's jobs, newest first, without their heavy parts (for the strip of past reports)."""
        light = ("id", "kind", "title", "target", "started", "status", "error", "counts")
        with self._lock:
            return [{key: job[key] for key in light if key in job} for job in self._jobs if job["kind"] == kind]
