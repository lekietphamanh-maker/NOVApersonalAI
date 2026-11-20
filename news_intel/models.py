"""One news article as every part of the pipeline sees it."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Article:
    url: str                      # the original link, as the provider gave it
    title: str
    provider: str                 # "gnews", "gdelt", "rss"
    publisher: str = ""
    publisher_url: str = ""
    description: str = ""
    published_at: datetime | None = None   # from the source, UTC
    category: str = "general"
    language: str = ""
    country: str = ""
    image: str = ""
    extra: dict = field(default_factory=dict)
