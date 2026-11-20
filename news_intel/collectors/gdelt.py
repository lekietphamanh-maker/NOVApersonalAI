"""GDELT DOC 2.0 API: worldwide coverage, free and without a key. One query per category, at most one request
every 5 seconds (GDELT answers HTTP 429 to faster callers), articles from the last day."""
from __future__ import annotations

from ..models import Article
from ..normalize import parse_date
from .http import Fetcher, FetchError

URL = "https://api.gdeltproject.org/api/v2/doc/doc"
QUERIES = {
    "world": '(war OR summit OR diplomacy OR "united nations" OR ceasefire)',
    "politics": '(election OR parliament OR congress OR "prime minister" OR president)',
    "business": "(earnings OR merger OR acquisition OR company OR layoffs)",
    "finance": '(stocks OR inflation OR "interest rates" OR "central bank" OR markets)',
    "technology": "(technology OR software OR smartphone OR semiconductor OR cybersecurity)",
    "ai": '("artificial intelligence" OR "machine learning" OR "language model" OR chatbot)',
    "science": "(scientists OR research OR nasa OR astronomy OR physics)",
    "health": "(health OR disease OR vaccine OR hospital OR outbreak)",
    "entertainment": "(film OR music OR celebrity OR television OR concert)",
    "sports": "(football OR soccer OR basketball OR tennis OR olympics)",
    "environment": "(climate OR environment OR wildfire OR emissions OR drought)",
    "education": "(education OR school OR university OR students OR teachers)",
}


def parse(payload: dict, category: str) -> list[Article]:
    articles = []
    for item in (payload or {}).get("articles") or []:
        if not item.get("url") or not item.get("title"):
            continue
        articles.append(Article(url=item["url"], title=item["title"], provider="gdelt", category=category,
                                publisher=item.get("domain", ""), published_at=parse_date(item.get("seendate")),
                                language=item.get("language", ""), country=item.get("sourcecountry", ""),
                                image=item.get("socialimage") or ""))
    return articles


class GdeltCollector:
    name = "gdelt"

    def __init__(self, fetcher: Fetcher, max_records: int = 25, language: str = "english") -> None:
        self.fetcher, self.max, self.language = fetcher, max_records, language
        self.errors: list[str] = []

    def collect(self) -> list[Article]:
        articles: list[Article] = []
        for category, query in QUERIES.items():
            params = {"query": f"{query} sourcelang:{self.language}", "mode": "ArtList", "format": "json",
                      "maxrecords": self.max, "timespan": "1d", "sort": "DateDesc"}
            try:
                response = self.fetcher.get(URL, params, "application/json", every=5.5)
                text = response.text.strip()
                if not text.startswith("{"):  # GDELT says what's wrong in plain text (bad query, too fast)
                    self.errors.append(f"GDELT {category}: {text[:160]}")
                    continue
                articles += parse(response.json(), category)
            except FetchError as exc:
                self.errors.append(f"GDELT {category}: {exc}")
                # Unreachable (offline, DNS), or still limiting this address after the retries: the other
                # queries would only wait and fail the same way.
                if exc.status in (None, 429):
                    break
            except ValueError as exc:
                self.errors.append(f"GDELT {category}: unreadable answer ({exc})")
        return articles
