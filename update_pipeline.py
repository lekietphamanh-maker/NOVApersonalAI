"""Nova's self-update pipeline: apply recommended fixes, recheck the code, run the tests until
green, then push to the owner's GitHub repo. It only ever pushes OUT (to the owner's own repo,
on main, after green tests); it never installs anything FROM GitHub — that still needs the
owner's say-so first, every time.

The pipeline is driven from the REA and Shannon screens ("Update now") and runs on a worker
thread in dashboard.py. Everything in here is pure or takes its runners as arguments, so the
tests can run it without Windows, a network, Claude Code or git.
"""
from __future__ import annotations

import ast
import contextlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

DEFAULT_REPO = "lekietphamanh-maker/NOVApersonalAI"
DEFAULT_BRANCH = "main"
MAX_FIX_ROUNDS = 3
TOKEN_HELP = ("No GitHub token set yet — the last step (push) needs one. Make a classic token: "
              "github.com/settings/tokens → Generate new token (classic) → tick repo → Generate token, "
              "copy it, then paste it in Settings → Self-update · GitHub and click Save. "
              "It stays on this PC only. The fixes and tests below run anyway; only the push waits.")

STAGES = ("apply", "recheck", "test", "push", "done")


def valid_repo(value: Any) -> str | None:
    """owner/repo, or None when it isn't shaped like one."""
    text = str(value or "").strip()
    return text if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", text) else None


def token_set(token: str | None) -> bool:
    """Whether a GitHub token is stored. The token itself is never returned or logged."""
    return bool(str(token or "").strip())


# ---------- the fixes: what "Update now" applies ----------

def fixes_from_rea_job(job: dict[str, Any]) -> list[dict[str, str]]:
    """The upgrades in a REA report: its fit findings (things that would make Nova better).
    Each one is a fix for the pipeline to apply to Nova's own code."""
    fixes = []
    for finding in job.get("fit") or []:
        if not isinstance(finding, dict):
            continue
        fixes.append({"title": str(finding.get("area") or "Fit for Nova"),
                      "detail": str(finding.get("what") or ""),
                      "how": str(finding.get("how") or ""),
                      "improves": str(finding.get("improves") or "")})
    return fixes


def fixes_from_shannon_job(job: dict[str, Any]) -> list[dict[str, str]]:
    """The open holes in a Shannon report: every finding that isn't marked fixed, with its fix."""
    fixes = []
    for finding in job.get("findings") or []:
        if not isinstance(finding, dict) or finding.get("fixed"):
            continue
        fixes.append({"title": str(finding.get("title") or finding.get("kind") or "Finding"),
                      "detail": str(finding.get("proof") or ""),
                      "how": str(finding.get("fix") or ""),
                      "where": str(finding.get("where") or ""),
                      "severity": str(finding.get("severity") or "")})
    return fixes


def build_fix_task(fixes: list[dict[str, str]], target: str) -> str:
    """The job for Claude Code: apply every fix in the target folder, nothing else."""
    lines = [f"Apply these {len(fixes)} fix{'es' if len(fixes) != 1 else ''} to the code in {target}. "
             "Edit the files here only; do not install anything from GitHub or anywhere else, "
             "do not change unrelated code, and do not push anything — Nova pushes afterwards."]
    for number, fix in enumerate(fixes, 1):
        lines.append(f"\n{number}. {fix.get('title', '')}")
        if fix.get("detail"):
            lines.append(f"   What: {fix['detail']}")
        if fix.get("how"):
            lines.append(f"   How: {fix['how']}")
        if fix.get("where"):
            lines.append(f"   Where: {fix['where']}")
        if fix.get("improves"):
            lines.append(f"   Improves: {fix['improves']}")
    lines.append("\nEnd with a short list of what you changed, one line per file.")
    return "\n".join(lines)


def build_test_fix_task(failures: str, target: str) -> str:
    """The job for Claude Code when the tests fail: fix only what the failures name."""
    return (f"The test suite in {target} failed. Fix the failures below and nothing else — do not "
            "install anything from GitHub or anywhere else, and do not push anything.\n\n"
            f"{failures[:4000]}\n\nEnd with a short list of what you changed, one line per file.")


# ---------- the recheck: make the code concise, delete dead code ----------

def find_unused_imports(path: Path, used_elsewhere: set[str] | None = None) -> list[tuple[int, str]]:
    """(line, name) for imports a file never uses. Conservative: __init__.py files are skipped
    (their imports are the public surface), and a name counts as used when it appears anywhere
    as a name or an attribute root. Names in `used_elsewhere` — imported from this file by
    another module, or used as this module's attribute there — count as used too."""
    if path.name == "__init__.py":
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []
    imported: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported[(alias.asname or alias.name).split(".")[0]] = node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if alias.name != "*":
                    imported[alias.asname or alias.name] = node.lineno
    if not imported:
        return []
    used: set[str] = set(used_elsewhere or ())
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            value = node
            while isinstance(value, ast.Attribute):
                value = value.value
            if isinstance(value, ast.Name):
                used.add(value.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # A name only mentioned in a string — __all__, getattr("name"), a lazy import —
            # is still a use: removing it would break the re-export or the lookup.
            words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", node.value))
            used.update(name for name in imported if name in words)
    return sorted((line, name) for name, line in imported.items() if name not in used)


# Folders the recheck never rewrites: virtual environments, installed packages, generated output.
SKIP_DIRS = {".venv", "venv", "env", "node_modules", "build", "dist", "__pycache__"}


def _module_name(root: Path, path: Path) -> str:
    """The dotted name a file is imported under (a.py -> "a", pkg/mod.py -> "pkg.mod")."""
    relative = path.relative_to(root).with_suffix("")
    return ".".join(relative.parts)


def _names_used_from_elsewhere(root: Path, files: list[Path]) -> dict[str, set[str]]:
    """For each file, the names other files take from it: `from a import json` or `a.json`
    in another file means a.py's `import json` is not dead, even though a.py never uses it.
    A star import (`from a import *`) keeps every name in that file."""
    used: dict[str, set[str]] = {}
    parsed: dict[Path, Any] = {}
    for path in files:
        try:
            parsed[path] = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
    for path, tree in parsed.items():
        module = _module_name(root, path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == module:
                if any(alias.name == "*" for alias in node.names):
                    used.setdefault(module, set()).add("*")  # star import: every name may be used there
                else:
                    used.setdefault(module, set()).update(alias.asname or alias.name for alias in node.names)
            elif isinstance(node, ast.Attribute):
                # a.json.dumps in another file means a.py's `import json` is not dead.
                dotted: list[str] = []
                value: Any = node
                while isinstance(value, ast.Attribute):
                    dotted.append(value.attr)
                    value = value.value
                if isinstance(value, ast.Name):
                    dotted.append(value.id)
                    dotted.reverse()
                    full = ".".join(dotted)
                    if full.startswith(module + "."):
                        used.setdefault(module, set()).add(dotted[len(module.split("."))])
    return used


def _sole_statement_lines(tree: Any) -> set[int]:
    """Lines whose import is the only statement in its block. Removing one would leave an
    empty block — `try: import readline / except ImportError: pass` becomes a SyntaxError,
    and so would an `if TYPE_CHECKING:` block. Those imports stay."""
    sole: set[int] = set()
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field, None)
            if isinstance(stmts, list) and len(stmts) == 1 and isinstance(stmts[0], (ast.Import, ast.ImportFrom)):
                sole.add(stmts[0].lineno)
    return sole


def _git_changed_files(root: Path, runner: Callable[..., Any] = subprocess.run) -> list[Path] | None:
    """Python files git reports as changed (modified, staged, untracked), or None when git
    can't tell — a target that isn't a checkout. Renames report the new path."""
    try:
        done = runner(["git", "status", "--porcelain", "--", "*.py"], cwd=str(root), capture_output=True,
                      text=True, encoding="utf-8", errors="replace", timeout=30)
    except Exception:  # noqa: BLE001 - no git means no list, not a crash
        return None
    if (done.returncode or 0) != 0:
        return None
    files: list[Path] = []
    for line in (done.stdout or "").splitlines():
        path = line[3:] if len(line) > 3 else ""
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[-1]
        path = path.strip().strip('"')
        if path.endswith(".py"):
            files.append(root / path)
    return files


def remove_unused_imports(root: Path, runner: Callable[..., Any] = subprocess.run) -> list[dict[str, Any]]:
    """Delete the unused imports under root (Python files only). Only files git reports as
    changed are rewritten — the fixes just applied, plus anything already uncommitted — and
    virtual environments, installed packages and generated folders are never touched. When git
    can't tell (not a checkout), the whole tree is scanned with the same exclusions.
    Returns what changed: one entry per file, with the names removed. A file is only rewritten
    when every unused import on a line can go; a line shared with a used import is left alone,
    and an import that is the only statement in its block is left alone too."""
    git_changed = _git_changed_files(root, runner)
    if git_changed is None:
        files = [path for path in sorted(root.rglob("*.py"))
                 if not (set(path.relative_to(root).parts[:-1]) & SKIP_DIRS)
                 and not any(part.startswith(".") for part in path.relative_to(root).parts[:-1])]
    else:
        files = [path for path in sorted(set(git_changed))
                 if path.is_file() and path.suffix == ".py"
                 and not (set(path.relative_to(root).parts[:-1]) & SKIP_DIRS)]
    used_elsewhere = _names_used_from_elsewhere(root, files)
    removed: list[dict[str, Any]] = []
    for path in files:
        names = used_elsewhere.get(_module_name(root, path))
        if names and "*" in names:
            continue  # another file star-imports this one: every name may be used there
        unused = find_unused_imports(path, names)
        if not unused:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        sole = _sole_statement_lines(tree)
        unused = [(line, name) for line, name in unused if line not in sole]
        if not unused:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        except (OSError, UnicodeError):
            continue  # one unreadable file must not kill the recheck
        by_line: dict[int, list[str]] = {}
        for line, name in unused:
            by_line.setdefault(line, []).append(name)
        changed: dict[str, list[str]] = {}
        new_lines: list[str] = []
        for number, line in enumerate(lines, 1):
            names = by_line.get(number)
            if not names:
                new_lines.append(line)
                continue
            stripped = line.strip()
            if stripped.startswith("import ") and "," not in stripped and len(names) == 1:
                changed.setdefault(str(path.relative_to(root)), []).extend(names)
                continue  # the whole line goes
            if stripped.startswith("from ") and " import " in stripped:
                head, tail = stripped.split(" import ", 1)
                kept = [item.strip() for item in tail.split(",") if item.strip() and item.strip().split()[0] not in names]
                if kept and len(kept) < len(tail.split(",")):
                    new_lines.append(f"{head} import {', '.join(kept)}\n")
                    changed.setdefault(str(path.relative_to(root)), []).extend(names)
                    continue
            new_lines.append(line)  # a shared line we can't safely trim: leave it
        if changed:
            try:
                path.write_text("".join(new_lines), encoding="utf-8")
            except (OSError, UnicodeError):
                continue  # one unwritable file must not kill the recheck
            removed.append({"file": str(path.relative_to(root)), "names": sorted(set(sum(changed.values(), [])))})
    return removed


# ---------- the tests ----------

def find_test_runners() -> dict[str, list[str] | None]:
    """How to run each suite on this PC (None when the runner isn't here)."""
    python = sys.executable or shutil.which("python") or shutil.which("py")
    return {"pytest": [python, "-m", "pytest", "tests", "-q"] if python else None,
            "node": [shutil.which("node"), "--test", "tests"] if shutil.which("node") else None}


def parse_pytest_summary(output: str) -> tuple[int, int, int] | None:
    """(passed, failed, errored) from a pytest -q tail, or None when it didn't get that far.
    Either order works ("670 passed, 20 failed" and "20 failed, 670 passed")."""
    counts = {word: int(number) for number, word in re.findall(r"(\d+) (passed|failed|error)", output)}
    if "passed" not in counts and "failed" not in counts:
        return None
    return counts.get("passed", 0), counts.get("failed", 0), counts.get("error", 0)


def run_tests(repo_dir: Path, runner: Callable[..., Any] = subprocess.run,
              timeout: int = 20 * 60) -> dict[str, Any]:
    """Run the suites that can run here. Green means every suite that ran passed; a suite with
    no runner is skipped and named, and a missing pytest means the step fails (never push
    without the tests actually running)."""
    runners = find_test_runners()
    results: dict[str, Any] = {"suites": {}, "passed": 0, "failed": 0, "skipped": [], "ok": False}
    if runners["pytest"] is None:
        results["error"] = "No Python with pytest on this PC, so the tests couldn't run — nothing was pushed."
        return results
    for name, command in (("pytest", runners["pytest"]), ("node", runners["node"])):
        if command is None:
            results["skipped"].append(name)
            continue
        try:
            done = runner(command, cwd=str(repo_dir), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
            output = (done.stdout or "") + (done.stderr or "")
        except Exception as exc:  # noqa: BLE001 - a suite that can't start is a failure, not a crash
            results["suites"][name] = {"ok": False, "error": str(exc)[:200]}
            results["failed"] += 1
            continue
        counts = parse_pytest_summary(output) if name == "pytest" else None
        if name == "node":
            node_match = re.search(r"pass (\d+)", output)
            node_fail = re.search(r"fail (\d+)", output)
            counts = (int(node_match.group(1)) if node_match else 0,
                      int(node_fail.group(1)) if node_fail else 0, 0)
        passed, failed, errored = counts or (0, 0, 0)
        results["suites"][name] = {"ok": failed + errored == 0 and (done.returncode or 0) == 0,
                                   "passed": passed, "failed": failed, "errored": errored,
                                   "tail": "\n".join(output.strip().splitlines()[-25:])}
        results["passed"] += passed
        results["failed"] += failed + errored
    suites = results["suites"].values()
    results["ok"] = bool(results["suites"]) and all(suite["ok"] for suite in suites) and not results.get("error")
    if not results["ok"] and results["failed"] == 0:
        results["failed"] = sum(1 for suite in suites if not suite["ok"])
    return results


# ---------- the push: token via a temporary credential file, never in a log ----------

def dirty_files(repo_dir: Path, runner: Callable[..., Any] = subprocess.run) -> list[str]:
    """The uncommitted changes already here, so the summary can say the push carried them too
    instead of silently sweeping them in. [] when the tree is clean or git can't tell."""
    try:
        done = runner(["git", "status", "--porcelain"], cwd=str(repo_dir), capture_output=True,
                      text=True, encoding="utf-8", errors="replace", timeout=30)
    except Exception:  # noqa: BLE001 - no status means no claim about the tree
        return []
    return [line for line in (done.stdout or "").splitlines() if line.strip()]

@contextlib.contextmanager
def _credential_file(repo: str, token: str) -> Iterator[Path]:
    """A git credential-store file (0600) holding the token, deleted on exit."""
    handle, name = tempfile.mkstemp(prefix="nova-git-cred-", suffix=".txt")
    path = Path(name)
    try:
        os.fchmod(handle, stat.S_IRUSR | stat.S_IWUSR)
        os.write(handle, f"https://nova:{token}@github.com\n".encode("utf-8"))
        os.close(handle)
        yield path
    finally:
        try:
            os.close(handle)
        except OSError:
            pass
        try:
            path.unlink()
        except OSError:
            pass


def scrub(text: str, token: str) -> str:
    """The token must never appear in a message, a log or an error."""
    return text.replace(token, "[token]") if token else text


def _unpushed_count(repo_dir: Path, branch: str, runner: Callable[..., Any] = subprocess.run) -> int | None:
    """How many local commits the remote branch doesn't have yet, or None when git can't tell
    (no remote branch yet, or no git at all). None means 'push anyway': pushing with nothing
    new is harmless, and it is the only way the first push can happen."""
    try:
        done = runner(["git", "rev-list", "--count", f"origin/{branch}..HEAD"], cwd=str(repo_dir),
                      capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except Exception:  # noqa: BLE001 - no count means no claim; push anyway
        return None
    if (done.returncode or 0) != 0:
        return None
    try:
        return int((done.stdout or "").strip())
    except ValueError:
        return None


def push_to_github(repo_dir: Path, repo: str, token: str, branch: str = DEFAULT_BRANCH,
                   runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    """Commit what's changed and push it to the owner's repo on branch. Refuses when the remote
    isn't that repo (never push anywhere else), and never puts the token in its answer."""
    if not token:
        return {"ok": False, "error": "No GitHub token set. " + TOKEN_HELP}
    repo_dir = Path(repo_dir)
    if not (repo_dir / ".git").is_dir():
        return {"ok": False, "error": f"{repo_dir} isn't a git checkout, so there's nothing to push."}
    try:
        remote = runner(["git", "remote", "get-url", "origin"], cwd=str(repo_dir), capture_output=True,
                        text=True, encoding="utf-8", errors="replace", timeout=30)
        url = (remote.stdout or "").strip()
    except Exception as exc:  # noqa: BLE001 - no remote means no push
        return {"ok": False, "error": f"Couldn't read the git remote: {exc}"}
    if repo not in url:
        return {"ok": False,
                "error": f"The remote here is {url or 'not set'} — not {repo}, so Nova won't push to it."}
    try:
        with _credential_file(repo, token) as creds:
            helper = f"store --file={creds}"
            runner(["git", "add", "-A"], cwd=str(repo_dir), capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=60)
            commit = runner(["git", "commit", "-m", "Nova self-update: apply recommended fixes"],
                            cwd=str(repo_dir), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=60)
            if "nothing to commit" in (commit.stdout or "") + (commit.stderr or ""):
                # A failed push last time leaves its commit local; "nothing new" must not
                # report the update as done while that commit is still unpushed.
                unpushed = _unpushed_count(repo_dir, branch, runner)
                if unpushed == 0:
                    return {"ok": True, "pushed": False, "message": "Nothing changed, so there was nothing to push."}
            pushed = runner(["git", "-c", f"credential.helper={helper}", "push", "origin", branch],
                            cwd=str(repo_dir), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=5 * 60)
            if pushed.returncode != 0:
                return {"ok": False, "error": "The push failed: "
                        + scrub(((pushed.stderr or pushed.stdout) or "git push failed").strip().splitlines()[-1][:200], token)}
    except Exception as exc:  # noqa: BLE001 - a push that can't run is a failure, not a crash
        return {"ok": False, "error": f"The push couldn't run: {scrub(str(exc)[:200], token)}"}
    return {"ok": True, "pushed": True, "message": f"Pushed to {repo} on {branch}."}


# ---------- the report file ----------

def read_report(path: str) -> str:
    """The full report text from its file, or a plain error when it isn't there."""
    if not path:
        raise ValueError("That report isn't there any more.")
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ValueError("The report file isn't there any more.") from exc


# ---------- the pipeline's state: step order, retry cap, summary ----------

class Pipeline:
    """The pipeline's state machine: apply -> recheck -> test -> (fix, test, up to 3 rounds) -> push -> done.
    The dashboard drives it; the tests check the order and the cap without running anything."""

    def __init__(self, source: str, fixes: list[dict[str, str]], target: str, repo: str) -> None:
        self.source = source
        self.fixes = fixes
        self.target = target
        self.repo = repo
        self.stage = "idle"
        self.fix_round = 0
        self.steps: list[dict[str, Any]] = [{"stage": stage, "status": "waiting", "detail": ""} for stage in STAGES]
        self.error = ""
        self.summary = ""

    def start_stage(self, stage: str, detail: str = "") -> None:
        self.stage = stage
        for step in self.steps:
            if step["stage"] == stage:
                step["status"] = "running"
                step["detail"] = detail

    def finish_stage(self, stage: str, detail: str = "") -> None:
        for step in self.steps:
            if step["stage"] == stage:
                step["status"] = "done"
                step["detail"] = detail

    def fail(self, stage: str, error: str) -> None:
        self.stage = "failed"
        self.error = error
        for step in self.steps:
            if step["stage"] == stage:
                step["status"] = "failed"
                step["detail"] = error

    def can_retry_tests(self) -> bool:
        """Another fix round is allowed while the cap isn't reached."""
        return self.fix_round < MAX_FIX_ROUNDS

    def note_fix_round(self) -> None:
        self.fix_round += 1
        self.stage = "fix"

    def state(self) -> dict[str, Any]:
        return {"source": self.source, "stage": self.stage, "fix_round": self.fix_round,
                "fixes": len(self.fixes), "target": self.target, "repo": self.repo,
                "steps": [dict(step) for step in self.steps], "error": self.error,
                "summary": self.summary, "running": self.stage not in ("idle", "done", "failed")}

    def finish(self, summary: str) -> None:
        self.stage = "done"
        self.summary = summary
        for step in self.steps:
            if step["status"] == "running":
                step["status"] = "done"
