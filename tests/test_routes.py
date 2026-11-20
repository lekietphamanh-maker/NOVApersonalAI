"""Fastest routes on a made-up city: a fast main road beats a shorter slow one, one-way streets count for vehicles
but not walkers, stops go in the quickest order, the search is recorded for the map, and the roads are kept on disk."""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
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
