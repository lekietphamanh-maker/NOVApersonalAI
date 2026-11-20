"""The news database: SQLite now (one file in Nova's data folder), the same tables in Postgres/Supabase later
(migrations/postgres). Each article is stored once, by its canonical link, with its source kept for checking.

Migrations are numbered and applied in order on open (PRAGMA user_version); full-text search uses FTS5 when this
SQLite has it, plain LIKE otherwise.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import Article
from .normalize import title_key

MIGRATIONS = [
    """
    CREATE TABLE articles (
        id INTEGER PRIMARY KEY,
        url TEXT NOT NULL UNIQUE,                 -- canonical link: one row per story
        original_url TEXT NOT NULL,               -- exactly as the provider gave it, for checking
        title TEXT NOT NULL,
        title_key TEXT NOT NULL,
        publisher TEXT NOT NULL DEFAULT '',
        publisher_url TEXT NOT NULL DEFAULT '',
        provider TEXT NOT NULL,
        language TEXT NOT NULL DEFAULT '',
        country TEXT NOT NULL DEFAULT '',
        category TEXT NOT NULL DEFAULT 'general',
        subcategory TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        image TEXT NOT NULL DEFAULT '',
        published_at TEXT NOT NULL,               -- UTC, from the source
        collected_at TEXT NOT NULL,               -- UTC, when Nova collected it
        summary TEXT NOT NULL DEFAULT '',
        key_facts TEXT NOT NULL DEFAULT '[]',
        entities TEXT NOT NULL DEFAULT '{}',
        location TEXT NOT NULL DEFAULT '',
        importance INTEGER,
        impact TEXT NOT NULL DEFAULT '',
        sentiment TEXT NOT NULL DEFAULT '',
        claims TEXT NOT NULL DEFAULT '[]',
        related_ids TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'new',       -- new, processed, failed
        attempts INTEGER NOT NULL DEFAULT 0,
        error TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL DEFAULT '',
        processed_at TEXT
    );
    CREATE INDEX articles_published ON articles(published_at);
    CREATE INDEX articles_category ON articles(category, published_at);
    CREATE INDEX articles_status ON articles(status, published_at);
    CREATE INDEX articles_title_key ON articles(title_key);
    CREATE TABLE runs (
        id INTEGER PRIMARY KEY,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        collected INTEGER NOT NULL DEFAULT 0,
        added INTEGER NOT NULL DEFAULT 0,
        duplicates INTEGER NOT NULL DEFAULT 0,
        rejected TEXT NOT NULL DEFAULT '{}',
        processed INTEGER NOT NULL DEFAULT 0,
        failed INTEGER NOT NULL DEFAULT 0,
        providers TEXT NOT NULL DEFAULT '{}',
        errors TEXT NOT NULL DEFAULT '[]',
        briefing TEXT NOT NULL DEFAULT ''
    );
    """,
]
FTS = """
CREATE VIRTUAL TABLE articles_fts USING fts5(title, description, summary, publisher, content='articles',
                                             content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER articles_ai AFTER INSERT ON articles BEGIN
  INSERT INTO articles_fts(rowid, title, description, summary, publisher)
  VALUES (new.id, new.title, new.description, new.summary, new.publisher);
END;
CREATE TRIGGER articles_ad AFTER DELETE ON articles BEGIN
  INSERT INTO articles_fts(articles_fts, rowid, title, description, summary, publisher)
  VALUES ('delete', old.id, old.title, old.description, old.summary, old.publisher);
END;
CREATE TRIGGER articles_au AFTER UPDATE OF title, description, summary, publisher ON articles BEGIN
  INSERT INTO articles_fts(articles_fts, rowid, title, description, summary, publisher)
  VALUES ('delete', old.id, old.title, old.description, old.summary, old.publisher);
  INSERT INTO articles_fts(rowid, title, description, summary, publisher)
  VALUES (new.id, new.title, new.description, new.summary, new.publisher);
END;
"""
JSON_FIELDS = ("key_facts", "entities", "claims", "related_ids")


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.fts = False
        self._migrate()

    def _migrate(self) -> None:
        with self._lock, self.db:
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            for number, script in enumerate(MIGRATIONS, start=1):
                if version < number:
                    self.db.executescript(script)
                    self.db.execute(f"PRAGMA user_version = {number}")
            exists = self.db.execute("SELECT 1 FROM sqlite_master WHERE name = 'articles_fts'").fetchone()
            if not exists:
                try:
                    self.db.executescript(FTS)
                    self.db.execute("INSERT INTO articles_fts(articles_fts) VALUES ('rebuild')")
                except sqlite3.OperationalError:  # this SQLite has no FTS5: searches fall back to LIKE
                    pass
            self.fts = bool(self.db.execute("SELECT 1 FROM sqlite_master WHERE name = 'articles_fts'").fetchone())

    def close(self) -> None:
        self.db.close()

    # ---- articles ----
    def add(self, article: Article, url: str, collected: datetime) -> int | None:
        """The new row's id, or None when it is a duplicate: the same link, or the same headline from the same
        publisher in the last three days."""
        key = title_key(article.title, article.publisher)
        since = iso(collected - timedelta(days=3))
        with self._lock, self.db:
            if self.db.execute("SELECT 1 FROM articles WHERE title_key = ? AND publisher = ? AND published_at >= ?",
                               (key, article.publisher, since)).fetchone():
                return None
            cursor = self.db.execute(
                "INSERT OR IGNORE INTO articles (url, original_url, title, title_key, publisher, publisher_url, provider, "
                "language, country, category, description, image, published_at, collected_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (url, article.url, article.title, key, article.publisher, article.publisher_url, article.provider,
                 article.language, article.country, article.category, article.description, article.image,
                 iso(article.published_at), iso(collected)))
            return cursor.lastrowid if cursor.rowcount else None

    def pending(self, limit: int) -> list[dict[str, Any]]:
        """Articles still to analyze, newest first (a failed one is tried again, up to three times)."""
        with self._lock:
            rows = self.db.execute("SELECT * FROM articles WHERE status IN ('new', 'failed') AND attempts < 3 "
                                   "ORDER BY published_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(row) for row in rows]

    def save_analysis(self, article_id: int, analysis: dict[str, Any], model: str) -> None:
        with self._lock, self.db:
            self.db.execute(
                "UPDATE articles SET summary = ?, category = ?, subcategory = ?, key_facts = ?, entities = ?, location = ?, "
                "importance = ?, impact = ?, sentiment = ?, claims = ?, status = 'processed', attempts = attempts + 1, "
                "error = '', model = ?, processed_at = ? WHERE id = ?",
                (analysis["summary"], analysis["category"], analysis["subcategory"], json.dumps(analysis["key_facts"]),
                 json.dumps(analysis["entities"]), analysis["location"], analysis["importance"], analysis["impact"],
                 analysis["sentiment"], json.dumps(analysis["claims"]), model, iso(datetime.now(timezone.utc)), article_id))

    def mark_failed(self, article_id: int, error: str) -> None:
        with self._lock, self.db:
            self.db.execute("UPDATE articles SET status = 'failed', attempts = attempts + 1, error = ? WHERE id = ?",
                            (str(error)[:300], article_id))

    def link_related(self, article_ids: list[int], days: int = 7) -> None:
        """Related stories: the same headline from another publisher, or two or more shared names."""
        with self._lock, self.db:
            for article_id in article_ids:
                row = self.db.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
                if row is None:
                    continue
                names = {name.lower() for group in json.loads(row["entities"] or "{}").values() for name in group}
                since = iso(datetime.fromisoformat(row["published_at"].replace("Z", "+00:00")) - timedelta(days=days))
                related = []
                for other in self.db.execute("SELECT id, title_key, entities FROM articles WHERE id != ? AND published_at >= ? "
                                             "ORDER BY published_at DESC LIMIT 400", (article_id, since)):
                    shared = names & {name.lower() for group in json.loads(other["entities"] or "{}").values() for name in group}
                    if other["title_key"] == row["title_key"] or len(shared) >= 2:
                        related.append(other["id"])
                if related:
                    self.db.execute("UPDATE articles SET related_ids = ? WHERE id = ?", (json.dumps(related[:10]), article_id))
                    for other_id in related[:10]:
                        current = json.loads(self.db.execute("SELECT related_ids FROM articles WHERE id = ?",
                                                             (other_id,)).fetchone()[0])
                        if article_id not in current:
                            self.db.execute("UPDATE articles SET related_ids = ? WHERE id = ?",
                                            (json.dumps((current + [article_id])[-10:]), other_id))

    def search(self, query: str = "", category: str = "", days: float = 1, offset_days: float = 0, source: str = "",
               limit: int = 8, now: datetime | None = None) -> list[dict[str, Any]]:
        """Articles published in the window [now - offset - days, now - offset], newest day first; within a day the
        best match for the words asked for (full-text rank) and the most important first."""
        now = now or datetime.now(timezone.utc)
        end = now - timedelta(days=offset_days)
        clauses, values = ["a.published_at >= ?", "a.published_at <= ?"], [iso(end - timedelta(days=days)), iso(end)]
        if category:
            clauses.append("a.category = ?")
            values.append(category)
        if source:
            clauses.append("(a.publisher LIKE ? OR a.url LIKE ?)")
            values += [f"%{source}%", f"%{source}%"]
        words = [word for word in "".join(char if char.isalnum() else " " for char in query).split() if len(word) > 1]
        # Words asked for: the newest day first (the latest developments). Top stories: the most important first.
        order = ("substr(a.published_at, 1, 10) DESC, COALESCE(a.importance, 0) DESC, a.published_at DESC" if words
                 else "COALESCE(a.importance, 0) DESC, a.published_at DESC")
        with self._lock:
            if words and self.fts:
                match = " OR ".join(f'"{word}"' for word in words[:12])
                sql = (f"SELECT a.* FROM articles_fts f JOIN articles a ON a.id = f.rowid WHERE articles_fts MATCH ? AND "
                       f"{' AND '.join(clauses)} ORDER BY substr(a.published_at, 1, 10) DESC, "
                       f"bm25(articles_fts) + -0.3 * COALESCE(a.importance, 0), a.published_at DESC LIMIT ?")
                rows = self.db.execute(sql, [match, *values, limit]).fetchall()
            else:
                for word in words[:12]:
                    clauses.append("(a.title LIKE ? OR a.description LIKE ? OR a.summary LIKE ?)")
                    values += [f"%{word}%"] * 3
                rows = self.db.execute(f"SELECT a.* FROM articles a WHERE {' AND '.join(clauses)} ORDER BY {order} LIMIT ?",
                                       [*values, limit]).fetchall()
        return [self._row(row) for row in rows]

    def get(self, article_ids: list[int]) -> list[dict[str, Any]]:
        if not article_ids:
            return []
        with self._lock:
            rows = self.db.execute(f"SELECT * FROM articles WHERE id IN ({','.join('?' * len(article_ids))})",
                                   article_ids).fetchall()
        return [self._row(row) for row in rows]

    def counts(self) -> dict[str, int]:
        with self._lock:
            rows = self.db.execute("SELECT status, COUNT(*) FROM articles GROUP BY status").fetchall()
        counts = {status: count for status, count in rows}
        return {"total": sum(counts.values()), **counts}

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        for name in JSON_FIELDS:
            item[name] = json.loads(item.get(name) or ("{}" if name == "entities" else "[]"))
        return item

    # ---- runs ----
    def start_run(self, now: datetime | None = None) -> int:
        with self._lock, self.db:
            return self.db.execute("INSERT INTO runs (started_at) VALUES (?)",
                                   (iso(now or datetime.now(timezone.utc)),)).lastrowid

    def finish_run(self, run_id: int, **stats: Any) -> None:
        stats = {key: json.dumps(value) if isinstance(value, (dict, list)) else value for key, value in stats.items()}
        with self._lock, self.db:
            self.db.execute(f"UPDATE runs SET finished_at = ?, {', '.join(f'{key} = ?' for key in stats)} WHERE id = ?",
                            (iso(datetime.now(timezone.utc)), *stats.values(), run_id))

    def runs(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for name in ("rejected", "providers", "errors"):
                item[name] = json.loads(item[name] or ("[]" if name == "errors" else "{}"))
            result.append(item)
        return result
