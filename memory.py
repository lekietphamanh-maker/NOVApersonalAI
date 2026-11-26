"""Small, dependency-free SQLite memory for chat history and local tasks."""
from __future__ import annotations

import json
import re
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def default_database_path() -> Path:
    """Keep desktop data under Nova's per-user folder; portable data is launcher-relative."""
    configured = os.environ.get("ALFRED_DATA_DIR")
    if configured:
        return Path(configured) / "memory.sqlite3"
    # Compatibility path for running the original source tree directly.
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "JarvisLocalAssistant" / "memory.sqlite3"
    return Path.home() / ".local" / "share" / "alfred-local-assistant" / "memory.sqlite3"


class Memory:
    """SQLite store for recent conversation messages and captured tasks."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.shared = None  # a pc_sync.SharedMemory while facts and tasks are shared with the owner's other PC
        self._sharing = threading.RLock()  # a merge never sees a remember or forget halfway done
        self._preserve_legacy_database()
        self._initialize()

    def _share(self, kind: str, op: str, text: str) -> None:
        if self.shared is not None:
            self.shared.record(kind, op, text)

    def _preserve_legacy_database(self) -> None:
        """Back up old JARVIS memory only when the desktop launcher opts in."""
        if os.environ.get("ALFRED_ALLOW_LEGACY_MIGRATION") != "1" or self.path.exists():
            return
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            return
        legacy = Path(local_app_data) / "JarvisLocalAssistant" / "memory.sqlite3"
        if legacy.resolve() == self.path.resolve() or not legacy.is_file():
            return
        # SQLite's backup API safely includes committed data from a WAL database.
        with sqlite3.connect(legacy) as source, sqlite3.connect(self.path) as destination:
            source.backup(destination)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'tool')),
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def save_message(self, message: dict[str, Any]) -> None:
        role = message.get("role")
        if role not in {"user", "assistant", "tool"}:
            raise ValueError(f"Unsupported message role: {role!r}")
        content = message.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        metadata = {key: value for key, value in message.items() if key not in {"role", "content"}}
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO messages(role, content, metadata_json) VALUES (?, ?, ?)",
                (role, content, json.dumps(metadata, ensure_ascii=False)),
            )

    def recent_messages(self, limit: int = 20) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT role, content, metadata_json FROM messages ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in reversed(rows):
            message: dict[str, Any] = {"role": row["role"], "content": row["content"]}
            try:
                metadata = json.loads(row["metadata_json"])
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            if isinstance(metadata, dict):
                message.update(metadata)
            messages.append(message)
        # Ollama expects a user message to start a supplied conversation history.
        while messages and messages[0].get("role") != "user":
            messages.pop(0)
        return messages

    def add_task(self, task: str) -> int:
        if not isinstance(task, str):
            raise ValueError("Task text must be a string.")
        clean_task = " ".join(task.split())
        if not clean_task:
            raise ValueError("Task text cannot be empty.")
        if len(clean_task) > 240:
            raise ValueError("Task text must be 240 characters or fewer.")
        with self._sharing, self._connection() as connection:
            self._share("task", "remember", clean_task)
            cursor = connection.execute("INSERT INTO tasks(task) VALUES (?)", (clean_task,))
            return int(cursor.lastrowid)

    def list_tasks(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, task, created_at FROM tasks ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    # Facts the user asked Nova to remember ("remember I prefer aisle seats").
    def add_fact(self, fact: str) -> int:
        clean = " ".join(str(fact).split())[:200]
        if not clean:
            raise ValueError("The fact is empty.")
        with self._sharing, self._connection() as connection:
            self._share("fact", "remember", clean)  # even when known here: the other PC may have forgotten it
            for row in connection.execute("SELECT id, fact FROM facts").fetchall():
                if row["fact"].casefold() == clean.casefold():
                    return int(row["id"])
            return int(connection.execute("INSERT INTO facts(fact) VALUES (?)", (clean,)).lastrowid)

    def list_facts(self, limit: int = 40) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute("SELECT id, fact FROM facts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in reversed(rows)]

    def forget_facts(self, words: str) -> list[str]:
        """Forget every fact containing all of these words; returns what was forgotten."""
        wanted = [word.casefold() for word in re.findall(r"\w{3,}", str(words))]
        if not wanted:
            return []
        with self._sharing:
            forgotten = [fact for fact in self.list_facts(limit=1000) if all(word in fact["fact"].casefold() for word in wanted)]
            for fact in forgotten:
                self._share("fact", "forget", fact["fact"])
            with self._connection() as connection:
                connection.executemany("DELETE FROM facts WHERE id = ?", [(fact["id"],) for fact in forgotten])
        return [fact["fact"] for fact in forgotten]

    def delete_fact(self, fact_id: int) -> None:
        with self._sharing, self._connection() as connection:
            row = connection.execute("SELECT fact FROM facts WHERE id = ?", (int(fact_id),)).fetchone()
            if row is not None:
                self._share("fact", "forget", row["fact"])
            connection.execute("DELETE FROM facts WHERE id = ?", (int(fact_id),))

    def merge_shared(self) -> int:
        """Match facts and tasks to every PC's log: log what only this PC knows (e.g. from before sharing), add
        what another PC remembered, drop what one forgot. Returns how many rows changed here."""
        shared = self.shared
        if shared is None:
            return 0
        changed = 0
        with self._sharing:
            for kind, column in (("fact", "fact"), ("task", "task")):
                table = column + "s"
                newest = shared.newest(kind)
                with self._connection() as connection:
                    here: dict[str, list[int]] = {}
                    for row in connection.execute(f"SELECT id, {column}, created_at FROM {table}").fetchall():  # noqa: S608 - fixed names
                        key = row[column].casefold()
                        if key not in newest:
                            shared.record(kind, "remember", row[column], at=_epoch(row["created_at"]))
                            newest[key] = ("remember", row[column])
                        here.setdefault(key, []).append(int(row["id"]))
                    for key, (op, text) in newest.items():
                        if op == "remember" and key not in here:
                            connection.execute(f"INSERT INTO {table}({column}) VALUES (?)", (text,))  # noqa: S608
                            changed += 1
                        elif op == "forget" and key in here:
                            connection.executemany(f"DELETE FROM {table} WHERE id = ?", [(row_id,) for row_id in here[key]])  # noqa: S608
                            changed += len(here[key])
        return changed


def _epoch(created_at: str) -> float:
    """SQLite's CURRENT_TIMESTAMP (UTC) in epoch seconds."""
    try:
        return datetime.strptime(str(created_at), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0
