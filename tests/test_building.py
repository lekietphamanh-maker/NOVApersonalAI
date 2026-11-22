"""Building mode: a Blueprint plan is checked against the bench's real catalog before anything is drawn, the bench's own
checks come back to Nova, and the open bench rides along with her questions."""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

import building
import instant_commands
import tools

EMPTY_BENCH = {"v": 1, "items": [], "wires": []}
CATALOG = building.load_catalog(Path(__file__).resolve().parent.parent / "ui" / "circuit" / "catalog.json")
BLINK = {"title": "Blinking LED", "board": "uno", "parts": [{"type": "led"}],
         "wires": [{"a": "uno.d13", "b": "led.sig", "color": "Yellow"}, {"a": "uno.GND", "b": "led.GND"}],
         "bom": [{"item": "220 ohm resistor", "qty": 1, "note": "only for a bare LED"}, "USB cable"],
         "steps": ["Plug the Uno into USB.", "Wire D13 to the LED's SIG pin.", ""], "notes": "D13 also drives the L light."}


def open_bench(emit: Any = None) -> building.BuildingBench:
    bench = building.BuildingBench(Path(tempfile.mkdtemp()), emit or (lambda event: None), CATALOG)
    bench.sync(True, "Blink", "", "Parts on the bench (1): uno (Arduino Uno R3)\nChecks: no problems found.")
    return bench


class PinTests(unittest.TestCase):
    def pins(self, board: str) -> list[dict[str, Any]]:
        return CATALOG["boards"][board]["pins"]

    def test_a_pin_is_found_however_it_is_written(self) -> None:
        self.assertEqual(building.resolve_pin(self.pins("uno"), "d13"), "D13")
        self.assertEqual(building.resolve_pin(self.pins("uno"), " D 13 "), "D13")
        self.assertEqual(building.resolve_pin(self.pins("uno"), "TX"), "D1 / TX")  # a word of a longer name
        self.assertEqual(building.resolve_pin(self.pins("uno"), "d1/tx"), "D1 / TX")
        self.assertEqual(building.resolve_pin(self.pins("uno"), "GND"), "GND")

    def test_a_pin_that_isnt_there_or_is_unclear_is_not_guessed(self) -> None:
        self.assertIsNone(building.resolve_pin(self.pins("uno"), "D99"))
        self.assertIsNone(building.resolve_pin(self.pins("uno"), ""))
        self.assertIsNone(building.resolve_pin(self.pins("uno"), "A"))  # many pins start with it

    def test_the_catalog_matches_the_blink_example_wires(self) -> None:
        for wire in next(item for item in CATALOG["examples"] if item["id"] == "blink")["wires"]:
            ref, pin = wire["a"].split(".", 1)
            self.assertIsNotNone(building.resolve_pin(self.pins("uno"), pin), wire)


class PlanTests(unittest.TestCase):
    def test_a_good_plan_comes_out_with_the_benchs_own_names(self) -> None:
        plan, problem = building.plan_from_arguments(BLINK, CATALOG)
        self.assertEqual(problem, "")
        self.assertEqual(plan["board"], "uno")
        self.assertEqual(plan["parts"], [{"type": "mod:led", "ref": "led"}])
        self.assertEqual(plan["wires"], [{"a": "uno.D13", "b": "led.SIG", "color": "yellow"}, {"a": "uno.GND", "b": "led.GND", "color": ""}])
        self.assertEqual(plan["bom"], [{"item": "220 ohm resistor", "qty": 1, "note": "only for a bare LED"}, {"item": "USB cable", "qty": 1, "note": ""}])
        self.assertEqual(plan["steps"], ["Plug the Uno into USB.", "Wire D13 to the LED's SIG pin."])
        self.assertFalse(plan["keep"])

    def test_a_made_up_board_part_or_pin_builds_nothing_and_names_what_exists(self) -> None:
        plan, problem = building.plan_from_arguments({**BLINK, "board": "raspberry"}, CATALOG)
        self.assertIsNone(plan)
        self.assertIn("uno", problem)
        plan, problem = building.plan_from_arguments({**BLINK, "parts": [{"type": "flux-capacitor"}]}, CATALOG)
        self.assertIsNone(plan)
        self.assertIn("There is no part 'flux-capacitor'. Parts: led, rgb", problem)
        plan, problem = building.plan_from_arguments({**BLINK, "wires": [{"a": "uno.D99", "b": "led.SIG"}]}, CATALOG)
        self.assertIsNone(plan)
        self.assertIn("uno has no pin 'D99'. Its pins: SCL, SDA", problem)
        self.assertIn("Nothing was built", problem)
        plan, problem = building.plan_from_arguments({**BLINK, "wires": [{"a": "uno.D13", "b": "motor.M+"}]}, CATALOG)
        self.assertIn("there is no part 'motor'. Parts on this bench: uno, led", problem)

    def test_two_parts_of_one_kind_get_their_own_names(self) -> None:
        plan, _ = building.plan_from_arguments({"board": "uno", "parts": ["led", "led", {"type": "mod:led", "ref": "Status LED!"}],
                                                "wires": [{"a": "uno.D13", "b": "led2.SIG"}, {"a": "uno.D12", "b": "statusled.SIG"}]}, CATALOG)
        self.assertEqual([part["ref"] for part in plan["parts"]], ["led", "led2", "statusled"])
        self.assertEqual([wire["b"] for wire in plan["wires"]], ["led2.SIG", "statusled.SIG"])

    def test_a_wire_to_itself_is_dropped_and_sizes_are_limited(self) -> None:
        plan, _ = building.plan_from_arguments({**BLINK, "wires": [{"a": "uno.D13", "b": "uno.d13"}]}, CATALOG)
        self.assertEqual(plan["wires"], [])
        many, _ = building.plan_from_arguments({"board": "mega", "parts": [{"type": "led"}] * 40,
                                                "wires": [{"a": "mega.D13", "b": "led.SIG"}] * 200,
                                                "bom": [f"part {index}" for index in range(100)], "steps": ["x"] * 100}, CATALOG)
        self.assertEqual((len(many["parts"]), len(many["wires"]), len(many["bom"]), len(many["steps"])),
                         (building.MAX_PLAN_PARTS, building.MAX_PLAN_WIRES, building.MAX_BOM, building.MAX_STEPS))


class BenchTests(unittest.TestCase):
    def test_nova_reads_the_bench_and_the_library_only_while_it_is_open(self) -> None:
        bench = building.BuildingBench(Path(tempfile.mkdtemp()), lambda event: None, CATALOG)
        self.assertEqual(bench.context(), "")
        self.assertIn("isn't open", bench.act("read", {}))
        bench.sync(True, "Blink", "", "Parts on the bench (1): uno (Arduino Uno R3)\nChecks: no problems found.")
        text = bench.context()
        self.assertIn("Parts on the bench (1): uno", text)
        self.assertIn("Boards: uno (Arduino Uno R3, 5 V logic)", text)
        self.assertIn("led [SIG, GND]", text)
        self.assertIn("uno.D13 to led.SIG", text)  # the worked example
        bench.sync(False)
        self.assertEqual(bench.context(), "")

    def test_pins_answers_with_the_exact_names(self) -> None:
        bench = open_bench()
        self.assertIn("Pins of 5 mm LED module (led): SIG, GND.", bench.act("pins", {"part": "led"}))
        self.assertIn("D13", bench.act("pins", {"part": "board:uno"}))
        self.assertIn("give part", bench.act("pins", {"part": "toaster"}))

    def test_a_blueprint_is_drawn_by_the_bench_and_its_checks_come_back(self) -> None:
        sent: list[dict[str, Any]] = []
        bench = building.BuildingBench(Path(tempfile.mkdtemp()), lambda event: (sent.append(event), answer(event)), CATALOG)

        def answer(event: dict[str, Any]) -> None:  # the HUD, drawing it and reporting what the bench's checks say
            threading.Thread(target=lambda: bench.sync(True, "", "", "", None, None, None, "", event["token"],
                                                       {"parts": 2, "wired": 2, "missing": [], "checks": "no problems found."})).start()
        bench.sync(True, circuit=EMPTY_BENCH)
        said = bench.act("blueprint", BLINK)
        self.assertEqual(sent[0]["type"], "building_command")
        self.assertEqual(sent[0]["command"], "blueprint")
        self.assertEqual(sent[0]["plan"]["wires"][0], {"a": "uno.D13", "b": "led.SIG", "color": "yellow"})
        self.assertIn("Built Blinking LED on the bench: 2 parts and 2 wires.", said)
        self.assertIn("The bench's checks: no problems found.", said)

    def test_what_the_bench_could_not_place_and_its_errors_reach_nova(self) -> None:
        bench = building.BuildingBench(Path(tempfile.mkdtemp()), lambda event: answer(event), CATALOG)

        def answer(event: dict[str, Any]) -> None:
            bench.sync(True, "", "", "", None, None, None, "", event["token"], {
                "parts": 2, "wired": 1, "missing": ["wire uno.D13 to led.SIG"], "checks": "ERROR: Short circuit: Arduino Uno R3 5V is wired straight to GND."})
        bench.sync(True, circuit=EMPTY_BENCH)
        said = bench.act("blueprint", BLINK)
        self.assertIn("Could not place: wire uno.D13 to led.SIG.", said)
        self.assertIn("ERROR: Short circuit", said)
        self.assertIn("call blueprint again", said)

    def test_a_bench_that_does_not_answer_is_said_so_and_a_bad_plan_never_reaches_it(self) -> None:
        sent: list[dict[str, Any]] = []
        bench = building.BuildingBench(Path(tempfile.mkdtemp()), sent.append, CATALOG)
        bench.sync(True, circuit=EMPTY_BENCH)
        original = building.APPLY_WAIT_SECONDS
        building.APPLY_WAIT_SECONDS = 0.05
        self.addCleanup(setattr, building, "APPLY_WAIT_SECONDS", original)
        self.assertIn("didn't answer", bench.act("blueprint", BLINK))
        sent.clear()
        self.assertIn("Not done", bench.act("blueprint", {**BLINK, "board": "nope"}))
        self.assertEqual(sent, [])
        self.assertIn("read, pins or blueprint", bench.act("explode", {}))

    def test_a_bench_that_is_still_starting_says_so_at_once(self) -> None:
        sent: list[dict[str, Any]] = []
        bench = building.BuildingBench(Path(tempfile.mkdtemp()), sent.append, CATALOG)
        bench.sync(True, text="The bench is still starting.")  # the HUD has opened but not sent the bench yet
        self.assertIn("still starting", bench.act("blueprint", BLINK))
        self.assertEqual(sent, [])

    def test_a_pin_is_found_the_way_the_bench_finds_it(self) -> None:
        self.assertEqual(building.resolve_pin(CATALOG["boards"]["uno"]["pins"], "3V3"), "3.3V")
        self.assertEqual(building.resolve_pin(CATALOG["boards"]["uno"]["pins"], "3.3 v"), "3.3V")

    def test_the_building_tool_runs_through_nova_and_says_when_it_is_closed(self) -> None:
        bench = open_bench()
        self.assertIn("Pins of", tools.execute_tool("building", {"action": "pins", "part": "uno"}, None, lambda *a: True, building=bench.act))
        self.assertIn("isn't open", tools.execute_tool("building", {"action": "read"}, None, lambda *a: True))

    def test_the_open_building_command_is_an_instant_one(self) -> None:
        self.assertEqual(instant_commands.match("open building mode").arguments, {"on": True})
        self.assertEqual(instant_commands.match("start the circuit bench").arguments, {"on": True})
        self.assertEqual(instant_commands.match("close building mode").arguments, {"on": False})
        self.assertIsNone(instant_commands.match("build me a robot that waves"))


class ProjectTests(unittest.TestCase):
    CIRCUIT = {"v": 1, "items": [{"ref": "uno", "type": "board:uno", "x": 0, "y": 0, "rot": 0, "state": {}},
                                  {"ref": "led", "type": "mod:led", "x": 68.5, "y": -3, "rot": 90, "state": {"on": False, "level": 1}}],
               "wires": [{"a": ["uno", 4], "b": ["led", 0], "color": "red"}, {"a": ["uno", 3], "b": ["led", 1], "color": "black"}]}

    def test_a_project_keeps_the_bench_the_parts_list_and_the_steps(self) -> None:
        bench = open_bench()
        self.assertTrue(bench.save("", "", self.CIRCUIT, [], [], "").startswith("Building "))  # untitled
        name = bench.save('Blink/ "one"', "Blinking LED", self.CIRCUIT, BLINK["bom"], BLINK["steps"], "tip")
        self.assertEqual(name, "Blink one")
        self.assertIn(name, [entry["name"] for entry in bench.saved()])
        loaded = bench.load(name)
        self.assertEqual(loaded["circuit"], self.CIRCUIT | {"items": [{**self.CIRCUIT["items"][0], "x": 0.0, "y": 0.0},
                                                                       {**self.CIRCUIT["items"][1], "x": 68.5, "y": -3.0}],
                                                            "wires": loaded["circuit"]["wires"]})
        self.assertEqual(loaded["bom"][0], {"item": "220 ohm resistor", "qty": 1, "note": "only for a bare LED"})
        self.assertEqual(loaded["steps"], ["Plug the Uno into USB.", "Wire D13 to the LED's SIG pin."])
        bench.delete(name)
        self.assertNotIn(name, [entry["name"] for entry in bench.saved()])
        with self.assertRaises(ValueError):
            bench.load(name)

    def test_only_a_well_formed_bench_is_kept(self) -> None:
        dirty = {"items": [
            {"ref": "uno", "type": "board:uno", "x": 1e9, "y": float("inf"), "rot": 450, "state": {"a": {"nested": 1}, "b": "x" * 99, "c": 2, "d": True}},
            {"ref": "uno", "type": "board:mega"}, {"ref": "bad ref!", "type": "mod:led"}, {"ref": "evil", "type": "script:alert"},
            {"ref": "led", "type": "mod:led", "opts": {"color": "red", "deep": [1]}}, "junk"],
            "wires": [{"a": ["uno", 1], "b": ["led", 0], "color": "<b>"}, {"a": ["uno", 1], "b": ["ghost", 0]},
                      {"a": ["uno", -1], "b": ["led", 0]}, {"a": ["uno", True], "b": ["led", 0]}, {"a": "uno.D1", "b": ["led", 0]}]}
        bench = building.clean_circuit(dirty)
        self.assertEqual([part["ref"] for part in bench["items"]], ["uno", "led"])
        uno, led = bench["items"]
        self.assertEqual((uno["x"], uno["y"], uno["rot"]), (5000.0, 0.0, 90))
        self.assertEqual(uno["state"], {"b": "x" * 40, "c": 2, "d": True})
        self.assertEqual(led["opts"], {"color": "red"})
        self.assertEqual(bench["wires"], [{"a": ["uno", 1], "b": ["led", 0], "color": ""}])
        self.assertIsNone(building.clean_circuit("not a bench"))
        many = building.clean_circuit({"items": [{"ref": f"p{index}", "type": "mod:led"} for index in range(80)],
                                      "wires": [{"a": ["p0", 1], "b": ["p1", 1]}] * 400})
        self.assertEqual((len(many["items"]), len(many["wires"])), (building.MAX_CIRCUIT_PARTS, building.MAX_CIRCUIT_WIRES))


if __name__ == "__main__":
    unittest.main()
