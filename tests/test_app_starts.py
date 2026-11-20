"""The real app is built and started (no window): every feature's setup runs in an order that works, and the
screens added lately answer. Catches what unit tests of single features can't, like setup that runs too early."""
from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from unittest import mock


def _tk() -> types.ModuleType:
    """Tk itself where it exists (Windows, the Mac); a stand-in on a Linux Python built without it."""
    try:
        import tkinter
        tkinter.Tk().destroy()
        return tkinter
    except Exception:
        module = types.ModuleType("tkinter")

        class Root:
            def after(self, _ms, _call=None, *_args):
                return "after"

            def __getattr__(self, _name):
                return lambda *args, **kwargs: None
        module.Tk, module.TclError = Root, Exception
        return module


class AppStartsTests(unittest.TestCase):
    def test_the_app_starts_and_the_new_screens_answer(self) -> None:
        tk = _tk()
        data = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"ALFRED_DATA_DIR": data}), mock.patch.dict(sys.modules, {"tkinter": tk}):
            sys.modules.pop("dashboard", None)
            import dashboard
            root = tk.Tk()
            app = dashboard.AlfredApp(root, {"notices": []})
            try:
                self.assertTrue(app.start(open_window=False))
                for action in ("skills_board", "rea_view", "shannon_view", "knowledge_catalog"):
                    self.assertTrue(app._run_action(action, {}).get("ok"), action)
                board = app._run_action("skills_board", {})
                self.assertGreater(len(board["entries"]), 30)
                job = app.lab_jobs.add("shannon", title="shop", findings=[{"severity": "high", "title": "IDOR"}])
                fixed = app._run_action("shannon_fix", {"id": job["id"], "index": 0, "fixed": True})
                self.assertTrue(fixed["job"]["findings"][0]["fixed"])  # solved: the spot calms to green and stays so
                self.assertFalse(app._run_action("shannon_fix", {"id": job["id"], "index": 5, "fixed": True})["ok"])
                self._advance_mode(app)
                app._run_action("lab_view", {"view": "shannon", "open": True})
                sent: list = []
                with mock.patch.object(app.ui, "emit", sent.append), \
                        mock.patch.object(type(app.ui), "clients", new_callable=mock.PropertyMock, return_value=1):
                    app._run_gesture("next")  # a swipe moves the shield, not the music
                self.assertEqual(sent, [{"type": "shannon_command", "command": "next"}])
            finally:
                app.closing = True
                app.ui.stop()
                if hasattr(root, "destroy"):
                    try:
                        root.destroy()
                    except Exception:
                        pass
            sys.modules.pop("dashboard", None)


    def _advance_mode(self, app) -> None:
        app._run_action("advance", {"on": True})
        self.assertTrue(app.state["settings"]["advance"])
        board = app._run_action("advance_board", {})
        self.assertEqual({"library", "skills", "counts", "widgets", "apps"} <= board.keys(), True)
        self.assertEqual([item["id"] for item in board["apps"][:3]], ["rea", "shannon", "openproject"])
        app._run_action("advance_widgets", {"widgets": ["pc", "clock", "nonsense", "pc"]})
        self.assertEqual(app.state["settings"]["advance_widgets"], ["pc", "clock"])
        added = app._run_action("app_add", {"name": "My site", "target": "https://klee.dev"})
        self.assertEqual(added["apps"][-1]["name"], "My site")
        self.assertFalse(app._run_action("app_add", {"name": "Bad", "target": "not a thing"})["ok"])
        removed = app._run_action("app_remove", {"id": added["apps"][-1]["id"]})
        self.assertNotIn("My site", [item["name"] for item in removed["apps"]])
        self.assertEqual(app.agent.advance(False), "Advance mode off.")


if __name__ == "__main__":
    unittest.main()
