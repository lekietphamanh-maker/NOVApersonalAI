"""The new dashboard actions for reports and "Update now", called the way the HUD calls them —
with a fake app, so no Nova, no Claude Code and no network is needed."""
from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path

import dashboard
import update_pipeline


class FakeJobs:
    def __init__(self, jobs: dict[str, dict]) -> None:
        self.jobs = jobs

    def get(self, job_id: str) -> dict | None:
        return self.jobs.get(job_id)


def fake_app(**extra: object) -> types.SimpleNamespace:
    settings: dict = {}
    app = types.SimpleNamespace(
        settings=settings,
        _save_setting=lambda key, value: settings.__setitem__(key, value),
        _update=lambda **kwargs: None,
        lab_jobs=FakeJobs({}),
        deep_work=types.SimpleNamespace(available=False),
        pipeline=None,
        _pipeline_lock=__import__("threading").Lock(),
    )
    for key, value in extra.items():
        setattr(app, key, value)
    # The actions call the app's own helpers; a fake app needs them bound, the way
    # test_hud_controls.py binds _act_approve onto its fake.
    for name in ("_report_text", "_lab_job", "_nova_repo_dir", "_shannon_target_dir", "_start_pipeline",
                 "_github_token", "_run_pipeline", "_run_pipeline_safe"):
        method = getattr(dashboard.AlfredApp, name)
        setattr(app, name, lambda *args, _method=method, **kwargs: _method(app, *args, **kwargs))
    return app


class GithubTokenTests(unittest.TestCase):
    def setUp(self) -> None:
        import secret_store
        secret_store.forget("github_token")

    def tearDown(self) -> None:
        import secret_store
        secret_store.forget("github_token")

    def test_token_is_sealed_and_never_sent_back(self) -> None:
        import secret_store
        app = fake_app()
        result = dashboard.AlfredApp._act_github_token(app, {"token": "ghp_secret_token", "repo": "a/b"})
        self.assertTrue(result["ok"])
        self.assertTrue(result["token_set"])
        self.assertEqual(result["repo"], "a/b")
        self.assertEqual(secret_store.load("github_token"), "ghp_secret_token")
        self.assertNotIn("github_token", app.settings)
        self.assertNotIn("ghp_secret_token", str(result))

    def test_bad_repo_falls_back_to_novas(self) -> None:
        import secret_store
        app = fake_app()
        result = dashboard.AlfredApp._act_github_token(app, {"token": "", "repo": "not a repo"})
        self.assertFalse(result["token_set"])
        self.assertEqual(result["repo"], update_pipeline.DEFAULT_REPO)
        self.assertNotIn("github_token", app.settings)
        self.assertIsNone(secret_store.load("github_token"))

    def test_empty_token_leaves_the_old_one_alone(self) -> None:
        import secret_store
        secret_store.save("github_token", "ghp_old")
        app = fake_app()
        result = dashboard.AlfredApp._act_github_token(app, {"token": "   ", "repo": "a/b"})
        self.assertTrue(result["token_set"])
        self.assertEqual(secret_store.load("github_token"), "ghp_old")
        self.assertNotIn("github_token", app.settings)

    def test_a_plaintext_token_in_settings_is_moved_to_the_store(self) -> None:
        import secret_store
        app = fake_app()
        app.settings["github_token"] = "ghp_legacy"
        self.assertEqual(app._github_token(), "ghp_legacy")
        self.assertEqual(secret_store.load("github_token"), "ghp_legacy")
        self.assertNotIn("github_token", app.settings)


class ReportTextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.report = Path(self.tmp.name) / "report.md"
        self.report.write_text("# Full report\n\nEverything.\n", encoding="utf-8")
        self.job = {"id": "abc", "kind": "rea", "title": "RE App", "report": str(self.report)}
        self.app = fake_app(lab_jobs=FakeJobs({"abc": self.job}))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_rea_report_text_returns_the_whole_report(self) -> None:
        result = dashboard.AlfredApp._act_rea_report_text(self.app, {"id": "abc"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["title"], "RE App")
        self.assertIn("Everything.", result["text"])

    def test_missing_job_raises_like_the_other_report_actions(self) -> None:
        # _lab_job raises ValueError; the dispatcher turns it into {ok: False, ...} for the page.
        with self.assertRaisesRegex(ValueError, "isn't there any more"):
            dashboard.AlfredApp._act_rea_report_text(self.app, {"id": "gone"})

    def test_shannon_report_text(self) -> None:
        job = {"id": "s1", "kind": "shannon", "title": "Shannon", "report": str(self.report)}
        app = fake_app(lab_jobs=FakeJobs({"s1": job}))
        result = dashboard.AlfredApp._act_shannon_report_text(app, {"id": "s1"})
        self.assertTrue(result["ok"])
        self.assertIn("Everything.", result["text"])


class UpdateNowTests(unittest.TestCase):
    def test_status_with_no_pipeline_is_idle(self) -> None:
        app = fake_app()
        status = dashboard.AlfredApp._act_self_update_status(app, {})
        self.assertEqual(status["stage"], "idle")
        self.assertFalse(status["running"])
        self.assertEqual([step["stage"] for step in status["steps"]],
                         ["apply", "recheck", "test", "push", "done"])

    def test_update_now_with_no_upgrades_says_so(self) -> None:
        job = {"id": "abc", "kind": "rea", "title": "RE App", "fit": []}
        app = fake_app(lab_jobs=FakeJobs({"abc": job}))
        result = dashboard.AlfredApp._act_rea_update_now(app, {"id": "abc"})
        self.assertFalse(result["ok"])
        self.assertIn("Nothing to update", result["error"])

    def test_update_now_without_claude_code_says_so_plainly(self) -> None:
        job = {"id": "abc", "kind": "rea", "title": "RE App",
               "fit": [{"area": "Voice", "what": "Hear better", "how": "Wait longer", "improves": "voice"}]}
        app = fake_app(lab_jobs=FakeJobs({"abc": job}))
        result = dashboard.AlfredApp._act_rea_update_now(app, {"id": "abc"})
        self.assertFalse(result["ok"])
        self.assertIn("Claude Code", result["error"])

    def test_a_second_update_waits_for_the_first(self) -> None:
        pipe = update_pipeline.Pipeline("rea", [{"title": "Fix"}], "C:\\Nova", update_pipeline.DEFAULT_REPO)
        pipe.start_stage("apply")
        app = fake_app(pipeline=pipe, deep_work=types.SimpleNamespace(available=True))
        result = dashboard.AlfredApp._start_pipeline(app, "rea", [{"title": "Fix"}], Path("C:\\Nova"))
        self.assertFalse(result["ok"])
        self.assertIn("already running", result["error"])

    def test_starting_reserves_the_pipeline_at_once(self) -> None:
        # A pipeline that is still idle must not let a second "Update now" slip in while
        # the first worker is still checking the tree.
        app = fake_app(deep_work=types.SimpleNamespace(available=True),
                       ui=types.SimpleNamespace(emit=lambda *args, **kwargs: None))
        result = dashboard.AlfredApp._start_pipeline(app, "rea", [{"title": "Fix"}], Path("C:\\Nova"))
        self.assertTrue(result["ok"])
        self.assertEqual(app.pipeline.state()["stage"], "apply")
        self.assertTrue(app.pipeline.state()["running"])
        second = dashboard.AlfredApp._start_pipeline(app, "rea", [{"title": "Fix"}], Path("C:\\Nova"))
        self.assertFalse(second["ok"])
        self.assertIn("already running", second["error"])

    def test_a_failed_recheck_ends_the_pipeline(self) -> None:
        from unittest import mock
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app = fake_app(ui=types.SimpleNamespace(emit=lambda *args, **kwargs: None))
        pipe = update_pipeline.Pipeline("rea", [{"title": "Fix"}], tmp.name, update_pipeline.DEFAULT_REPO)
        fake_claude = types.SimpleNamespace(find=lambda: "claude", run=lambda *args, **kwargs: "applied")
        with mock.patch.object(dashboard, "claude_code", fake_claude):
            with mock.patch.object(update_pipeline, "remove_unused_imports",
                                   side_effect=RuntimeError("boom")):
                app._run_pipeline(pipe)
        self.assertEqual(pipe.state()["stage"], "failed")
        steps = {step["stage"]: step["status"] for step in pipe.state()["steps"]}
        self.assertEqual(steps["recheck"], "failed")
        self.assertIn("boom", pipe.state()["error"])
        self.assertFalse(pipe.state()["running"])

    def test_an_unexpected_worker_failure_still_ends_the_pipeline(self) -> None:
        app = fake_app(ui=types.SimpleNamespace(emit=lambda *args, **kwargs: None))
        pipe = update_pipeline.Pipeline("rea", [{"title": "Fix"}], "C:\\Nova", update_pipeline.DEFAULT_REPO)
        app._run_pipeline = lambda _pipe: (_ for _ in ()).throw(RuntimeError("kaboom"))
        app._run_pipeline_safe(pipe)
        self.assertEqual(pipe.state()["stage"], "failed")
        self.assertIn("Update failed", pipe.state()["error"])
        self.assertFalse(pipe.state()["running"])

    def test_shannon_update_now_without_a_folder_says_so(self) -> None:
        job = {"id": "s1", "kind": "shannon_simulate", "target": "localhost:3000",
               "findings": [{"title": "Hole", "fix": "Close it"}]}
        app = fake_app(lab_jobs=FakeJobs({"s1": job}))
        result = dashboard.AlfredApp._act_shannon_update_now(app, {"id": "s1"})
        self.assertFalse(result["ok"])
        self.assertIn("project folder", result["error"])


if __name__ == "__main__":
    unittest.main()
