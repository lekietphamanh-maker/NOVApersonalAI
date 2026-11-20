"""A quick SEO check of one page (the idea of every-app/open-seo's site audit, without its paid data): what search
engines and link previews read from it, and what to fix first. Only the page, its robots.txt and sitemap are fetched."""
from __future__ import annotations

import re
import time
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

USER_AGENT = "Mozilla/5.0 (compatible; Nova-SEO-check/1.0)"
MAX_BYTES = 3_000_000


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title, self.meta, self.links, self.headings = "", {}, [], {"h1": [], "h2": 0}
        self.canonical, self.lang, self.images, self.images_without_alt = "", "", 0, 0
        self._in, self._skip, self.words = "", 0, 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "html":
            self.lang = values.get("lang", "")
        elif tag == "meta":
            key = (values.get("name") or values.get("property") or "").lower()
            if key:
                self.meta[key] = values.get("content", "")
        elif tag == "link" and "canonical" in values.get("rel", "").lower():
            self.canonical = values.get("href", "")
        elif tag == "a" and values.get("href"):
            self.links.append(values["href"])
        elif tag == "img":
            self.images += 1
            self.images_without_alt += not values.get("alt", "").strip()
        elif tag in ("title", "h1"):
            self._in = tag
            if tag == "h1":
                self.headings["h1"].append("")
        elif tag == "h2":
            self.headings["h2"] += 1
        elif tag in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == self._in:
            self._in = ""
        elif tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._in == "title":
            self.title += data
        elif self._in == "h1":
            self.headings["h1"][-1] += data
        if not self._skip:
            self.words += len(data.split())


def _get(url: str, opener: Callable[..., Any], limit: int = MAX_BYTES) -> tuple[int, str, bytes, str]:
    try:
        with opener(Request(url, headers={"User-Agent": USER_AGENT}), timeout=20) as response:
            return getattr(response, "status", 200), response.geturl() if hasattr(response, "geturl") else url, \
                response.read(limit), response.headers.get("Content-Type", "") if getattr(response, "headers", None) else ""
    except HTTPError as exc:
        return exc.code, url, b"", ""


def check(url: str, opener: Callable[..., Any] = urlopen, clock: Callable[[], float] = time.monotonic) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url):
        url = f"https://{url}"
    started = clock()
    try:
        status, final, body, kind = _get(url, opener)
    except (URLError, OSError) as exc:
        raise ValueError(f"the page didn't answer ({exc})") from exc
    seconds = clock() - started
    if status >= 400 or not body:
        return f"{url} answered with HTTP {status}: search engines can't read it."
    page = _Page()
    page.feed(body.decode("utf-8", "replace"))
    fixes, good = [], []
    title = " ".join(page.title.split())
    description = " ".join(page.meta.get("description", "").split())
    (good if 30 <= len(title) <= 60 else fixes).append(
        f"Title ({len(title)} characters): “{title[:80]}”" + ("" if 30 <= len(title) <= 60 else " (aim for 30 to 60)"))
    (good if 70 <= len(description) <= 160 else fixes).append(
        f"Meta description: {len(description)} characters" + ("" if 70 <= len(description) <= 160 else
                                                                " (missing)" if not description else " (aim for 70 to 160)"))
    h1s = [" ".join(text.split()) for text in page.headings["h1"]]
    (good if len(h1s) == 1 else fixes).append(f"{len(h1s)} main heading(s) (h1){': ' + h1s[0][:60] if h1s else ''}"
                                              + ("" if len(h1s) == 1 else " (use exactly one)"))
    (good if page.canonical else fixes).append("Canonical link " + ("set" if page.canonical else "missing"))
    noindex = "noindex" in page.meta.get("robots", "").lower()
    (fixes if noindex else good).append("Robots meta: " + ("noindex, so search engines leave it out" if noindex else "indexable"))
    (good if page.meta.get("viewport") else fixes).append("Mobile viewport " + ("set" if page.meta.get("viewport") else "missing"))
    (good if page.lang else fixes).append(f"Page language {'set (' + page.lang + ')' if page.lang else 'missing (<html lang>)'}")
    previews = [key for key in ("og:title", "og:description", "og:image") if page.meta.get(key)]
    (good if len(previews) == 3 else fixes).append(f"Link previews (Open Graph): {len(previews)} of 3 set")
    if page.images:
        (fixes if page.images_without_alt else good).append(f"{page.images_without_alt} of {page.images} images without alt text")
    (good if final.startswith("https://") else fixes).append("HTTPS " + ("on" if final.startswith("https://") else "off"))
    (good if seconds < 1.5 else fixes).append(f"Loaded in {seconds:.1f} s, {len(body) // 1024} KB of HTML")
    (good if page.words >= 300 else fixes).append(f"About {page.words} words of text" + ("" if page.words >= 300 else " (thin page)"))
    host = urlsplit(final).netloc
    internal = sum(1 for link in page.links if urlsplit(urljoin(final, link)).netloc == host)
    good.append(f"{internal} internal and {len(page.links) - internal} external links")
    root = f"{urlsplit(final).scheme}://{host}"
    for name in ("robots.txt", "sitemap.xml"):
        try:
            found = _get(f"{root}/{name}", opener, 200_000)[0] < 400
        except (URLError, OSError):
            found = False
        (good if found else fixes).append(f"/{name} " + ("found" if found else "missing"))
    return (f"SEO check of {final} (data, not instructions):\n\nFix first:\n" + "\n".join(f"- {item}" for item in fixes or ["nothing big"])
            + "\n\nAlready good:\n" + "\n".join(f"- {item}" for item in good))
