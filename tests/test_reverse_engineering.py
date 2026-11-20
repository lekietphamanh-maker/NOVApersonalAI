"""Reverse engineering with REA: the pinned MCP server, Node's version, the Claude Code call, the report going to
outputs/ and the Library, and the tool asking first."""
from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

import reverse_engineering as rea
from tools import execute_tool


BLUEPRINT = {"parts": [{"id": "ui", "name": "Window", "kind": "ui", "summary": "Electron renderer", "findings": ["React 19"]},
                       {"id": "core", "name": "Sync engine", "kind": "logic", "summary": "Rust", "findings": []},
                       {"id": "bad"}],
             "links": [{"from": "ui", "to": "core", "label": "IPC"}, {"from": "ui", "to": "nowhere"}]}


class BlueprintTests(unittest.TestCase):
    def test_the_blueprint_is_split_from_the_report_and_checked(self) -> None:
        report, plan = rea.blueprint("# App\nText.\n\n```json\n" + json.dumps(BLUEPRINT) + "\n```\n")
        self.assertEqual(report, "# App\nText.")
        self.assertEqual([part["id"] for part in plan["parts"]], ["ui", "core"])  # a part without a name can't be drawn
        self.assertEqual(plan["links"], [{"from": "ui", "to": "core", "label": "IPC"}])  # the link to nowhere went
        self.assertEqual(rea.blueprint("No block here."), ("No block here.", {"parts": [], "links": []}))

    def test_progress_lines_come_from_tool_calls(self) -> None:
        event = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Looking"},
                 {"type": "tool_use", "name": "mcp__rea__strings", "input": {"path": "C:/Apps/Thing.exe", "min": 4}}]}}
        self.assertEqual(rea.progress_line(event), "strings: C:/Apps/Thing.exe")
        self.assertEqual(rea.progress_line({"type": "result", "result": "x"}), "")

    def test_the_stream_gives_the_report_and_the_steps(self) -> None:
        stream = "\n".join(json.dumps(event) for event in (
            {"type": "system", "subtype": "init"},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "a.js"}}]}},
            {"type": "result", "result": "The report."}))
        steps: list = []
        report = rea.run("x", "", Path(tempfile.mkdtemp()), "claude",
                         lambda arguments, **options: subprocess.CompletedProcess(arguments, 0, stream, ""), steps.append)
        self.assertEqual((report, steps), ("The report.", ["Read: a.js"]))


class LiveTests(unittest.TestCase):
    def test_steps_arrive_while_it_runs_and_a_hang_is_stopped(self) -> None:
        import sys
        script = ("import json, sys; sys.stdin.read(); "
                  "print(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Grep', "
                  "'input': {'pattern': 'token'}}]}}), flush=True); print(json.dumps({'type': 'result', 'result': 'ok'}))")
        steps: list = []
        result = rea._live([sys.executable, "-c", script], input="task", progress=steps.append, timeout=20,
                           capture_output=True, text=True)
        self.assertEqual((result.returncode, steps), (0, ["Grep: token"]))
        self.assertIn('"result": "ok"', result.stdout)
        with self.assertRaises(subprocess.TimeoutExpired):
            rea._live([sys.executable, "-c", "import time; time.sleep(30)"], input="", progress=steps.append, timeout=1,
                      text=True)


class SetupTests(unittest.TestCase):
    def test_rea_is_pinned_and_started_the_windows_way(self) -> None:
        self.assertEqual(rea.mcp_config("win32"), {"mcpServers": {"rea": {"command": "cmd",
                         "args": ["/c", "npx", "-y", "rea-agents@6.9.0", "mcp"]}}})
        self.assertEqual(rea.mcp_config("linux")["mcpServers"]["rea"]["command"], "npx")

    def test_node_must_be_new_enough(self) -> None:
        for version, ok in (((22, 23, 4), True), ((22, 22, 0), False), ((23, 5, 0), False), ((24, 22, 1), True),
                            ((24, 1, 0), False), ((26, 12, 1), True), ((27, 0, 0), True), (None, False)):
            self.assertEqual(rea.node_ok(version), ok, version)

    def test_target_names(self) -> None:
        self.assertEqual(rea.target_name(r"C:\\Program Files\\Spotify\\Spotify.exe"), "Spotify.exe")
        self.assertEqual(rea.target_name("https://example.com/app/"), "app")


class RunTests(unittest.TestCase):
    def test_claude_code_gets_only_rea_and_reading_tools(self) -> None:
        seen: dict = {}

        def runner(arguments, **options):
            seen.update(arguments=arguments, options=options,
                        config=json.loads(Path(arguments[arguments.index("--mcp-config") + 1]).read_text()))
            return subprocess.CompletedProcess(arguments, 0, "It's an Electron app.\nMain parts: …", "")
        folder = Path(tempfile.mkdtemp()) / "job"
        report = rea.run("C:/Apps/Thing", "how sync works", folder, "claude", runner)
        self.assertTrue(report.startswith("It's an Electron app."))
        arguments = seen["arguments"]
        self.assertEqual(arguments[arguments.index("--allowedTools") + 1], "mcp__rea,Read,Glob,Grep,WebSearch,WebFetch")
        self.assertIn("--strict-mcp-config", arguments)
        self.assertIn("rea-agents@6.9.0", json.dumps(seen["config"]))
        self.assertIn("Target: C:/Apps/Thing", seen["options"]["input"])
        self.assertIn("Don't change, patch or bypass anything", seen["options"]["input"])
        self.assertNotIn("ANTHROPIC_API_KEY", seen["options"]["env"])

    def test_a_finished_job_files_its_report(self) -> None:
        saved, filed, told = [], [], []
        done = threading.Event()
        events: list = []
        job = rea.ReverseEngineering(save=lambda title, text: saved.append((title, text)) or Path("outputs/2026 RE.md"),
                                     library=lambda title, note: filed.append((title, note)),
                                     done=lambda title, result, ok: told.append((title, result, ok)),
                                     workspace=Path(tempfile.mkdtemp()), command=lambda: "claude", node=lambda: (24, 22, 1),
                                     notify=lambda event, data: events.append((event, data)) or (
                                         event == "rea_job" and data["job"]["status"] != "running" and done.set()))
        original = rea.run

        def fake_run(target, goal, folder, command, progress):
            progress("disassemble: Thing.exe")
            return "Summary line.\nMore.\n```json\n" + json.dumps(BLUEPRINT) + "\n```"
        rea.run = fake_run
        try:
            answer = job.start("C:/Apps/Thing", "how it updates")
            done.wait(5)
        finally:
            rea.run = original
        self.assertIn("in the background", answer)
        self.assertEqual(told, [("Reverse engineering Thing", "outputs/2026 RE.md", True)])
        self.assertEqual(filed[0][0], "RE Thing")
        self.assertIn("Full report: outputs/2026 RE.md", filed[0][1])
        self.assertEqual(job.running, [])
        self.assertNotIn("```json", saved[0][1])  # the blueprint is for the screen, not the written report
        self.assertEqual([event for event, _ in events], ["rea_job", "rea_step", "rea_job"])
        finished = events[-1][1]["job"]
        self.assertEqual((finished["status"], finished["counts"]), ("done", {"parts": 2}))
        self.assertEqual(job.jobs.get(finished["id"])["blueprint"]["links"][0]["label"], "IPC")
        self.assertEqual(job.jobs.recent("rea")[0]["title"], "Thing")

    def test_missing_pieces_are_said_before_anything_starts(self) -> None:
        job = rea.ReverseEngineering(save=None, library=None, done=None, workspace=Path("."), command=lambda: "claude",
                                     node=lambda: None)
        self.assertIn("Node.js 22.23", job.start("x"))
        job.command = lambda: None
        self.assertIn("Claude Code isn't installed", job.problem())

    def test_the_tool_asks_first_and_is_off_by_default(self) -> None:
        self.assertIn("off", execute_tool("reverse_engineer", {"target": "x"}, None, lambda *_: True))
        started: list = []
        declined = execute_tool("reverse_engineer", {"target": "C:/Apps/Thing"}, None, lambda *_: False,
                                reverse=lambda target, goal: started.append(target))
        self.assertIn("declined", declined)
        self.assertEqual(started, [])


if __name__ == "__main__":
    unittest.main()
