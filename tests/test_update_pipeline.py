"""Self-update pipeline: step order, retry cap, token gating, dead-code hooks and the push —
all without Windows, a network, Claude Code or git."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import update_pipeline


class RepoTests(unittest.TestCase):
    def test_valid_repo(self) -> None:
        self.assertEqual(update_pipeline.valid_repo("lekietphamanh-maker/NOVApersonalAI"),
                         "lekietphamanh-maker/NOVApersonalAI")
        self.assertIsNone(update_pipeline.valid_repo("not-a-repo"))
        self.assertIsNone(update_pipeline.valid_repo("https://github.com/a/b"))
        self.assertIsNone(update_pipeline.valid_repo(""))

    def test_token_set_never_returns_the_token(self) -> None:
        self.assertTrue(update_pipeline.token_set("ghp_secret"))
        self.assertFalse(update_pipeline.token_set(""))
        self.assertFalse(update_pipeline.token_set("  "))
        self.assertFalse(update_pipeline.token_set(None))


class FixesTests(unittest.TestCase):
    def test_rea_fixes_come_from_the_fit_findings(self) -> None:
        job = {"fit": [{"area": "Voice", "what": "Better hearing", "how": "Raise the pause wait",
                        "improves": "voice"},
                       {"area": "Empty", "what": "", "how": "", "improves": ""}]}
        fixes = update_pipeline.fixes_from_rea_job(job)
        self.assertEqual(len(fixes), 2)
        self.assertEqual(fixes[0]["title"], "Voice")
        self.assertEqual(update_pipeline.fixes_from_rea_job({"fit": []}), [])
        self.assertEqual(update_pipeline.fixes_from_rea_job({}), [])

    def test_shannon_fixes_skip_what_is_already_fixed(self) -> None:
        job = {"findings": [{"title": "Open port", "proof": "port 22 answers", "fix": "Close it",
                             "where": "localhost", "severity": "high", "fixed": False},
                            {"title": "Done", "fix": "Already shut", "fixed": True}]}
        fixes = update_pipeline.fixes_from_shannon_job(job)
        self.assertEqual(len(fixes), 1)
        self.assertEqual(fixes[0]["title"], "Open port")
        self.assertEqual(fixes[0]["how"], "Close it")

    def test_fix_task_lists_every_fix_and_forbids_installing(self) -> None:
        fixes = [{"title": "Close the port", "detail": "port 22 answers", "how": "Close it",
                  "where": "localhost", "severity": "high"}]
        task = update_pipeline.build_fix_task(fixes, "C:\\Nova")
        self.assertIn("Close the port", task)
        self.assertIn("port 22 answers", task)
        self.assertIn("C:\\Nova", task)
        self.assertIn("do not install anything from github", task.lower())

    def test_test_fix_task_carries_the_failures(self) -> None:
        task = update_pipeline.build_test_fix_task("FAILED tests/test_x.py::T::test_y - assert 1 == 2", "C:\\Nova")
        self.assertIn("FAILED tests/test_x.py", task)
        self.assertIn("do not install anything from github", task.lower())


class DeadCodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_unused_import_is_found_and_used_is_not(self) -> None:
        (self.root / "a.py").write_text("import os\nimport json\n\nprint(os.getcwd())\n", encoding="utf-8")
        self.assertEqual(update_pipeline.find_unused_imports(self.root / "a.py"), [(2, "json")])

    def test_from_imports_and_aliases(self) -> None:
        (self.root / "a.py").write_text("from pathlib import Path, PurePath\n\nprint(Path('.'))\n",
                                        encoding="utf-8")
        self.assertEqual(update_pipeline.find_unused_imports(self.root / "a.py"), [(1, "PurePath")])

    def test_init_files_are_left_alone(self) -> None:
        (self.root / "__init__.py").write_text("from .a import thing\n", encoding="utf-8")
        self.assertEqual(update_pipeline.find_unused_imports(self.root / "__init__.py"), [])

    def test_a_name_only_in_a_string_counts_as_used(self) -> None:
        # __all__ re-exports and getattr("name") lookups would break if the import went away.
        (self.root / "a.py").write_text("from .b import thing\n\n__all__ = [\"thing\"]\n", encoding="utf-8")
        self.assertEqual(update_pipeline.find_unused_imports(self.root / "a.py"), [])
        (self.root / "a.py").write_text("import os\n\nprint(getattr(__import__('os'), 'getcwd')())\n", encoding="utf-8")
        self.assertEqual(update_pipeline.find_unused_imports(self.root / "a.py"), [])

    def test_remove_unused_imports_rewrites_only_safe_lines(self) -> None:
        (self.root / "a.py").write_text("import os\nimport json\nfrom pathlib import Path, PurePath\n\nprint(os.getcwd())\nprint(Path('.'))\n",
                                        encoding="utf-8")
        removed = update_pipeline.remove_unused_imports(self.root)
        self.assertEqual(removed, [{"file": "a.py", "names": ["PurePath", "json"]}])
        self.assertEqual((self.root / "a.py").read_text(encoding="utf-8"),
                         "import os\nfrom pathlib import Path\n\nprint(os.getcwd())\nprint(Path('.'))\n")

    def test_a_sole_import_in_a_block_is_left_alone(self) -> None:
        # Removing the only import in a try/except or TYPE_CHECKING block would leave an
        # empty block behind — a SyntaxError, not a cleanup.
        (self.root / "a.py").write_text("try:\n    import readline\nexcept ImportError:\n    pass\n", encoding="utf-8")
        (self.root / "b.py").write_text("from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    import json\n", encoding="utf-8")
        self.assertEqual(update_pipeline.remove_unused_imports(self.root), [])
        self.assertIn("import readline", (self.root / "a.py").read_text(encoding="utf-8"))
        self.assertIn("import json", (self.root / "b.py").read_text(encoding="utf-8"))

    def test_names_used_by_other_modules_are_kept(self) -> None:
        (self.root / "a.py").write_text("import json\n", encoding="utf-8")
        (self.root / "b.py").write_text("from a import json\n\nprint(json.dumps({}))\n", encoding="utf-8")
        (self.root / "c.py").write_text("import a\n\nprint(a.json.dumps({}))\n", encoding="utf-8")
        self.assertEqual(update_pipeline.remove_unused_imports(self.root), [])
        (self.root / "d.py").write_text("from a import *\n", encoding="utf-8")
        self.assertEqual(update_pipeline.remove_unused_imports(self.root), [])

    def test_only_git_changed_files_are_rewritten(self) -> None:
        (self.root / "a.py").write_text("import os\nimport json\n\nprint(os.getcwd())\n", encoding="utf-8")
        (self.root / "b.py").write_text("import os\nimport json\n\nprint(os.getcwd())\n", encoding="utf-8")

        def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(command, 0, stdout=" M a.py\n")

        removed = update_pipeline.remove_unused_imports(self.root, runner=fake_runner)
        self.assertEqual(removed, [{"file": "a.py", "names": ["json"]}])
        self.assertIn("import json", (self.root / "b.py").read_text(encoding="utf-8"))

    def test_generated_and_venv_folders_are_never_rewritten(self) -> None:
        for folder in ("venv", "env", "node_modules", "build", "dist", ".venv", ".hidden"):
            path = self.root / folder / "x.py"
            path.parent.mkdir(parents=True)
            path.write_text("import os\nimport json\n\nprint(os.getcwd())\n", encoding="utf-8")
        self.assertEqual(update_pipeline.remove_unused_imports(self.root), [])

    def test_an_unreadable_file_does_not_kill_the_recheck(self) -> None:
        (self.root / "bad.py").write_bytes(b"import os\n\xff\xfe not utf-8\n")
        (self.root / "a.py").write_text("import os\nimport json\n\nprint(os.getcwd())\n", encoding="utf-8")
        removed = update_pipeline.remove_unused_imports(self.root)
        self.assertEqual(removed, [{"file": "a.py", "names": ["json"]}])


class PytestSummaryTests(unittest.TestCase):
    def test_both_orders(self) -> None:
        self.assertEqual(update_pipeline.parse_pytest_summary("670 passed, 39 skipped in 45s"), (670, 0, 0))
        self.assertEqual(update_pipeline.parse_pytest_summary("20 failed, 670 passed, 39 skipped"), (670, 20, 0))
        self.assertEqual(update_pipeline.parse_pytest_summary("15 failed, 660 passed, 15 errors, 39 skipped"),
                         (660, 15, 15))
        self.assertIsNone(update_pipeline.parse_pytest_summary("collecting..."))


class RunTestsTests(unittest.TestCase):
    def test_a_suite_that_exits_nonzero_without_counts_still_fails(self) -> None:
        # pytest exiting 4 (no tests folder) with empty output must not count as green.
        def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(command, 4, stdout="", stderr="")

        results = update_pipeline.run_tests(Path("."), runner=fake_runner)
        self.assertFalse(results["ok"])
        self.assertGreaterEqual(results["failed"], 1)
        self.assertEqual(results["passed"], 0)

    def test_a_green_run_counts(self) -> None:
        def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            if "pytest" in command:
                return subprocess.CompletedProcess(command, 0, stdout="2 passed in 1s\n")
            return subprocess.CompletedProcess(command, 0, stdout="pass 2\nfail 0\n")

        results = update_pipeline.run_tests(Path("."), runner=fake_runner)
        self.assertTrue(results["ok"])
        self.assertEqual(results["passed"], 4)
        self.assertEqual(results["failed"], 0)


class PushTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_push_without_a_token_says_how_to_make_one(self) -> None:
        result = update_pipeline.push_to_github(self.root, update_pipeline.DEFAULT_REPO, "")
        self.assertFalse(result["ok"])
        self.assertIn("github.com/settings/tokens", result["error"])

    def test_push_refuses_a_folder_that_isnt_a_checkout(self) -> None:
        result = update_pipeline.push_to_github(self.root, update_pipeline.DEFAULT_REPO, "ghp_x")
        self.assertFalse(result["ok"])
        self.assertIn("isn't a git checkout", result["error"])

    def test_dirty_files_lists_what_was_already_there(self) -> None:
        def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(command, 0, stdout=" M a.py\n?? b.py\n")

        self.assertEqual(update_pipeline.dirty_files(self.root, runner=fake_runner), [" M a.py", "?? b.py"])
        self.assertEqual(update_pipeline.dirty_files(
            self.root, runner=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no git"))), [])

    def test_push_refuses_a_remote_that_isnt_his_repo(self) -> None:
        (self.root / ".git").mkdir()
        calls: list[list[str]] = []

        def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="https://github.com/someone-else/other.git\n")

        result = update_pipeline.push_to_github(self.root, update_pipeline.DEFAULT_REPO, "ghp_x", runner=fake_runner)
        self.assertFalse(result["ok"])
        self.assertIn("won't push", result["error"])
        self.assertEqual([call for call in calls if call[:2] == ["git", "push"]], [])

    def test_push_uses_a_temp_credential_file_and_never_leaks_the_token(self) -> None:
        (self.root / ".git").mkdir()
        seen: list[str] = []

        def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            seen.append(" ".join(command))
            if command[:3] == ["git", "remote", "get-url"]:
                return subprocess.CompletedProcess(command, 0,
                    stdout="https://github.com/lekietphamanh-maker/NOVApersonalAI.git\n")
            if command[:2] == ["git", "commit"]:
                return subprocess.CompletedProcess(command, 0, stdout="nothing to commit")
            if command[:2] == ["git", "rev-list"]:
                return subprocess.CompletedProcess(command, 0, stdout="0\n")
            return subprocess.CompletedProcess(command, 0, stdout="")

        result = update_pipeline.push_to_github(self.root, update_pipeline.DEFAULT_REPO, "ghp_secret_token",
                                            runner=fake_runner)
        self.assertTrue(result["ok"])
        self.assertFalse(result["pushed"])  # nothing changed
        self.assertNotIn("ghp_secret_token", " ".join(seen))
        self.assertEqual([call for call in seen if "push" in call], [])  # nothing to push, no push ran

    def test_nothing_to_commit_with_an_unpushed_commit_still_pushes(self) -> None:
        (self.root / ".git").mkdir()
        calls: list[list[str]] = []

        def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            calls.append(command)
            if command[:3] == ["git", "remote", "get-url"]:
                return subprocess.CompletedProcess(command, 0,
                    stdout="https://github.com/lekietphamanh-maker/NOVApersonalAI.git\n")
            if command[:2] == ["git", "commit"]:
                return subprocess.CompletedProcess(command, 0, stdout="nothing to commit")
            if command[:2] == ["git", "rev-list"]:
                return subprocess.CompletedProcess(command, 0, stdout="1\n")
            return subprocess.CompletedProcess(command, 0, stdout="")

        result = update_pipeline.push_to_github(self.root, update_pipeline.DEFAULT_REPO, "ghp_x",
                                                runner=fake_runner)
        self.assertTrue(result["ok"])
        self.assertTrue(result["pushed"])
        pushes = [call for call in calls if "push" in call]
        self.assertEqual(len(pushes), 1)
        self.assertEqual(pushes[0][-2:], ["origin", "main"])

    def test_scrub_removes_the_token(self) -> None:
        self.assertEqual(update_pipeline.scrub("failed with ghp_abc inside", "ghp_abc"),
                         "failed with [token] inside")


class PipelineTests(unittest.TestCase):
    def test_stage_order_and_retry_cap(self) -> None:
        pipe = update_pipeline.Pipeline("shannon", [{"title": "Fix"}], "C:\\Nova", update_pipeline.DEFAULT_REPO)
        self.assertEqual([step["stage"] for step in pipe.steps],
                         ["apply", "recheck", "test", "push", "done"])
        self.assertTrue(pipe.can_retry_tests())
        pipe.note_fix_round()
        pipe.note_fix_round()
        pipe.note_fix_round()
        self.assertFalse(pipe.can_retry_tests())  # three rounds, then it stops
        self.assertEqual(pipe.fix_round, 3)

    def test_state_never_carries_the_token(self) -> None:
        pipe = update_pipeline.Pipeline("rea", [], "C:\\Nova", update_pipeline.DEFAULT_REPO)
        state = json.dumps(pipe.state())
        self.assertNotIn("ghp", state)
        self.assertTrue(pipe.state()["running"] is False)


class ReportTests(unittest.TestCase):
    def test_read_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.md"
            path.write_text("# Full report\n\nEverything.\n", encoding="utf-8")
            self.assertIn("Everything.", update_pipeline.read_report(str(path)))
        with self.assertRaises(ValueError):
            update_pipeline.read_report(str(Path(tmp) / "gone.md"))
        with self.assertRaises(ValueError):
            update_pipeline.read_report("")


if __name__ == "__main__":
    unittest.main()
