"""Builds ui/world-110m.json, the World view's map, from world-atlas's countries-110m.json (Natural Earth 1:110m,
public domain; world-atlas is ISC). Run once: npm pack world-atlas@2.0.2, unpack it, then
    python scripts/make_world_map.py path/to/package/countries-110m.json

Each country keeps its name, its outline rings as flat [lon, lat, lon, lat, …] lists (2 decimals), its bounding box
and a centre (its largest ring's centroid), which places news about it on the globe.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def decode_arcs(topology: dict) -> list[list[tuple[float, float]]]:
    (scale_x, scale_y), (shift_x, shift_y) = topology["transform"]["scale"], topology["transform"]["translate"]
    arcs = []
    for arc in topology["arcs"]:
        x = y = 0
        points = []
        for dx, dy in arc:
            x, y = x + dx, y + dy
            points.append((x * scale_x + shift_x, y * scale_y + shift_y))
        arcs.append(points)
    return arcs


def ring(arcs: list[list[tuple[float, float]]], indexes: list[int]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for index in indexes:
        arc = arcs[index] if index >= 0 else arcs[~index][::-1]
        points.extend(arc[1:] if points else arc)
    return points


def area(points: list[tuple[float, float]]) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]))) / 2


def centre(points: list[tuple[float, float]]) -> tuple[float, float]:
    """The ring's centroid; a ring across the date line (Russia, Fiji) is unwrapped first."""
    if max(x for x, _ in points) - min(x for x, _ in points) > 180:
        points = [(x + 360 if x < 0 else x, y) for x, y in points]
    twice_area = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        cross = x1 * y2 - x2 * y1
        twice_area += cross
        cx, cy = cx + (x1 + x2) * cross, cy + (y1 + y2) * cross
    if abs(twice_area) < 1e-9:
        x, y = sum(x for x, _ in points) / len(points), sum(y for _, y in points) / len(points)
    else:
        x, y = cx / (3 * twice_area), cy / (3 * twice_area)
    return ((x + 180) % 360) - 180, y


def build(topology: dict) -> dict:
    arcs = decode_arcs(topology)
    countries = []
    for geometry in topology["objects"]["countries"]["geometries"]:
        polygons = {"Polygon": [geometry.get("arcs", [])], "MultiPolygon": geometry.get("arcs", [])}.get(geometry["type"], [])
        rings = [ring(arcs, indexes) for polygon in polygons for indexes in polygon]
        rings = [points for points in rings if len(points) > 2]
        if not rings:
            continue
        middle = centre(max(rings, key=area))
        all_x, all_y = [x for points in rings for x, _ in points], [y for points in rings for _, y in points]
        countries.append({
            "name": geometry["properties"]["name"],
            "center": [round(middle[0], 2), round(middle[1], 2)],
            "bbox": [round(min(all_x), 2), round(min(all_y), 2), round(max(all_x), 2), round(max(all_y), 2)],
            "rings": [[round(value, 2) for point in points for value in point] for points in rings]})
    return {"source": "Natural Earth 1:110m (public domain), via world-atlas 2.0.2 (ISC)", "countries": countries}


if __name__ == "__main__":
    data = build(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    out = Path(__file__).resolve().parent.parent / "ui" / "world-110m.json"
    out.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"{len(data['countries'])} countries → {out} ({out.stat().st_size // 1024} KB)")
