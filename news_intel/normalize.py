"""Clean, comparable articles: one canonical link per story, a title fingerprint, checked dates, a category."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .config import CATEGORIES
from .models import Article

_TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|dclid|mc_cid|mc_eid|ref|ref_src|cmpid|ocid|smid|cmp|taid|at_.*|"
                       r"sr_share|share|src|soc_src|soc_trk|guccounter|guce_.*|_ga|ito|intcmp)$", re.IGNORECASE)


def canonical_url(url: str) -> str:
    """The same article under one key: no tracking parameters, fragment, "www." or trailing slash; http = https."""
    parts = urlsplit(str(url).strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    if not host:
        return ""
    query = urlencode(sorted((key, value) for key, value in parse_qsl(parts.query, keep_blank_values=False)
                             if not _TRACKING.match(key)))
    path = re.sub(r"/{2,}", "/", parts.path or "/").rstrip("/") or "/"
    return urlunsplit(("https", host + (f":{parts.port}" if parts.port not in (None, 80, 443) else ""), path, query, ""))


def title_key(title: str, publisher: str = "") -> str:
    """A fingerprint for spotting the same headline twice: lower case, no accents or punctuation, no " - Publisher"."""
    text = str(title)
    if publisher:
        text = re.sub(rf"\s+[-|–—]\s+{re.escape(publisher)}\s*$", "", text, flags=re.IGNORECASE)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def parse_date(value) -> datetime | None:
    """ISO 8601 ("2026-11-19T04:30:00Z"), GDELT ("20261119T043000Z"), RSS dates or a time.struct_time → UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if hasattr(value, "tm_year"):  # feedparser's parsed dates are UTC struct_time
        return datetime(*value[:6], tzinfo=timezone.utc)
    text = str(value).strip()
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except ValueError:
        pass
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(text).astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        return None


def date_problem(article: Article, now: datetime, max_age_hours: int) -> str:
    """Why an article's date can't be used ("" when it can): missing, in the future, or too old."""
    if article.published_at is None:
        return "no publication date"
    if article.published_at > now + timedelta(hours=2):
        return "dated in the future"
    if article.published_at < now - timedelta(hours=max_age_hours):
        return "too old"
    return ""


_CATEGORY_WORDS = {
    "ai": r"\b(artificial intelligence|a\.i\.|machine learning|chatgpt|openai|anthropic|claude|gemini|llm|large language model|deepmind)\b",
    "environment": r"\b(climate|emissions|wildfire|deforestation|pollution|biodiversity|renewable|heatwave|cop\d\d)\b",
    "education": r"\b(school|students|teachers|university|universities|college|education|exam)\b",
    "finance": r"\b(stocks?|shares|markets?|inflation|interest rates?|central bank|fed|bonds?|crypto|bitcoin|nasdaq|dow)\b",
    "politics": r"\b(election|parliament|congress|senate|president|prime minister|minister|vote|campaign|government)\b",
    "health": r"\b(health|disease|virus|vaccine|hospital|cancer|outbreak|medical|drug)\b",
    "science": r"\b(scientists?|study|research|nasa|space|physics|astronom\w+|species|fossil)\b",
    "sports": r"\b(match|league|cup|championship|olympic\w*|tournament|coach|goal|nba|nfl|fifa)\b",
    "technology": r"\b(software|smartphone|chip|semiconductor|app|cyber\w*|tech|startup|apple|google|microsoft)\b",
    "business": r"\b(company|earnings|merger|acquisition|ceo|revenue|profit|layoffs|deal)\b",
    "entertainment": r"\b(film|movie|music|album|celebrity|actor|actress|tv series|box office|grammy|oscar)\b",
}


def guess_category(article: Article) -> str:
    """The provider's category when it has a precise one, else the first topic its words point to."""
    if article.category in CATEGORIES and article.category != "general":
        return article.category
    text = f"{article.title} {article.description}".lower()
    for category, words in _CATEGORY_WORDS.items():
        if re.search(words, text):
            return category
    return "general"


def clean(article: Article) -> Article:
    """Tidy text fields (whitespace, HTML left in descriptions, overly long text)."""
    article.title = " ".join(re.sub(r"<[^>]+>", " ", article.title).split())[:400]
    article.description = " ".join(re.sub(r"<[^>]+>", " ", article.description or "").split())[:1500]
    article.publisher = " ".join((article.publisher or urlsplit(article.url).hostname or "").split())[:120]
    article.category = guess_category(article)
    return article
