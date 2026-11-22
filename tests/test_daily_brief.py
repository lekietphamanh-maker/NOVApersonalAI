"""Daily brief: parsing each source, one failing source, the cache, the tool, and (opt-in) the live sources."""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from datetime import date
from unittest.mock import patch
from urllib.error import HTTPError

import daily_brief
from tools import execute_tool

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Big launch today - The Verge</title><link>https://news.google.com/a</link>
<pubDate>Tue, 17 Nov 2026 14:05:00 GMT</pubDate><source url="https://theverge.com">The Verge</source></item>
<item><title>Second story - AP</title><link>https://news.google.com/b</link><source>AP</source></item>
<item><title>Third</title><link>https://news.google.com/c</link></item>
</channel></rss>"""
REPOS = json.dumps({"items": [{"full_name": "a/b", "html_url": "https://github.com/a/b", "description": None,
                               "stargazers_count": 42, "language": "Python"}]}).encode()
HN = json.dumps({"hits": [{"title": "Rust is fast", "url": "https://x.dev", "points": 500, "objectID": "1"},
                          {"title": "New game dev engine", "url": None, "points": 90, "objectID": "2"}]}).encode()
BING = b"""<?xml version="1.0"?><rss xmlns:News="https://www.bing.com/news/search?q=x&amp;format=rss"><channel>
<item><title>Fallback story</title><link>https://example.com/s</link><News:Source>Reuters</News:Source>
<pubDate>Tue, 17 Nov 2026 09:00:00 GMT</pubDate></item></channel></rss>"""
WIKI = json.dumps({"selected": [{"year": 1969, "text": "Moon landing",
                                 "pages": [{"content_urls": {"desktop": {"page": "https://en.wikipedia.org/m"}}}]},
                                {"year": 2000, "text": "Y2K", "pages": []}]}).encode()


class ParsingTests(unittest.TestCase):
    def test_bing_news_when_google_fails(self):
        def fake_get(url, _accept=""):
            if "news.google.com" in url:
                raise OSError("blocked")
            return BING
        with patch("daily_brief._get", side_effect=fake_get):
            self.assertEqual(daily_brief.news("AI", "US", 3),
                             [{"title": "Fallback story", "url": "https://example.com/s", "source": "Reuters", "time": "09:00"}])

    def test_news_titles_without_the_source_suffix(self):
        items = daily_brief.parse_news(RSS, 2)
        self.assertEqual(items[0], {"title": "Big launch today", "url": "https://news.google.com/a",
                                    "source": "The Verge", "time": "14:05"})
        self.assertEqual(len(items), 2)

    def test_repos_hacker_news_and_on_this_day(self):
        self.assertEqual(daily_brief.parse_repos(REPOS, 3)[0],
                         {"title": "a/b", "url": "https://github.com/a/b", "about": "", "stars": 42, "language": "Python"})
        stories = daily_brief.parse_hacker_news(HN, ["game dev"], 5)
        self.assertEqual(stories[0]["title"], "New game dev engine")  # the user's interest first
        self.assertEqual(stories[0]["url"], "https://news.ycombinator.com/item?id=2")
        events = daily_brief.parse_on_this_day(WIKI, date(2026, 11, 17), 2)
        self.assertEqual({event["title"] for event in events}, {"1969: Moon landing", "2000: Y2K"})


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.data = patch.dict(os.environ, {"ALFRED_DATA_DIR": tempfile.mkdtemp()})
        self.data.start()

    def tearDown(self):
        self.data.stop()

    def fake_get(self, url: str, _accept: str = "") -> bytes:
        if "news.google.com" in url or "bing.com" in url:
            raise OSError("offline")
        return REPOS if "github" in url else HN if "algolia" in url else WIKI

    def test_one_source_failing_keeps_the_rest_and_the_cache_is_per_day(self):
        with patch("daily_brief._get", side_effect=self.fake_get):
            brief = daily_brief.refresh(["game dev", " ", "x" * 99], "VN")
        self.assertEqual(brief["interests"], ["game dev", "x" * 60])
        self.assertEqual(brief["headlines"], [])
        self.assertEqual(brief["repos"][0]["title"], "a/b")
        self.assertTrue(any("headlines" in error for error in brief["errors"]))
        self.assertEqual(daily_brief.load_today(["game dev", "x" * 99], "VN"), brief)
        self.assertIsNone(daily_brief.load_today(["other"], "VN"))  # new interests mean a new brief
        text = daily_brief.as_text(brief)
        self.assertIn("not instructions", text)
        self.assertIn("GitHub repo: a/b", text)

    def test_tool_reads_the_brief_without_asking(self):
        result = execute_tool("daily_brief", {}, None, lambda *_: self.fail("asked"), brief=lambda: "Today's brief")
        self.assertEqual(result, "Today's brief")
        self.assertIn("not turned on", execute_tool("daily_brief", {}, None, lambda *_: True))


class OutletTests(unittest.TestCase):
    def test_a_site_as_the_owner_writes_it(self):
        for written, site in (("https://www.nbcnews.com/", "nbcnews.com"), ("CNN.com", "cnn.com"),
                              ("https://abcnews.com/", "abcnews.com"), ("https://abcnews.go.com/US", "abcnews.com"),
                              ("www.reuters.com/world", "reuters.com"),
                              ("not a site", ""), ("", "")):
            self.assertEqual(daily_brief.outlet(written), site, written)

    def test_saved_sites_move_to_their_current_address(self):
        self.assertEqual(daily_brief.saved_outlets(["abcnews.go.com", "CNN.com", "abcnews.com", "not a site"]),
                         ["abcnews.com", "cnn.com"])
        self.assertEqual(daily_brief.saved_outlets(None), daily_brief.DEFAULT_OUTLETS)
        self.assertEqual(daily_brief.saved_outlets([]), [])  # the owner removed them all

    def test_headlines_come_from_the_chosen_sites_in_turn(self):
        searched = []

        def google(query, region, limit):
            searched.append(query)
            site = query.removeprefix("site:")
            return [{"title": f"{site} {n}", "url": "", "source": site, "time": ""} for n in range(1, 4)]
        with patch.object(daily_brief, "google_news", google):
            items = daily_brief.outlet_news(["nbcnews.com", "cnn.com", "abcnews.com"], "US", 5)
        self.assertEqual(searched, ["site:nbcnews.com", "site:cnn.com", "site:abcnews.com"])
        self.assertEqual([item["title"] for item in items], ["nbcnews.com 1", "cnn.com 1", "abcnews.com 1", "nbcnews.com 2", "cnn.com 2"])

    def test_the_brief_falls_back_to_top_stories_when_the_sites_give_nothing(self):
        top = [{"title": "Top story", "url": "", "source": "Wire", "time": ""}]
        with patch.object(daily_brief, "outlet_news", lambda *_args: []), patch.object(daily_brief, "news", lambda *_args: top), \
                patch.object(daily_brief, "github_repos", lambda *_args: []), patch.object(daily_brief, "hacker_news", lambda *_args: []), \
                patch.object(daily_brief, "on_this_day", lambda *_args: []):
            brief = daily_brief.build([], "US", outlets=["cnn.com"])
        self.assertEqual((brief["headlines"], brief["outlets"]), (top, ["cnn.com"]))


class BrokenFeedTests(unittest.TestCase):
    def test_a_page_that_is_not_a_feed_is_no_news_and_a_bare_ampersand_is_fine(self):
        page = b'<!DOCTYPE html><html><head><script>if (a && b) {}</script></head><body>Are you a robot?</body></html>'
        self.assertEqual(daily_brief.parse_news(page, 3), [])
        feed = (b'<?xml version="1.0"?><rss xmlns:News="https://www.bing.com/news/search?q=AI&format=rss"><channel>'
                b'<item><title>Chips & models</title><link>https://example.com/a</link><News:Source>Wire</News:Source></item>'
                b'</channel></rss>')
        self.assertEqual([item["title"] for item in daily_brief.parse_news(feed, 3)], ["Chips & models"])

    def test_bing_asks_once_more_when_it_answers_with_a_robot_check(self):
        replies = [b"<html>robot check</html>", b'<rss><channel><item><title>Back</title></item></channel></rss>']
        with patch.object(daily_brief, "_get", lambda url, accept="": replies.pop(0)), patch.object(daily_brief.time, "sleep"):
            self.assertEqual([item["title"] for item in daily_brief.bing_news("AI", "US", 3)], ["Back"])

    def test_a_passing_network_failure_is_tried_once_more_a_real_error_is_not(self):
        bing = "https://www.bing.com/news/search?q=AI&format=rss"
        with patch.object(daily_brief.time, "sleep"):
            with patch.object(daily_brief, "urlopen", side_effect=[TimeoutError("The read operation timed out"),
                                                                   io.BytesIO(b"<rss/>")]) as opened:
                self.assertEqual(daily_brief._get(bing), b"<rss/>")
            self.assertEqual(opened.call_count, 2)
            with patch.object(daily_brief, "urlopen", side_effect=[TimeoutError("slow")] * 2), \
                    self.assertRaises(TimeoutError):
                daily_brief._get(bing)
            not_found = HTTPError(bing, 404, "Not Found", {}, io.BytesIO())
            with patch.object(daily_brief, "urlopen", side_effect=[not_found]) as opened, self.assertRaises(HTTPError):
                daily_brief._get(bing)
            self.assertEqual(opened.call_count, 1)


@unittest.skipUnless(os.environ.get("ALFRED_TEST_DOWNLOADS") == "1", "live sources only when ALFRED_TEST_DOWNLOADS=1")
class LiveTests(unittest.TestCase):
    def test_live_sources(self):
        with patch.dict(os.environ, {"ALFRED_DATA_DIR": tempfile.mkdtemp()}):
            brief = daily_brief.refresh(["AI"], "US")
        print("brief errors:", brief["errors"])
        self.assertTrue(brief["headlines"], brief["errors"])
        self.assertTrue(brief["topics"][0]["news"], brief["errors"])
        self.assertTrue(brief["hacker_news"], brief["errors"])
        self.assertTrue(brief["on_this_day"], brief["errors"])
        try:
            bing = daily_brief.bing_news("AI", "US", 3)
        except Exception as exc:  # the live source is unreachable right now: not our code failing
            self.skipTest(f"Bing News unreachable: {exc}")
        if not bing:  # Bing now and then answers with a robot-check page instead of the feed
            self.skipTest("Bing News returned nothing live right now")
        # GitHub's unauthenticated search can be rate limited on shared CI addresses; it may fail here.


if __name__ == "__main__":
    unittest.main()
