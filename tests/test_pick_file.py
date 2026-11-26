"""The Browse buttons in Rea and Shannon: the native file window returns the picked path (or nothing when the
owner cancels), so the target box fills itself instead of the owner typing a path."""
from __future__ import annotations

import sys
import tempfile
import types
import unittest
import unittest.mock
from pathlib import Path

try:
    import tkinter  # noqa: F401  (Windows has it; a bare Linux Python may not)
    import tkinter.filedialog  # noqa: F401
except ImportError:
    filedialog = types.SimpleNamespace(askopenfilename=None, askdirectory=None)
    sys.modules["tkinter"] = types.SimpleNamespace(Tk=object, TclError=Exception, filedialog=filedialog)
    sys.modules["tkinter.filedialog"] = filedialog

try:
    import dashboard  # noqa: E402
except ImportError:  # optional deps (e.g. httpx) missing in a bare checkout; the PC install has them
    dashboard = None  # type: ignore[assignment]


@unittest.skipIf(dashboard is None, "dashboard needs its optional dependencies installed")
class PickFileTests(unittest.TestCase):
    def setUp(self) -> None:
        home = Path(tempfile.mkdtemp())
        (home / "Documents" / "Nova Projects").mkdir(parents=True)
        self.app = types.SimpleNamespace(
            shannon=types.SimpleNamespace(projects_folder=home / "Documents" / "Nova Projects"))

    def test_rea_pick_file_returns_the_clicked_file(self) -> None:
        with unittest.mock.patch("tkinter.filedialog.askopenfilename", return_value="/home/me/shop/app.py"):
            result = dashboard.AlfredApp._act_rea_pick(self.app, {"kind": "file"})
        self.assertEqual(result, {"ok": True, "picked": True, "path": "/home/me/shop/app.py"})

    def test_rea_pick_folder_returns_the_clicked_folder(self) -> None:
        with unittest.mock.patch("tkinter.filedialog.askdirectory", return_value="/home/me/shop"):
            result = dashboard.AlfredApp._act_rea_pick(self.app, {"kind": "folder"})
        self.assertEqual(result, {"ok": True, "picked": True, "path": "/home/me/shop"})

    def test_rea_pick_cancelled_is_not_an_error(self) -> None:
        with unittest.mock.patch("tkinter.filedialog.askopenfilename", return_value=""):
            result = dashboard.AlfredApp._act_rea_pick(self.app, {"kind": "file"})
        self.assertEqual(result, {"ok": True, "picked": False, "path": ""})

    def test_shannon_pick_app_starts_in_nova_projects(self) -> None:
        with unittest.mock.patch("tkinter.filedialog.askdirectory", return_value="/home/me/Documents/Nova Projects/shop") as pick:
            result = dashboard.AlfredApp._act_shannon_pick(self.app, {"kind": "app"})
        self.assertEqual(pick.call_args.kwargs["initialdir"], str(self.app.shannon.projects_folder))
        self.assertEqual(result, {"ok": True, "picked": True, "path": "/home/me/Documents/Nova Projects/shop"})

    def test_pick_actions_are_registered(self) -> None:
        self.assertIn("rea_pick", dashboard.AlfredApp.ACTIONS)
        self.assertIn("shannon_pick", dashboard.AlfredApp.ACTIONS)


if __name__ == "__main__":
    unittest.main()
