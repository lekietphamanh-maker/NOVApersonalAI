"""Shannon (github.com/KeygraphHQ/shannon): an AI pentester that reads a project's source, attacks the running app
and reports only the holes it could actually prove, each with its proof and a fix.

Nova runs the pinned npm package with npx inside WSL2 (Shannon doesn't run on Windows itself; it needs Docker Desktop
with WSL integration), on the owner's own project folder and its running app, and only on this PC or the home network:
it really attacks what it's pointed at. Shannon 3.5 talks to Claude with an API key (a Claude plan isn't enough), and a
full run costs API credit. The stages it reaches light up on the Mission board; report.sarif becomes the cards; the
written report goes to the project's security folder and a Library entry under "Security checks".
"""
from __future__ import annotations

import http.client
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
_SEVERITY_RANK = {severity: index for index, severity in enumerate(SEVERITIES)}
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


# ---------- Attack Nova herself ----------
# The same machinery as Simulate attack (scripted steps, AiSOC triage, ledger, shield, verdict, report), but the
# target is Nova herself: her own code (this repo, derived from this file's own location, never a picked folder)
# and her own running screen (the loopback origin the HUD is served from, handed over by the dashboard once its
# UI server is up). Anything else is refused. Each step is a REAL check against Nova's actual code, and each
# step's detail says what it probed and what it found — and whether the check was live or only read the code.
# AiSOC's table has no prompt-injection or supply-chain entry, so the steps map to the nearest ATT&CK technique
# and the detail names the real attack. Nothing is really exploited and nothing leaves the PC.
NOVA_MARKERS = ("agent.py", "dashboard.py", "ui_server.py", "update_pipeline.py", "shannon_runner.py")

SELF_STEPS: list[dict[str, Any]] = [
    {"technique": "command injection", "stage": "exploit", "severity": "high", "check": "_check_prompt_injection"},
    {"technique": "brute force", "stage": "exploit", "severity": "critical", "check": "_check_ui_token"},
    {"technique": "privilege escalation", "stage": "analysis", "severity": "high", "check": "_check_approval"},
    {"technique": "ssrf", "stage": "validate", "severity": "medium", "check": "_check_ssrf"},
    {"technique": "data exfiltration", "stage": "validate", "severity": "high", "check": "_check_self_update"},
]


def nova_repo_root() -> Path:
    """Nova's own code: the folder this file runs from. Never a picked folder, never a guess."""
    return Path(__file__).resolve().parent


def resolve_self_target(repo: str | Path | None = None, origin: str | None = None,
                        ui_origin: Callable[[], str | None] | None = None) -> tuple[Path, str]:
    """Nova herself, and nothing else: (her repo root, her running loopback origin). A repo must be this
    checkout (the marker files prove it); an origin must be loopback and the one her UI server is actually
    serving. A folder that isn't Nova's code, a non-loopback address or a public URL is refused."""
    root = nova_repo_root()
    if repo is None:
        resolved_repo = root
    else:
        candidate = Path(os.path.expanduser(str(repo))).resolve()
        if candidate != root or not all((candidate / marker).is_file() for marker in NOVA_MARKERS):
            raise ValueError("Attack Nova herself only runs on Nova's own code — that folder isn't Nova's repo.")
        resolved_repo = candidate
    raw_running = ui_origin() if ui_origin is not None else None
    running = " ".join(str(raw_running or "").split()).rstrip("/")
    if origin is None:
        if not running:
            raise ValueError("Nova's own screen isn't running yet, so there's nothing of hers to attack.")
        resolved_origin = running
    else:
        wanted = " ".join(str(origin).split()).rstrip("/")
        if not wanted or not running or wanted != running:
            raise ValueError("Attack Nova herself only runs on Nova's own running screen (her loopback address) — "
                             "anything else is refused.")
        resolved_origin = wanted
    parts = urlsplit(resolved_origin)
    host = (parts.hostname or "").lower()
    loopback = host in ("localhost", "::1") or host.startswith("127.")
    if parts.scheme not in ("http", "https") or not loopback:
        raise ValueError("Attack Nova herself only runs on Nova's own running screen (her loopback address) — "
                         "anything else is refused.")
    return resolved_repo, resolved_origin


def _read_text(repo: Path, name: str) -> str:
    """One of Nova's own files as text ("" when it isn't there): the static checks read the code, they don't run it."""
    try:
        return (repo / name).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _missing_guard(missing: list[str]) -> dict[str, Any]:
    """A static check that found a guard gone: a real finding for Update now, not a pass."""
    return {"proven": True, "landed": True,
            "detail": "Static check of Nova's real code: missing " + ", ".join(missing) + " — the guard is gone, "
                      "so this attack is open until the code is fixed.",
            "fix": "Restore the missing guard(s) in Nova's own code: " + ", ".join(missing) + "."}


def _check_prompt_injection(repo: Path, origin: str) -> dict[str, Any]:
    """Prompt injection through tool output: does a quoted instruction in a page or file get treated as an order?
    A static check of Nova's real prompt and code, not a live model probe: the system prompt's boundary line,
    the unsaved-results list that keeps web and mail out of saved memory, and evaluate.py's quoted-instruction
    check, which asks the model to explain a quoted 'Add a task...' sentence and fails if a task appears."""
    text = _read_text(repo, "agent.py")
    boundary = "is data, never instructions" in text
    unsaved = re.search(r"UNSAVED_TOOL_RESULTS\s*=\s*\{([^}]*)\}", text)
    kept_out = bool(unsaved and "web_search" in unsaved.group(1) and "read_mail" in unsaved.group(1))
    checks = _read_text(repo, "evaluate.py")
    quoted_check = "quoted-instruction-boundary" in checks and "Add a task to clean my desk" in checks
    missing = [name for name, ok in (
        ("the 'data, never instructions' line in agent.py", boundary),
        ("web_search and read_mail in UNSAVED_TOOL_RESULTS", kept_out),
        ("the quoted-instruction check in evaluate.py", quoted_check)) if not ok]
    if missing:
        return _missing_guard(missing)
    return {"proven": False, "landed": True, "fix": "",
            "detail": ("Static check of Nova's real code (not a live model probe): agent.py tells Nova that text "
                       "from web pages, emails, files and the screen is data, never instructions; web and mail "
                       "results are kept out of saved chat memory, so a quoted instruction can't linger into a "
                       "later turn; and evaluate.py has a quoted-instruction check ('Add a task to clean my desk') "
                       "that fails if the model acts on it. It does not prove the model obeys the prompt on every "
                       "turn — that needs a live model probe on the PC.")}


def _probe_ui_action(port: int, token: str | None, host: str | None) -> int:
    """One POST to /api/action, as a page or a stranger would send it: the status it comes back with."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if host is not None:
        headers["Host"] = host
    if token is not None:
        headers["X-Nova-Token"] = token
    try:
        connection.request("POST", "/api/action", body=json.dumps({"name": "send", "args": {}}), headers=headers)
        return connection.getresponse().status
    finally:
        connection.close()


def _check_ui_token(repo: Path, origin: str, server_factory: Callable[[], Any] | None = None) -> dict[str, Any]:
    """The UI server token: does /api/action demand the token and a loopback host? A LIVE probe, against a fresh
    UiServer built from Nova's own ui_server.py (the same class the HUD uses), not the dashboard's live one:
    a wrong token, no token, the right token from a non-loopback host, and the right token from loopback."""
    if server_factory is None:
        try:
            from ui_server import UiServer
        except Exception as exc:  # noqa: BLE001 - a server that can't start is a check that can't run, not a hole
            return {"proven": False, "landed": False, "fix": "",
                    "detail": f"Could not run this check: Nova's ui_server couldn't be started here ({exc}). "
                              "This is not a pass — it needs a human look on the PC."}
        server_factory = lambda: UiServer(on_action=lambda name, args: {"ok": True}, snapshot=lambda: {})
    try:
        server = server_factory()
        server.start(port=0)
    except Exception as exc:  # noqa: BLE001 - same: the check couldn't run
        return {"proven": False, "landed": False, "fix": "",
                "detail": f"Could not run this check: Nova's UI server couldn't be started here ({exc}). "
                          "This is not a pass — it needs a human look on the PC."}
    try:
        port = urlsplit(server.url).port or 0
        token = server.token
        random_token = server_factory().token != token
        wrong = _probe_ui_action(port, "wrong-token", None)
        missing = _probe_ui_action(port, None, None)
        foreign = _probe_ui_action(port, token, "evil.example:80")
        good = _probe_ui_action(port, token, None)
    except Exception as exc:  # noqa: BLE001 - the probe itself broke; say so, don't call it a pass
        return {"proven": False, "landed": False, "fix": "",
                "detail": f"Could not run this check: the probe broke ({exc}). "
                          "This is not a pass — it needs a human look on the PC."}
    finally:
        server.stop()
    wrong_answers = [f"a wrong token was answered {wrong} instead of 401" if wrong != 401 else "",
                     f"no token was answered {missing} instead of 401" if missing != 401 else "",
                     f"the right token from a non-loopback host was answered {foreign} instead of 403"
                     if foreign != 403 else "",
                     f"the right token from loopback was answered {good} instead of 200" if good != 200 else "",
                     "the token is the same on every run instead of random" if not random_token else ""]
    wrong_answers = [answer for answer in wrong_answers if answer]
    if wrong_answers:
        return {"proven": True, "landed": True,
                "detail": "Live probe on Nova's own UiServer code: " + "; ".join(wrong_answers) + ".",
                "fix": "Make /api/action in ui_server.py demand the per-run token (hmac.compare_digest against "
                       "X-Nova-Token) and a loopback Host, as test_ui_server.py expects."}
    return {"proven": False, "landed": True, "fix": "",
            "detail": ("Live probe on Nova's own UiServer code (a fresh server started here, the same class the "
                       "HUD uses — not the dashboard's live one): a wrong token got 401, no token got 401, the "
                       "right token from a non-loopback host got 403, and the right token from loopback got "
                       "through (200). The token is random per run. The probe never touched the dashboard's "
                       "live server.")}


def _check_approval(repo: Path, origin: str) -> dict[str, Any]:
    """Unauthorised actions: does Nova ask before installing code, sending or deleting? A static check of the
    real approval path — the prompt line, the dashboard's ask-and-wait, and the install rule in discover.py."""
    agent = _read_text(repo, "agent.py")
    dashboard = _read_text(repo, "dashboard.py")
    discover = _read_text(repo, "discover.py")
    tools = _read_text(repo, "tools.py")
    missing = [name for name, ok in (
        ("agent.py asking before anything that saves, changes, searches or sends",
         "asks the user before anything that saves, changes, searches or sends" in agent),
        ("dashboard._confirm_action asking and waiting for yes or no",
         "_confirm_action" in dashboard and "_ask_and_wait" in dashboard),
        ("discover.py: Nova asks the owner before installing code from GitHub",
         "before installing any code from GitHub" in discover),
        ("tools.py: screen actions go through the owner's approval", "owner's approval" in tools)) if not ok]
    if missing:
        return _missing_guard(missing)
    return {"proven": False, "landed": True, "fix": "",
            "detail": ("Static check of the real approval path: agent.py says the program asks the user before "
                       "anything that saves, changes, searches or sends; dashboard._confirm_action asks out loud "
                       "or in a pop-up and waits for yes, no, Esc or a timeout; and discover.py says Nova asks "
                       "the owner before installing any code from GitHub. On autopilot the owner has already said "
                       "yes to every step, so no per-action question is asked — that is the owner's choice, not "
                       "a bypass; with autopilot off, each action is asked.")}


def _check_ssrf(repo: Path, origin: str) -> dict[str, Any]:
    """SSRF: can Nova be talked into fetching an arbitrary URL? A static check of the real fetch paths — the web
    search's one fixed address, the tools (no fetch-a-URL tool), and the agent's own fetches to local Ollama."""
    search = _read_text(repo, "web_search.py")
    urls = set(re.findall(r"https?://[^\s\"'<>]+", search))
    only_duckduckgo = urls == {"https://html.duckduckgo.com/html/"}
    tools = _read_text(repo, "tools.py")
    web_tool = re.search(r"def execute_web_tool\(([^)]*)\)", tools)
    no_fetch_tool = "urlopen" not in tools and "requests." not in tools and bool(web_tool and "approve" in web_tool.group(1))
    agent = _read_text(repo, "agent.py")
    local_ollama = "must be a plain local URL" in agent
    missing = [name for name, ok in (
        ("web_search.py fetching only DuckDuckGo's fixed search page", only_duckduckgo),
        ("no fetch-a-URL tool in tools.py, and the web tool gated by approval", no_fetch_tool),
        ("the agent's own fetches going to a plain local Ollama URL", local_ollama)) if not ok]
    if missing:
        return _missing_guard(missing)
    return {"proven": False, "landed": True, "fix": "",
            "detail": ("Static check of the real fetch paths: web_search.py only ever fetches DuckDuckGo's fixed "
                       "search page (the query goes as POST data, never as a fetched URL); tools.py has no "
                       "fetch-a-URL tool, and the `web` tool only opens an address as a tool call the owner "
                       "approved; the agent's own fetches go to the local Ollama server, whose address must be a "
                       "plain local URL. No live fetch was attempted, and no URL from page text is fetched on "
                       "its own.")}


def _check_self_update(repo: Path, origin: str) -> dict[str, Any]:
    """The self-update pipeline: does it check the remote before pushing? A static check of the real pipeline —
    the remote check and the token in push_to_github, and the dashboard's green-tests gate before the push."""
    pipeline = _read_text(repo, "update_pipeline.py")
    dashboard = _read_text(repo, "dashboard.py")
    missing = [name for name, ok in (
        ("push_to_github refusing a remote that isn't the owner's repo", "repo not in url" in pipeline),
        ("push_to_github needing a token", "if not token" in pipeline),
        ("the pipeline never installing anything from GitHub", "never installs anything FROM GitHub" in pipeline),
        ("the dashboard only pushing after green tests",
         'if results["ok"]' in dashboard and "push_to_github(target, pipe.repo, token)" in dashboard)) if not ok]
    if missing:
        return _missing_guard(missing)
    return {"proven": False, "landed": True, "fix": "",
            "detail": ("Static check of the real pipeline code: push_to_github reads the git remote and refuses "
                       "to push anywhere but the owner's repo, it needs a token, and the dashboard only pushes "
                       "after the test suites are green — a failing suite stops the update instead of pushing. "
                       "The pipeline only ever pushes out; it never installs anything from GitHub. No push was "
                       "attempted.")}


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
    return sorted(cards, key=lambda card: _SEVERITY_RANK[card["severity"]])


def counts(cards: list[dict[str, str]]) -> dict[str, int]:
    return {severity: sum(card["severity"] == severity for card in cards) for severity in SEVERITIES}


class Shannon:
    """Runs one Shannon job at a time in the background. notify(event, data) tells the Mission board as it goes:
    "shannon_job" when a job starts, changes stage or ends, "shannon_line" for its output."""

    def __init__(self, jobs: JobLog, library: Callable[[str, str], None], notify: Callable[[str, dict], None],
                 key: Callable[[], str | None], home: Path | None = None, platform: str = sys.platform,
                 run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                 popen: Callable[..., Any] = subprocess.Popen, outputs: Path | None = None,
                 ui_origin: Callable[[], str | None] | None = None) -> None:
        self.jobs, self.library, self.notify, self.key = jobs, library, notify, key
        self.home = Path(home or Path.home())
        self._outputs = Path(outputs) if outputs is not None else None
        self.platform, self._run, self._popen = platform, run, popen
        # Where Nova's own screen is served from (the dashboard sets this once its UI server is up): the
        # self-attack's origin. A plain attribute so the dashboard can hand it over after this is built.
        self.ui_origin = ui_origin
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

    def _self_target(self, value: Any) -> tuple[Path, str]:
        """Nova herself: her repo root and her running loopback origin. A value may name one of them, but it
        must still be hers — a folder that isn't Nova's code, or an address that isn't her running screen, is
        refused with the same ValueError."""
        text = " ".join(str(value or "").split())
        repo_value = origin_value = None
        if text.startswith(("http://", "https://")):
            origin_value = text
        elif text:
            repo_value = text
        return resolve_self_target(repo_value, origin_value, self.ui_origin)

    def _self_steps(self, repo: Path, origin: str) -> list[dict[str, Any]]:
        """The Nova-specific steps: each check runs against her real code and reports what it probed and found.
        The checks are looked up by name, so a test can stand one in for a broken version."""
        steps = []
        for spec in SELF_STEPS:
            try:
                found = globals()[spec["check"]](repo, origin)
            except Exception as exc:  # noqa: BLE001 - a check that crashes is not a pass and not a hole: say so
                found = {"proven": False, "landed": False, "fix": "",
                         "detail": f"Could not run this check ({exc}). "
                                   "This is not a pass — it needs a human look on the PC."}
            steps.append({"technique": spec["technique"], "stage": spec["stage"], "severity": spec["severity"],
                          "landed": bool(found.get("landed", True)), "proven": bool(found.get("proven")),
                          "detail": str(found.get("detail") or ""), "fix": str(found.get("fix") or "")})
        return steps

    def simulate_attack(self, kind: str, value: Any,
                        rationale_hook: Callable[[dict[str, Any]], str | None] | None = None) -> dict[str, Any]:
        """Runs the scripted attack on the target and feeds every step through AiSOC triage and the ledger.
        Needs no Docker, no API key and no network: nothing is really attacked, installed or sent anywhere. The
        report and the ledger go to outputs/; the job is filed as kind "shannon_simulate" so the screen can show
        it again. Raises ValueError for a target Shannon wouldn't accept. Kind "self" attacks Nova herself:
        her own repo is the job's target, so Update now fixes Nova's own code."""
        kind = str(kind or "").strip().lower()
        if kind not in (*SIM_ATTACKS, "self"):
            raise ValueError("Pick app, file, web or self for the simulation.")
        if kind == "self":
            repo, origin = self._self_target(value)
            target, display = str(repo), f"{repo} (screen {origin})"
            raw_steps = self._self_steps(repo, origin)
        else:
            target = self._sim_target(kind, value)
            display, origin = target, ""
            raw_steps = SIM_ATTACKS[kind]
        stamp = datetime.now()
        slug = re.sub(r"[^a-z0-9]+", "-", target.lower()).strip("-")[-40:] or "target"
        base = self.outputs / f"{stamp:%Y-%m-%d %H%M} simulated attack {slug}"
        ledger = aisoc.DecisionLedger(base.with_suffix(".jsonl"))
        extra = {"origin": origin} if kind == "self" else {}
        job = self.jobs.add("shannon_simulate", title=f"Simulated attack: {display}", target=target,
                            target_kind=kind, counts={}, **extra)
        ledger.append("nova", "simulate_start", f"{kind} target {display}", "simulation started", job=job["id"])
        alerts: list[dict[str, Any]] = []
        for step in raw_steps:
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
            # A self-attack files only what it proved: a passed check is not a hole to fix, so it gets no card
            # and no Update now fix. The other simulations file every step, as before.
            if kind != "self" or incident["proven"]:
                first = incident["alerts"][0]
                cards.append({"severity": incident["severity"], "kind": incident["technique"],
                              "title": f"{incident['technique']}: {first['detail']}"[:160],
                              "where": target, "proof": first["detail"][:1200], "fix": incident["fix"][:1200]})
        steps = []
        for alert in alerts:
            verdict = by_technique[alert["technique"]]
            steps.append({**alert, "verdict": verdict["verdict"], "confidence": verdict["confidence"],
                          "rationale": verdict["rationale"], "technique_id": verdict["technique_id"],
                          "tactic": verdict["tactic"]})
        overall = aisoc.overall_verdict(verdicts)
        ledger.append("aisoc", "triage_done", f"{len(incidents)} incidents from {len(alerts)} steps",
                      overall["verdict"], confidence=overall["confidence"])
        note = ("Update now for this report fixes Nova's own code; Nova needs a restart to pick the fixes up."
                if kind == "self" else "")
        report = self._write_sim_report(base.with_suffix(".md"), display, kind, stamp, steps, overall,
                                        ledger.path, note)
        done = self.jobs.update(job["id"], status="done", stage="report", findings=cards, counts=counts(cards),
                                report=str(report), verdict=overall, ledger=str(ledger.path))
        return {"ok": True, "job": done, "kind": kind, "target": target, "origin": origin, "steps": steps,
                "incidents": incidents, "verdict": overall, "report": str(report), "ledger": str(ledger.path)}

    def _write_sim_report(self, path: Path, target: str, kind: str, stamp: datetime, steps: list[dict[str, Any]],
                          overall: dict[str, Any], ledger: Path, note: str = "") -> Path:
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
                 f"(confidence {overall['confidence']}) — {overall['rationale']}", ""]
        if note:
            lines += [note, ""]
        lines += ["## Steps", ""]
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
                if stage:
                    index = STAGES.index(stage)
                    if index > reached:
                        reached = index
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
