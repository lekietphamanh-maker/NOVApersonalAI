"""The library: projects, repos and ideas in the vault, sorted by topic; what needs the owner; voice commands."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from library import Library, parse_command


class LibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp())
        self.library = Library(self.vault)
        wiki = self.vault / "wiki"
        wiki.mkdir()
        (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
        (wiki / "AI.md").write_text(
            "# AI\n\nHow machines learn from data.\n\n## 2026-11-10 · clip\n- Transformers use attention (from [[raw/clips/a]])\n"
            "Related: [[Robotics]], [[Python]]\n\n## 2026-11-18 · activity\n- Small models run on a laptop (from [[raw/b]])\n",
            encoding="utf-8")
        (wiki / "Robotics.md").write_text("# Robotics\n\nRobots that sense and move.\n", encoding="utf-8")
        os.utime(wiki / "Robotics.md", (time.time() - 86400 * 30, time.time() - 86400 * 30))

    def test_a_project_is_a_note_obsidian_reads_and_comes_back_the_same(self) -> None:
        saved = self.library.save("Nova Library", status="building", topic="ai", repo="github.com/me/nova",
                                  next='Wire "voice": next, open', note="Shelf of my builds.\n\n- carousel", new=True)
        text = (self.vault / "library" / "Nova Library.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith('---\nstatus: "building"\ntopic: "ai"\nrepo: "https://github.com/me/nova"\n'))
        self.assertIn("Topic: [[ai]]", text)  # linked to the wiki topic in Obsidian's graph
        again = self.library.find("nova library")
        self.assertEqual(again, saved)
        self.assertEqual(again.next, 'Wire "voice": next, open')
        self.assertEqual(again.note, "Shelf of my builds.\n\n- carousel")

    def test_changing_renaming_and_no_overwriting(self) -> None:
        self.library.save("Drone app", topic="Robotics", new=True)
        with self.assertRaises(ValueError):
            self.library.save("drone APP", new=True)  # a new idea never overwrites one already there
        self.library.save("Drone app", status="building")
        self.assertEqual(self.library.find("Drone app").topic, "Robotics")  # untouched fields stay
        self.library.save("Drone App", previous="Drone app")  # only the case changes
        self.library.save("Sky Drone", previous="Drone App", next="Buy a frame")
        self.assertEqual([project.title for project in self.library.projects()], ["Sky Drone"])
        self.assertEqual(self.library.find("sky drone").status, "building")
        self.assertTrue(self.library.delete("Sky Drone"))
        self.assertEqual(self.library.projects(), [])

    def test_bad_input_is_refused(self) -> None:
        for fields in ({"title": "  "}, {"title": "X", "status": "done"}, {"title": "X", "repo": "not a link"}):
            with self.assertRaises(ValueError):
                self.library.save(**fields)

    def test_topics_join_the_wiki_and_the_projects(self) -> None:
        self.library.save("Nova Library", status="building", topic="ai")
        self.library.save("Chess bot", topic="ai", new=True)
        self.library.save("Loose idea", new=True)
        (self.vault / "library" / "Chess bot.sync-conflict-20261119-1.md").write_text("---\n---\n# x\n", encoding="utf-8")
        topics = {topic["name"]: topic for topic in self.library.topics()}
        self.assertEqual(set(topics), {"AI", "Robotics", "Unsorted"})  # "ai" is the wiki's AI; no conflict copy
        self.assertEqual((topics["AI"]["ideas"], topics["AI"]["projects"], topics["AI"]["notes"]), (1, 1, 2))
        self.assertEqual(topics["AI"]["summary"], "How machines learn from data.")
        self.assertEqual(topics["AI"]["related"], ["Python", "Robotics"])
        self.assertEqual([topic["name"] for topic in self.library.topics()][-1], "Unsorted")
        opened = self.library.topic("ai")
        self.assertEqual(opened["name"], "AI")
        self.assertEqual(opened["facts"][0], "Small models run on a laptop (from [[raw/b]])")  # newest first
        self.assertEqual({project["title"] for project in opened["projects"]}, {"Nova Library", "Chess bot"})

    def test_what_needs_the_owner_first(self) -> None:
        for title, status, next_step in (("Old build", "building", "Fix login"), ("Fresh build", "building", ""),
                                         ("An idea", "idea", ""), ("Done", "shipped", ""), ("Later", "paused", "")):
            self.library.save(title, status=status, next=next_step)
        path = self.vault / "library" / "Old build.md"
        stale = (datetime.now() - timedelta(days=12)).strftime("%Y-%m-%d %H:%M")
        path.write_text(path.read_text(encoding="utf-8").replace(
            next(line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("updated:")),
            f'updated: "{stale}"'), encoding="utf-8")
        needs = self.library.needs()
        self.assertEqual([item["title"] for item in needs], ["Old build", "Fresh build", "An idea"])
        self.assertEqual(needs[0]["why"], "Stalled 12 days · next: Fix login")
        self.assertEqual(needs[2]["why"], "Idea · build it or park it?")
        self.assertIn("1. Old build (building, Unsorted): Stalled 12 days", self.library.needs_text())

    def test_naming_something_out_loud_finds_it(self) -> None:
        self.library.save("Drone app", topic="Robotics")
        self.assertEqual(self.library.match("robotics"), {"kind": "topic", "name": "Robotics"})
        self.assertEqual(self.library.match("the robotics topic"), {"kind": "topic", "name": "Robotics"})
        self.assertEqual(self.library.match("drone app"), {"kind": "project", "name": "Drone app"})
        self.assertEqual(self.library.match("the drone ap project"), {"kind": "project", "name": "Drone app"})
        self.assertIsNone(self.library.match("pizza recipes"))

    def test_an_empty_vault_is_an_empty_library(self) -> None:
        empty = Library(Path(tempfile.mkdtemp()) / "nothing here")
        self.assertEqual(empty.snapshot()["topics"], [])
        self.assertIn("Nothing in the library", empty.needs_text())


class VoiceCommandTests(unittest.TestCase):
    def test_short_commands_while_the_library_is_open(self) -> None:
        cases = {"next": {"command": "next"}, "Next one, please": {"command": "next"}, "go left": {"command": "previous"},
                 "Hey Nova, open it": {"command": "open"}, "pick this one": {"command": "open"},
                 "go back": {"command": "back"}, "close the library": {"command": "close"},
                 "show me the ideas": {"command": "shelf", "shelf": "ideas"}, "my projects": {"command": "shelf", "shelf": "projects"},
                 "what needs me": {"command": "shelf", "shelf": "needs"}, "open 3": {"command": "pick", "number": 3},
                 "number three": {"command": "pick", "number": 3}, "pick 12": {"command": "pick", "number": 12},
                 "open robotics": {"command": "find", "text": "robotics"},
                 "go to the drone app": {"command": "find", "text": "drone app"},
                 "tiếp theo": {"command": "next"}, "quay lại": {"command": "back"}, "mở ba": {"command": "pick", "number": 3}}
        for said, command in cases.items():
            self.assertEqual(parse_command(said), command, said)

    def test_anything_else_goes_to_nova(self) -> None:
        for said in ("what's the weather tomorrow", "three", "add an idea about a drone that waters plants",
                     "tell me about the history of the library of alexandria and why it burned down", ""):
            self.assertIsNone(parse_command(said), said)


if __name__ == "__main__":
    unittest.main()
