"""Shannon: only the owner's own app on this PC or home network, the pinned package inside WSL with the API key passed
through, stages lit from its output, report.sarif turned into cards (worst first), and the Library entry."""
from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

import shannon_runner as shannon
from lab_jobs import JobLog

SARIF = {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "shannon", "rules": [
    {"id": "shannon/xss", "shortDescription": {"text": "Stored XSS in comments"}, "help": {"text": "Escape output."}},
    {"id": "shannon/injection", "shortDescription": {"text": "SQL injection in search"},
     "properties": {"security-severity": "9.8"}, "help": {"text": "Use parameterised queries."}}]}},
    "results": [
        {"ruleId": "shannon/xss", "level": "warning", "message": {"text": "Posted <script>alert(1)</script>, it ran."},
         "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/comments.ts"}, "region": {"startLine": 42}}}]},
        {"ruleId": "shannon/injection", "level": "error", "message": {"text": "' OR 1=1 -- returned every user."}}]}]}


class TargetTests(unittest.TestCase):
    def test_only_this_pc_or_the_home_network(self) -> None:
        self.assertEqual(shannon.docker_target("localhost:3000/login"), "http://host.docker.internal:3000/login")
        self.assertEqual(shannon.docker_target("https://127.0.0.1:8443"), "https://host.docker.internal:8443")
        self.assertEqual(shannon.docker_target("http://192.168.1.20:5000"), "http://192.168.1.20:5000")
        for outside in ("https://example.com", "http://8.8.8.8", "shop.mycompany.com"):
            with self.assertRaises(ValueError, msg=outside):
                shannon.docker_target(outside)

    def test_windows_folders_as_wsl_sees_them(self) -> None:
        self.assertEqual(shannon.wsl_path(r"C:\Users\me\Documents\Nova Projects\shop", "win32"),
                         "/mnt/c/Users/me/Documents/Nova Projects/shop")
        self.assertEqual(shannon.shell("x", "win32"), ["wsl", "--", "bash", "-lc", "x"])

    def test_stages_from_its_output(self) -> None:
        self.assertEqual(shannon.stage_of("[pre-recon] mapping the code"), "recon")
        self.assertEqual(shannon.stage_of("Starting vulnerability analysis (5 agents)"), "analysis")
        self.assertEqual(shannon.stage_of("injection agent: exploitation succeeded"), "exploit")
        self.assertEqual(shannon.stage_of("Reconciliation of findings"), "validate")
        self.assertIsNone(shannon.stage_of("npm warn deprecated"))

    def test_sarif_cards_worst_first(self) -> None:
        cards = shannon.findings(SARIF)
        self.assertEqual([(card["severity"], card["kind"]) for card in cards], [("critical", "injection"), ("medium", "xss")])
        self.assertEqual(cards[1]["where"], "src/comments.ts:42")
        self.assertEqual(cards[0]["fix"], "Use parameterised queries.")
        self.assertEqual(shannon.counts(cards), {"critical": 1, "high": 0, "medium": 1, "low": 0})


class FakeProcess:
    def __init__(self, lines: list[str], output: Path) -> None:
        self.output, self.killed = output, False
        self.stdout = self._lines(lines)

    def _lines(self, lines: list[str]):
        for line in lines:
            yield line + "\n"
        (self.output / "deliverables").mkdir(parents=True, exist_ok=True)
        (self.output / "deliverables" / "report.sarif").write_text(json.dumps(SARIF))
        (self.output / "deliverables" / "Security-Assessment-Report.md").write_text("# Report")

    def wait(self) -> int:
        return 0

    def kill(self) -> None:
        self.killed = True


class RunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())
        (self.home / "Documents" / "Nova Projects" / "shop").mkdir(parents=True)
        self.events: list = []
        self.filed: list = []
        self.finished = threading.Event()
        self.started: dict = {}

        def popen(arguments, **options):
            self.started.update(arguments=arguments, options=options)
            output = next((self.home / "Documents" / "Nova Projects" / "Security checks").iterdir())
            return FakeProcess(["\x1b[32m[pre-recon]\x1b[0m reading src/", "Starting exploitation", "reporting phase"], output)

        def notify(event, data):
            self.events.append((event, data))
            if event == "shannon_job" and data["job"]["status"] != "running":
                self.finished.set()
        self.runner = shannon.Shannon(JobLog(self.home / "jobs.json"), library=lambda title, note: self.filed.append((title, note)),
                                      notify=notify, key=lambda: "sk-ant-test", home=self.home, platform="win32",
                                      popen=popen)

    def test_a_check_runs_in_wsl_and_ends_as_cards_and_a_library_entry(self) -> None:
        job = self.runner.start("localhost:3000", "shop")
        self.assertTrue(self.finished.wait(5))
        arguments = self.started["arguments"]
        self.assertEqual(arguments[:4], ["wsl", "--", "bash", "-lc"])
        self.assertIn("npx -y @keygraph/shannon@3.5.0 start -u http://host.docker.internal:3000", arguments[4])
        self.assertIn("ANTHROPIC_API_KEY/u", self.started["options"]["env"]["WSLENV"])
        self.assertEqual(self.started["options"]["env"]["ANTHROPIC_API_KEY"], "sk-ant-test")
        stages = [data["job"]["stage"] for event, data in self.events if event == "shannon_job"]
        self.assertEqual(stages, ["", "recon", "exploit", "report", "report"])
        self.assertIn(("shannon_line", {"id": job["id"], "line": "[pre-recon] reading src/"}), self.events)  # no colours
        done = self.runner.jobs.get(job["id"])
        self.assertEqual((done["status"], done["counts"]["critical"]), ("done", 1))
        self.assertEqual(self.filed[0][0], "Security check shop")
        self.assertIn("1 critical, 1 medium", self.filed[0][1])
        self.assertIsNone(self.runner.process)

    def test_only_the_owners_folders_and_one_at_a_time(self) -> None:
        with self.assertRaises(ValueError):
            self.runner.start("localhost:3000", "/etc")
        with self.assertRaises(ValueError):
            self.runner.start("localhost:3000", "missing")
        self.runner.process = object()
        with self.assertRaises(ValueError):
            self.runner.start("localhost:3000", "shop")

    def test_what_is_missing_is_said_in_order(self) -> None:
        answers = {"true": 0, "docker": 1}

        def run(arguments, **options):
            script = arguments[-1]
            if script.startswith("docker"):
                return subprocess.CompletedProcess(arguments, answers["docker"], "" if answers["docker"] else "ok\n", "")
            if script.startswith("node"):
                return subprocess.CompletedProcess(arguments, 0, "v18.19.0\n", "")
            return subprocess.CompletedProcess(arguments, answers["true"], "", "")
        self.runner._run = run
        self.assertIn("Docker isn't running", self.runner.problem())
        answers["docker"] = 0
        self.assertIn("Node.js 20", self.runner.problem())
        self.runner.key = lambda: None
        self.assertIn("Claude API key", self.runner.problem())


if __name__ == "__main__":
    unittest.main()
