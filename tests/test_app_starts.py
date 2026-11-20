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
            finally:
                app.closing = True
                app.ui.stop()
                if hasattr(root, "destroy"):
                    try:
                        root.destroy()
                    except Exception:
                        pass
            sys.modules.pop("dashboard", None)


if __name__ == "__main__":
    unittest.main()
