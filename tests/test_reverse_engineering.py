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
        job = rea.ReverseEngineering(save=lambda title, text: saved.append((title, text)) or Path("outputs/2026 RE.md"),
                                     library=lambda title, note: filed.append((title, note)),
                                     done=lambda title, result, ok: told.append((title, result, ok)) or done.set(),
                                     workspace=Path(tempfile.mkdtemp()), command=lambda: "claude", node=lambda: (24, 22, 1))
        original = rea.run
        rea.run = lambda target, goal, folder, command: "Summary line.\nMore."
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
