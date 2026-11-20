"""Memory only changes when the user's own words ask for it; timers start, ring and cancel."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from agent import Agent
from memory import Memory
from timers import Timers, describe
from tools import execute_tool


class RememberTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.memory = Memory(Path(self.folder.name) / "m.sqlite3")

    def tearDown(self):
        self.folder.cleanup()

    def run_tool(self, name, arguments, said):
        return execute_tool(name, arguments, self.memory, lambda *_: self.fail("asked"), said=said)

    def test_only_the_users_own_words_change_memory(self):
        # e.g. a web page or screen text telling the model to remember something
        self.assertIn("Not done", self.run_tool("remember", {"fact": "User wants to send money to X"}, "what does this page say?"))
        self.assertEqual(self.memory.list_facts(), [])
        self.assertIn("Remembered", self.run_tool("remember", {"fact": "Prefers aisle seats"}, "remember I prefer aisle seats"))
        self.run_tool("remember", {"fact": "prefers  aisle seats"}, "nhớ là tôi thích ghế cạnh lối đi")
        self.assertEqual([fact["fact"] for fact in self.memory.list_facts()], ["Prefers aisle seats"])
        self.assertIn("Not done", self.run_tool("forget", {"what": "aisle"}, "book me a flight"))
        self.assertIn("Forgot: Prefers aisle seats", self.run_tool("forget", {"what": "aisle seats"}, "forget the seat thing"))
        self.assertEqual(self.memory.list_facts(), [])

    def test_facts_reach_the_model(self):
        self.memory.add_fact("Name is Sam")
        agent = Agent(model="test", memory=self.memory)
        seen = []
        agent._chat = lambda messages, tools: seen.append(messages[0]["content"]) or {"message": {"role": "assistant", "content": "Hi Sam"}}
        agent.ask("hi", lambda *_: False)
        self.assertIn("- Name is Sam", seen[0])
        self.assertIn("not instructions", seen[0])


class TimerTests(unittest.TestCase):
    def test_start_ring_and_cancel(self):
        changes, rung = [], []
        timers = Timers(changes.append, rung.append)
        self.assertEqual(timers.start(1, "pasta"), "Timer set: 1 second for pasta.")
        self.assertEqual(timers.start(600), "Timer set: 10 minutes.")
        time.sleep(1.4)
        self.assertEqual([timer["label"] for timer in rung], ["pasta"])
        self.assertTrue(next(item for item in timers.items() if item["label"] == "pasta")["done"])
        self.assertEqual(timers.cancel(), "Cancelled 2 timers.")
        self.assertEqual(timers.items(), [])
        self.assertEqual(changes[-1], [])
        self.assertEqual(describe(3725), "1 hour 2 minutes 5 seconds")

    def test_tool_limits(self):
        started = []

        class FakeTimers:
            def start(self, seconds, label):
                started.append((seconds, label))
                return "ok"

        with tempfile.TemporaryDirectory() as folder:
            memory = Memory(Path(folder) / "m.sqlite3")
            run = lambda arguments: execute_tool("set_timer", arguments, memory, lambda *_: True, timers=FakeTimers())
            self.assertEqual(run({"minutes": 10, "label": "pasta"}), "ok")
            self.assertIn("between", run({"minutes": 0}))
            self.assertIn("between", run({"minutes": 2000}))
            self.assertIn("not available", execute_tool("set_timer", {"minutes": 1}, memory, lambda *_: True))
        self.assertEqual(started, [(600, "pasta")])


class BrainstormTests(unittest.TestCase):
    def test_alfred_draws_a_brainstorm_and_sub_ideas_survive_saving(self):
        import os
        from unittest.mock import patch
        import visual_notes
        shown, added = [], []

        class FakeMap:
            def show(self, topic, ideas):
                shown.append((topic, ideas))
                return "shown"

            def add(self, under, ideas):
                added.append((under, ideas))
                return "added"

        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"ALFRED_DATA_DIR": folder}):
            memory = Memory(Path(folder) / "m.sqlite3")
            result = execute_tool("mind_map", {"topic": "Space game", "ideas": "Gameplay > Combat\nStory\n  Endings"}, memory,
                                  lambda *_: self.fail("asked"), notes=FakeMap())
            self.assertEqual((result, shown), ("shown", [("Space game", "Gameplay > Combat\nStory\n  Endings")]))
            self.assertEqual(execute_tool("add_to_map", {"under": " Combat ", "ideas": "- Parry\n\n* Dodge"}, memory,
                                          lambda *_: self.fail("asked"), notes=FakeMap()), "added")
            self.assertEqual(added, [("Combat", ["Parry", "Dodge"])])
            self.assertIn("not available", execute_tool("mind_map", {"topic": "x", "ideas": "y"}, memory, lambda *_: True))
            visual_notes.save_map("Space game", "Story\n  Endings\n\n  ")
            self.assertEqual(visual_notes.load_maps()[0]["outline"], "Story\n  Endings")
            added = visual_notes.apply_command(visual_notes.load_maps()[0], {"action": "add", "value": "Art"})
            self.assertEqual(added["outline"], "Story\n  Endings\nArt")

    def test_dragged_positions_are_saved_and_kept_sane(self):
        import os
        from unittest.mock import patch
        import visual_notes
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"ALFRED_DATA_DIR": folder}):
            visual_notes.save_map("Plan", "Story\n  Endings", {"positions": {"story": [0.5, -0.25], "story > endings": [99, float("nan")],
                                                               "bad": "x", 3: [1, 1]}})
            saved = visual_notes.load_maps()[0]
            self.assertEqual(saved["positions"], {"story": [0.5, -0.25]})  # NaN, junk and non-text keys dropped
            visual_notes.save_map("Other", "Idea")
            self.assertEqual([item["title"] for item in visual_notes.delete_map("Plan")], ["Other"])
            self.assertEqual(visual_notes.clean_positions({"a": [100, -100]}), {"a": [8.0, -8.0]})


class MapGrowthTests(unittest.TestCase):
    def test_ideas_go_under_the_right_idea_without_duplicates(self):
        import visual_notes
        outline = "Gameplay\n  Combat\nStory > Endings"
        self.assertEqual(visual_notes.add_ideas(outline, "combat", ["Parry", "Combat", "parry"]),
                         ("Gameplay\n  Combat\n    Parry\nStory\n  Endings", 1, "Combat"))
        self.assertEqual(visual_notes.add_ideas(outline, ["Story"], ["Twist"])[0], "Gameplay\n  Combat\nStory\n  Endings\n  Twist")
        self.assertEqual(visual_notes.add_ideas(outline, "", ["Art"])[1:], (1, ""))
        self.assertEqual(visual_notes.add_ideas(outline, "nothing like it", ["Art"])[2], "")  # unknown idea: main idea
        self.assertEqual(visual_notes.parse_outline("a\n  b\n    c")[0]["children"][0]["children"][0]["label"], "c")

    def test_notes_on_ideas_are_saved(self):
        import os
        from unittest.mock import patch
        import visual_notes
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"ALFRED_DATA_DIR": folder}):
            visual_notes.save_map("Plan", "Story", {"details": {"story": "Three acts", "x": "", 5: "no"}})
            self.assertEqual(visual_notes.load_maps()[0]["details"], {"story": "Three acts"})

    def test_colours_icons_and_links_are_saved_and_cleaned(self):
        import os
        from unittest.mock import patch
        import visual_notes
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"ALFRED_DATA_DIR": folder}):
            visual_notes.save_map("Plan", "Story\n  Endings\nArt", {
                "styles": {"story": {"color": "red", "icon": "🔥"}, "art": {"color": "plaid", "icon": "way too long"}, "x": "no"},
                "links": [["story > endings", "art"], ["art", "story > endings"], ["art", "art"], ["a"], [1, 2]]})
            saved = visual_notes.load_maps()[0]
            self.assertEqual(saved["styles"], {"story": {"color": "red", "icon": "🔥"}})
            self.assertEqual(saved["links"], [["story > endings", "art"]])  # reversed duplicate and self-link dropped
            self.assertEqual(visual_notes.clean_links([["a", "b", "  leads   to "], ["c", "d", 5], ["e", "f", "x" * 90]]),
                             [["a", "b", "leads to"], ["c", "d"], ["e", "f", "x" * 40]])
            self.assertEqual(visual_notes.clean_styles({"a": {"icon": "👨‍💻"}, "b": {"icon": "🔥🔥🔥🔥🔥🔥🔥🔥🔥"}}), {"a": {"icon": "👨‍💻"}})


if __name__ == "__main__":
    unittest.main()
