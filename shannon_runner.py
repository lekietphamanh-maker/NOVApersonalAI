"""Shannon (github.com/KeygraphHQ/shannon): an AI pentester that reads a project's source, attacks the running app
and reports only the holes it could actually prove, each with its proof and a fix.

Nova runs the pinned npm package with npx inside WSL2 (Shannon doesn't run on Windows itself; it needs Docker Desktop
with WSL integration), on the owner's own project folder and its running app, and only on this PC or the home network:
it really attacks what it's pointed at. Shannon 3.5 talks to Claude with an API key (a Claude plan isn't enough), and a
full run costs API credit. The stages it reaches light up on the Mission board; report.sarif becomes the cards; the
written report goes to the project's security folder and a Library entry under "Security checks".
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import shlex
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from lab_jobs import JobLog

import aisoc

PACKAGE = "@keygraph/shannon@3.5.0"  # pinned: a new Shannon is a change to Nova, reviewed like any other
STAGES = ("recon", "analysis", "exploit", "validate", "report")
STAGE_PATTERNS = {  # words in Shannon's --follow output that say a stage has started
    "recon": re.compile(r"\b(pre-?recon|recon(naissance)?)\b", re.IGNORECASE),
    "analysis": re.compile(r"\b(vuln(erability)?[- ]analysis|sast|analysis (phase|agent))\b", re.IGNORECASE),
    "exploit": re.compile(r"\bexploit(ation|ing)?\b", re.IGNORECASE),
    "validate": re.compile(r"\b(validat\w*|reconcil\w*)\b", re.IGNORECASE),
    "report": re.compile(r"\b(reporting|report (phase|agent|generation))\b", re.IGNORECASE),
}
SEVERITIES = ("critical", "high", "medium", "low")
LEVELS = {"error": "high", "warning": "medium", "note": "low"}  # SARIF level → severity when no score is given
NODE_MAJOR = 20
TIMEOUT_SECONDS = 4 * 60 * 60
LIBRARY_TOPIC = "Security checks"
LOCAL_NAMES = {"localhost", "host.docker.internal"}


# ---------- Simulate attack (Shannon + AiSOC) ----------
# A scripted attack, not a real one: no exploit ever runs, nothing is installed and nothing leaves this PC. Each
# step is one of Shannon's own stages, written so stage_of() reads it back, and each step is triaged by aisoc.py.
# "landed" means the step reached the target (a red block on the shield); "proven" means it proved a hole.
_BRUTE_FORCE_STEP = {"technique": "brute force", "stage": "exploit", "severity": "high", "landed": True,
                     "proven": True, "detail": "Simulated login attempts accepted a weak test password.",
                     "fix": "Require a strong password and lock the account after a few failed logins."}

SIM_ATTACKS: dict[str, list[dict[str, Any]]] = {
    "web": [
        {"technique": "port scan", "stage": "recon", "severity": "low", "landed": True, "proven": False,
         "detail": "Open ports answered on the app (the scan reached it).", "fix": ""},
        {"technique": "service fingerprinting", "stage": "recon", "severity": "low", "landed": True, "proven": False,
         "detail": "The web server and its version showed in its headers.", "fix": ""},
        dict(_BRUTE_FORCE_STEP),
        {"technique": "sql injection", "stage": "exploit", "severity": "critical", "landed": True, "proven": True,
         "detail": "A simulated ' OR 1=1 -- probe returned rows it should not have.",
         "fix": "Use parameterised queries; never build SQL from user input."},
        {"technique": "cross-site scripting", "stage": "exploit", "severity": "medium", "landed": False, "proven": False,
         "detail": "A simulated <script> probe was escaped and did not run.", "fix": ""},
        {"technique": "path traversal", "stage": "validate", "severity": "medium", "landed": False, "proven": False,
         "detail": "A simulated ../ probe was blocked by the app.", "fix": ""},
    ],
    "app": [
        {"technique": "port scan", "stage": "recon", "severity": "low", "landed": True, "proven": False,
         "detail": "Open ports answered on this PC (the scan reached the app's machine).", "fix": ""},
        {"technique": "directory enumeration", "stage": "analysis", "severity": "medium", "landed": True, "proven": True,
         "detail": "A simulated scan found an exposed backup file in the project folder.",
         "fix": "Remove backup and hidden files from the deployed folder."},
        dict(_BRUTE_FORCE_STEP),
        {"technique": "sql injection", "stage": "exploit", "severity": "critical", "landed": False, "proven": False,
         "detail": "A simulated injection probe was stopped by parameterised queries.", "fix": ""},
        {"technique": "ssrf", "stage": "validate", "severity": "medium", "landed": False, "proven": False,
         "detail": "A simulated request to an internal address was refused.", "fix": ""},
    ],
    "file": [
        {"technique": "metadata leak", "stage": "recon", "severity": "low", "landed": True, "proven": False,
         "detail": "The file's metadata (author, paths) was readable; nothing sensitive in it.", "fix": ""},
        {"technique": "macro execution", "stage": "exploit", "severity": "high", "landed": False, "proven": False,
         "detail": "A simulated macro did not run: macros are disabled for this file.", "fix": ""},
        {"technique": "malformed file", "stage": "exploit", "severity": "medium", "landed": True, "proven": True,
         "detail": "A crafted file made the parser crash (a denial of service).",
         "fix": "Update the parser and open untrusted files in a sandbox."},
        {"technique": "archive slip", "stage": "exploit", "severity": "high", "landed": False, "proven": False,
         "detail": "A crafted archive entry trying to escape its folder was blocked.", "fix": ""},
        {"technique": "embedded link", "stage": "validate", "severity": "medium", "landed": True, "proven": True,
         "detail": "An embedded link in the file points outside; opening it would phone home.",
         "fix": "Strip external links from untrusted files."},
    ],
}


def _sim_line(step: dict[str, Any]) -> str:
    """A step as a line of Shannon's own output, so stage_of() reads its stage back."""
    technique, detail = step["technique"], step["detail"]
    if step["stage"] == "recon":
        return f"[pre-recon] {technique}: {detail}"
    if step["stage"] == "analysis":
        return f"vulnerability analysis: {technique}: {detail}"
    if step["stage"] == "exploit":
        return f"exploitation: {technique}: {detail}"
    return f"validating {technique}: {detail}"


def docker_target(url: str) -> str:
    """The app's address as Shannon's containers reach it. Only this PC or the home network: Shannon really attacks."""
    text = " ".join(str(url).split())
    if not re.match(r"^https?://", text):
        text = f"http://{text}"
    parts = urlsplit(text)
    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError("give the address of your running app, like http://localhost:3000")
    local = host in LOCAL_NAMES or host.endswith(".local")
    if not local:
        try:
            address = ipaddress.ip_address(host)
            local = address.is_loopback or address.is_private
        except ValueError:
            local = False
    if not local:
        raise ValueError("Shannon attacks what it's pointed at, so Nova runs it only on an app on this PC or your home "
                         "network (localhost, 127.0.0.1, 192.168.x.x…)")
    if host in ("localhost", "::1") or host.startswith("127."):  # inside Docker, localhost is the container itself
        port = f":{parts.port}" if parts.port else ""
        parts = parts._replace(netloc=f"host.docker.internal{port}")
    return urlunsplit(parts)


def wsl_path(path: Path | str, platform: str = sys.platform) -> str:
    """C:\\Users\\me\\x → /mnt/c/Users/me/x (how WSL sees a Windows folder)."""
    if platform != "win32":
        return str(path)
    windows = PureWindowsPath(str(path))
    drive = windows.drive.rstrip(":").lower()
    return "/mnt/" + drive + "/" + "/".join(windows.parts[1:])


def shell(script: str, platform: str = sys.platform) -> list[str]:
    return ["wsl", "--", "bash", "-lc", script] if platform == "win32" else ["bash", "-lc", script]


def start_script(url: str, repo: str, workspace: str, output: str) -> str:
    return " ".join(shlex.quote(part) for part in
                    ("npx", "-y", PACKAGE, "start", "-u", url, "-r", repo, "-w", workspace, "-o", output, "--follow"))


def stage_of(line: str) -> str | None:
    """The latest stage a line of Shannon's output speaks of."""
    found = None
    for stage in STAGES:
        if STAGE_PATTERNS[stage].search(line):
            found = stage
    return found


def _severity(result: dict, rule: dict) -> str:
    for source in (result.get("properties") or {}, rule.get("properties") or {}):
        named = str(source.get("severity") or "").lower()
        if named in SEVERITIES:
            return named
        score = source.get("security-severity")
        try:
            value = float(score)
        except (TypeError, ValueError):
            continue
        return "critical" if value >= 9 else "high" if value >= 7 else "medium" if value >= 4 else "low"
    return LEVELS.get(str(result.get("level") or "warning"), "medium")


def _text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("markdown") or value.get("text") or ""
    return " ".join(str(value or "").split())


def findings(sarif: dict) -> list[dict[str, str]]:
    """Shannon's report.sarif as cards: severity, kind, title, where, proof and fix; the worst first."""
    cards: list[dict[str, str]] = []
    for run in sarif.get("runs") or []:
        rules = {rule.get("id"): rule for rule in ((run.get("tool") or {}).get("driver") or {}).get("rules") or []}
        for result in run.get("results") or []:
            rule = rules.get(result.get("ruleId"), {})
            place = ((result.get("locations") or [{}])[0].get("physicalLocation") or {})
            where = (place.get("artifactLocation") or {}).get("uri") or ""
            line = (place.get("region") or {}).get("startLine")
            cards.append({
                "severity": _severity(result, rule),
                "kind": str(result.get("ruleId") or "finding").rsplit("/", 1)[-1],
                "title": (_text(rule.get("shortDescription")) or _text(rule.get("name")) or _text(result.get("message")))[:160],
                "where": f"{where}:{line}" if where and line else where,
                "proof": _text(result.get("message"))[:1200],
                "fix": (_text(rule.get("help")) or _text(rule.get("fullDescription")))[:1200],
            })
    return sorted(cards, key=lambda card: SEVERITIES.index(card["severity"]))


def counts(cards: list[dict[str, str]]) -> dict[str, int]:
    return {severity: sum(card["severity"] == severity for card in cards) for severity in SEVERITIES}


class Shannon:
    """Runs one Shannon job at a time in the background. notify(event, data) tells the Mission board as it goes:
    "shannon_job" when a job starts, changes stage or ends, "shannon_line" for its output."""

    def __init__(self, jobs: JobLog, library: Callable[[str, str], None], notify: Callable[[str, dict], None],
                 key: Callable[[], str | None], home: Path | None = None, platform: str = sys.platform,
                 run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                 popen: Callable[..., Any] = subprocess.Popen, outputs: Path | None = None) -> None:
        self.jobs, self.library, self.notify, self.key = jobs, library, notify, key
        self.home = Path(home or Path.home())
        self._outputs = Path(outputs) if outputs is not None else None
        self.platform, self._run, self._popen = platform, run, popen
        self.process: Any = None
        self.job_id = ""

    @property
    def outputs(self) -> Path:
        """Where simulation reports and the AiSOC ledger go: the vault's outputs/ when Nova gives it, else the
        default vault folder's outputs/."""
        return self._outputs or (self.home / "Documents" / "Second Brain" / "outputs")

    @property
    def projects_folder(self) -> Path:
        return self.home / "Documents" / "Nova Projects"

    def projects(self) -> list[str]:
        folder = self.projects_folder
        skip = {"Reverse engineering", "Security checks"}
        return sorted(path.name for path in folder.iterdir() if path.is_dir() and path.name not in skip) if folder.is_dir() else []

    def _quiet(self) -> dict[str, Any]:
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if self.platform == "win32" else {}

    def _check(self, script: str) -> subprocess.CompletedProcess | None:
        try:
            return self._run(shell(script, self.platform), capture_output=True, text=True, timeout=40, **self._quiet())
        except (OSError, subprocess.TimeoutExpired):
            return None

    def problem(self) -> str:
        """Why Shannon can't run here right now ("" when it can). Takes a few seconds: call it off the main thread."""
        if not self.key():
            return ("Shannon needs a Claude API key (Settings → Claude → API key); Shannon 3.5 doesn't work with a "
                    "Claude plan alone")
        if self.platform == "win32":
            status = self._check("true")
            if status is None or status.returncode != 0:
                return "WSL2 isn't set up: run “wsl --install” in an admin terminal, restart, then open Ubuntu once"
        docker = self._check("docker info >/dev/null 2>&1 && echo ok")
        if docker is None or "ok" not in (docker.stdout or ""):
            return ("Docker isn't running inside WSL: install Docker Desktop, turn on Settings → Resources → WSL "
                    "integration, and start it")
        node = self._check("node --version")
        major = re.match(r"v(\d+)", (node.stdout or "").strip()) if node is not None else None
        if major is None or int(major[1]) < NODE_MAJOR:
            return f"Node.js {NODE_MAJOR} or newer isn't installed inside WSL (in Ubuntu: install nvm, then “nvm install --lts”)"
        return ""

    def _repo(self, project: str) -> Path:
        text = str(project).strip().strip('"')
        path = Path(os.path.expanduser(text)) if text else Path()
        if not path.is_absolute():
            path = self.projects_folder / text
        if not text or not path.is_dir():
            raise ValueError(f"there's no project folder {path}")
        if self.home.resolve() not in path.resolve().parents:
            raise ValueError("Shannon reads only your own project folders (in your user folder)")
        return path

    def start(self, url: str, project: str) -> dict[str, Any]:
        """Starts a job (or ValueError saying why it can't). The readiness check is the caller's (see problem())."""
        if self.process is not None:
            raise ValueError("Shannon is already running a check; stop it first or wait for it")
        target = docker_target(url)
        repo = self._repo(project)
        stamp = datetime.now()
        slug = re.sub(r"[^a-z0-9]+", "-", repo.name.lower()).strip("-")[:30] or "app"
        workspace = f"nova-{slug}-{stamp:%Y%m%d-%H%M}"
        output = self.projects_folder / "Security checks" / f"{repo.name} {stamp:%Y-%m-%d %H%M}"
        output.mkdir(parents=True, exist_ok=True)
        job = self.jobs.add("shannon", title=repo.name, target=target, repo=str(repo), workspace=workspace,
                            output=str(output), stage="", counts={})
        environment = {**os.environ, "ANTHROPIC_API_KEY": self.key() or ""}
        if self.platform == "win32":  # WSL passes on only the variables named here
            environment["WSLENV"] = ":".join(filter(None, (os.environ.get("WSLENV"), "ANTHROPIC_API_KEY/u")))
        script = start_script(target, wsl_path(repo, self.platform), workspace, wsl_path(output, self.platform))
        self.process = self._popen(shell(script, self.platform), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                   env=environment, **self._quiet())
        self.job_id = job["id"]
        self.notify("shannon_job", {"job": job})
        threading.Thread(target=self._follow, args=(job, output), name="NovaShannon", daemon=True).start()
        return job

    def stop(self) -> None:
        process, job = self.process, self.jobs.get(self.job_id)
        if process is None or job is None:
            return
        self.jobs.update(job["id"], stopped=True)
        process.kill()
        self._check(" ".join(shlex.quote(part) for part in ("npx", "-y", PACKAGE, "stop", job["workspace"])))

    # ---------- Simulate attack: Shannon's stages + AiSOC triage, nothing really exploited ----------

    def _sim_target(self, kind: str, value: Any) -> str:
        """The target, validated exactly the way a real Shannon run validates it: a web address must be local
        (docker_target), an app must be the owner's own project folder (_repo), a file must be the owner's own
        file under their user folder. Anything else is refused with the same ValueError."""
        text = " ".join(str(value or "").split())
        if not text:
            raise ValueError("Say what to simulate the attack on: an app, a file, or a local address.")
        if kind == "web":
            return docker_target(text)
        if kind == "app":
            return str(self._repo(text))
        path = Path(os.path.expanduser(text))
        if not path.is_absolute():
            path = self.home / text
        if not path.is_file():
            raise ValueError(f"there's no file {path}")
        if self.home.resolve() not in path.resolve().parents:
            raise ValueError("Simulate only on your own files (in your user folder)")
        return str(path)

    def simulate_attack(self, kind: str, value: Any,
                        rationale_hook: Callable[[dict[str, Any]], str | None] | None = None) -> dict[str, Any]:
        """Runs the scripted attack on the target and feeds every step through AiSOC triage and the ledger.
        Needs no Docker, no API key and no network: nothing is really attacked, installed or sent anywhere. The
        report and the ledger go to outputs/; the job is filed as kind "shannon_simulate" so the screen can show
        it again. Raises ValueError for a target Shannon wouldn't accept."""
        kind = str(kind or "").strip().lower()
        if kind not in SIM_ATTACKS:
            raise ValueError("Pick app, file or web for the simulation.")
        target = self._sim_target(kind, value)
        stamp = datetime.now()
        slug = re.sub(r"[^a-z0-9]+", "-", target.lower()).strip("-")[-40:] or "target"
        base = self.outputs / f"{stamp:%Y-%m-%d %H%M} simulated attack {slug}"
        ledger = aisoc.DecisionLedger(base.with_suffix(".jsonl"))
        job = self.jobs.add("shannon_simulate", title=f"Simulated attack: {target}", target=target,
                            target_kind=kind, counts={})
        ledger.append("nova", "simulate_start", f"{kind} target {target}", "simulation started", job=job["id"])
        alerts: list[dict[str, Any]] = []
        for step in SIM_ATTACKS[kind]:
            line = _sim_line(step)
            alert = {"technique": step["technique"], "target": target, "stage": stage_of(line) or step["stage"],
                     "severity": step["severity"], "landed": step["landed"], "proven": step["proven"],
                     "detail": step["detail"], "fix": step["fix"],
                     "time": stamp.isoformat(timespec="seconds"), "line": line}
            alerts.append(alert)
            ledger.append("shannon", "attack_step", f"{step['technique']} on {target}",
                          f"landed={step['landed']} proven={step['proven']}",
                          stage=alert["stage"], severity=step["severity"])
        incidents = aisoc.fuse_alerts(alerts)
        verdicts: list[dict[str, Any]] = []
        cards: list[dict[str, str]] = []
        by_technique = {}
        for incident in incidents:
            result = aisoc.triage(incident, ledger=ledger, rationale_hook=rationale_hook)
            verdicts.append(result["verdict"])
            by_technique[incident["technique"]] = result["verdict"]
            first = incident["alerts"][0]
            cards.append({"severity": incident["severity"], "kind": incident["technique"],
                          "title": f"{incident['technique']}: {first['detail']}"[:160],
                          "where": target, "proof": first["detail"][:1200], "fix": incident["fix"][:1200]})
        steps = [{**alert, "verdict": by_technique[alert["technique"]]["verdict"],
                  "confidence": by_technique[alert["technique"]]["confidence"],
                  "rationale": by_technique[alert["technique"]]["rationale"],
                  "technique_id": by_technique[alert["technique"]]["technique_id"],
                  "tactic": by_technique[alert["technique"]]["tactic"]} for alert in alerts]
        overall = aisoc.overall_verdict(verdicts)
        ledger.append("aisoc", "triage_done", f"{len(incidents)} incidents from {len(alerts)} steps",
                      overall["verdict"], confidence=overall["confidence"])
        report = self._write_sim_report(base.with_suffix(".md"), target, kind, stamp, steps, overall, ledger.path)
        done = self.jobs.update(job["id"], status="done", stage="report", findings=cards, counts=counts(cards),
                                report=str(report), verdict=overall, ledger=str(ledger.path))
        return {"ok": True, "job": done, "kind": kind, "target": target, "steps": steps,
                "incidents": incidents, "verdict": overall, "report": str(report), "ledger": str(ledger.path)}

    def _write_sim_report(self, path: Path, target: str, kind: str, stamp: datetime, steps: list[dict[str, Any]],
                          overall: dict[str, Any], ledger: Path) -> Path:
        """The simulation's report in outputs/, never replacing an earlier one."""
        self.outputs.mkdir(parents=True, exist_ok=True)
        counter = 1
        while path.exists():
            counter += 1
            path = path.with_name(f"{path.stem} {counter}{path.suffix}")
        lines = [f"# Simulated attack: {target}", "",
                 f"Made by Nova {stamp:%Y-%m-%d %H:%M} — a simulation, not a real attack: no exploit ran, nothing "
                 "was installed and nothing left this PC.", "",
                 f"Target: {target} ({kind})", f"AiSOC verdict: **{overall['verdict']}** "
                 f"(confidence {overall['confidence']}) — {overall['rationale']}", "",
                 "## Steps", ""]
        for step in steps:
            landed = "landed" if step["landed"] else "blocked"
            proven = "proved a hole" if step["proven"] else "proved nothing"
            lines.append(f"- **{step['technique']}** ({step['tactic']} {step['technique_id']}, {step['stage']}, "
                         f"{step['severity']}) — {landed}, {proven}. AiSOC: {step['verdict']} "
                         f"(confidence {step['confidence']}). {step['rationale']}")
            if step["fix"]:
                lines.append(f"  Fix: {step['fix']}")
        lines += ["", f"Decision ledger: {ledger}", ""]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _follow(self, job: dict[str, Any], output: Path) -> None:
        reached = -1
        tail: list[str] = []
        timer = threading.Timer(TIMEOUT_SECONDS, self.process.kill)
        timer.start()
        try:
            for raw in self.process.stdout:
                line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", raw).strip()[:240]  # no terminal colours
                if not line:
                    continue
                tail = [*tail[-79:], line]
                self.notify("shannon_line", {"id": job["id"], "line": line})
                stage = stage_of(line)
                if stage and STAGES.index(stage) > reached:
                    reached = STAGES.index(stage)
                    self.notify("shannon_job", {"job": self.jobs.update(job["id"], stage=stage)})
            code = self.process.wait()
        finally:
            timer.cancel()
            self.process = None
        self.notify("shannon_job", {"job": self._finish(job, output, code, tail)})

    def _finish(self, job: dict[str, Any], output: Path, code: int, tail: list[str]) -> dict[str, Any] | None:
        sarif = next(output.rglob("report.sarif"), None)
        report = next(output.rglob("Security-Assessment-Report.md"), None)
        try:
            cards = findings(json.loads(sarif.read_text(encoding="utf-8"))) if sarif else []
        except (OSError, ValueError):
            cards = []
        stopped = bool((self.jobs.get(job["id"]) or {}).get("stopped"))
        if report is None:
            why = "stopped" if stopped else (tail[-1] if tail else f"Shannon stopped (code {code})")
            return self.jobs.update(job["id"], status="failed", error=why[:300], log=tail[-40:])
        tally = counts(cards)
        self.library(f"Security check {job['title']}",
                     f"App: {job['target']}\nProject: {job['repo']}\nProven holes: "
                     + ", ".join(f"{number} {severity}" for severity, number in tally.items() if number)
                     + f"\nFull report: {report}\n\n" + "\n".join(f"- [{card['severity']}] {card['title']}" for card in cards[:12]))
        return self.jobs.update(job["id"], status="done", stage="report", findings=cards, counts=tally,
                                report=str(report), log=tail[-40:])
