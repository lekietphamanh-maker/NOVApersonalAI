"""Building mode in a real browser with the real createBuild: a blueprint from Nova is drawn by the bench and its own
checks go back to her; every plan Python accepts is one the bench can wire (every board, every example); the parts list
and steps show beside the bench; projects save, open and start over; and the bench claims its own keys. (Edge on
Windows, Chromium elsewhere; skipped without WebGL.)"""
from __future__ import annotations

import re
import unittest
from typing import Any

import building
from tests.bench_browser import ORIGIN, UI, browser_page
from tests.test_web_tasks import _browser_available

CATALOG = building.load_catalog(UI / "circuit" / "catalog.json")
PLAN_ARGUMENTS = {"title": "Blinking LED", "board": "uno", "parts": [{"type": "led"}],
                  "wires": [{"a": "uno.d13", "b": "led.sig", "color": "yellow"}, {"a": "uno.GND", "b": "led.GND"}],
                  "bom": [{"item": "220 ohm resistor", "qty": 1, "note": "only for a bare LED"}],
                  "steps": ["Plug the Uno into USB.", "Wire D13 to the LED's SIG pin."], "notes": "D13 also drives the L light."}


def harness_page() -> str:
    """The Building mode section of the real index.html, with a stand-in for Nova's side (saving, opening). Saved
    projects live in sessionStorage."""
    index = (UI / "index.html").read_text(encoding="utf-8")
    section = re.search(r'<section id="build".*?</section>', index, re.S).group(0).replace(' hidden aria-label', ' aria-label', 1)
    return f"""<!doctype html><meta charset="utf-8"><title>building harness</title>
<link rel="stylesheet" href="/hud.css"><link rel="stylesheet" href="/circuit/bench.css"><link rel="stylesheet" href="/build.css">
<body>{section}
<script type="module">
  import {{ createBuild }} from "/build.js";
  window.calls = []; window.toasts = [];
  const saved = JSON.parse(sessionStorage.getItem("saved") || "{{}}");
  const list = () => Object.keys(saved).map((name) => ({{ name, saved: "now" }}));
  const act = async (name, args = {{}}) => {{
    window.calls.push([name, JSON.parse(JSON.stringify(args))]);
    if (name === "build_save") {{
      const title = args.name || args.title || "Project";
      saved[title] = JSON.parse(JSON.stringify(args));
      sessionStorage.setItem("saved", JSON.stringify(saved));
      return {{ ok: true, name: title, saved: list() }};
    }}
    if (name === "build_list") return {{ ok: true, saved: list() }};
    if (name === "build_load") return {{ ok: true, ...saved[args.name], name: args.name }};
    return {{ ok: true }};
  }};
  window.build = createBuild(document.getElementById("build"), {{ act, toast: (...args) => window.toasts.push(args), onOpenChange: () => {{}} }});
  window.build.open();
  window.ready = true;
</script>"""


@unittest.skipUnless(_browser_available(), "needs Playwright and Edge (Windows) or a Chromium")
class BuildingModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._browser = browser_page({"/harness.html": harness_page()})
        cls.page, cls.problems = cls._browser.__enter__()
        cls.page.goto(f"{ORIGIN}/harness.html")
        cls.page.wait_for_function("window.ready")
        if not cls.page.evaluate("!!document.createElement('canvas').getContext('webgl2')"):
            cls._browser.__exit__(None, None, None)
            raise unittest.SkipTest("this browser has no WebGL")
        cls.page.wait_for_function("document.querySelector('#build-bench').bench?.ready", timeout=90000, polling=250)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._browser.__exit__(None, None, None)

    def setUp(self) -> None:
        self.page.evaluate("""() => { const bench = document.querySelector('#build-bench').bench; bench.freeBuild(); bench.addItem('board:uno', {}); bench._changed(); window.calls.length = 0; }""")

    def apply(self, plan: dict[str, Any], token: str = "t1") -> dict[str, Any]:
        """Nova's plan arrives as a building_command event; wait for the HUD's report of what the bench did."""
        self.page.evaluate("([plan, token]) => window.build.command({ command: 'blueprint', plan, token })", [plan, token])
        self.page.wait_for_function("(token) => window.calls.some(c => c[0] === 'build_sync' && c[1].applied === token)", arg=token, timeout=60000, polling=100)
        return self.page.evaluate("(token) => window.calls.find(c => c[0] === 'build_sync' && c[1].applied === token)[1].result", token)

    def plan(self, arguments: dict[str, Any]) -> dict[str, Any]:
        plan, problem = building.plan_from_arguments(arguments, CATALOG)
        self.assertEqual(problem, "")
        return plan

    def test_a_blueprint_is_drawn_and_the_benchs_checks_come_back(self) -> None:
        result = self.apply(self.plan(PLAN_ARGUMENTS))
        self.assertEqual((result["parts"], result["wired"], result["missing"], result["checks"]), (2, 2, [], "no problems found."))
        text = self.page.evaluate("document.querySelector('#build-bench').bench.describe()")
        self.assertIn("uno.D13 to led.SIG", text)
        self.assertEqual(self.page.locator("#build-plan-title").text_content(), "Blinking LED")
        self.assertEqual(self.page.evaluate("[...document.querySelectorAll('#build-bom li')].map(li => [...li.children].map(child => child.textContent))"),
                         [["×1", "Arduino Uno R3"], ["×1", "5 mm LED module"], ["×1", "220 ohm resistor", "only for a bare LED"]])
        self.assertEqual(self.page.evaluate("[...document.querySelectorAll('#build-steps li')].map(li => li.textContent)"), PLAN_ARGUMENTS["steps"])
        self.assertEqual(self.page.locator("#build-notes").text_content(), PLAN_ARGUMENTS["notes"])
        self.assertTrue(self.page.locator("#build-plan-hint").is_hidden())
        # and what Nova reads of it, once the HUD has synced
        self.page.wait_for_function("window.calls.filter(c => c[0] === 'build_sync').at(-1)?.[1].text.includes('uno.D13 to led.SIG')", polling=100)

    def test_a_short_circuit_in_nova_s_wiring_is_reported_so_she_can_fix_it(self) -> None:
        bad = {**PLAN_ARGUMENTS, "wires": [*PLAN_ARGUMENTS["wires"], {"a": "uno.5V", "b": "uno.GND"}]}
        result = self.apply(self.plan(bad), "t2")
        self.assertEqual(result["wired"], 3)
        self.assertIn("ERROR: Short circuit", result["checks"])

    def test_a_pin_the_bench_does_not_have_is_reported_not_guessed(self) -> None:
        plan = self.plan(PLAN_ARGUMENTS)
        plan["wires"].append({"a": "uno.D13", "b": "led.NOPE", "color": ""})  # past Python's check, as a stale catalog would be
        result = self.apply(plan, "t3")
        self.assertEqual(result["missing"], ["wire uno.D13 to led.NOPE"])
        self.assertEqual(result["wired"], 2)

    def test_every_board_can_be_wired_from_a_plan_python_accepts(self) -> None:
        for board, entry in CATALOG["boards"].items():
            dig = next(pin["name"] for pin in entry["pins"] if pin["kind"] == "dig")
            gnd = next(pin["name"] for pin in entry["pins"] if pin["kind"] == "gnd")
            plan = self.plan({"board": board, "parts": ["led"], "wires": [{"a": f"{board}.{dig}", "b": "led.SIG"}, {"a": f"{board}.{gnd}", "b": "led.GND"}]})
            result = self.apply(plan, f"b-{board}")
            self.assertEqual((result["parts"], result["wired"], result["missing"]), (2, 2, []), board)

    def test_every_single_board_example_mission_can_be_built_as_a_plan(self) -> None:
        built = 0
        for example in CATALOG["examples"]:
            boards = [part for part in example["parts"] if part["type"].startswith("board:")]
            if len(boards) != 1:
                continue  # two-board missions (a serial link) aren't one blueprint
            board = boards[0]["type"].removeprefix("board:")
            parts = [{"type": part["type"].removeprefix("mod:"), "ref": part["ref"]} for part in example["parts"] if part["type"].startswith("mod:")]
            # a plan's board is named by its id; a mission may call it something else ("pill")
            rename = lambda end: board + end[len(boards[0]["ref"]):] if end.startswith(boards[0]["ref"] + ".") else end  # noqa: E731
            wires = [{"a": rename(wire["a"]), "b": rename(wire["b"]), "color": wire["color"]} for wire in example["wires"]]
            plan = self.plan({"board": board, "parts": parts, "wires": wires})
            result = self.apply(plan, f"e-{example['id']}")
            self.assertEqual((result["wired"], result["missing"]), (len(example["wires"]), []), example["id"])
            built += 1
        self.assertGreaterEqual(built, 8)

    def test_the_owners_own_bench_is_kept_before_a_blueprint_replaces_it(self) -> None:
        self.page.evaluate("document.querySelector('#build-bench').bench.addItem('mod:buzzer', {}, true)")  # the owner adds a part
        self.apply(self.plan(PLAN_ARGUMENTS), "k1")
        kept = self.page.evaluate("window.calls.filter(c => c[0] === 'build_save').at(-1)[1]")
        self.assertEqual(kept["name"], "Before Nova's build")
        self.assertEqual([part["ref"] for part in kept["circuit"]["items"]], ["uno", "buzzer"])
        self.page.wait_for_function("window.toasts.some(toast => /Before Nova/.test(toast[0]))")
        saves = self.page.evaluate("window.calls.filter(c => c[0] === 'build_save').length")
        self.apply(self.plan({**PLAN_ARGUMENTS, "title": "Again"}), "k2")  # nothing of the owner's to keep this time
        self.assertEqual(self.page.evaluate("window.calls.filter(c => c[0] === 'build_save').length"), saves)

    def test_a_project_is_saved_started_over_and_opened_again(self) -> None:
        self.apply(self.plan(PLAN_ARGUMENTS), "t4")
        self.page.fill("#build-name", "Blink")
        self.assertTrue(self.page.locator("#build-dirty").is_visible())
        self.page.click("#build-save")
        self.page.wait_for_function("window.toasts.some(toast => /Saved/.test(toast[0]))")
        saved = self.page.evaluate("window.calls.filter(c => c[0] === 'build_save').at(-1)[1]")
        self.assertEqual(building.clean_circuit(saved["circuit"]), saved["circuit"])  # what a real bench sends is what Nova's side keeps
        self.assertEqual((saved["title"], len(saved["bom"]), len(saved["steps"])), ("Blinking LED", 1, 2))
        self.assertTrue(self.page.locator("#build-dirty").is_hidden())

        self.page.click("#build-new")  # nothing unsaved: it starts at once
        self.page.wait_for_function("document.querySelector('#build-bench').bench.items.length === 1")
        self.assertEqual(self.page.locator("#build-steps li").count(), 0)
        self.assertEqual(self.page.locator("#build-plan-title").text_content(), "Blueprint")

        self.page.evaluate("document.querySelector('#build-open').open = true")
        self.page.wait_for_selector("#build-saved button")
        self.page.locator("#build-saved li", has_text="Blink").locator("button").first.click()
        self.page.wait_for_function("document.querySelector('#build-bench').bench.items.length === 2")
        self.assertEqual(self.page.evaluate("document.querySelector('#build-bench').bench.getState()"), saved["circuit"])
        self.assertEqual(self.page.locator("#build-steps li").count(), 2)
        self.assertEqual(self.page.locator("#build-plan-title").text_content(), "Blinking LED")

    def test_the_bench_claims_its_own_keys_and_esc_leaves_otherwise(self) -> None:
        self.page.locator("#build-bench .rl-canvas canvas").click(position={"x": 5, "y": 5})
        self.assertTrue(self.page.evaluate("window.build.handleKey({ key: 'Escape' })"))
        self.assertTrue(self.page.evaluate("window.build.isOpen()"))  # Esc went to the bench (it cancels a wire)
        self.assertTrue(self.page.evaluate("window.build.handleKey({ key: 'Delete' })"))
        self.assertFalse(self.page.evaluate("window.build.handleKey({ key: 'x' })"))
        self.page.locator(".build-bar").click(position={"x": 400, "y": 5})  # outside the bench: its focus goes
        self.assertTrue(self.page.evaluate("window.build.handleKey({ key: 'Escape' })"))
        self.assertFalse(self.page.evaluate("window.build.isOpen()"))
        self.page.wait_for_function("window.calls.filter(c => c[0] === 'build_sync').at(-1)?.[1].open === false")
        self.page.evaluate("window.build.open()")  # and it comes back as it was
        self.page.wait_for_function("window.calls.filter(c => c[0] === 'build_sync').at(-1)?.[1].open === true")
        self.assertEqual(self.page.evaluate("document.querySelector('#build-bench').bench.items.length"), 1)

    def test_nothing_in_the_page_complained(self) -> None:
        self.assertEqual(self.problems, [])


if __name__ == "__main__":
    unittest.main()
