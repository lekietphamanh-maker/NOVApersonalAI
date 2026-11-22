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


class SimulateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())
        (self.home / "Documents" / "Nova Projects" / "shop").mkdir(parents=True)
        (self.home / "notes.txt").write_text("my own file")
        self.runner = shannon.Shannon(JobLog(self.home / "jobs.json"), library=lambda title, note: None,
                                      notify=lambda event, data: None, key=lambda: "sk-ant-test",
                                      home=self.home, platform="win32",
                                      outputs=self.home / "outputs")

    def test_non_local_targets_are_refused_the_way_shannon_refuses_them(self) -> None:
        for kind, value in (("web", "https://example.com"), ("web", "http://8.8.8.8"),
                            ("app", "missing"), ("app", "/etc"),
                            ("file", "missing.txt"), ("file", "/etc/passwd")):
            with self.assertRaises(ValueError, msg=f"{kind} {value}"):
                self.runner.simulate_attack(kind, value)
        with self.assertRaises(ValueError):
            self.runner.simulate_attack("sideways", "localhost:3000")
        with self.assertRaises(ValueError):
            self.runner.simulate_attack("web", "")

    def test_each_step_line_reads_back_as_its_own_stage(self) -> None:
        for steps in shannon.SIM_ATTACKS.values():
            for step in steps:
                self.assertEqual(shannon.stage_of(shannon._sim_line(step)), step["stage"], step["technique"])

    def test_a_web_simulation_is_triaged_filed_and_reported(self) -> None:
        result = self.runner.simulate_attack("web", "localhost:3000")
        self.assertTrue(result["ok"])
        self.assertEqual(result["target"], "http://host.docker.internal:3000")
        self.assertEqual(len(result["steps"]), 6)
        self.assertEqual(result["verdict"]["verdict"], "mitigated")  # proven holes with fixes, nothing unhandled
        self.assertEqual(result["verdict"]["counts"], {"resolved": 4, "mitigated": 2, "needs review": 0})
        for step in result["steps"]:
            self.assertIn(step["verdict"], ("resolved", "mitigated", "needs review"))
            self.assertTrue(step["technique_id"] and step["tactic"] != "unknown")
        report = Path(result["report"])
        self.assertTrue(report.is_file())
        self.assertIn("AiSOC verdict: **mitigated**", report.read_text(encoding="utf-8"))
        self.assertIn("a simulation, not a real attack", report.read_text(encoding="utf-8"))
        ledger = shannon.aisoc.replay_ledger(result["ledger"])
        self.assertEqual([entry["action"] for entry in ledger],
                         ["simulate_start"] + ["attack_step"] * 6 + ["triage"] * 6 + ["triage_done"])
        self.assertEqual(ledger[-1]["outcome"], "mitigated")
        job = self.runner.jobs.get(result["job"]["id"])
        self.assertEqual((job["kind"], job["status"], job["counts"]["critical"]), ("shannon_simulate", "done", 1))
        self.assertEqual(len(job["findings"]), 6)

    def test_app_and_file_targets_use_their_own_steps(self) -> None:
        app = self.runner.simulate_attack("app", "shop")
        self.assertEqual(app["target"], str(self.home / "Documents" / "Nova Projects" / "shop"))
        self.assertEqual([step["technique"] for step in app["steps"]],
                         ["port scan", "directory enumeration", "brute force", "sql injection", "ssrf"])
        filed = self.runner.simulate_attack("file", "notes.txt")
        self.assertEqual(filed["target"], str(self.home / "notes.txt"))
        self.assertEqual([step["technique"] for step in filed["steps"]],
                         ["metadata leak", "macro execution", "malformed file", "archive slip", "embedded link"])
        self.assertTrue(Path(filed["report"]).is_file())
        self.assertTrue(Path(filed["ledger"]).is_file())


if __name__ == "__main__":
    unittest.main()
