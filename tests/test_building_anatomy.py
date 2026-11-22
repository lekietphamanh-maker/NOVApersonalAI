"""Building mode, explained with Anatomy: the bench as an isometric figure (wheresryan22/anatomy, MIT) — one
shaded box per part, wires arcing part to part, a framed card with a live readout, every number from the bench."""
from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import building

CATALOG = building.load_catalog(Path(__file__).resolve().parent.parent / "ui" / "circuit" / "catalog.json")
BLINK = {"v": 1,
         "items": [{"ref": "uno", "type": "board:uno", "x": 0, "y": 0, "rot": 0, "state": {}},
                   {"ref": "led", "type": "mod:led", "x": 10, "y": 10, "rot": 0, "state": {}}],
         "wires": [{"a": ["uno", 13], "b": ["led", 0], "color": "yellow"},
                   {"a": ["uno", 0], "b": ["led", 1], "color": "black"}]}


def open_bench(circuit=None, text="", title="Blinking LED"):
    events: list[dict] = []
    bench = building.BuildingBench(Path(tempfile.mkdtemp()), events.append, CATALOG)
    bench.sync(True, "Blink", title, text or "Parts on the bench (2): uno (Arduino Uno R3)\nChecks: no problems found.",
               circuit if circuit is not None else BLINK)
    return bench, events


class AnatomyTests(unittest.TestCase):
    def test_empty_bench_still_draws_a_card(self) -> None:
        bench, _ = open_bench({"v": 1, "items": [], "wires": []}, "The bench is empty.")
        svg = bench.anatomy_svg()
        ET.fromstring(svg)
        self.assertIn("Fig 1", svg)
        self.assertIn("The bench is empty", svg)
        self.assertIn("0 PARTS", svg)
        self.assertIn("0 WIRES", svg)

    def test_blink_bench_readout_matches_the_bench(self) -> None:
        bench, _ = open_bench()
        svg = bench.anatomy_svg()
        ET.fromstring(svg)
        self.assertIn("BOARD uno", svg)
        self.assertIn("1 PART", svg)
        self.assertIn("2 WIRES", svg)
        self.assertIn("Arduino Uno R3", svg)          # the board's real name, in the caption
        self.assertIn("no problems found", svg)       # the bench's own checks, in the readout
        self.assertGreaterEqual(svg.count("<polygon"), 20)  # base, feet, board, LED, part, chip: small shaded boxes

    def test_the_figure_is_deterministic(self) -> None:
        bench, _ = open_bench()
        self.assertEqual(bench.anatomy_svg(), bench.anatomy_svg())

    def test_checks_with_an_error_show_in_the_readout(self) -> None:
        bench, _ = open_bench(text="Parts on the bench (2): uno\nChecks: ERROR: 5 V into a 3.3 V pin")
        self.assertIn("ERROR: 5 V into a 3.3 V pin", bench.anatomy_svg())

    def test_labels_are_escaped(self) -> None:
        bench, _ = open_bench(title="<script>alert(1)</script>")
        svg = bench.anatomy_svg()
        self.assertNotIn("<script>", svg)
        self.assertIn("&lt;script&gt;", svg)
        ET.fromstring(svg)

    def test_many_parts_still_draw_and_stay_deterministic(self) -> None:
        items = [{"ref": "uno", "type": "board:uno", "x": 0, "y": 0, "rot": 0, "state": {}}]
        items += [{"ref": f"part{i}", "type": "mod:led", "x": i, "y": i, "rot": 0, "state": {}}
                  for i in range(14)]
        bench, _ = open_bench({"v": 1, "items": items, "wires": []})
        svg = bench.anatomy_svg()
        ET.fromstring(svg)
        self.assertIn("14 PARTS", svg)
        self.assertIn("part13", svg)
        self.assertEqual(svg, bench.anatomy_svg())

    def test_act_anatomy_sends_the_figure_to_the_lab(self) -> None:
        bench, events = open_bench()
        answer = bench.act("anatomy", {})
        self.assertEqual(answer, "Drew the bench as an Anatomy figure — it's in the Build lab beside the bench.")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "building_command")
        self.assertEqual(events[0]["command"], "anatomy")
        self.assertIn("<svg", events[0]["svg"])
        ET.fromstring(events[0]["svg"])

    def test_act_anatomy_needs_the_bench_open(self) -> None:
        bench = building.BuildingBench(Path(tempfile.mkdtemp()), lambda event: None, CATALOG)
        self.assertIn("isn't open", bench.act("anatomy", {}))
        bench.sync(True, "Blink", "", "Checks: no problems found.", BLINK)
        self.assertIn("anatomy", bench.act("nope", {}))

    def test_unknown_wire_colours_fall_back_to_gold(self) -> None:
        circuit = {"v": 1, "items": BLINK["items"],
                   "wires": [{"a": ["uno", 13], "b": ["led", 0], "color": "chartreuse"},
                             {"a": ["uno", 0], "b": ["led", 1], "color": "#12ab34"}]}
        bench, _ = open_bench(circuit)
        svg = bench.anatomy_svg()
        self.assertIn("#ffb040", svg)   # the fallback gold for a colour the bench doesn't know
        self.assertIn("#12ab34", svg)   # a real hex colour passes through
        ET.fromstring(svg)


if __name__ == "__main__":
    unittest.main()
