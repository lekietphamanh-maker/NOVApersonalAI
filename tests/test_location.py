"""Location, weather and local news: parsing each service's real answer format, the tools (set_location asks
first, nothing without a place), and live calls on CI (ALFRED_TEST_DOWNLOADS=1)."""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import URLError

import location
from tools import execute_tool

GEOCODE = {"results": [
    {"id": 1905468, "name": "Da Nang", "latitude": 16.06778, "longitude": 108.22083, "country_code": "VN",
     "timezone": "Asia/Ho_Chi_Minh", "country": "Vietnam", "admin1": "Da Nang"},
    {"id": 1, "name": "Springfield", "latitude": 39.80172, "longitude": -89.64371, "country_code": "US",
     "country": "United States", "admin1": "Illinois"}], "generationtime_ms": 0.9}
FORECAST = {"timezone": "Asia/Ho_Chi_Minh",
            "current": {"time": "2026-11-18T14:00", "temperature_2m": 28.4, "apparent_temperature": 31.2,
                        "relative_humidity_2m": 74, "weather_code": 2, "wind_speed_10m": 11.6},
            "daily": {"time": ["2026-11-18", "2026-11-19", "2026-11-20"], "weather_code": [61, 3, 95],
                      "temperature_2m_max": [30.1, 29.0, 27.5], "temperature_2m_min": [24.2, 23.8, 23.0],
                      "precipitation_probability_max": [80, 20, 90]}}
REVERSE = {"lat": "16.0678", "lon": "108.2208", "display_name": "Da Nang, Vietnam",
           "address": {"city": "Da Nang", "ISO3166-2-lvl4": "VN-DN", "country": "Vietnam", "country_code": "vn"}}


class ParsingTests(unittest.TestCase):
    def test_places_from_a_name_with_an_optional_country_or_region(self) -> None:
        self.assertEqual(location.parse_places(GEOCODE), {"name": "Da Nang", "region": "Da Nang", "country": "Vietnam",
                                                          "country_code": "VN", "lat": 16.068, "lon": 108.221})
        self.assertEqual(location.parse_places(GEOCODE, "illinois")["name"], "Springfield")
        self.assertIsNone(location.parse_places({"generationtime_ms": 0.5}))

    def test_a_point_becomes_its_city(self) -> None:
        place = location.parse_reverse(REVERSE, 16.0678, 108.2208)
        self.assertEqual((place["name"], place["country_code"]), ("Da Nang", "VN"))
        self.assertEqual(location.parse_reverse({"address": {"town": "Hoi An", "country": "Vietnam"}}, 15.88, 108.33)["name"],
                         "Hoi An")
        place = location.parse_ipinfo({"city": "Da Nang", "region": "Da Nang", "country": "VN", "loc": "16.0678,108.2208"})
        self.assertEqual((place["name"], place["lat"], place["lon"]), ("Da Nang", 16.068, 108.221))

    def test_weather_reads_like_a_person_would_say_it(self) -> None:
        short, lines = location.weather_lines(FORECAST)
        self.assertEqual(short, "28°C · partly cloudy")
        self.assertEqual(lines[0], "Now: 28°C, partly cloudy, feels like 31°C, humidity 74%, wind 12 km/h.")
        self.assertEqual(lines[1], "Today: light rain, 24 to 30°C, 80% chance of rain.")
        self.assertEqual(lines[2], "Tomorrow: overcast, 24 to 29°C, 20% chance of rain.")
        self.assertTrue(lines[3].startswith("Friday: thunderstorm"))
        self.assertEqual(location.weather_lines(FORECAST, fahrenheit=True)[0], "28°F · partly cloudy")


class LocationToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved: dict = {}
        self.place = location.Location(load=lambda: self.saved.get("place"), save=lambda place: self.saved.update(place=place))

    def test_nothing_without_a_place(self) -> None:
        self.assertEqual(execute_tool("weather", {}, None, lambda *_: True, location=self.place), location.NO_PLACE)
        self.assertEqual(execute_tool("local_news", {}, None, lambda *_: True, location=self.place), location.NO_PLACE)

    def test_set_location_asks_first_then_weather_uses_it(self) -> None:
        asked: list[str] = []
        with patch.object(location, "_get_json", lambda url, timeout=12: GEOCODE if "geocoding" in url else FORECAST):
            result = execute_tool("set_location", {"place": "Da Nang"}, None,
                                  lambda name, arguments: asked.append(arguments["summary"]) or False, location=self.place)
            self.assertIn("declined", result)
            self.assertIsNone(self.saved.get("place"))
            result = execute_tool("set_location", {"place": "Da Nang"}, None, lambda *_: True, location=self.place)
            self.assertEqual(result, "Location saved: Da Nang, Vietnam.")
            self.assertIn("Open-Meteo", asked[0])
            weather = execute_tool("weather", {}, None, lambda *_: self.fail("weather must not ask"), location=self.place)
        self.assertIn("Weather in Da Nang, Vietnam", weather)
        self.assertIn("Now: 28°C, partly cloudy", weather)

    def test_a_place_from_this_pc_is_looked_up_again_after_an_hour(self) -> None:
        self.saved["place"] = {"name": "Old Town", "lat": 1.0, "lon": 2.0, "source": "device", "updated": 0}
        moved = {"name": "Da Nang", "country": "Vietnam", "lat": 16.068, "lon": 108.221, "how": "Windows location"}
        with patch.object(location, "device_place", lambda: dict(moved)), \
                patch.object(location, "_get_json", lambda url, timeout=12: FORECAST):
            self.assertIn("Da Nang", self.place.weather_text())
        self.assertEqual(self.saved["place"]["name"], "Da Nang")


class KnownPlaceTests(unittest.TestCase):
    """Nova never asks for a place she already has."""

    def setUp(self) -> None:
        self.saved: dict = {"place": {"name": "Da Nang", "country": "Vietnam", "country_code": "VN", "lat": 16.068,
                                      "lon": 108.221, "source": "city", "updated": time.time()}}
        self.place = location.Location(load=lambda: self.saved.get("place"), save=lambda place: self.saved.update(place=place))

    def test_the_saved_city_is_recognised_however_it_is_written(self) -> None:
        for text in ("Da Nang", "da nang, vietnam", "Đà Nẵng", "  DA   NANG "):
            self.assertTrue(self.place.is_saved(text), text)
        self.assertFalse(self.place.is_saved("Hanoi"))
        self.assertFalse(location.Location(load=lambda: None, save=lambda _place: None).is_saved("Da Nang"))

    def test_set_location_for_the_saved_city_asks_nothing(self) -> None:
        result = execute_tool("set_location", {"place": "Đà Nẵng"}, None, lambda *_: self.fail("must not ask"),
                              location=self.place)
        self.assertIn("already the owner's saved location", result)

    def test_another_citys_weather_leaves_the_saved_place_alone(self) -> None:
        hanoi = {"results": [{"name": "Hanoi", "latitude": 21.0245, "longitude": 105.8412, "country_code": "VN",
                              "country": "Vietnam", "admin1": "Hanoi"}]}
        with patch.object(location, "_get_json", lambda url, timeout=12: hanoi if "geocoding" in url else FORECAST):
            text = execute_tool("weather", {"place": "Hanoi"}, None, lambda *_: self.fail("must not ask"), location=self.place)
            own = execute_tool("weather", {"place": "da nang"}, None, lambda *_: self.fail("must not ask"), location=self.place)
        self.assertIn("Weather in Hanoi, Vietnam", text)
        self.assertIn("unchanged", text)
        self.assertIn("Weather in Da Nang, Vietnam", own)
        self.assertEqual(self.saved["place"]["name"], "Da Nang")

    def test_nova_is_told_where_the_owner_is(self) -> None:
        import tempfile
        from pathlib import Path
        from agent import Agent
        from memory import Memory
        agent = Agent(memory=Memory(Path(tempfile.mkdtemp()) / "memory.sqlite3"))
        agent.location = self.place
        seen: list[str] = []
        agent._chat = lambda messages, tools: seen.append(messages[0]["content"]) or {"message": {"role": "assistant", "content": "ok"}}
        agent.ask("what's the weather like?", lambda *_: True)
        self.assertIn("Where your owner is: Da Nang, Vietnam", seen[0])
        self.assertIn("Never ask where they are", seen[0])
        self.saved["place"] = None
        self.assertIn("isn't saved yet", agent._where_prompt())


class NetworkTests(unittest.TestCase):
    def test_a_passing_network_failure_is_tried_once_more_a_real_error_is_not(self) -> None:
        import contextlib
        import io
        from urllib.error import HTTPError, URLError
        answers = [URLError(TimeoutError("The handshake operation timed out")), b'{"ok": 1}']

        def flaky(request, timeout):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return contextlib.nullcontext(io.BytesIO(answer))
        with patch.object(location, "urlopen", flaky), patch.object(location.time, "sleep", lambda _seconds: None):
            self.assertEqual(location._get_json("https://example.invalid/x"), {"ok": 1})
            calls: list[int] = []

            def missing(request, timeout):
                calls.append(1)
                raise HTTPError(request.full_url, 404, "Not Found", None, None)
            with patch.object(location, "urlopen", missing), self.assertRaises(HTTPError):
                location._get_json("https://example.invalid/y")
            self.assertEqual(len(calls), 1)


class DeviceLocationTests(unittest.TestCase):
    def test_a_windows_location_service_that_never_answers_falls_back_to_the_connection(self) -> None:
        started = time.monotonic()
        with self.assertRaises(TimeoutError):  # a call that hangs forever is given up on in time
            location.with_time_limit(lambda: threading.Event().wait(), 0.3, "no answer")
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(location.with_time_limit(lambda: 7, 1, "no answer"), 7)
        with self.assertRaises(PermissionError):
            location.with_time_limit(lambda: (_ for _ in ()).throw(PermissionError("off")), 1, "no answer")
        ipinfo = {"city": "Da Nang", "region": "Da Nang", "country": "VN", "loc": "16.0678,108.2208"}
        with patch.object(location, "windows_coordinates", side_effect=TimeoutError("Windows location didn't answer")), \
                patch.object(location, "_get_json", lambda url, timeout=12: ipinfo):
            place = location.device_place()
        self.assertEqual(place["name"], "Da Nang")
        self.assertIn("internet connection", place["how"])


def show(*parts: object) -> None:
    """Print for the CI log: a Windows console's code page can't show every character (Đà Nẵng in a headline)."""
    encoding = sys.stdout.encoding or "utf-8"
    print(" ".join(str(part) for part in parts).encode(encoding, "replace").decode(encoding))


@unittest.skipUnless(os.environ.get("ALFRED_TEST_DOWNLOADS") == "1", "calls Open-Meteo, OpenStreetMap and Google News")
class LiveLocationTests(unittest.TestCase):
    def test_city_weather_and_local_news(self) -> None:
        saved: dict = {}
        place = location.Location(load=lambda: saved.get("place"), save=lambda value: saved.update(place=value))
        found = place.set_city("Da Nang, Vietnam")
        show("place:", found)
        self.assertEqual(found["country_code"], "VN")
        show(place.news_text())
        show("reverse:", location.place_at(found["lat"], found["lon"]))
        try:
            text = place.weather_text()
        except (URLError, TimeoutError) as exc:
            # Open-Meteo's forecast server now and then lets a CI machine's handshake time out (three runs so far);
            # its format is checked with recorded answers above. Any other failure still fails here.
            if not isinstance(getattr(exc, "reason", exc), TimeoutError):
                raise
            self.skipTest(f"Open-Meteo's forecast didn't answer this CI machine in time: {exc}")
        show(text)
        self.assertIn("Now:", text)

    def test_this_pcs_location_works_or_says_why(self) -> None:
        try:
            show("this PC:", location.device_place())
        except LookupError as exc:  # CI machines may have no location at all
            show("no location here:", exc)
            self.assertIn("Type your city", str(exc))


if __name__ == "__main__":
    unittest.main()
