"""Fastest routes on a made-up city: a fast main road beats a shorter slow one, one-way streets count for vehicles
but not walkers, stops go in the quickest order, the search is recorded for the map, and the roads are kept on disk."""
from __future__ import annotations

import io
import json
import os
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import routes

# A 5 x 5 grid of streets 0.002° apart (about 220 m), node id = row * 10 + column + 1.
# Row 0 is a primary road (fast), the rest residential; column 2 is one-way southwards (from row 0 to row 4).
LAT0, LON0, STEP = 10.80, 106.60, 0.002


def node_id(row: int, column: int) -> int:
    return row * 10 + column + 1


def city() -> dict:
    elements = [{"type": "node", "id": node_id(r, c), "lat": LAT0 - r * STEP, "lon": LON0 + c * STEP}
                for r in range(5) for c in range(5)]
    for r in range(5):
        elements.append({"type": "way", "id": 1000 + r, "nodes": [node_id(r, c) for c in range(5)],
                         "tags": {"highway": "primary" if r == 0 else "residential"}})
    for c in range(5):
        tags = {"highway": "residential", **({"oneway": "yes"} if c == 2 else {})}
        elements.append({"type": "way", "id": 2000 + c, "nodes": [node_id(r, c) for r in range(5)], "tags": tags})
    elements.append({"type": "way", "id": 3000, "nodes": [node_id(4, 0), node_id(4, 4)],
                     "tags": {"highway": "residential", "access": "private"}})  # never used
    return {"elements": elements}


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


PLACES = {"A": (0, 0), "B": (0, 4), "C": (4, 2), "D": (2, 4), "E": (4, 4), "F": (0, 2)}


class RouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[str] = []

        def opener(request, timeout):
            self.calls.append(request.full_url)
            self.assertEqual(request.get_header("User-agent"), routes.USER_AGENT)
            if "nominatim" in request.full_url:
                name = parse_qs(urlsplit(request.full_url).query)["q"][0].split(",")[0]
                if name not in PLACES:
                    return Answer(b"[]")
                r, c = PLACES[name]
                return Answer(json.dumps([{"lat": str(LAT0 - r * STEP), "lon": str(LON0 + c * STEP)}]).encode())
            return Answer(json.dumps(city()).encode())
        self.clock = [1_000_000.0]
        self.router = routes.Router(Path(tempfile.mkdtemp()), opener=opener, clock=lambda: self.clock[0] + 10 * len(self.calls))

    def test_the_fast_main_road_and_the_search_for_the_map(self) -> None:
        route = self.router.route("A", "B", mode="car")
        self.assertEqual([place["name"] for place in route.places], ["A", "B"])
        self.assertAlmostEqual(route.metres, 4 * routes.haversine(LAT0, LON0, LAT0, LON0 + STEP), delta=1)
        self.assertAlmostEqual(route.seconds, route.metres / (45 / 3.6), delta=1)  # the primary road at 45 km/h
        self.assertTrue(route.searched and all(len(segment) == 5 for segment in route.searched))
        self.assertGreater(len(route.roads), 5)
        self.assertIn("About 1 min", route.summary())
        self.assertIn("google.com/maps/dir/?api=1&origin=10.800000%2C106.600000", route.google_maps())

    def test_one_way_streets_count_for_vehicles_not_walkers(self) -> None:
        block = routes.haversine(LAT0, LON0, LAT0 - STEP, LON0)
        walk = self.router.route("C", "F", mode="walk")  # straight up the one-way street: 4 blocks
        ride = self.router.route("C", "F", mode="motorbike")  # not allowed up it: round by the next street
        self.assertAlmostEqual(walk.metres, 4 * block, delta=1)
        self.assertGreater(ride.metres, walk.metres + block)

    def test_stops_go_in_the_quickest_order_and_the_roads_are_kept(self) -> None:
        route = self.router.route("A", "E", stops=["C", "D"], mode="walk")
        self.assertEqual([place["name"] for place in route.places], ["A", "D", "C", "E"] if route.reordered else
                         ["A", "C", "D", "E"])
        straight = self.router.route("A", "E", stops=["C", "D"], mode="walk", reorder=False)
        self.assertLessEqual(route.seconds, straight.seconds)
        self.assertEqual(len(route.legs), 3)
        overpass_calls = [url for url in self.calls if "overpass" in url]
        self.assertEqual(len(overpass_calls), 1)  # the second route used the roads kept on disk
        self.assertIn("Google Maps", route.summary())

    def test_problems_are_said_plainly(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self.router.route("A", "Atlantis")
        self.assertIn("couldn't find “Atlantis”", str(caught.exception))
        self.assertIsNone(routes.road_speed({"highway": "motorway"}, "motorbike"))  # no motorbikes on expressways
        self.assertEqual(routes.road_speed({"highway": "residential", "maxspeed": "10"}, "car"), 10)
        self.assertEqual(routes.best_order([[0, 5, 1], [5, 0, 1], [1, 1, 0]], keep_end=True), [0, 1, 2])


BOX_RE = re.compile(r"\]\(([^)]+)\);")


def overpass_box(request) -> tuple[float, float, float, float]:
    """The (south, west, north, east) box an Overpass POST asked for."""
    data = parse_qs(request.data.decode())["data"][0]
    return tuple(float(value) for value in BOX_RE.search(data).group(1).split(","))


class ScriptedOpener:
    """A fake map server: Nominatim answers from a dict of places, Overpass from a script. Each script entry is
    ("ok", data) or ("fail", status), or one callable used for every call; an empty script answers Nominatim
    from the places dict and Overpass with the made-up city. `places` maps a name to (lat, lon), or to
    (lat, lon, boundingbox) when a test needs keep_city's box."""

    def __init__(self, places, overpass=None, nominatim=None) -> None:
        self.places = places
        self.overpass = overpass if overpass is not None else []
        self.nominatim = nominatim if nominatim is not None else []
        self.total = 0
        self.overpass_urls: list[str] = []
        self.boxes: list[tuple[float, float, float, float]] = []

    def _next(self, script, url):
        outcome = script(url) if callable(script) else (script.pop(0) if script else ("ok", None))
        kind, value = outcome
        if kind == "fail":
            reason = {502: "Bad Gateway", 503: "Service Unavailable", 429: "Too Many Requests"}.get(value, "Error")
            raise HTTPError(url, value, reason, {}, None)
        return value

    def __call__(self, request, timeout):
        self.total += 1
        url = request.full_url
        assert request.get_header("User-agent") == routes.USER_AGENT
        if "nominatim" in url:
            data = self._next(self.nominatim, url)
            if data is not None:
                return Answer(json.dumps(data).encode())
            name = parse_qs(urlsplit(url).query)["q"][0].split(",")[0]
            found = self.places.get(name)
            if found is None:
                return Answer(b"[]")
            hit = {"lat": str(found[0]), "lon": str(found[1])}
            if len(found) > 2:
                hit["boundingbox"] = [str(value) for value in found[2]]
            return Answer(json.dumps([hit]).encode())
        self.boxes.append(overpass_box(request))
        self.overpass_urls.append(url)
        data = self._next(self.overpass, url)
        return Answer(json.dumps(data if data is not None else city()).encode())


def fail_always(status: int):
    return lambda url: ("fail", status)


class RouteFixTests(unittest.TestCase):
    """The 502 and the too-big county, with the servers scripted: retries, mirrors, kept roads, corridors,
    tiles, and the plain words the screen shows when nothing works."""

    def make_router(self, places, overpass=None, nominatim=None, clock=None, sleep=None):
        opener = ScriptedOpener(places, overpass, nominatim)
        sleeps: list[float] = []
        router = routes.Router(Path(tempfile.mkdtemp()), opener=opener,
                               clock=clock or (lambda: 1_000_000.0 + 100 * opener.total),
                               sleep=sleep or sleeps.append)
        return router, opener, sleeps

    def test_retries_a_502_then_succeeds(self) -> None:
        router, opener, sleeps = self.make_router(
            {"A": (LAT0, LON0), "B": (LAT0, LON0 + 4 * STEP)}, overpass=[("fail", 502), ("ok", None)])
        route = router.route("A", "B", mode="car")
        self.assertEqual([place["name"] for place in route.places], ["A", "B"])
        self.assertEqual(len(opener.overpass_urls), 2)  # the failed try, then the retry
        self.assertEqual(sleeps, [1.0])  # one short wait between the two tries, nothing more

    def test_retries_a_502_from_the_place_search_too(self) -> None:
        router, opener, sleeps = self.make_router(
            {"A": (LAT0, LON0), "B": (LAT0, LON0 + 4 * STEP)}, nominatim=[("fail", 502)])
        route = router.route("A", "B", mode="car")
        self.assertEqual([place["name"] for place in route.places], ["A", "B"])
        self.assertEqual(sleeps, [1.0])

    def test_falls_back_to_overpass_mirrors(self) -> None:
        def mirror_only(url):
            return ("fail", 502) if "overpass-api.de" in url else ("ok", None)
        router, opener, sleeps = self.make_router(
            {"A": (LAT0, LON0), "B": (LAT0, LON0 + 4 * STEP)}, overpass=mirror_only)
        route = router.route("A", "B", mode="car")
        self.assertEqual([place["name"] for place in route.places], ["A", "B"])
        self.assertEqual(opener.overpass_urls[:3], [routes.OVERPASS] * 3)  # the primary, tried three times
        self.assertIn("overpass.kumi.systems", opener.overpass_urls[3])  # then the first mirror answers
        self.assertEqual(len(opener.overpass_urls), 4)
        self.assertEqual(sleeps, [1.0, 2.0])

    def test_reuses_kept_roads_when_the_fresh_download_fails(self) -> None:
        now = [time.time()]
        router, opener, _sleeps = self.make_router(
            {"A": (LAT0, LON0), "B": (LAT0, LON0 + 4 * STEP)},
            clock=lambda: now[0], sleep=lambda _seconds: None)
        first = router.route("A", "B", mode="car")
        self.assertEqual(len(opener.overpass_urls), 1)
        opener.overpass = fail_always(502)  # the servers go down afterwards
        now[0] += 31 * 86400  # past the 30 days, so the kept copy is stale and a fresh download is tried
        tried = len(opener.overpass_urls)
        second = router.route("A", "B", mode="car")
        self.assertGreater(len(opener.overpass_urls), tried)  # it did try to download again
        self.assertAlmostEqual(second.metres, first.metres, delta=1)  # and fell back to the stale kept roads

    def test_all_servers_failing_says_so_plainly(self) -> None:
        router, opener, sleeps = self.make_router(
            {"A": (LAT0, LON0), "B": (LAT0, LON0 + 4 * STEP)}, overpass=fail_always(502))
        with self.assertRaises(OSError) as caught:
            router.route("A", "B", mode="car")
        message = str(caught.exception)
        self.assertIn("didn't answer", message)
        self.assertIn("try again", message)
        self.assertIn("As the crow flies", message)  # still something useful: how far apart they are
        self.assertIn("google.com/maps/dir", message)  # and the link that routes them live
        self.assertEqual(len(opener.overpass_urls), 12)  # three tries on each of the four addresses
        self.assertEqual(sleeps, [1.0, 2.0] * 4)
        router, opener, _sleeps = self.make_router(
            {"A": (LAT0, LON0), "B": (LAT0, LON0 + 4 * STEP)}, nominatim=fail_always(503))
        with self.assertRaises(OSError) as caught:
            router.route("A", "B", mode="car")
        self.assertIn("place search", str(caught.exception))
        self.assertIn("try again", str(caught.exception))
        self.assertEqual(opener.total, 3)  # three tries on the one place search, then it gives up plainly

    def test_far_apart_towns_use_a_corridor_not_the_whole_county(self) -> None:
        # Two towns 0.70° apart east-west (about 65 km): the old code refused the whole box between them.
        router, opener, _sleeps = self.make_router(
            {"West": (34.20, -77.90), "East": (34.25, -77.20)})
        route = router.route("West", "East", mode="car")
        self.assertEqual([place["name"] for place in route.places], ["West", "East"])
        self.assertEqual(len(opener.boxes), 2)  # the corridor, fetched tile by tile along its length
        for box in opener.boxes:
            self.assertLessEqual(box[3] - box[1], 0.5)  # no one giant query
            self.assertLessEqual(box[2] - box[0], 0.3)  # a thin strip, not the county
        self.assertLess(max(box[3] - box[1] for box in opener.boxes), 0.70)  # never the whole span at once

    def test_tiled_fetch_merges_and_dedupes(self) -> None:
        calls = [0]

        def varying(url):
            calls[0] += 1
            if calls[0] % 2 == 0:
                extra = city()
                extra["elements"] = extra["elements"] + [
                    {"type": "node", "id": 9001, "lat": LAT0, "lon": LON0},
                    {"type": "node", "id": 9002, "lat": LAT0, "lon": LON0 + STEP},
                    {"type": "way", "id": 9000, "nodes": [9001, 9002], "tags": {"highway": "residential"}}]
                return ("ok", extra)
            return ("ok", None)
        router, opener, _sleeps = self.make_router(
            {"West": (34.20, -77.90), "East": (34.25, -77.20)}, overpass=varying)
        west = router.geocode("West")
        east = router.geocode("East")
        roads = router.roads([west, east], "car")
        base = len(routes.Roads.from_overpass(city(), "car").lines)
        self.assertEqual(len(opener.boxes), 2)
        self.assertEqual(len(roads.lines), base + 1)  # the shared ways once, the extra way from tile two

    def test_still_too_big_says_so_plainly(self) -> None:
        router, opener, _sleeps = self.make_router(
            {"Big County": (11.5, 107.5, (10.0, 13.0, 106.0, 109.0))})
        with self.assertRaises(ValueError) as caught:
            router.keep_city("Big County")
        self.assertIn("too big to keep", str(caught.exception))
        self.assertIn("towns inside it", str(caught.exception))
        self.assertEqual(opener.overpass_urls, [])  # refused before any download
        router, opener, _sleeps = self.make_router(
            {"Far West": (10.0, 106.0), "Far East": (15.0, 106.0)})
        with self.assertRaises(ValueError) as caught:
            router.route("Far West", "Far East", mode="car")
        message = str(caught.exception)
        self.assertIn("too far apart", message)
        self.assertIn("towns closer together", message)
        self.assertIn("google.com/maps/dir", message)
        self.assertEqual(opener.overpass_urls, [])  # refused before any download

    def test_keep_city_works_for_a_county_in_tiles(self) -> None:
        router, opener, _sleeps = self.make_router(
            {"New Hanover County": (34.3, -77.6, (34.0, 34.65, -78.0, -77.35)),
             "Wilmington": (34.20, -77.90), "Wrightsville": (34.35, -77.50)})
        self.assertEqual(router.keep_city("New Hanover County"), "New Hanover County")
        self.assertEqual(len(opener.boxes), 4)  # a 0.65° county, in four tiles
        for box in opener.boxes:
            self.assertLessEqual(max(box[2] - box[0], box[3] - box[1]), 0.5)
        kept = json.loads((router.cache / "city-New_Hanover_County.json").read_text(encoding="utf-8"))
        self.assertEqual(kept["nova_box"], [34.0, -78.0, 34.65, -77.35])  # the whole county, in one kept file
        route = router.route("Wilmington", "Wrightsville", mode="car")
        self.assertEqual([place["name"] for place in route.places], ["Wilmington", "Wrightsville"])
        self.assertEqual(len(opener.overpass_urls), 4)  # the route used the kept county: no download at all

    def test_a_second_keep_of_the_same_city_waits_for_the_first(self) -> None:
        started, release = threading.Event(), threading.Event()

        def blocking(url):
            if not started.is_set():
                started.set()
                self.assertTrue(release.wait(timeout=10))
            return ("ok", None)
        router, opener, _sleeps = self.make_router(
            {"New Hanover County": (34.3, -77.6, (34.0, 34.65, -78.0, -77.35))}, overpass=blocking)
        results: list[str] = []

        def keep() -> None:
            results.append(router.keep_city("New Hanover County"))
        first = threading.Thread(target=keep)
        first.start()
        self.assertTrue(started.wait(timeout=10))  # the first keep is mid-download
        second = threading.Thread(target=keep)
        second.start()
        time.sleep(0.5)  # let the second keep reach the one already running
        release.set()
        first.join(timeout=10)
        second.join(timeout=10)
        self.assertEqual(results, ["New Hanover County", "New Hanover County"])
        self.assertEqual(len(opener.overpass_urls), 4)  # one set of tiles, not one per click


@unittest.skipUnless(os.environ.get("ALFRED_TEST_DOWNLOADS") == "1", "set ALFRED_TEST_DOWNLOADS=1 to reach OpenStreetMap")
class LiveRouteTests(unittest.TestCase):
    def test_a_real_route_in_ho_chi_minh_city(self) -> None:
        router = routes.Router(Path(tempfile.mkdtemp()), near=lambda: "Ho Chi Minh City, Vietnam")
        route = router.route("Ben Thanh Market", "Saigon Notre-Dame Basilica", mode="motorbike")
        print(route.summary().encode("ascii", "replace").decode())  # the runner's console is cp1252
        self.assertLess(route.metres, 5000)
        self.assertGreater(len(route.searched), 10)


if __name__ == "__main__":
    unittest.main()


class PartialRoadsTests(unittest.TestCase):
    def test_an_overpass_timeout_is_a_failure_not_the_citys_roads(self) -> None:
        import io
        answer = json.dumps({"remark": "runtime error: Query timed out in \"query\" at line 1 after 181 seconds.",
                             "elements": [{"type": "node", "id": 1, "lat": 10.0, "lon": 106.0}]}).encode()
        router = routes.Router(Path(tempfile.mkdtemp()), opener=lambda request, timeout=0: io.BytesIO(answer),
                               sleep=lambda _seconds: None)
        with self.assertRaises(OSError):
            router._roads_for_box((10.0, 106.0, 10.1, 106.1), tiled=False)
        self.assertEqual(list(router.cache.glob("roads-*.json")), [])  # nothing half-downloaded kept for 30 days
