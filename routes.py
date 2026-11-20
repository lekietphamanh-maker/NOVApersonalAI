"""Fastest routes on real roads, worked out on this PC: from A to B, or through several stops in the best order.

Places are found with OpenStreetMap's Nominatim; the roads around them come from OpenStreetMap's Overpass API (kept on
disk for 30 days, so the same city is quick and works offline afterwards). The route itself is found here with
Dijkstra's search, and the order in which the search reached each road is kept: Nova's map replays it, the search
spreading out along the streets until it reaches the destination, then the fastest path lights up.

Times assume the usual speed of each kind of road: OpenStreetMap has no live traffic. Only the place names and the
map area are sent anywhere.
"""
from __future__ import annotations

import hashlib
import heapq
import itertools
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"
USER_AGENT = "Nova-Route/1.0"
CACHE_DAYS = 30
MAX_SPAN_DEGREES = 0.6         # about 65 km: farther than this, the roads would be too much to fetch
MAX_STOPS = 6
MAX_SEARCH_SEGMENTS = 30_000   # what the map replays of the search
MODES = ("motorbike", "car", "walk")
# km/h by road type (Vietnam-like city traffic for two-wheelers)
SPEEDS = {
    "car": {"motorway": 90, "trunk": 60, "primary": 45, "secondary": 38, "tertiary": 32, "unclassified": 28,
            "residential": 22, "living_street": 10, "service": 12, "track": 10},
    "motorbike": {"trunk": 50, "primary": 40, "secondary": 35, "tertiary": 30, "unclassified": 28, "residential": 24,
                  "living_street": 15, "service": 18, "track": 15, "path": 10},
    "walk": {name: 4.8 for name in ("trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
                                     "living_street", "service", "track", "path", "footway", "pedestrian", "steps",
                                     "cycleway")},
}
NO = {"no", "private"}


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Metres between two points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 12_742_000 * math.asin(math.sqrt(a))


def road_speed(tags: dict[str, str], mode: str) -> float | None:
    """km/h on this road for this mode, or None when it can't be used."""
    kind = tags.get("highway", "").removesuffix("_link")
    speed = SPEEDS[mode].get(kind)
    own = {"car": "motorcar", "motorbike": "motorcycle", "walk": "foot"}[mode]
    if tags.get(own) in NO or (tags.get("access") in NO and tags.get(own) not in ("yes", "designated", "permissive")):
        return None
    if speed is None:
        return 4.8 if mode == "walk" and tags.get("foot") in ("yes", "designated") else None
    if mode != "walk" and tags.get("maxspeed", "").isdigit():
        speed = min(speed, float(tags["maxspeed"]))
    return speed


def one_way(tags: dict[str, str], mode: str) -> int:
    """1: only forward, -1: only backward, 0: both ways (walkers may go both ways)."""
    if mode == "walk":
        return 0
    value = tags.get("oneway", "")
    if value in ("yes", "true", "1") or (tags.get("junction") == "roundabout" and value != "no"):
        return 1
    return -1 if value == "-1" else 0


@dataclass
class Roads:
    nodes: dict[int, tuple[float, float]]                      # id -> (lat, lon)
    edges: dict[int, list[tuple[int, float]]]                  # id -> [(next id, seconds)]
    lines: list[list[float]] = field(default_factory=list)     # each road as [lon, lat, lon, lat, …] for the map

    @classmethod
    def from_overpass(cls, data: dict[str, Any], mode: str) -> Roads:
        nodes = {item["id"]: (item["lat"], item["lon"]) for item in data.get("elements", []) if item.get("type") == "node"}
        edges: dict[int, list[tuple[int, float]]] = {}
        lines: list[list[float]] = []
        for way in (item for item in data.get("elements", []) if item.get("type") == "way"):
            tags = way.get("tags") or {}
            speed = road_speed(tags, mode)
            ids = [node for node in way.get("nodes", []) if node in nodes]
            if speed is None or len(ids) < 2:
                continue
            direction = one_way(tags, mode)
            metres_per_second = speed / 3.6
            for start, end in zip(ids, ids[1:]):
                seconds = haversine(*nodes[start], *nodes[end]) / metres_per_second
                if direction >= 0:
                    edges.setdefault(start, []).append((end, seconds))
                if direction <= 0:
                    edges.setdefault(end, []).append((start, seconds))
            lines.append([round(value, 5) for node in ids for value in (nodes[node][1], nodes[node][0])])
        used = set(edges) | {node for targets in edges.values() for node, _ in targets}
        return cls({node: nodes[node] for node in used}, edges, lines)

    def nearest(self, lat: float, lon: float) -> int:
        """The road point closest to a place (one that leads somewhere)."""
        scale = math.cos(math.radians(lat))
        return min((node for node in self.edges), key=lambda node: (self.nodes[node][0] - lat) ** 2
                   + ((self.nodes[node][1] - lon) * scale) ** 2)

    def search(self, start: int, goals: set[int]) -> tuple[dict[int, float], dict[int, int], list[tuple[int, int]]]:
        """Dijkstra from start until every goal is reached: (seconds to each reached point, where it came from,
        the roads in the order the search took them)."""
        best, came, taken = {start: 0.0}, {}, []
        queue, done, left = [(0.0, start)], set(), set(goals)
        while queue and left:
            seconds, node = heapq.heappop(queue)
            if node in done:
                continue
            done.add(node)
            left.discard(node)
            if node in came:
                taken.append((came[node], node))
            for following, cost in self.edges.get(node, ()):
                total = seconds + cost
                if total < best.get(following, math.inf):
                    best[following], came[following] = total, node
                    heapq.heappush(queue, (total, following))
        return best, came, taken


def path(came: dict[int, int], start: int, end: int) -> list[int]:
    nodes = [end]
    while nodes[-1] != start:
        nodes.append(came[nodes[-1]])
    return nodes[::-1]


def best_order(times: list[list[float]], keep_end: bool) -> list[int]:
    """The visiting order with the least total time: the first place stays first, and the last stays last when it's
    the destination. Brute force: at most 6 places, 120 orders."""
    count = len(times)
    middle = list(range(1, count - 1 if keep_end else count))
    def total(order: tuple[int, ...]) -> float:
        stops = [0, *order, *([count - 1] if keep_end else [])]
        return sum(times[a][b] for a, b in zip(stops, stops[1:]))
    chosen = min(itertools.permutations(middle), key=total)
    return [0, *chosen, *([count - 1] if keep_end else [])]


@dataclass
class Route:
    places: list[dict[str, Any]]                    # [{"name", "lat", "lon"}] in visiting order
    mode: str
    seconds: float
    metres: float
    legs: list[dict[str, float]]                    # [{"seconds", "metres"}] between consecutive places
    line: list[list[float]]                         # each leg's path as [lon, lat, …]
    searched: list[list[float]]                     # [leg, lon1, lat1, lon2, lat2] in search order
    roads: list[list[float]]                        # the map's roads
    reordered: bool = False

    def google_maps(self) -> str:
        ends = [f"{place['lat']:.6f},{place['lon']:.6f}" for place in self.places]
        query = {"api": 1, "origin": ends[0], "destination": ends[-1],
                 "travelmode": "walking" if self.mode == "walk" else "driving"}
        if len(ends) > 2:
            query["waypoints"] = "|".join(ends[1:-1])
        return "https://www.google.com/maps/dir/?" + urlencode(query, quote_via=quote)

    def summary(self) -> str:
        how = {"motorbike": "by motorbike", "car": "by car", "walk": "on foot"}[self.mode]
        names = " → ".join(place["name"] for place in self.places)
        legs = "".join(f"\n- {self.places[index]['name']} → {self.places[index + 1]['name']}: {describe(leg['seconds'])}, "
                       f"{leg['metres'] / 1000:.1f} km" for index, leg in enumerate(self.legs)) if len(self.legs) > 1 else ""
        order = " (stops put in the quickest order)" if self.reordered else ""
        return (f"Fastest route {how}: {names}{order}. About {describe(self.seconds)}, {self.metres / 1000:.1f} km, at "
                f"normal speeds (no live traffic).{legs}\nThe map on Nova's screen shows it; Google Maps for live "
                f"traffic: {self.google_maps()}")


def describe(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d} min"


class Router:
    def __init__(self, cache: Path, opener: Callable[..., Any] = urlopen, clock: Callable[[], float] = time.time,
                 near: Callable[[], str] = lambda: "") -> None:
        self.cache, self._open, self._clock, self.near = Path(cache), opener, clock, near
        self._last_geocode = 0.0

    def _fetch(self, request: Request, timeout: int) -> bytes:
        with self._open(request, timeout=timeout) as response:
            return response.read(200_000_000)

    def geocode(self, place: str) -> dict[str, Any]:
        """A place the owner named, near their saved city first (Nominatim allows one request a second)."""
        name = " ".join(str(place).split())[:120]
        if not name:
            raise ValueError("say where from and where to")
        for query in ([f"{name}, {self.near()}"] if self.near() else []) + [name]:
            wait = 1.0 - (self._clock() - self._last_geocode)
            if wait > 0:
                time.sleep(wait)
            self._last_geocode = self._clock()
            found = json.loads(self._fetch(Request(NOMINATIM + "?" + urlencode({"q": query, "format": "json", "limit": 1}),
                                                   headers={"User-Agent": USER_AGENT}), 20))
            if found:
                return {"name": name, "lat": float(found[0]["lat"]), "lon": float(found[0]["lon"])}
        raise ValueError(f"couldn't find “{name}” on the map")

    def roads(self, places: list[dict[str, Any]], mode: str) -> Roads:
        south, north = min(p["lat"] for p in places), max(p["lat"] for p in places)
        west, east = min(p["lon"] for p in places), max(p["lon"] for p in places)
        if max(north - south, east - west) > MAX_SPAN_DEGREES:
            raise ValueError("those places are too far apart for the map on this PC (over about 65 km)")
        margin = max(0.015, 0.15 * max(north - south, east - west))
        box = tuple(round(value, 3) for value in (south - margin, west - margin, north + margin, east + margin))
        kinds = "|".join(sorted({kind for speeds in SPEEDS.values() for kind in speeds}))
        query = (f'[out:json][timeout:90];way["highway"~"^({kinds})(_link)?$"]{box};out body;>;out skel qt;')
        key = hashlib.sha1(query.encode()).hexdigest()[:16]
        saved = self.cache / f"roads-{key}.json"
        if saved.is_file() and self._clock() - saved.stat().st_mtime < CACHE_DAYS * 86400:
            data = json.loads(saved.read_text(encoding="utf-8"))
        else:
            data = json.loads(self._fetch(Request(OVERPASS, data=urlencode({"data": query}).encode(),
                                                  headers={"User-Agent": USER_AGENT}), 120))
            self.cache.mkdir(parents=True, exist_ok=True)
            saved.write_text(json.dumps(data), encoding="utf-8")
        return Roads.from_overpass(data, mode)

    def route(self, start: str, end: str, stops: list[str] | None = None, mode: str = "motorbike",
              reorder: bool = True) -> Route:
        mode = mode if mode in MODES else "motorbike"
        names = [start, *(stops or [])[:MAX_STOPS - 2], end]
        places = [self.geocode(name) for name in names]
        roads = self.roads(places, mode)
        points = [roads.nearest(place["lat"], place["lon"]) for place in places]
        searches = {}
        if reorder and len(points) > 3:
            times = []
            for index, point in enumerate(points):
                searches[index] = roads.search(point, set(points))
                times.append([searches[index][0].get(other, math.inf) for other in points])
            order = best_order(times, keep_end=True)
        else:
            order = list(range(len(points)))
        legs, line, searched, total_seconds, total_metres = [], [], [], 0.0, 0.0
        for leg, (a, b) in enumerate(zip(order, order[1:])):
            best, came, taken = roads.search(points[a], {points[b]})  # each leg's own search: that's what the map replays
            if points[b] not in best:
                raise ValueError(f"there's no road route from {places[a]['name']} to {places[b]['name']} {mode}")
            nodes = path(came, points[a], points[b])
            metres = sum(haversine(*roads.nodes[x], *roads.nodes[y]) for x, y in zip(nodes, nodes[1:]))
            legs.append({"seconds": best[points[b]], "metres": metres})
            total_seconds, total_metres = total_seconds + best[points[b]], total_metres + metres
            line.append([round(value, 5) for node in nodes for value in (roads.nodes[node][1], roads.nodes[node][0])])
            searched += [[leg, *(round(value, 5) for value in (*roads.nodes[x][::-1], *roads.nodes[y][::-1]))]
                         for x, y in taken]
        step = max(1, len(searched) // MAX_SEARCH_SEGMENTS)
        return Route([places[index] for index in order], mode, total_seconds, total_metres, legs, line,
                     searched[::step], roads.lines, reordered=order != sorted(order))
