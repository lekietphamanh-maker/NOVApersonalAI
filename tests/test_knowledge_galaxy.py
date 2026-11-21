"""Tests for knowledge_galaxy.build_graph."""
from __future__ import annotations

import math
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

import knowledge_galaxy
from knowledge_galaxy import _excerpt, _node_id, _spherical_spread, build_graph


@pytest.fixture(autouse=True)
def _no_archmancer(monkeypatch):
    """Prevent archmancer from loading in tests (it adds real skill nodes)."""
    monkeypatch.setitem(sys.modules, "archmancer", None)


class TestNodeId:
    def test_deterministic(self):
        assert _node_id("wiki", "Rust") == _node_id("wiki", "Rust")

    def test_different_kinds(self):
        assert _node_id("wiki", "Rust") != _node_id("fact", "Rust")

    def test_length(self):
        assert len(_node_id("skill", "agent-loops")) == 12


class TestExcerpt:
    def test_strips_headings(self):
        text = "# Title\n\nBody of the note is here and it matters."
        result = _excerpt(text)
        assert "Body" in result
        assert "Title" not in result

    def test_truncates_long_text(self):
        text = "word " * 100
        result = _excerpt(text)
        assert len(result) <= knowledge_galaxy.MAX_EXCERPT + 3
        assert result.endswith("...")

    def test_empty(self):
        assert _excerpt("") == ""


class TestSphericalSpread:
    def test_count(self):
        assert len(_spherical_spread(10)) == 10

    def test_radius(self):
        for x, y, z in _spherical_spread(20, radius=40):
            dist = math.sqrt(x * x + y * y + z * z)
            assert dist <= 40.1

    def test_single_point(self):
        pts = _spherical_spread(1)
        assert len(pts) == 1

    def test_zero(self):
        assert _spherical_spread(0) == []


class TestBuildGraph:
    def test_empty(self):
        graph = build_graph()
        assert graph == {"nodes": [], "edges": []}

    def test_facts_only(self):
        facts = [{"id": 1, "fact": "Klee likes TypeScript"}, {"id": 2, "fact": "Nova runs on Windows"}]
        graph = build_graph(facts=facts)
        fact_nodes = [n for n in graph["nodes"] if n["kind"] == "fact"]
        assert len(fact_nodes) == 2
        assert all("x" in n and "y" in n and "z" in n for n in graph["nodes"])

    def test_wiki_pages(self, tmp_path: Path):
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "Rust.md").write_text("# Rust\n\nA systems language. See [[Python]].\n")
        (wiki / "Python.md").write_text("# Python\n\nA scripting language.\n")
        (wiki / "index.md").write_text("index page, should be skipped\n")

        graph = build_graph(vault_folder=tmp_path)
        wiki_nodes = [n for n in graph["nodes"] if n["kind"] == "wiki"]
        assert len(wiki_nodes) == 2
        labels = {n["label"] for n in wiki_nodes}
        assert labels == {"Rust", "Python"}
        assert len(graph["edges"]) == 1

    def test_raw_sources(self, tmp_path: Path):
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "Rust.md").write_text("# Rust\n\nSee [[raw/clips/rust-talk]].\n")
        raw = tmp_path / "raw" / "clips"
        raw.mkdir(parents=True)
        (raw / "rust-talk.md").write_text("Talk about Rust by someone.\n")

        graph = build_graph(vault_folder=tmp_path)
        source_nodes = [n for n in graph["nodes"] if n["kind"] == "source"]
        assert len(source_nodes) == 1
        assert source_nodes[0]["label"] == "rust-talk"

    def test_fact_wiki_linking(self, tmp_path: Path):
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "Rust.md").write_text("# Rust\n\nSystems programming.\n")

        graph = build_graph(vault_folder=tmp_path, facts=[{"id": 1, "fact": "I am learning Rust"}])
        fact_nodes = [n for n in graph["nodes"] if n["kind"] == "fact"]
        assert len(fact_nodes) == 1
        assert len(graph["edges"]) >= 1

    def test_node_positions_unique(self, tmp_path: Path):
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        for i in range(10):
            (wiki / f"Topic{i}.md").write_text(f"# Topic {i}\n\nSome content.\n")
        graph = build_graph(vault_folder=tmp_path)
        positions = [(n["x"], n["y"], n["z"]) for n in graph["nodes"]]
        assert len(set(positions)) == len(positions)

    def test_node_sizes(self):
        facts = [{"id": 1, "fact": "small fact"}]
        graph = build_graph(facts=facts)
        assert graph["nodes"][0]["size"] > 0

    def test_edges_no_self_loops(self, tmp_path: Path):
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "A.md").write_text("# A\n\nSee [[A]].\n")
        graph = build_graph(vault_folder=tmp_path)
        for edge in graph["edges"]:
            assert edge["source"] != edge["target"]

    def test_blank_facts_skipped(self):
        facts = [{"id": 1, "fact": ""}, {"id": 2, "fact": "   "}, {"id": 3, "fact": "valid"}]
        graph = build_graph(facts=facts)
        fact_nodes = [n for n in graph["nodes"] if n["kind"] == "fact"]
        assert len(fact_nodes) == 1

    def test_archmancer_integration(self, tmp_path: Path, monkeypatch):
        import types
        fake_arch = types.ModuleType("archmancer")
        fake_arch.SKILLS = {"agent-loops": "some doc", "tool-use": "other doc"}
        fake_arch.read_skill = lambda name: f"Docs for {name}"
        monkeypatch.setitem(__import__("sys").modules, "archmancer", fake_arch)

        graph = build_graph()
        skill_nodes = [n for n in graph["nodes"] if n["kind"] == "skill"]
        assert len(skill_nodes) == 2
        labels = {n["label"] for n in skill_nodes}
        assert "Agent Loops" in labels
        assert "Tool Use" in labels
