"""Settings from environment variables (see .env.example), with defaults that work without any key."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

CATEGORIES = ("world", "politics", "business", "finance", "technology", "ai", "science", "health", "entertainment",
              "sports", "environment", "education", "general")

# Publishers read directly (their own feeds keep the original article links). Change them with NEWS_RSS_FEEDS.
# CNN stopped updating its RSS in 2023: CNN comes in through Google News with the owner's sites.
DEFAULT_FEEDS: tuple[tuple[str, str, str], ...] = (
    ("NBC News", "https://feeds.nbcnews.com/nbcnews/public/news", "general"),
    ("ABC News", "https://abcnews.go.com/abcnews/topstories", "general"),
    ("BBC News", "https://feeds.bbci.co.uk/news/world/rss.xml", "world"),
    ("NPR", "https://feeds.npr.org/1001/rss.xml", "general"),
    ("The Guardian", "https://www.theguardian.com/world/rss", "world"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", "world"),
    ("TechCrunch", "https://techcrunch.com/feed/", "technology"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", "technology"),
    ("ScienceDaily", "https://www.sciencedaily.com/rss/all.xml", "science"),
)


def load_env_file(path: Path | str = ".env") -> None:
    """KEY=value lines from a .env file into the environment, without replacing what is already set."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        key, equals, value = line.strip().partition("=")
        if equals and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.split(" #", 1)[0].strip().strip('"').strip("'"))


def data_dir() -> Path:
    """Nova's data folder (the same one the app uses)."""
    return Path(os.environ.get("ALFRED_DATA_DIR")
                or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Alfred" / "DesktopData")


def _feeds(raw: str) -> tuple[tuple[str, str, str], ...]:
    """NEWS_RSS_FEEDS: "Name|https://feed|category; Name|https://feed|category"."""
    feeds = []
    for entry in raw.split(";"):
        parts = [part.strip() for part in entry.split("|")]
        if len(parts) >= 2 and parts[1].startswith(("http://", "https://")):
            category = parts[2] if len(parts) > 2 and parts[2] in CATEGORIES else "general"
            feeds.append((parts[0] or parts[1], parts[1], category))
    return tuple(feeds)


def gnews_key() -> str:
    """GNEWS_API_KEY, else the key saved from Nova's BRIEF panel (a file in Nova's data folder). Never logged."""
    key = os.environ.get("GNEWS_API_KEY", "").strip()
    if key:
        return key
    try:
        return (data_dir() / "gnews_api_key").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@dataclass
class NewsConfig:
    db_path: Path = field(default_factory=lambda: Path(os.environ.get("NEWS_DB_PATH") or data_dir() / "news.sqlite3"))
    gnews_key: str = field(default_factory=gnews_key)
    gnews_lang: str = field(default_factory=lambda: os.environ.get("NEWS_GNEWS_LANG", "en"))
    gnews_country: str = field(default_factory=lambda: os.environ.get("NEWS_GNEWS_COUNTRY", "us"))
    gnews_max: int = 10                      # articles per request (the free plan's ceiling)
    gdelt: bool = field(default_factory=lambda: os.environ.get("NEWS_GDELT", "1") != "0")
    gdelt_max: int = 25                      # articles per category query (GDELT allows up to 250)
    feeds: tuple[tuple[str, str, str], ...] = field(
        default_factory=lambda: _feeds(os.environ.get("NEWS_RSS_FEEDS", "")) or DEFAULT_FEEDS)
    google_news_sites: tuple[str, ...] = ()  # the owner's own news sites, read through Google News RSS
    run_at: str = field(default_factory=lambda: os.environ.get("NEWS_RUN_AT", "06:00"))
    llm_model: str = field(default_factory=lambda: os.environ.get("NEWS_LLM_MODEL", "qwen3:4b"))
    ollama_url: str = field(default_factory=lambda: (os.environ.get("ALFRED_API_URL")
                                                     or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434"))
    max_analyze: int = field(default_factory=lambda: int(os.environ.get("NEWS_MAX_ANALYZE", "120")))
    max_age_hours: int = 72                  # older articles are not collected; the last 24 hours come first
