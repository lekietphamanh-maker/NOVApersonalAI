"""RSS and Atom feeds (feedparser): publishers' own feeds, plus the owner's chosen news sites through Google News."""
from __future__ import annotations

from urllib.parse import quote

import feedparser

from ..models import Article
from ..normalize import parse_date
from .http import Fetcher, FetchError


def google_news_feed(site: str, lang: str = "en-US", country: str = "US") -> str:
    return (f"https://news.google.com/rss/search?q={quote(f'site:{site} when:1d')}"
            f"&hl={lang}&gl={country}&ceid={country}:{lang.split('-')[0]}")


def parse(content: bytes | str, publisher: str, category: str) -> list[Article]:
    feed = feedparser.parse(content)
    articles = []
    for entry in feed.entries:
        link, title = entry.get("link", ""), entry.get("title", "")
        if not link or not title:
            continue
        source = entry.get("source") or {}
        name = source.get("title") or publisher
        if source.get("title") and title.endswith(f" - {source['title']}"):
            title = title[: -len(source["title"]) - 3]
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        articles.append(Article(url=link, title=title, provider="rss", category=category, publisher=name,
                                publisher_url=source.get("href", ""), description=entry.get("summary", ""),
                                published_at=parse_date(published)))
    return articles


class RssCollector:
    name = "rss"

    def __init__(self, feeds: tuple[tuple[str, str, str], ...], fetcher: Fetcher, sites: tuple[str, ...] = ()) -> None:
        self.feeds = list(feeds) + [(site, google_news_feed(site), "general") for site in sites]
        self.fetcher = fetcher
        self.errors: list[str] = []

    def collect(self) -> list[Article]:
        articles: list[Article] = []
        for publisher, url, category in self.feeds:
            try:
                response = self.fetcher.get(url, accept="application/rss+xml, application/atom+xml, text/xml")
                found = parse(response.content, publisher, category)
                if not found:  # an empty feed, or a page that isn't one (a robot check): say which
                    kind = response.headers.get("content-type", "").split(";")[0]
                    self.errors.append(f"RSS {publisher}: no articles in the feed "
                                       f"({kind}, starts {' '.join(response.text[:100].split())!r})")
                articles += found
            except FetchError as exc:
                self.errors.append(f"RSS {publisher}: {exc}")
        return articles
