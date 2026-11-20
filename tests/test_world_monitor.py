"""The World view: each public feed read into events, news placed on its country, places found in what the owner says,
a feed that fails leaving the others standing, the 15-minute cache, the spoken brief and the voice tool."""
from __future__ import annotations

import io
import json
import os
import unittest
from datetime import datetime, timezone

import world_monitor as world
from tools import execute_tool

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
USGS = {"features": [
    {"properties": {"mag": 6.8, "place": "40 km S of Hualien, Taiwan", "time": int(NOW.timestamp() * 1000) - 3_600_000,
                    "url": "https://earthquake.usgs.gov/x", "title": "M 6.8 - 40 km S of Hualien, Taiwan"},
     "geometry": {"coordinates": [121.6, 23.6, 10]}},
    {"properties": {"mag": 4.6, "place": "Fiji region", "time": int(NOW.timestamp() * 1000) - 6 * 86_400_000,
                    "title": "M 4.6 - Fiji region"}, "geometry": {"coordinates": [179.9, -17.9, 500]}}]}
EONET = {"events": [
    {"title": "Wildfire near Valparaíso", "categories": [{"id": "wildfires"}], "sources": [{"url": "https://inciweb/x"}],
     "geometry": [{"date": "2026-11-20T06:00:00Z", "type": "Point", "coordinates": [-71.5, -33.1]}]},
    {"title": "Sea ice", "categories": [{"id": "seaLakeIce"}],
     "geometry": [{"date": "2026-11-20T06:00:00Z", "type": "Point", "coordinates": [0, 80]}]}]}
GDACS = b"""<?xml version="1.0"?><rss xmlns:geo="http://www.w3.org/2003/01/geo/wgs84_pos#" xmlns:gdacs="http://www.gdacs.org"><channel>
<item><title>Red alert for tropical cyclone FUNG-WONG</title><link>https://gdacs.org/tc</link>
<pubDate>Thu, 20 Nov 2026 03:00:00 GMT</pubDate><geo:Point><geo:lat>14.5</geo:lat><geo:long>124.0</geo:long></geo:Point>
<gdacs:eventtype>TC</gdacs:eventtype><gdacs:alertlevel>Red</gdacs:alertlevel><gdacs:country>Philippines</gdacs:country></item>
<item><title>Earthquake (dup of USGS)</title><pubDate>Thu, 20 Nov 2026 03:00:00 GMT</pubDate>
<geo:Point><geo:lat>1</geo:lat><geo:long>1</geo:long></geo:Point><gdacs:eventtype>EQ</gdacs:eventtype></item>
</channel></rss>"""
NEWS = [
    {"title": "Airstrikes hit Gaza as ceasefire talks stall", "summary": "", "location": "Gaza",
     "published_at": "2026-11-20T08:00:00Z", "importance": 9, "url": "https://news/1", "publisher": "AP"},
    {"title": "Japan unveils new chip plan", "summary": "Tokyo invests", "location": "",
     "published_at": "2026-11-20T09:00:00Z", "importance": 4, "url": "https://news/2", "publisher": "Reuters"},
    {"title": "Markets calm", "summary": "", "location": "", "published_at": "2026-11-20T09:00:00Z", "url": "https://news/3"}]


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FeedTests(unittest.TestCase):
    def test_each_feed_becomes_events(self) -> None:
        quakes = world.parse_usgs(USGS)
        self.assertEqual((quakes[0]["layer"], quakes[0]["severity"], quakes[0]["lon"]), ("quakes", 3, 121.6))
        fires = world.parse_eonet(EONET)
        self.assertEqual([(event["layer"], event["title"]) for event in fires], [("fires", "Wildfire near Valparaíso")])
        alerts = world.parse_gdacs(GDACS)
        self.assertEqual([(event["layer"], event["severity"], event["place"]) for event in alerts], [("storms", 3, "Philippines")])

    def test_news_is_placed_on_its_country_and_fighting_is_conflict(self) -> None:
        events = world.news_events(NEWS, world.Places())
        self.assertEqual([(event["layer"], event["place"]) for event in events], [("conflict", "Palestine"), ("news", "Japan")])

    def test_places_from_what_the_owner_says(self) -> None:
        places = world.Places()
        self.assertEqual(places.find("what's happening in the Middle East this week")["name"], "Middle East")
        self.assertEqual(places.find("news from the us")["country"], "United States of America")
        self.assertEqual(places.find("Kyiv")["country"], "Ukraine")
        self.assertIsNone(places.find("everywhere"))
        self.assertIsNone(places.country_in("Tell us what you think"))  # "us" in a sentence isn't the country
        russia = places.countries["Russia"]["center"]
        self.assertTrue(80 < russia[0] < 110 and 55 < russia[1] < 68)  # its centre isn't split by the date line

    def test_inside_handles_regions_across_the_date_line(self) -> None:
        pacific = {"bbox": [170, -30, -170, 10], "country": None}
        self.assertTrue(world.inside({"lon": 179.0, "lat": -17.0}, pacific))
        self.assertTrue(world.inside({"lon": -175.0, "lat": -17.0}, pacific))
        self.assertFalse(world.inside({"lon": 0.0, "lat": 0.0}, pacific))


class MonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[str] = []
        self.clock = [NOW.timestamp()]
        self.down: set[str] = set()

        def opener(request, timeout):
            url = request.full_url
            self.calls.append(url)
            self.assertEqual(request.get_header("User-agent"), world.USER_AGENT)
            if any(part in url for part in self.down):
                raise OSError("offline")
            if "usgs" in url:
                return Answer(json.dumps(USGS).encode())
            if "eonet" in url:
                return Answer(json.dumps(EONET).encode())
            return Answer(GDACS)
        self.monitor = world.WorldMonitor(news=lambda days: NEWS, opener=opener, clock=lambda: self.clock[0])

    def test_one_day_sorted_worst_first_and_cached(self) -> None:
        snapshot = self.monitor.events(1)
        self.assertEqual(snapshot["events"][0]["severity"], 3)
        self.assertNotIn("M 4.6 - Fiji region", [event["title"] for event in snapshot["events"]])  # six days old
        self.assertIn("M 4.6 - Fiji region", [event["title"] for event in self.monitor.events(7)["events"]])
        self.assertEqual(len(self.calls), 3)  # the second call came from the cache
        self.assertTrue(self.monitor.cached())
        self.clock[0] += 16 * 60
        self.assertFalse(self.monitor.cached())

    def test_a_feed_that_fails_leaves_the_others(self) -> None:
        self.down = {"gdacs"}
        snapshot = self.monitor.events(1)
        self.assertEqual(list(snapshot["errors"]), ["GDACS"])
        self.assertIn("quakes", {event["layer"] for event in snapshot["events"]})

    def test_the_brief_for_a_place(self) -> None:
        text, place = self.monitor.brief("the Middle East", 1)
        self.assertEqual(place["name"], "Middle East")
        self.assertIn("Conflict: 1 stories (Palestine 1)", text)
        self.assertNotIn("Taiwan", text)
        whole, nowhere = self.monitor.brief("", 1)
        self.assertIsNone(nowhere)
        self.assertIn("Earthquakes: 1. M 6.8 - 40 km S of Hualien, Taiwan", whole)
        self.monitor.news = lambda days: None
        self.assertIn("news desk is off", self.monitor.brief("", 1)[0])

    def test_the_voice_tool(self) -> None:
        asked: list = []
        answer = execute_tool("world", {"action": "brief", "place": "Japan", "days": 7}, None, lambda *_: False,
                              world=lambda action, place, days: asked.append((action, place, days)) or "Quiet.")
        self.assertEqual((answer, asked), ("Quiet.", [("brief", "Japan", 7)]))
        self.assertIn("isn't available", execute_tool("world", {"action": "show"}, None, lambda *_: True))


@unittest.skipUnless(os.environ.get("ALFRED_TEST_DOWNLOADS") == "1", "set ALFRED_TEST_DOWNLOADS=1 to reach the real feeds")
class LiveFeedTests(unittest.TestCase):
    """The real USGS, NASA EONET and GDACS feeds still read the way Nova expects (CI, with network)."""

    def test_the_real_feeds(self) -> None:
        snapshot = world.WorldMonitor(news=None).events(7)
        self.assertEqual(snapshot["errors"], {})
        layers = {event["layer"] for event in snapshot["events"]}
        self.assertIn("quakes", layers)  # there is always a magnitude 4.5+ earthquake in a week
        print(f"{len(snapshot['events'])} events; layers {sorted(layers)}")


if __name__ == "__main__":
    unittest.main()
