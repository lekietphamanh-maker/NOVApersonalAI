"""Skills: notes in the vault run by a phrase, a button or a schedule; results in outputs/; long work on Claude Code."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import types
import unittest
import unittest.mock
from datetime import datetime
from pathlib import Path

try:
    import tkinter  # noqa: F401
except ImportError:
    sys.modules["tkinter"] = types.SimpleNamespace(Tk=object, TclError=Exception)

import claude_code
import dashboard  # noqa: E402
import skills as skill_notes
from agent import Agent
from memory import Memory
from skills import Skills, check_schedule, parse, render, slot_today
from tools import execute_tool

FRIDAY_8AM = datetime(2026, 11, 20, 8, 0)


class SkillNoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp())
        self.skills = Skills(self.vault)
        self.skills.ensure_defaults()

    def test_a_note_round_trips_and_a_hand_written_typo_still_runs(self) -> None:
        skill = self.skills.get("plan-today")
        self.assertEqual(parse(skill.name, render(skill)), skill)
        self.assertEqual(parse("x", "---\ntitle: X\nschedule: every tuesday\n---\nDo it.").schedule, "manual")
        self.assertIsNone(parse("x", "just a note without a title"))

    def test_schedules(self) -> None:
        for good in ("manual", "Daily 07:30", "weekdays 7:05", "weekly sunday 18:00", "monthly 1 09:00"):
            check_schedule(good)
        for bad in ("daily", "weekly funday 10:00", "monthly 31 09:00", "daily 25:00", "every morning"):
            with self.assertRaises(ValueError, msg=bad):
                check_schedule(bad)
        saturday = datetime(2026, 11, 21, 9, 0)
        self.assertIsNone(slot_today("weekdays 07:30", saturday))
        self.assertEqual(slot_today("weekly saturday 08:00", saturday), saturday.replace(hour=8))
        self.assertIsNone(slot_today("monthly 1 09:00", saturday))

    def test_due_today_once_and_catching_up_the_same_day_only(self) -> None:
        self.assertEqual([skill.name for skill in self.skills.due(FRIDAY_8AM, {})], ["plan-today"])
        ran = {"plan-today": FRIDAY_8AM.replace(hour=7, minute=31).isoformat()}
        self.assertEqual(self.skills.due(FRIDAY_8AM, ran), [])
        yesterday = {"plan-today": datetime(2026, 11, 19, 7, 30).isoformat()}
        self.assertEqual(len(self.skills.due(FRIDAY_8AM.replace(hour=7, minute=0), yesterday)), 0)  # not time yet today
        friday_evening = FRIDAY_8AM.replace(hour=17, minute=5)
        self.assertIn("weekly-review", [skill.name for skill in self.skills.due(friday_evening, ran)])

    def test_the_phrase_runs_it_a_long_sentence_does_not(self) -> None:
        self.assertEqual(self.skills.match("Plan my day please, Nova").name, "plan-today")
        self.assertEqual(self.skills.match("review my week").name, "weekly-review")
        self.assertIsNone(self.skills.match("can you explain how other people plan my day when they have a lot of meetings"))
        self.assertIsNone(self.skills.match("what's the weather"))

    def test_adding_and_outputs(self) -> None:
        skill = self.skills.add("Sum up my Fridays", "Sum up what I did this week.", "friday summary, sum up my week",
                                "weekly friday 18:00")
        self.assertEqual((skill.name, skill.says), ("sum-up-my-fridays", ["friday summary", "sum up my week"]))
        self.assertTrue((self.vault / "skills" / "sum-up-my-fridays.md").exists())
        for bad in ({"title": "Sum up my Fridays", "instructions": "again"}, {"title": "", "instructions": "x"},
                    {"title": "New", "instructions": "x", "schedule": "sometimes"}):
            with self.assertRaises(ValueError):
                self.skills.add(**bad)
        first = self.skills.save_output("Plan my day", "1. Ship it", FRIDAY_8AM)
        second = self.skills.save_output("Plan my day", "2. Again", FRIDAY_8AM)
        self.assertEqual((first.name, second.name), ("2026-11-20 Plan my day.md", "2026-11-20 Plan my day 2.md"))
        self.assertIn("1. Ship it", first.read_text(encoding="utf-8"))

    def test_the_defaults_are_written_once_and_then_left_alone(self) -> None:
        (self.vault / "skills" / "plan-today.md").unlink()
        self.skills.ensure_defaults()
        self.assertIsNone(self.skills.get("plan-today"))  # the owner deleted it: it stays deleted


class SkillToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skills = Skills(Path(tempfile.mkdtemp()))
        self.skills.ensure_defaults()

    def run_tool(self, arguments: dict, approve=lambda *_: True, deep_work=None) -> str:
        return execute_tool("skills", arguments, None, approve, skills=self.skills, deep_work=deep_work)

    def test_list_run_add_and_save(self) -> None:
        self.assertIn("Plan my day (plan-today)", self.run_tool({"action": "list"}))
        self.assertIn('Run my skill "Weekly review" now', self.run_tool({"action": "run", "name": "weekly review"}))
        self.assertIn("no skill by that name", self.run_tool({"action": "run", "name": "nope"}))
        made = self.run_tool({"action": "add", "title": "Gym log", "instructions": "Log my workout.", "says": "log my workout"})
        self.assertIn("Say “log my workout” to run it", made)
        self.assertIn("declined", self.run_tool({"action": "add", "title": "X", "instructions": "y"}, approve=lambda *_: False))
        self.assertIn("Saved in outputs/", self.run_tool({"action": "save", "title": "Notes", "text": "hello"}))

    def test_long_work_goes_to_claude_code(self) -> None:
        self.skills.add("Explainer", "Explain transformers.", brain="claude-code")
        self.assertIn("call deep_work", self.run_tool({"action": "run", "name": "explainer"}))
        handed: list[tuple[str, str]] = []
        result = execute_tool("deep_work", {"title": "Jev vs LLMs", "task": "Write an explainer."}, None, lambda *_: True,
                              deep_work=lambda title, task: handed.append((title, task)) or "working")
        self.assertEqual((result, handed), ("working", [("Jev vs LLMs", "Write an explainer.")]))
        self.assertIn("isn't installed", execute_tool("deep_work", {"title": "x", "task": "y"}, None, lambda *_: True))


class ClaudeCodeTests(unittest.TestCase):
    def test_the_task_goes_in_by_stdin_with_read_only_tools(self) -> None:
        calls: list[dict] = []

        def runner(command, **kwargs):
            calls.append({"command": command, **kwargs})
            return subprocess.CompletedProcess(command, 0, stdout="# Explainer\n\nDone.\n", stderr="")
        answer = claude_code.run("Write an explainer & more | stuff", Path("/vault"), "claude.cmd", runner=runner)
        self.assertEqual(answer, "# Explainer\n\nDone.")
        call = calls[0]
        self.assertEqual(call["command"], ["claude.cmd", "-p", "--output-format", "text", "--allowedTools", claude_code.ALLOWED_TOOLS])
        self.assertTrue(call["input"].endswith("Write an explainer & more | stuff"))  # never on the command line
        self.assertEqual(call["cwd"], str(Path("/vault")))
        self.assertFalse({"Write", "Edit", "Bash"} & set(claude_code.ALLOWED_TOOLS.split(",")))  # it can't change or run anything

    def test_it_runs_on_the_claude_plan_never_on_an_api_key(self) -> None:
        seen: list[dict] = []
        runner = lambda command, **kwargs: seen.append(kwargs["env"]) or subprocess.CompletedProcess(command, 0, "ok", "")  # noqa: E731
        with unittest.mock.patch.dict(claude_code.os.environ, {"ANTHROPIC_API_KEY": "sk-ant-x", "PATH": "/bin"}):
            claude_code.run("x", Path("."), "claude", runner=runner)
        self.assertNotIn("ANTHROPIC_API_KEY", seen[0])
        self.assertEqual(seen[0]["PATH"], "/bin")

    def test_a_failure_says_why(self) -> None:
        failing = lambda command, **_kw: subprocess.CompletedProcess(command, 1, stdout="", stderr="Error: not logged in")  # noqa: E731
        with self.assertRaisesRegex(RuntimeError, "not logged in"):
            claude_code.run("x", Path("."), "claude", runner=failing)

    def test_background_work_is_saved_and_announced(self) -> None:
        folder = Path(tempfile.mkdtemp())
        shelf = Skills(folder)
        finished = threading.Event()
        told: list[tuple] = []
        work = claude_code.DeepWork(lambda: folder, shelf.save_output,
                                    lambda *args: (told.append(args), finished.set()), command=lambda: "claude")
        original = claude_code.run
        claude_code.run = lambda task, cwd, command: f"Result for: {task[-12:]}"
        self.addCleanup(setattr, claude_code, "run", original)
        self.assertIn("working on", work.start("Jev vs LLMs", "Write it up."))
        self.assertTrue(finished.wait(5))
        self.assertEqual(told[0][0], "Jev vs LLMs")
        self.assertTrue(told[0][2])
        self.assertIn("Write it up.", (folder / told[0][1]).read_text(encoding="utf-8"))
        absent = claude_code.DeepWork(lambda: folder, shelf.save_output, lambda *_: None, command=lambda: None)
        self.assertIn("isn't installed", absent.start("x", "y"))


class SkillTurnTests(unittest.TestCase):
    """The dashboard's side: a skill's turn, its result in outputs/, and its tools only while it runs."""

    def setUp(self) -> None:
        self.skills = Skills(Path(tempfile.mkdtemp()))
        self.skills.ensure_defaults()
        self.settings: dict = {}
        self.chat: list[tuple] = []
        self.started: list[str] = []
        self.app = types.SimpleNamespace(
            skills=self.skills, settings=self.settings, running_skill=None, turn_cancel=threading.Event(),
            state={"busy": False}, agent=types.SimpleNamespace(only_tools=None),
            deep_work=types.SimpleNamespace(available=False, running=[], start=lambda title, task: "Claude Code is working. Tell them."),
            voice=types.SimpleNamespace(stop_speaking=lambda: None), _save_setting=self.settings.__setitem__,
            _append_chat=lambda who, text, role: self.chat.append((who, text)), _set_busy=lambda busy: None,
            _update=lambda **_changes: None, _toast=lambda *_args: None, _chat_worker=lambda prompt: None)
        for method in ("_start_skill", "_finish_skill", "_skills_state"):
            setattr(self.app, method, types.MethodType(getattr(dashboard.AlfredApp, method), self.app))
        original = dashboard.threading.Thread
        dashboard.threading.Thread = lambda target, args=(), daemon=None, **_kw: types.SimpleNamespace(
            start=lambda: self.started.append(args[0]))
        self.addCleanup(setattr, dashboard.threading, "Thread", original)

    def test_a_skill_turn_uses_its_tools_and_saves_its_result(self) -> None:
        self.app._start_skill(self.skills.get("plan-today"), said="plan my day")
        self.assertTrue(self.started[0].startswith('Run my skill "Plan my day" now'))
        self.assertEqual(self.app.agent.only_tools, {"weather", "library", "news", "second_brain", "skills"})
        self.assertIn("plan-today", self.settings["skill_runs"])
        self.app._finish_skill("1. Weather: sunny\n2. Ship Nova")
        self.assertIsNone(self.app.agent.only_tools)
        saved = list(self.skills.outputs.glob("*Plan my day.md"))
        self.assertEqual(len(saved), 1)
        self.assertIn("Ship Nova", saved[0].read_text(encoding="utf-8"))

    def test_a_stopped_skill_saves_nothing_and_long_work_goes_to_claude_code(self) -> None:
        self.app._start_skill(self.skills.get("weekly-review"))
        self.app.turn_cancel.set()
        self.app._finish_skill("Stopped.")
        self.assertFalse(self.skills.outputs.exists())
        long_work = self.skills.add("Explainer", "Explain it.", brain="claude-code")
        self.app.turn_cancel.clear()
        self.app.state["busy"] = True  # Claude Code works in the background, even while Nova is busy
        self.assertIsNone(self.app._start_skill(long_work))
        self.assertEqual(self.chat[-1], ("NOVA", "Claude Code is working."))


class OnlyItsToolsTests(unittest.TestCase):
    def test_a_skill_naming_its_tools_gets_only_those(self) -> None:
        agent = Agent(model="test", memory=Memory(Path(tempfile.mkdtemp()) / "m.sqlite3"))
        offered = lambda: {tool["function"]["name"] for tool in agent._offered(  # noqa: E731
            [{"function": {"name": name}} for name in ("weather", "web_search", "calculate")])}
        self.assertEqual(offered(), {"web_search", "calculate"})  # weather needs a location
        agent.only_tools = {"calculate"}
        self.assertEqual(offered(), {"calculate"})


if __name__ == "__main__":
    unittest.main()
