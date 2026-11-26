"""Reminders at a time of day (kept across restarts, missed ones said once, repeats moved on) and build mode (Claude
Code writing only in the project's own folder)."""
from __future__ import annotations

import subprocess
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path

import claude_code
from reminders import Reminders, describe, next_time, parse_time, spoken
from tools import execute_tool

FRIDAY_9AM = datetime(2026, 11, 20, 9, 0)


class ReminderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = FRIDAY_9AM
        self.path = Path(tempfile.mkdtemp()) / "reminders.json"
        self.box = Reminders(self.path, clock=lambda: self.now)

    def test_set_said_on_time_and_kept_across_a_restart(self) -> None:
        self.box.add("call mom", "2026-11-20 17:00")
        self.assertEqual([item.text for item in Reminders(self.path).items()], ["call mom"])  # a new Nova reads the file
        self.now = datetime(2026, 11, 20, 17, 0, 20)
        [(item, late)] = self.box.due()
        self.assertEqual(spoken(item, late), "Reminder: call mom.")
        self.assertEqual(self.box.items(), [])

    def test_missed_while_the_pc_was_off_is_said_once_as_missed(self) -> None:
        self.box.add("submit homework", "2026-11-20 10:00")
        self.now = datetime(2026, 11, 20, 18, 0)
        self.assertEqual([spoken(*fired) for fired in self.box.due()], ["Reminder, missed at 10:00: submit homework."])
        self.assertEqual(self.box.due(), [])

    def test_repeats(self) -> None:
        stand_up = self.box.add("stand-up", "2026-11-20 08:00", "weekdays")  # 8:00 passed today: Monday
        self.assertEqual(stand_up.at, "2026-11-23 08:00")
        self.assertEqual(next_time(datetime(2026, 1, 31, 9, 0), "monthly"), datetime(2026, 2, 28, 9, 0))
        self.assertEqual(next_time(datetime(2026, 12, 15, 9, 0), "monthly"), datetime(2027, 1, 15, 9, 0))
        self.box.add("water plants", "2026-11-20 18:00", "daily")
        self.now = datetime(2026, 11, 22, 19, 0)  # off for two days: said once, then tomorrow
        self.assertEqual([item.text for item, _late in self.box.due()], ["water plants"])
        self.assertEqual({item.text: item.at for item in self.box.items()}["water plants"], "2026-11-23 18:00")
        self.assertIn("every weekday", describe(stand_up))

    def test_bad_times_and_cancelling(self) -> None:
        for when in ("tomorrow", "5pm", "2026-13-01 10:00"):
            with self.assertRaises(ValueError):
                parse_time(when)
        with self.assertRaisesRegex(ValueError, "already passed"):
            self.box.add("old", "2026-11-19 10:00")
        self.box.add("call the dentist", "2026-11-21 09:00")
        self.box.add("call mom", "2026-11-21 10:00")
        self.assertEqual([item.text for item in self.box.cancel("dentist")], ["call the dentist"])
        self.assertEqual([item.text for item in self.box.items()], ["call mom"])

    def test_the_tool(self) -> None:
        run = lambda arguments: execute_tool("reminder", arguments, None, lambda *_: True, reminders=self.box)  # noqa: E731
        self.assertIn("Reminder set: call mom: Friday 20 November, 17:00",
                      run({"action": "add", "text": "call mom", "when": "2026-11-20T17:00"}))
        self.assertIn("Not set", run({"action": "add", "text": "x", "when": "later"}))
        self.assertIn("call mom", run({"action": "list"}))
        self.assertIn("Say which reminder", run({"action": "cancel"}))  # no words never means "all of them"
        self.assertIn("call mom", run({"action": "list"}))
        self.assertIn("Cancelled", run({"action": "cancel", "text": "mom"}))
        self.assertEqual(run({"action": "list"}), "No reminders ahead.")


class BuildModeTests(unittest.TestCase):
    def test_it_may_only_write_files_and_use_git_in_the_project_folder(self) -> None:
        calls: list[dict] = []

        def runner(command, **kwargs):
            calls.append({"command": command, **kwargs})
            return subprocess.CompletedProcess(command, 0, "Made a portfolio site.\nOpen index.html.\nNothing to run.", "")
        folder = claude_code.project_folder("My Portfolio Site!", Path("/projects"))
        self.assertEqual(folder, Path("/projects/my-portfolio-site"))
        claude_code.run("Build my portfolio.", folder, "claude", runner=runner, building=True)
        command = calls[0]["command"]
        self.assertEqual(command[command.index("--permission-mode") + 1], "acceptEdits")
        allowed = command[command.index("--allowedTools") + 1].split(",")
        self.assertIn("Write", allowed)
        self.assertFalse([tool for tool in allowed if tool.startswith("Bash(") and not tool.startswith("Bash(git ")])
        self.assertEqual(calls[0]["cwd"], str(folder))
        self.assertTrue(calls[0]["input"].startswith(claude_code.BUILD_INSTRUCTIONS))

    def test_a_build_runs_in_the_background_then_says_where(self) -> None:
        projects = Path(tempfile.mkdtemp())
        finished = threading.Event()
        heard: list[tuple] = []
        saved: list[tuple] = []
        work = claude_code.DeepWork(lambda: projects, lambda title, text: saved.append((title, text)) or projects / "x.md",
                                    lambda *_: None, command=lambda: "claude",
                                    built=lambda *args: (heard.append(args), finished.set()), projects=projects)
        original = claude_code.run
        claude_code.run = lambda task, folder, command, building=False: ((folder / "index.html").write_text("<h1>Hi</h1>"), "Made it.")[1]
        self.addCleanup(setattr, claude_code, "run", original)
        self.assertIn("Nova opens it when it is done", work.build("Portfolio site", "A one-page portfolio."))
        self.assertTrue(finished.wait(5))
        name, folder, ok, said = heard[0]
        self.assertEqual((name, ok, said), ("portfolio-site", True, "Made it."))
        self.assertTrue((folder / "index.html").exists())
        self.assertEqual(saved[0][0], "Build: portfolio-site")
        self.assertIn("isn't installed", claude_code.DeepWork(lambda: projects, lambda *_: None, lambda *_: None,
                                                             command=lambda: None).build("x", "y"))

    def test_the_build_tool(self) -> None:
        asked: list[str] = []
        result = execute_tool("build", {"name": "portfolio site", "task": "A one-page portfolio."}, None,
                              lambda name, details: asked.append(details["summary"]) or True,
                              build=lambda name, task: f"building {name}")
        self.assertEqual((result, asked), ("building portfolio site", ["Build with Claude Code in Documents/Nova Projects: portfolio site"]))
        self.assertIn("isn't installed", execute_tool("build", {"name": "x", "task": "y"}, None, lambda *_: True))


if __name__ == "__main__":
    unittest.main()
