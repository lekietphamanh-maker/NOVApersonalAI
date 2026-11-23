"""Shannon: only the owner's own app on this PC or home network, the pinned package inside WSL with the API key passed
through, stages lit from its output, report.sarif turned into cards (worst first), and the Library entry."""
from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import shannon_runner as shannon
import update_pipeline
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


class SelfTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())
        self.runner = shannon.Shannon(JobLog(self.home / "jobs.json"), library=lambda title, note: None,
                                      notify=lambda event, data: None, key=lambda: "sk-ant-test",
                                      home=self.home, platform="win32",
                                      outputs=self.home / "outputs",
                                      ui_origin=lambda: "http://127.0.0.1:8770")

    def test_self_target_is_novas_own_repo_and_running_screen(self) -> None:
        repo, origin = shannon.resolve_self_target(ui_origin=lambda: "http://127.0.0.1:8770")
        self.assertEqual(repo, shannon.nova_repo_root())
        self.assertEqual(origin, "http://127.0.0.1:8770")
        for marker in shannon.NOVA_MARKERS:
            self.assertTrue((repo / marker).is_file(), marker)
        # The running origin, spelled with a trailing slash, is the same origin.
        _, same = shannon.resolve_self_target(origin="http://127.0.0.1:8770/",
                                              ui_origin=lambda: "http://127.0.0.1:8770")
        self.assertEqual(same, "http://127.0.0.1:8770")
        # Nova's own repo, named outright, is accepted too.
        named, _ = shannon.resolve_self_target(repo=str(repo), ui_origin=lambda: "http://127.0.0.1:8770")
        self.assertEqual(named, repo)

    def test_anything_else_is_refused(self) -> None:
        for kwargs in ({"repo": str(self.home)},  # a folder that isn't Nova's code
                       {"repo": "/etc"},
                       {"origin": "https://example.com", "ui_origin": lambda: "http://127.0.0.1:8770"},
                       {"origin": "http://8.8.8.8:8770", "ui_origin": lambda: "http://127.0.0.1:8770"},
                       # Loopback, but not Nova's screen.
                       {"origin": "http://127.0.0.1:9999", "ui_origin": lambda: "http://127.0.0.1:8770"},
                       # A loopback address with no running screen to match it against.
                       {"origin": "http://127.0.0.1:8770", "ui_origin": lambda: None}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                shannon.resolve_self_target(**kwargs)
        with self.assertRaises(ValueError):  # no screen running at all
            shannon.resolve_self_target(ui_origin=lambda: None)
        for value in (str(self.home), "https://example.com", "http://127.0.0.1:9999"):
            with self.assertRaises(ValueError, msg=value):
                self.runner.simulate_attack("self", value)

    def test_no_running_screen_means_no_self_attack(self) -> None:
        runner = shannon.Shannon(JobLog(self.home / "jobs2.json"), library=lambda title, note: None,
                                 notify=lambda event, data: None, key=lambda: "sk-ant-test",
                                 home=self.home, platform="win32", outputs=self.home / "outputs")
        with self.assertRaises(ValueError):
            runner.simulate_attack("self", None)


class SelfCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())
        self.runner = shannon.Shannon(JobLog(self.home / "jobs.json"), library=lambda title, note: None,
                                      notify=lambda event, data: None, key=lambda: "sk-ant-test",
                                      home=self.home, platform="win32",
                                      outputs=self.home / "outputs",
                                      ui_origin=lambda: "http://127.0.0.1:8770")

    def test_each_self_step_line_reads_back_as_its_own_stage(self) -> None:
        for spec in shannon.SELF_STEPS:
            step = {"technique": spec["technique"], "stage": spec["stage"], "detail": "x",
                    "severity": spec["severity"], "landed": True, "proven": False, "fix": ""}
            self.assertEqual(shannon.stage_of(shannon._sim_line(step)), spec["stage"], spec["technique"])

    def test_the_real_checks_pass_on_novas_real_code(self) -> None:
        repo = shannon.nova_repo_root()
        for spec in shannon.SELF_STEPS:
            found = getattr(shannon, spec["check"])(repo, "http://127.0.0.1:8770")
            self.assertFalse(found["proven"], f"{spec['technique']}: {found['detail']}")
            self.assertTrue(found["landed"], spec["technique"])
            self.assertTrue(found["detail"])
            # Every step says what it probed and whether it was live or only read the code.
            self.assertTrue("Static check" in found["detail"] or "Live probe" in found["detail"], spec["technique"])

    def test_a_missing_guard_is_recorded_as_a_finding_not_a_pass(self) -> None:
        doctored = Path(tempfile.mkdtemp())
        (doctored / "agent.py").write_text("SYSTEM_PROMPT = 'be nice'\nUNSAVED_TOOL_RESULTS = set()\n")
        (doctored / "evaluate.py").write_text("")
        found = shannon._check_prompt_injection(doctored, "http://127.0.0.1:8770")
        self.assertTrue(found["proven"])
        self.assertIn("data, never instructions", found["fix"])
        (doctored / "dashboard.py").write_text("nothing here\n")
        (doctored / "discover.py").write_text("nothing here\n")
        (doctored / "tools.py").write_text("nothing here\n")
        found = shannon._check_approval(doctored, "http://127.0.0.1:8770")
        self.assertTrue(found["proven"])
        (doctored / "web_search.py").write_text('urlopen(Request("https://evil.example/x"))\n')
        (doctored / "tools.py").write_text("def fetch_url(url):\n    return urlopen(url)\n")
        found = shannon._check_ssrf(doctored, "http://127.0.0.1:8770")
        self.assertTrue(found["proven"])
        (doctored / "update_pipeline.py").write_text("def push_to_github():\n    pass\n")
        (doctored / "dashboard.py").write_text("push_to_github(target, pipe.repo, token)\n")
        found = shannon._check_self_update(doctored, "http://127.0.0.1:8770")
        self.assertTrue(found["proven"])

    def test_the_token_probe_records_a_server_that_accepts_anything(self) -> None:
        class AlwaysYes(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server naming
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok": true}')

            def log_message(self, *_args) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), AlwaysYes)
        threading.Thread(target=server.serve_forever, name="StubUiServer", daemon=True).start()
        try:
            port = server.server_address[1]
            factory = lambda: SimpleNamespace(url=f"http://127.0.0.1:{port}", token="fixed-token",
                                              start=lambda port=0: None, stop=lambda: None)
            found = shannon._check_ui_token(shannon.nova_repo_root(), "http://127.0.0.1:8770",
                                            server_factory=factory)
        finally:
            server.shutdown()
            server.server_close()
        self.assertTrue(found["proven"])
        self.assertIn("401", found["detail"])  # a wrong token was answered 200, not 401


class SelfRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())
        self.runner = shannon.Shannon(JobLog(self.home / "jobs.json"), library=lambda title, note: None,
                                      notify=lambda event, data: None, key=lambda: "sk-ant-test",
                                      home=self.home, platform="win32",
                                      outputs=self.home / "outputs",
                                      ui_origin=lambda: "http://127.0.0.1:8770")

    def test_attack_nova_herself_runs_all_five_steps_and_files_no_holes(self) -> None:
        result = self.runner.simulate_attack("self", None)
        self.assertTrue(result["ok"])
        self.assertEqual(result["kind"], "self")
        self.assertEqual(result["target"], str(shannon.nova_repo_root()))
        self.assertEqual(result["origin"], "http://127.0.0.1:8770")
        self.assertEqual([step["technique"] for step in result["steps"]],
                         ["command injection", "brute force", "privilege escalation", "ssrf", "data exfiltration"])
        for step in result["steps"]:
            self.assertIn(step["verdict"], ("resolved", "mitigated", "needs review"))
            self.assertTrue(step["technique_id"] and step["tactic"] != "unknown")
        self.assertEqual(result["verdict"]["verdict"], "resolved")
        self.assertEqual(result["verdict"]["counts"], {"resolved": 5, "mitigated": 0, "needs review": 0})
        self.assertEqual(result["job"]["findings"], [])  # nothing proven: no cards, no Update now fix
        self.assertEqual(result["job"]["counts"], {"critical": 0, "high": 0, "medium": 0, "low": 0})
        self.assertEqual(update_pipeline.fixes_from_shannon_job(result["job"]), [])
        report = Path(result["report"]).read_text(encoding="utf-8")
        self.assertIn("a simulation, not a real attack", report)
        self.assertIn("restart to pick the fixes up", report)
        ledger = shannon.aisoc.replay_ledger(result["ledger"])
        self.assertEqual([entry["action"] for entry in ledger],
                         ["simulate_start"] + ["attack_step"] * 5 + ["triage"] * 5 + ["triage_done"])
        job = self.runner.jobs.get(result["job"]["id"])
        self.assertEqual((job["kind"], job["target_kind"], job["status"]), ("shannon_simulate", "self", "done"))
        self.assertEqual(job["origin"], "http://127.0.0.1:8770")

    def test_a_proven_self_finding_becomes_an_update_now_fix_for_novas_repo(self) -> None:
        real = shannon._check_ssrf

        def broken(repo, origin):
            return {"proven": True, "landed": True, "fix": "Stop fetching arbitrary URLs.",
                    "detail": "A probe fetched an arbitrary URL."}

        shannon._check_ssrf = broken  # the steps look the check up by name at run time
        try:
            result = self.runner.simulate_attack("self", None)
        finally:
            shannon._check_ssrf = real
        self.assertEqual(len(result["job"]["findings"]), 1)
        self.assertEqual(result["job"]["findings"][0]["severity"], "medium")
        self.assertEqual(result["verdict"]["verdict"], "mitigated")
        fixes = update_pipeline.fixes_from_shannon_job(result["job"])
        self.assertEqual(len(fixes), 1)
        self.assertEqual(fixes[0]["how"], "Stop fetching arbitrary URLs.")
        # Update now's target is Nova's own repo, not a picked project folder.
        self.assertEqual(Path(result["job"]["target"]), shannon.nova_repo_root())
        self.assertEqual(result["job"]["target_kind"], "self")


if __name__ == "__main__":
    unittest.main()
