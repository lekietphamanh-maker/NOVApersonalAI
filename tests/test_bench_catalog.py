"""ui/circuit/catalog.json lists the bench's boards and parts with their real pin names, and the guided missions as worked
examples. Python checks a Blueprint plan against it and tells the model what exists, so it must be what the bench really
has: this test builds every board and part in a real browser and compares.

Regenerate after changing a board or part:  python -m tests.test_bench_catalog --write"""
from __future__ import annotations

import json
import sys
import unittest
from typing import Any

from tests.bench_browser import ORIGIN, UI, browser_page, skip_without_webgl
from tests.test_web_tasks import _browser_available

CATALOG = UI / "circuit" / "catalog.json"
PAGE = """<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="/circuit/bench.css">
<div class="rl-host" id="a" style="width:900px;height:600px"></div>
<script type="module">
  import { createBench } from "/circuit/lab/lab.js";
  import { BOARDS } from "/circuit/boards/index.js";
  window.bench = createBench(document.getElementById("a"), { boards: BOARDS, start: "uno", onReady: () => { window.ready = true; } });
</script>"""

EXTRACT = """() => {
  const lab = window.bench;
  const pinsOf = (type) => {
    const item = lab.addItem(type, {});
    const pins = item.pins.map((pin) => ({ name: pin.name, kind: pin.kind }));
    const logic = item.lab.logic;
    lab.removeItem(item);
    return { pins, logic };
  };
  const boards = {}, modules = {};
  for (const [id, def] of Object.entries(lab.boardDefs)) {
    const { pins, logic } = pinsOf('board:' + id);
    boards[id] = { name: def.name, logic, tagline: def.tagline, pins };
  }
  for (const [id, def] of Object.entries(lab.moduleDefs)) {
    modules[id] = { name: def.name, category: def.category, blurb: def.blurb, pins: pinsOf('mod:' + id).pins };
  }
  const examples = lab.missions.map((m) => ({ id: m.id, title: m.title, goal: m.goal, level: m.level,
    parts: m.parts.map((p) => ({ type: p.type, ref: p.ref })), wires: m.wires.map((w) => ({ a: w.a, b: w.b, color: w.color })) }));
  return { v: 1, boards, modules, examples };
}"""


def bench_catalog(page: Any) -> dict[str, Any]:
    page.goto(f"{ORIGIN}/catalog.html")
    page.wait_for_function("window.ready", timeout=90000, polling=250)
    return page.evaluate(EXTRACT)


def write_catalog() -> None:
    with browser_page({"/catalog.html": PAGE}) as (page, _problems):
        catalog = bench_catalog(page)
    CATALOG.write_text(json.dumps(catalog, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {CATALOG}: {len(catalog['boards'])} boards, {len(catalog['modules'])} parts, {len(catalog['examples'])} examples")


@unittest.skipUnless(_browser_available(), "needs Playwright and Edge (Windows) or a Chromium")
class CatalogTests(unittest.TestCase):
    def test_the_shipped_catalog_is_what_the_bench_really_has(self) -> None:
        with browser_page({"/catalog.html": PAGE}) as (page, _problems):
            page.goto(f"{ORIGIN}/catalog.html")
            skip_without_webgl(self, page)
            live = bench_catalog(page)
        shipped = json.loads(CATALOG.read_text(encoding="utf-8"))
        self.assertEqual(shipped, live, "ui/circuit/catalog.json is stale: python -m tests.test_bench_catalog --write")

    def test_every_example_wire_uses_pins_that_exist(self) -> None:
        shipped = json.loads(CATALOG.read_text(encoding="utf-8"))
        for example in shipped["examples"]:
            pins: dict[str, set[str]] = {}
            for part in example["parts"]:
                kind, part_id = part["type"].split(":")
                library = shipped["boards" if kind == "board" else "modules"]
                pins[part["ref"] or part_id] = {pin["name"] for pin in library[part_id]["pins"]}
            for wire in example["wires"]:
                for end in (wire["a"], wire["b"]):
                    ref, pin = end.split(".", 1)
                    self.assertIn(pin, pins[ref], f"{example['id']}: {end}")


if __name__ == "__main__":
    if "--write" in sys.argv:
        write_catalog()
    else:
        unittest.main()
