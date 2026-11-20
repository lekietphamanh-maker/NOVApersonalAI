"""The news desk end to end with recorded provider answers: normalizing, duplicates, dates, each provider's format,
retries and key hiding, the database and its search, checking the AI's answers, a full run (with a provider failing),
and the cited answers Nova's assistant gets. Live provider checks are at the bottom (CI only)."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from daily_brief import DEFAULT_OUTLETS
from news_intel import analysis, assistant, normalize, pipeline, scheduler
from news_intel.collectors import gdelt, gnews, rss
from news_intel.collectors.http import Fetcher, FetchError, httpx, redact
from news_intel.config import DEFAULT_FEEDS, NewsConfig
from news_intel.models import Article
from news_intel.store import Store

NOW = datetime(2026, 11, 19, 6, 0, tzinfo=timezone.utc)
GNEWS = {"totalArticles": 2, "articles": [
    {"id": "a1", "title": "Chipmaker unveils faster AI processor", "description": "Nvidia said the chip doubles speed.",
     "content": "…", "url": "https://www.example.com/tech/chip?utm_source=gnews", "image": "https://img/1.jpg",
     "publishedAt": "2026-11-19T04:30:00Z", "lang": "en", "source": {"id": "s1", "name": "Example Tech",
                                                                     "url": "https://www.example.com", "country": "us"}},
    {"title": "", "url": "https://broken.example.com"}]}
GDELT = {"articles": [{"url": "https://news.example.org/world/summit/", "url_mobile": "", "title": "Leaders meet at summit",
                       "seendate": "20261119T031500Z", "socialimage": "", "domain": "news.example.org",
                       "language": "English", "sourcecountry": "France"}]}
RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Wire</title>
<item><title>Storm hits coast - Coastal Daily</title><link>https://coastal.example.net/storm</link>
<source url="https://coastal.example.net">Coastal Daily</source><description>&lt;p&gt;Heavy rain&lt;/p&gt;</description>
<pubDate>Thu, 19 Nov 2026 02:00:00 GMT</pubDate></item>
<item><title>Old story</title><link>https://coastal.example.net/old</link><pubDate>Mon, 02 Nov 2026 02:00:00 GMT</pubDate></item>
</channel></rss>"""


class FakeResponse:
    def __init__(self, status: int = 200, body: object = None, text: str | None = None, headers: dict | None = None):
        self.status_code, self.headers = status, headers or {}
        self.content = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else (text or "").encode()
        self.text = text if text is not None else self.content.decode()

    def json(self):
        return json.loads(self.content)


class FakeClient:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def get(self, url, params=None, headers=None):
        self.calls.append((url, dict(params or {})))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def fetcher(*answers) -> Fetcher:
    return Fetcher(client=FakeClient(answers), sleep=lambda _seconds: None)


class NormalizeTests(unittest.TestCase):
    def test_one_link_per_story(self) -> None:
        same = ["http://www.example.com/a/b/?utm_source=x&id=7#top", "https://example.com/a/b?id=7&fbclid=abc",
                "https://EXAMPLE.com//a/b?id=7"]
        self.assertEqual({normalize.canonical_url(url) for url in same}, {"https://example.com/a/b?id=7"})
        self.assertEqual(normalize.canonical_url("not a link"), "")

    def test_headline_fingerprint_and_dates(self) -> None:
        self.assertEqual(normalize.title_key("Storm Hits Coast! - Coastal Daily", "Coastal Daily"), "storm hits coast")
        self.assertEqual(normalize.parse_date("20261119T031500Z"), datetime(2026, 11, 19, 3, 15, tzinfo=timezone.utc))
        self.assertEqual(normalize.parse_date("2026-11-19T04:30:00Z").hour, 4)
        self.assertEqual(normalize.parse_date("Thu, 19 Nov 2026 02:00:00 GMT").hour, 2)
        self.assertEqual(normalize.parse_date(time.strptime("2026-11-19 01:00", "%Y-%m-%d %H:%M")).hour, 1)
        self.assertIsNone(normalize.parse_date("yesterday-ish"))
        article = Article(url="https://x.com/a", title="t", provider="rss")
        for published, problem in ((None, "no publication date"), (NOW + timedelta(hours=5), "dated in the future"),
                                   (NOW - timedelta(days=5), "too old"), (NOW - timedelta(hours=3), "")):
            article.published_at = published
            self.assertEqual(normalize.date_problem(article, NOW, 72), problem)

    def test_category_from_the_words_when_the_provider_has_none(self) -> None:
        guess = lambda title, category="general": normalize.guess_category(Article("u", title, "rss", category=category))  # noqa: E731
        self.assertEqual(guess("OpenAI releases a new language model"), "ai")
        self.assertEqual(guess("Wildfire emissions break records"), "environment")
        self.assertEqual(guess("Anything at all", "sports"), "sports")
        self.assertEqual(guess("Local bakery opens"), "general")


class ProviderTests(unittest.TestCase):
    def test_each_provider_format(self) -> None:
        [item] = gnews.parse(GNEWS, "technology")
        self.assertEqual((item.publisher, item.country, item.published_at.hour), ("Example Tech", "us", 4))
        [item] = gdelt.parse(GDELT, "world")
        self.assertEqual((item.publisher, item.country, item.published_at.minute), ("news.example.org", "France", 15))
        items = rss.parse(RSS, "Wire", "general")
        self.assertEqual((items[0].title, items[0].publisher), ("Storm hits coast", "Coastal Daily"))
        self.assertIn("site%3Areuters.com", rss.google_news_feed("reuters.com"))

    def test_gnews_stops_for_the_day_on_a_used_up_key_and_never_shows_it(self) -> None:
        collector = gnews.GNewsCollector("SECRET123", fetcher(FakeResponse(200, GNEWS), FakeResponse(403, text="quota")))
        articles = collector.collect()
        self.assertEqual(len(articles), 1)
        self.assertEqual(len(collector.fetcher.client.calls), 2)  # stopped after the 403
        self.assertTrue(collector.errors and "SECRET123" not in " ".join(collector.errors))
        self.assertEqual(collector.fetcher.client.calls[0][1]["apikey"], "SECRET123")
        self.assertIn("no API key", (lambda c: (c.collect(), c.errors[0])[1])(gnews.GNewsCollector("", fetcher())))

    def test_gdelt_paces_itself_and_reads_its_plain_text_errors(self) -> None:
        answers = [FakeResponse(200, GDELT), FakeResponse(200, text="Please limit requests to one every 5 seconds")]
        answers += [FakeResponse(200, {"articles": []})] * (len(gdelt.QUERIES) - 2)
        waits: list[float] = []
        collector = gdelt.GdeltCollector(Fetcher(client=FakeClient(answers), sleep=waits.append))
        self.assertEqual(len(collector.collect()), 1)
        self.assertIn("Please limit requests", collector.errors[0])
        self.assertTrue(waits and max(waits) > 5)  # at least 5 s between two GDELT requests
        self.assertIn("sourcelang:english", collector.fetcher.client.calls[0][1]["query"])

    def test_an_unreachable_provider_is_noted_once(self) -> None:
        collector = gdelt.GdeltCollector(fetcher(*[httpx.ConnectError("no route")] * 3))
        self.assertEqual(collector.collect(), [])
        self.assertEqual(len(collector.errors), 1)  # not twelve slow failures

    def test_gdelt_backs_off_then_stops_for_the_run_while_it_limits_this_address(self) -> None:
        waits: list[float] = []
        too_fast = FakeResponse(429, text="Please limit requests to one every 5 seconds")
        collector = gdelt.GdeltCollector(Fetcher(client=FakeClient([too_fast] * 3), sleep=waits.append))
        self.assertEqual(collector.collect(), [])
        self.assertEqual(len(collector.fetcher.client.calls), 3)  # one query and its retries, not twelve queries
        self.assertIn("HTTP 429", collector.errors[0])
        self.assertEqual([wait for wait in waits if wait > 6], [11, 11])  # twice GDELT's own 5.5 s between tries

    def test_a_feed_with_no_articles_says_what_came_back(self) -> None:
        robot_check = FakeResponse(200, text="<html>\n<title>Before you continue to Google</title></html>",
                                   headers={"content-type": "text/html; charset=utf-8"})
        collector = rss.RssCollector((("Wire", "https://example.com/rss", "general"),), fetcher(robot_check))
        self.assertEqual(collector.collect(), [])
        self.assertIn("(text/html, starts '<html> <title>Before you continue", collector.errors[0])

    def test_retries_then_a_clear_error_without_secrets(self) -> None:
        self.assertEqual(fetcher(FakeResponse(503), FakeResponse(200, {"ok": 1})).get("https://api.example.com/x").json(), {"ok": 1})
        with self.assertRaises(FetchError) as caught:
            fetcher(*[httpx.ConnectTimeout("slow")] * 3).get("https://gnews.io/api/v4/search?q=a&apikey=SECRET")
        self.assertNotIn("SECRET", str(caught.exception))
        with self.assertRaises(FetchError) as caught:
            fetcher(FakeResponse(404, text="nope")).get("https://api.example.com/missing")
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(redact("https://x?apikey=abc&q=1"), "https://x?apikey=***&q=1")


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Store(Path(tempfile.mkdtemp()) / "news.sqlite3")
        self.addCleanup(self.store.close)

    def add(self, url, title, publisher="Wire", hours_ago=1, category="general", description=""):
        article = Article(url=url, title=title, provider="rss", publisher=publisher, category=category,
                          description=description, published_at=NOW - timedelta(hours=hours_ago))
        return self.store.add(article, normalize.canonical_url(url), NOW)

    def test_no_duplicates_and_sources_kept(self) -> None:
        first = self.add("https://a.com/1?utm_source=x", "Rates rise")
        self.assertIsNotNone(first)
        self.assertIsNone(self.add("https://a.com/1", "Rates rise again"))  # same link
        self.assertIsNone(self.add("https://a.com/2", "Rates RISE", publisher="Wire"))  # same headline, same publisher
        self.assertIsNotNone(self.add("https://b.com/9", "Rates rise", publisher="Other"))  # another publisher's report
        [row] = self.store.get([first])
        self.assertEqual((row["original_url"], row["url"]), ("https://a.com/1?utm_source=x", "https://a.com/1"))
        self.assertEqual(row["collected_at"], "2026-11-19T06:00:00Z")

    def test_search_by_words_category_window_and_source(self) -> None:
        self.add("https://a.com/1", "Nvidia earnings beat forecasts", category="business", description="Chips sold out")
        self.add("https://a.com/2", "Election results announced", category="politics")
        self.add("https://a.com/3", "Nvidia older news", category="business", hours_ago=24 * 10)
        titles = lambda **kwargs: [row["title"] for row in self.store.search(now=NOW, **kwargs)]  # noqa: E731
        self.assertEqual(titles(query="nvidia"), ["Nvidia earnings beat forecasts"])
        self.assertEqual(titles(query="nvidia", days=30), ["Nvidia earnings beat forecasts", "Nvidia older news"])
        self.assertEqual(titles(category="politics"), ["Election results announced"])
        self.assertEqual(titles(days=7, offset_days=7, query="nvidia"), ["Nvidia older news"])
        self.assertEqual(titles(source="nobody"), [])

    def test_analysis_attempts_related_stories_and_the_run_log(self) -> None:
        one = self.add("https://a.com/1", "Acme buys Beta")
        two = self.add("https://b.com/1", "Acme and Beta merge", publisher="Other")
        entities = {"people": [], "companies": ["Acme", "Beta"], "organizations": []}
        result = {"summary": "s", "category": "business", "subcategory": "m&a", "key_facts": [], "entities": entities,
                  "location": "", "importance": 6, "impact": "", "sentiment": "neutral", "claims": []}
        self.store.save_analysis(one, result, "qwen3:4b")
        self.store.save_analysis(two, result, "qwen3:4b")
        self.store.link_related([two])
        self.assertEqual(self.store.get([two])[0]["related_ids"], [one])
        self.assertEqual(self.store.get([one])[0]["related_ids"], [two])
        three = self.add("https://c.com/1", "Unreadable")
        for _ in range(3):
            self.store.mark_failed(three, "bad JSON")
        self.assertEqual(self.store.pending(10), [])  # three tries, then left alone
        run = self.store.start_run(NOW)
        self.store.finish_run(run, collected=3, errors=["x"], providers={"rss": 3})
        self.assertEqual((self.store.runs()[0]["collected"], self.store.runs()[0]["providers"]), (3, {"rss": 3}))


class AnalysisTests(unittest.TestCase):
    ARTICLE = {"title": "Acme accused of hiding losses, regulator says", "publisher": "Wire",
               "published_at": "2026-11-19T04:00:00Z", "category": "business",
               "description": "The regulator in Berlin said Acme reported 3 billion in losses late; Acme denies it."}

    def test_only_what_the_article_says_is_kept(self) -> None:
        raw = {"summary": "A regulator accused Acme of hiding losses.", "category": "finance", "subcategory": "Regulation",
               "key_facts": ["Acme reported 3 billion in losses late", "Acme's CEO resigned yesterday"],
               "people": ["Jane Doe"], "companies": ["Acme"], "organizations": ["regulator", "Interpol"],
               "location": "Berlin", "importance": 14, "impact": "Investors may react.", "sentiment": "upbeat",
               "claims": [{"text": "Acme hid losses", "kind": "allegation"}, {"text": "x", "kind": "rumour"}]}
        result = analysis.validate(raw, self.ARTICLE)
        self.assertEqual(result["key_facts"], ["Acme reported 3 billion in losses late"])  # the made-up one is dropped
        self.assertEqual(result["entities"], {"people": [], "companies": ["Acme"], "organizations": ["regulator"]})
        self.assertEqual((result["importance"], result["sentiment"], result["location"]), (10, "none", "Berlin"))
        self.assertEqual(result["claims"], [{"text": "Acme hid losses", "kind": "allegation"}])
        self.assertEqual(result["subcategory"], "regulation")
        with self.assertRaises(analysis.AnalysisError):
            analysis.validate({"summary": ""}, self.ARTICLE)

    def test_the_local_model_with_structured_output(self) -> None:
        class Client:
            def __init__(self, answer):
                self.answer, self.sent = answer, None

            def post(self, url, json=None):
                self.sent = json
                if isinstance(self.answer, Exception):
                    raise self.answer
                return FakeResponse(200, {"message": {"content": self.answer}})
        raw = {"summary": "Regulator accuses Acme.", "category": "business", "subcategory": "", "key_facts": [], "people": [],
               "companies": ["Acme"], "organizations": [], "location": "", "importance": 5, "impact": "",
               "sentiment": "negative", "claims": []}
        client = Client(json.dumps(raw))
        result = analysis.OllamaAnalyzer("http://127.0.0.1:11434", "qwen3:4b", client=client).analyze(self.ARTICLE)
        self.assertEqual(result["entities"]["companies"], ["Acme"])
        self.assertEqual((client.sent["format"]["type"], client.sent["think"], client.sent["options"]["num_ctx"]),
                         ("object", False, 4096))
        with self.assertRaises(analysis.Unreachable):
            analysis.OllamaAnalyzer("http://127.0.0.1:9", "m", client=Client(httpx.ConnectError("refused"))).analyze(self.ARTICLE)
        with self.assertRaises(analysis.AnalysisError):
            analysis.OllamaAnalyzer("http://x", "m", client=Client("not json")).analyze(self.ARTICLE)


class PipelineTests(unittest.TestCase):
    class Provider:
        def __init__(self, name, articles=None, fail=False):
            self.name, self.articles, self.fail, self.errors = name, articles or [], fail, []

        def collect(self):
            if self.fail:
                raise RuntimeError("provider down")
            return [Article(**vars(article)) for article in self.articles]

    class Reader:
        model = "test-model"

        def __init__(self, stop_after=None):
            self.stop_after, self.calls = stop_after, 0

        def analyze(self, article):
            self.calls += 1
            if self.stop_after is not None and self.calls > self.stop_after:
                raise analysis.Unreachable("Ollama isn't running")
            return analysis.validate({"summary": f"About {article['title']}.", "category": article["category"],
                                      "subcategory": "", "key_facts": [], "people": [], "companies": [],
                                      "organizations": [], "location": "", "importance": 7, "impact": "",
                                      "sentiment": "none", "claims": []}, article)

    def test_a_whole_run_goes_on_when_a_provider_fails(self) -> None:
        store = Store(Path(tempfile.mkdtemp()) / "news.sqlite3")
        self.addCleanup(store.close)
        fresh = lambda url, title, hours=1: Article(url=url, title=title, provider="rss", publisher="Wire",  # noqa: E731
                                                    published_at=NOW - timedelta(hours=hours))
        good = self.Provider("rss", [fresh("https://a.com/1", "Rates rise"), fresh("https://a.com/1?utm_source=z", "Rates rise"),
                                     fresh("https://a.com/2", "Old", hours=24 * 9), fresh("https://a.com/3", "Wildfire emissions spike")])
        config = NewsConfig(db_path=store.path, max_analyze=10)
        report = pipeline.run(config, store, [self.Provider("gdelt", fail=True), good], self.Reader(), now=NOW)
        self.assertEqual((report.collected, report.added, report.duplicates, report.processed), (4, 2, 1, 2))
        self.assertEqual(report.rejected, {"too old": 1})
        self.assertEqual(report.providers, {"gdelt": 0, "rss": 4})
        self.assertIn("gdelt: provider down", report.errors)
        self.assertIn("**Rates rise**", report.briefing)
        self.assertIn("## Environment", report.briefing)
        logged = store.runs()[0]
        self.assertEqual((logged["added"], logged["processed"], logged["errors"]), (2, 2, ["gdelt: provider down"]))
        again = pipeline.run(config, store, [good], self.Reader(), now=NOW)
        self.assertEqual((again.added, again.duplicates), (0, 3))  # the second morning adds nothing twice

    def test_without_the_ai_the_articles_wait_for_the_next_run(self) -> None:
        store = Store(Path(tempfile.mkdtemp()) / "news.sqlite3")
        self.addCleanup(store.close)
        articles = [Article(url=f"https://a.com/{n}", title=f"Story {n}", provider="rss", publisher="Wire",
                            published_at=NOW - timedelta(minutes=n)) for n in range(1, 4)]
        report = pipeline.run(NewsConfig(db_path=store.path), store, [self.Provider("rss", articles)], self.Reader(stop_after=1), now=NOW)
        self.assertEqual((report.added, report.processed, report.failed), (3, 1, 0))
        self.assertIn("AI analysis stopped", report.errors[-1])
        self.assertEqual(len(store.pending(10)), 2)
        self.assertEqual(len(store.search(query="story", now=NOW)), 3)  # searchable before the AI reads them


class AssistantTests(unittest.TestCase):
    def test_answers_carry_title_publisher_date_and_link(self) -> None:
        store = Store(Path(tempfile.mkdtemp()) / "news.sqlite3")
        self.addCleanup(store.close)
        self.assertIn("database is empty", assistant.lookup(store, now=NOW))
        article = Article(url="https://wire.com/acme", title="Acme accused of fraud", provider="rss", publisher="Wire",
                          category="business", published_at=NOW - timedelta(hours=2), description="Regulators allege fraud.")
        article_id = store.add(article, normalize.canonical_url(article.url), NOW)
        store.save_analysis(article_id, {"summary": "Regulators allege Acme hid losses.", "category": "business",
                                         "subcategory": "", "key_facts": ["Regulators allege fraud"], "entities": {},
                                         "location": "", "importance": 8, "impact": "Shareholders",
                                         "sentiment": "negative", "claims": [{"text": "Acme hid losses", "kind": "allegation"}]}, "m")
        text = assistant.lookup(store, "acme", now=NOW)
        self.assertIn("Acme accused of fraud | Wire | 2026-11-19 04:00 UTC | https://wire.com/acme", text)
        self.assertIn("Not confirmed (allegation or speculation): Acme hid losses", text)
        self.assertIn("cite each one you use by title, publisher, date and link", text)
        self.assertIn("No articles", assistant.lookup(store, "zebra", now=NOW))


class ScheduleTests(unittest.TestCase):
    def test_once_a_day_from_six(self) -> None:
        morning = datetime(2026, 11, 19, 5, 59)
        self.assertFalse(scheduler.due(morning, "06:00", None))
        self.assertTrue(scheduler.due(morning.replace(hour=6, minute=0), "06:00", date(2026, 11, 18)))
        self.assertTrue(scheduler.due(morning.replace(hour=14), "06:00", date(2026, 11, 18)))  # caught up after a late start
        self.assertFalse(scheduler.due(morning.replace(hour=14), "06:00", date(2026, 11, 19)))
        self.assertEqual(scheduler.run_time("nonsense").hour, 6)


@unittest.skipUnless(os.environ.get("ALFRED_TEST_DOWNLOADS") == "1", "live providers only when ALFRED_TEST_DOWNLOADS=1")
class LiveProviderTests(unittest.TestCase):
    """The real services, from the CI machine: GDELT (no key), every default feed and the owner's sites through
    Google News, GNews when a key is set. Each prints what it found, so the CI log shows which source is broken."""

    def fetcher(self, retries: int = 2) -> Fetcher:
        fetch = Fetcher(retries=retries)
        self.addCleanup(fetch.client.close)
        return fetch

    def test_gdelt_answers_in_the_format_we_read(self) -> None:
        collector = gdelt.GdeltCollector(self.fetcher(retries=4), max_records=5)
        two_queries = {category: gdelt.QUERIES[category] for category in ("world", "ai")}
        with mock.patch.dict(gdelt.QUERIES, two_queries, clear=True):
            articles = collector.collect()
        print("GDELT:", len(articles), [(item.publisher, item.title[:50]) for item in articles[:3]], collector.errors)
        if not articles and any("HTTP 429" in error for error in collector.errors):
            self.skipTest("GDELT kept limiting this shared CI address (HTTP 429), so its format wasn't checked here")
        self.assertTrue(articles, collector.errors)
        self.assertTrue(all(item.published_at for item in articles))

    def test_every_default_feed_has_fresh_articles(self) -> None:
        now, fetch, broken = datetime.now(timezone.utc), self.fetcher(), []
        sites = [(f"Google News · {site}", rss.google_news_feed(site), "general") for site in DEFAULT_OUTLETS]
        for publisher, url, category in [*sites, *DEFAULT_FEEDS]:
            collector = rss.RssCollector(((publisher, url, category),), fetch)
            items = collector.collect()
            fresh = [item for item in items if not normalize.date_problem(item, now, NewsConfig.max_age_hours)]
            newest = max((item.published_at for item in items if item.published_at), default=None)
            print(f"{publisher}: {len(items)} articles, {len(fresh)} fresh, newest {newest}", *collector.errors)
            if not fresh:
                broken.append(publisher)
        self.assertFalse(broken, f"no fresh articles from {broken}")

    @unittest.skipUnless(os.environ.get("GNEWS_API_KEY"), "set the GNEWS_API_KEY secret to test GNews")
    def test_gnews(self) -> None:
        collector = gnews.GNewsCollector(os.environ["GNEWS_API_KEY"], Fetcher(), max_articles=3)
        self.assertTrue(gnews.parse(collector._get("top-headlines", {"category": "general"}), "general"))


if __name__ == "__main__":
    unittest.main()
