"""Fastest routes on real roads, worked out on this PC: from A to B, or through several stops in the best order.

Places are found with OpenStreetMap's Nominatim; the roads around them come from OpenStreetMap's Overpass API (kept on
disk for 30 days, so the same city is quick and works offline afterwards). The route itself is found here with
Dijkstra's search, and the order in which the search reached each road is kept: Nova's map replays it, the search
spreading out along the streets until it reaches the destination, then the fastest path lights up.

When the map servers are busy they answer 502/503/429 a lot, so each fetch is tried a few times with a short wait,
then the next copy of the road server; a download that still fails falls back to the roads already kept on disk,
even an old copy. Far-apart places are fetched as a corridor along the straight line between them, in tiles no
bigger than about 55 km, instead of one giant box for the whole area between them.

Times assume the usual speed of each kind of road: OpenStreetMap has no live traffic. Only the place names and the
map area are sent anywhere.
"""
from __future__ import annotations

import hashlib
import heapq
import itertools
import json
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"
OVERPASS_MIRRORS = (OVERPASS, "https://overpass.kumi.systems/api/interpreter",
                    "https://overpass.nchc.org.tw/api/interpreter", "https://overpass.private.coffee/api/interpreter")
USER_AGENT = "Nova-Route/1.0"
CACHE_DAYS = 30
MAX_SPAN_DEGREES = 0.6         # about 65 km: farther than this, the roads would be too much to fetch
MAX_STOPS = 6
MAX_SEARCH_SEGMENTS = 30_000   # what the map replays of the search
RETRY_DELAYS = (1.0, 2.0)      # waits between the three tries on one server (502/503/429: the server is busy)
TILE_SPAN = 0.5                # one Overpass query never covers more than this, in degrees (about 55 km)
TILE_OVERLAP = 0.02            # tiles overlap a little, so a road crossing a border is in both
CORRIDOR_BUFFER = 0.05         # about 5 km of roads each side of the straight line between the places
MAX_CORRIDOR_TILES = 8         # a corridor longer than this (about 400 km) is refused, not fetched forever
MAX_KEEP_TILES = 25            # a place bigger than this (about 250 km across) is too big to keep, even in pieces
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
        return _google_maps_link(self.places, self.mode)

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


def _google_maps_link(places: list[dict[str, Any]], mode: str) -> str:
    ends = [f"{place['lat']:.6f},{place['lon']:.6f}" for place in places]
    query = {"api": 1, "origin": ends[0], "destination": ends[-1],
             "travelmode": "walking" if mode == "walk" else "driving"}
    if len(ends) > 2:
        query["waypoints"] = "|".join(ends[1:-1])
    return "https://www.google.com/maps/dir/?" + urlencode(query, quote_via=quote)


def _fallback_note(places: list[dict[str, Any]], mode: str) -> str:
    """What the screen can still offer when the roads couldn't be fetched: how far apart the places are as the
    crow flies, and the Google Maps link that routes them live."""
    km = sum(haversine(a["lat"], a["lon"], b["lat"], b["lon"]) for a, b in zip(places, places[1:])) / 1000
    return (f" As the crow flies it's {km:.1f} km from {places[0]['name']} to {places[-1]['name']}. "
            f"Google Maps can still route it live: {_google_maps_link(places, mode)}")


def _split_box(box: tuple[float, float, float, float], tile: float = TILE_SPAN,
               overlap: float = TILE_OVERLAP) -> list[tuple[float, float, float, float]]:
    """A box cut into tiles no wider than `tile`, overlapping a little so roads crossing a border are fetched in
    both tiles (the merge dedupes them)."""
    south, west, north, east = box

    def slices(low: float, high: float) -> list[tuple[float, float]]:
        cuts, start = [], low
        while start < high:
            cuts.append((start, min(high, start + tile)))
            if start + tile >= high:
                break
            start += tile - overlap
        return cuts

    return [tuple(round(value, 3) for value in (s, w, n, e))  # type: ignore[return-value]
            for s, n in slices(south, north) for w, e in slices(west, east)]


def _merge_overpass(datasets: list[dict[str, Any]]) -> dict[str, Any]:
    """Several Overpass answers as one: nodes and ways deduped by (type, id), so a road fetched in two tiles is
    kept once."""
    seen, elements = set(), []
    for data in datasets:
        for item in data.get("elements", []):
            key = (item.get("type"), item.get("id"))
            if key not in seen:
                seen.add(key)
                elements.append(item)
    return {"elements": elements}


class Router:
    def __init__(self, cache: Path, opener: Callable[..., Any] = urlopen, clock: Callable[[], float] = time.time,
                 near: Callable[[], str] = lambda: "", sleep: Callable[[float], None] = time.sleep) -> None:
        self.cache, self._open, self._clock, self.near, self._sleep = Path(cache), opener, clock, near, sleep
        self._last_geocode = 0.0
        self._keep_lock = threading.Lock()
        self._keeping: dict[str, dict[str, Any]] = {}  # city name -> {"done", "name", "error"} of a keep in progress

    def _fetch(self, request: Request, timeout: int) -> bytes:
        with self._open(request, timeout=timeout) as response:
            return response.read(200_000_000)

    def _fetch_retry(self, build: Callable[[str], Request], timeout: int, bases: tuple[str, ...],
                     label: str) -> bytes:
        """One fetch, tried a few times on each server in turn: a 502, 503 or 429 (or a dropped connection) means
        the server is busy, not that the request is wrong, so it waits a second, tries again, waits two seconds,
        tries once more, and only then moves on to the next copy of the server. A different HTTP error (a bad
        request, say) fails straight away. Raises a plain-word OSError when every server stayed silent."""
        last: Exception | None = None
        for base in bases:
            for attempt in range(len(RETRY_DELAYS) + 1):
                try:
                    return self._fetch(build(base), timeout)
                except HTTPError as exc:
                    last = exc
                    if exc.code not in (502, 503, 429):
                        raise
                except OSError as exc:  # unreachable, reset, timed out: the server may just be busy
                    last = exc
                if attempt < len(RETRY_DELAYS):
                    self._sleep(RETRY_DELAYS[attempt])
        raise OSError(f"{label} didn't answer, even after trying {len(bases)} "
                      f"{'address' if len(bases) == 1 else 'addresses'} — it's busy right now, so try again in a "
                      f"bit (last try: {last})")

    def _places_file(self) -> Path:
        return self.cache / "places.json"

    def geocode(self, place: str) -> dict[str, Any]:
        """A place the owner named, near their saved city first (Nominatim allows one request a second). Places found
        once are kept, so they work offline afterwards."""
        name = " ".join(str(place).split())[:120]
        if not name:
            raise ValueError("say where from and where to")
        try:
            known = json.loads(self._places_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            known = {}
        key = f"{name.lower()}|{self.near().lower()}"
        if key in known:
            return {"name": name, **known[key]}
        found = self._lookup(name)
        known[key] = {"lat": found["lat"], "lon": found["lon"]}
        self.cache.mkdir(parents=True, exist_ok=True)
        self._places_file().write_text(json.dumps(known), encoding="utf-8")
        return found

    def _lookup(self, name: str) -> dict[str, Any]:
        found = self._nominatim(name)
        if found is None:
            raise ValueError(f"couldn't find “{name}” on the map")
        return {"name": name, "lat": float(found["lat"]), "lon": float(found["lon"])}

    def _nominatim(self, name: str) -> dict[str, Any] | None:
        """The first Nominatim hit for a place, near the owner's city first (Nominatim allows one request a
        second), or None when it isn't on the map. Retried when the server is busy, like every other fetch."""
        for query in ([f"{name}, {self.near()}"] if self.near() else []) + [name]:
            wait = 1.0 - (self._clock() - self._last_geocode)
            if wait > 0:
                self._sleep(wait)
            self._last_geocode = self._clock()
            found = json.loads(self._fetch_retry(
                lambda base: Request(base + "?" + urlencode({"q": query, "format": "json", "limit": 1}),
                                     headers={"User-Agent": USER_AGENT}),
                20, (NOMINATIM,), "the place search"))
            if found:
                return found[0]
        return None

    def _kept_city(self, south: float, west: float, north: float, east: float) -> dict[str, Any] | None:
        """A city kept for offline use that covers this whole area."""
        for kept in sorted(self.cache.glob("city-*.json")):
            try:
                data = json.loads(kept.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            box = data.get("nova_box") or [90, 180, -90, -180]
            if box[0] <= south and box[1] <= west and north <= box[2] and east <= box[3]:
                return data
        return None

    def kept_cities(self) -> list[str]:
        return [path.stem.removeprefix("city-").replace("_", " ") for path in sorted(self.cache.glob("city-*.json"))]

    def keep_city(self, city: str) -> str:
        """Downloads all of a city's roads once and keeps them (no expiry), so routes inside it work offline.
        A county-sized place is fetched in tiles and merged into the one kept file; a place too big even in
        pieces is refused plainly. A second keep of the same city started while one is already running (a
        double-click on a button that takes minutes) waits for the first and shares its result instead of
        downloading the whole place twice."""
        name = " ".join(str(city).split())[:80]
        with self._keep_lock:
            running = self._keeping.get(name)
            if running is None:
                running = {"done": threading.Event(), "name": None, "error": None}
                self._keeping[name] = running
                mine = True
            else:
                mine = False
        if not mine:
            running["done"].wait()
            if running["error"] is not None:
                raise running["error"]
            return running["name"]
        try:
            running["name"] = self._keep_city_once(name)
            return running["name"]
        except Exception as exc:
            running["error"] = exc
            raise
        finally:
            running["done"].set()
            with self._keep_lock:
                self._keeping.pop(name, None)

    def _keep_city_once(self, name: str) -> str:
        found = self._nominatim(name)
        if found is None:
            raise ValueError(f"couldn't find “{name}” on the map")
        south, north, west, east = (float(value) for value in found["boundingbox"])
        box = (round(south, 3), round(west, 3), round(north, 3), round(east, 3))
        target = self.cache / f"city-{name.replace(' ', '_').replace('/', '_')[:60]}.json"
        try:
            if max(north - south, east - west) <= MAX_SPAN_DEGREES:
                data = self._download_roads(box)
            else:
                tiles = _split_box(box)
                if len(tiles) > MAX_KEEP_TILES:
                    across = round(max(north - south, east - west) * 111)
                    raise ValueError(f"{name} is too big to keep, even in pieces — about {across} km across. "
                                     f"Keep one town inside it instead, or just ask for a route between two "
                                     f"towns inside it.")
                data = _merge_overpass([self._download_roads(tile) for tile in tiles])
        except OSError:
            if target.is_file():
                return name  # the download failed, but the roads kept last time are still there: keep using them
            raise
        data["nova_box"] = [south, west, north, east]
        self.cache.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data), encoding="utf-8")
        return name

    def _download_roads(self, box: tuple[float, float, float, float]) -> dict[str, Any]:
        kinds = "|".join(sorted({kind for speeds in SPEEDS.values() for kind in speeds}))
        query = f'[out:json][timeout:180];way["highway"~"^({kinds})(_link)?$"]{box};out body;>;out skel qt;'
        return json.loads(self._fetch_retry(
            lambda base: Request(base, data=urlencode({"data": query}).encode(),
                                 headers={"User-Agent": USER_AGENT}),
            240, OVERPASS_MIRRORS, "the road server"))

    def _roads_for_box(self, box: tuple[float, float, float, float], tiled: bool) -> dict[str, Any] | None:
        """The roads for a box: a fresh copy kept on disk when there is one, else a download — in tiles when
        `tiled`, merged into one answer. Returns None when even tiled it would take more than MAX_CORRIDOR_TILES
        queries and there is no kept copy at all. When the download fails, a kept copy is used instead, even an
        old one past its 30 days: old roads beat no roads."""
        key = hashlib.sha1(repr(box).encode()).hexdigest()[:16]
        saved = self.cache / f"roads-{key}.json"
        if saved.is_file() and self._clock() - saved.stat().st_mtime < CACHE_DAYS * 86400:
            return json.loads(saved.read_text(encoding="utf-8"))
        tiles = _split_box(box) if tiled else [box]
        if len(tiles) > MAX_CORRIDOR_TILES:
            return json.loads(saved.read_text(encoding="utf-8")) if saved.is_file() else None
        try:
            data = _merge_overpass([self._download_roads(tile) for tile in tiles]) if tiled \
                else self._download_roads(box)
        except OSError:
            if saved.is_file():
                return json.loads(saved.read_text(encoding="utf-8"))
            raise
        self.cache.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps(data), encoding="utf-8")
        return data

    def roads(self, places: list[dict[str, Any]], mode: str) -> Roads:
        south, north = min(p["lat"] for p in places), max(p["lat"] for p in places)
        west, east = min(p["lon"] for p in places), max(p["lon"] for p in places)
        kept = self._kept_city(south, west, north, east)
        if kept is not None:
            return Roads.from_overpass(kept, mode)
        if max(north - south, east - west) <= MAX_SPAN_DEGREES:
            margin = max(0.015, 0.15 * max(north - south, east - west))
            box = tuple(round(value, 3) for value in (south - margin, west - margin, north + margin, east + margin))
            return Roads.from_overpass(self._roads_for_box(box, tiled=False), mode)
        # Far apart: fetch the corridor along the places — the straight line between them plus a buffer a few km
        # wide (wider on a longer trip) — not the whole box between them, so two towns in one big county need a
        # thin strip of roads, not the county. A long corridor is fetched tile by tile along its length.
        lats, lons = [p["lat"] for p in places], [p["lon"] for p in places]
        trip = max(max(lats) - min(lats), max(lons) - min(lons))
        buffer = max(CORRIDOR_BUFFER, 0.15 * trip)
        box = tuple(round(value, 3) for value in (min(lats) - buffer, min(lons) - buffer,
                                                  max(lats) + buffer, max(lons) + buffer))
        data = self._roads_for_box(box, tiled=True)
        if data is None:
            raise ValueError(f"those places are too far apart for the map on this PC to fetch, even a strip at a "
                             f"time.{_fallback_note(places, mode)} — or pick two towns closer together")
        return Roads.from_overpass(data, mode)

    def route(self, start: str, end: str, stops: list[str] | None = None, mode: str = "motorbike",
              reorder: bool = True) -> Route:
        mode = mode if mode in MODES else "motorbike"
        names = [start, *(stops or [])[:MAX_STOPS - 2], end]
        places = [self.geocode(name) for name in names]
        try:
            roads = self.roads(places, mode)
        except OSError as exc:  # the servers stayed silent even after retries, mirrors and kept roads: say so
            # plainly, and still offer what can be offered — how far apart they are, and Google Maps live.
            raise OSError(f"{exc}{_fallback_note(places, mode)}") from exc
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
                raise ValueError(f"there's no road route from {places[a]['name']} to {places[b]['name']} {mode}"
                                 f"{_fallback_note(places, mode)}")
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
