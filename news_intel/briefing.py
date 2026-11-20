"""The daily briefing: the most important stories of the last day, by topic, each with its source."""
from __future__ import annotations

from datetime import datetime, timezone

from .config import CATEGORIES
from .store import Store


def make_briefing(store: Store, now: datetime | None = None, per_category: int = 3) -> str:
    now = now or datetime.now(timezone.utc)
    lines = [f"# News briefing · {now:%A %d %B %Y}", ""]
    for category in CATEGORIES:
        items = store.search(category=category, days=1, limit=per_category, now=now)
        if not items:
            continue
        lines.append(f"## {category.capitalize() if category != 'ai' else 'AI'}")
        for item in items:
            about = item["summary"] or item["description"] or ""
            score = f" · importance {item['importance']}/10" if item["importance"] else ""
            lines.append(f"- **{item['title']}** ({item['publisher']}, {item['published_at'][:16].replace('T', ' ')} UTC"
                         f"{score}). {about} {item['original_url']}".rstrip())
        lines.append("")
    if len(lines) == 2:
        lines.append("No articles from the last day yet.")
    return "\n".join(lines).strip() + "\n"
