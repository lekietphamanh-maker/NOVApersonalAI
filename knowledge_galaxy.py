"""Build a graph of Nova's knowledge for the 3D galaxy view.

Reads the second brain wiki pages (topics + [[links]]), memory facts, and Archmancer skills,
and returns a JSON-serializable graph the UI renders as a star map.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LINK_RE = re.compile(r"\[\[([^\]]+)]]")
MAX_EXCERPT = 200
GOLDEN_ANGLE = math.pi * (3 - math.sqrt(5))


@dataclass(frozen=True)
class Node:
    id: str
    label: str
    kind: str  # "wiki", "fact", "skill", "source"
    excerpt: str = ""
    weight: int = 1


@dataclass(frozen=True)
class Edge:
    source: str
    target: str


def _node_id(kind: str, label: str) -> str:
    return hashlib.sha1(f"{kind}:{label}".encode()).hexdigest()[:12]


def _excerpt(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    body = " ".join(lines)
    return body[:MAX_EXCERPT].rsplit(" ", 1)[0] + ("..." if len(body) > MAX_EXCERPT else "")


def _spherical_spread(count: int, radius: float = 40.0) -> list[tuple[float, float, float]]:
    """Distribute points on a sphere using the Fibonacci lattice (even spacing)."""
    positions: list[tuple[float, float, float]] = []
    for i in range(count):
        y = 1 - (2 * i / max(count - 1, 1))
        r = math.sqrt(max(0, 1 - y * y))
        theta = GOLDEN_ANGLE * i
        x = math.cos(theta) * r * radius
        z = math.sin(theta) * r * radius
        positions.append((x, y * radius, z))
    return positions


def build_graph(vault_folder: Path | None = None,
                facts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return ``{"nodes": [...], "edges": [...]}`` for the galaxy renderer."""
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    links_by_page: dict[str, list[str]] = {}

    # --- wiki pages ---
    if vault_folder is not None:
        wiki = vault_folder / "wiki"
        if wiki.is_dir():
            for path in sorted(wiki.glob("*.md")):
                if path.stem == "index":
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                outgoing = [match.group(1) for match in LINK_RE.finditer(text)]
                nid = _node_id("wiki", path.stem)
                nodes[nid] = Node(id=nid, label=path.stem, kind="wiki",
                                  excerpt=_excerpt(text), weight=max(1, len(outgoing)))
                links_by_page[path.stem] = outgoing

        # build edges from [[links]]
        label_to_id = {node.label: node.id for node in nodes.values() if node.kind == "wiki"}
        for page_name, outgoing in links_by_page.items():
            source_id = label_to_id.get(page_name)
            if source_id is None:
                continue
            for target_label in outgoing:
                target_id = label_to_id.get(target_label)
                if target_id and target_id != source_id:
                    edges.append(Edge(source=source_id, target=target_id))

        # raw sources as smaller nodes
        raw = vault_folder / "raw"
        if raw.is_dir():
            for subfolder in ("clips", "notes"):
                folder = raw / subfolder
                if folder.is_dir():
                    for path in sorted(folder.glob("*.md"))[:50]:
                        nid = _node_id("source", path.stem)
                        text = path.read_text(encoding="utf-8", errors="replace")[:600]
                        nodes[nid] = Node(id=nid, label=path.stem, kind="source", excerpt=_excerpt(text))
                        ref = f"raw/{subfolder}/{path.stem}"
                        for page_name, outgoing in links_by_page.items():
                            if any(ref in link for link in outgoing):
                                pid = label_to_id.get(page_name)
                                if pid:
                                    edges.append(Edge(source=pid, target=nid))

    # --- memory facts ---
    if facts:
        for item in facts[:40]:
            text = item.get("fact", "") if isinstance(item, dict) else str(item)
            if not text.strip():
                continue
            nid = _node_id("fact", text)
            label = text[:60] + ("..." if len(text) > 60 else "")
            nodes[nid] = Node(id=nid, label=label, kind="fact", excerpt=text)
            words = set(re.findall(r"\w{4,}", text.lower()))
            for wiki_node in list(nodes.values()):
                if wiki_node.kind == "wiki":
                    if any(w in wiki_node.label.lower() for w in words):
                        edges.append(Edge(source=wiki_node.id, target=nid))

    # --- archmancer skills ---
    try:
        import archmancer
        for skill_name in archmancer.SKILLS:
            nid = _node_id("skill", skill_name)
            info = archmancer.read_skill(skill_name)
            nodes[nid] = Node(id=nid, label=skill_name.replace("-", " ").title(),
                              kind="skill", excerpt=info[:MAX_EXCERPT])
    except ImportError:
        pass

    # --- assign positions (Fibonacci sphere) ---
    node_list = list(nodes.values())
    positions = _spherical_spread(len(node_list))
    result_nodes = []
    for i, node in enumerate(node_list):
        x, y, z = positions[i] if i < len(positions) else (0, 0, 0)
        size = {"wiki": 1.0, "fact": 0.5, "skill": 0.8, "source": 0.4}.get(node.kind, 0.6)
        size *= min(2.0, 0.6 + node.weight * 0.15)
        result_nodes.append({
            "id": node.id, "label": node.label, "kind": node.kind,
            "excerpt": node.excerpt, "x": round(x, 2), "y": round(y, 2), "z": round(z, 2),
            "size": round(size, 2),
        })

    unique_edges = list({(e.source, e.target) for e in edges if e.source != e.target})
    result_edges = [{"source": s, "target": t} for s, t in unique_edges]

    return {"nodes": result_nodes, "edges": result_edges}
