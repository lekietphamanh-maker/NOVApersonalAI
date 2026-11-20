"""GNews API v4 (gnews.io): top headlines by category, plus searches for the topics it has no category for.

Needs an API key (GNEWS_API_KEY, or saved in Nova's BRIEF panel). The free plan allows 100 requests a day and
10 articles per request; one run here makes 14 requests. Without a key this provider is skipped.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..models import Article
from ..normalize import parse_date
from .http import Fetcher, FetchError

BASE = "https://gnews.io/api/v4"
CATEGORIES = {"general": "general", "world": "world", "nation": "politics", "business": "business",
              "technology": "technology", "entertainment": "entertainment", "sports": "sports",
              "science": "science", "health": "health"}
SEARCHES = {"ai": '"artificial intelligence" OR AI', "environment": "climate OR environment",
            "education": "education OR schools OR universities", "finance": "stocks OR markets OR inflation",
            "politics": "election OR parliament OR government"}


def parse(payload: dict, category: str) -> list[Article]:
    articles = []
    for item in (payload or {}).get("articles") or []:
        source = item.get("source") or {}
        if not item.get("url") or not item.get("title"):
            continue
        articles.append(Article(url=item["url"], title=item["title"], provider="gnews", category=category,
                                publisher=source.get("name", ""), publisher_url=source.get("url", ""),
                                description=item.get("description") or "", published_at=parse_date(item.get("publishedAt")),
                                language=item.get("lang", ""), country=source.get("country", ""), image=item.get("image") or ""))
    return articles


class GNewsCollector:
    name = "gnews"

    def __init__(self, key: str, fetcher: Fetcher, lang: str = "en", country: str = "us", max_articles: int = 10) -> None:
        self.key, self.fetcher, self.lang, self.country, self.max = key, fetcher, lang, country, max_articles
        self.errors: list[str] = []

    def _get(self, path: str, params: dict) -> dict:
        response = self.fetcher.get(f"{BASE}/{path}", {**params, "lang": self.lang, "country": self.country,
                                                       "max": self.max, "apikey": self.key}, "application/json", every=1.1)
        return response.json()

    def collect(self) -> list[Article]:
        if not self.key:
            self.errors.append("GNews skipped: no API key (GNEWS_API_KEY or BRIEF → News desk)")
            return []
        articles: list[Article] = []
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        jobs = [("top-headlines", {"category": category}, ours) for category, ours in CATEGORIES.items()]
        jobs += [("search", {"q": query, "from": since, "sortby": "publishedAt"}, ours) for ours, query in SEARCHES.items()]
        for path, params, ours in jobs:
            try:
                articles += parse(self._get(path, params), ours)
            except FetchError as exc:
                self.errors.append(f"GNews {params.get('category') or ours}: {exc}")
                if exc.status in (401, 403, None):  # bad key, the day's quota used up, or GNews unreachable: stop asking
                    break
            except ValueError as exc:
                self.errors.append(f"GNews {ours}: unreadable answer ({exc})")
        return articles
