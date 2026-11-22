"""The smoke test waits for the HUD, relaunches the browser once on a flaky first try, then fails."""
from __future__ import annotations

import sys
import types
import unittest

try:
    import tkinter  # noqa: F401  (Windows has it; a bare Linux Python may not)
except ImportError:
    sys.modules["tkinter"] = types.SimpleNamespace(Tk=object, TclError=Exception)

from dashboard import _smoke_retry  # noqa: E402


class SmokeRetryTests(unittest.TestCase):
    def test_connected_is_connected_at_any_time(self) -> None:
        self.assertEqual(_smoke_retry(True, 0, 0), "connected")
        self.assertEqual(_smoke_retry(True, 999, 1), "connected")

    def test_inside_the_window_it_waits(self) -> None:
        self.assertEqual(_smoke_retry(False, 0, 0), "wait")
        self.assertEqual(_smoke_retry(False, 89, 0), "wait")
        self.assertEqual(_smoke_retry(False, 90, 0), "wait")

    def test_past_the_window_it_relaunches_once_then_fails(self) -> None:
        self.assertEqual(_smoke_retry(False, 91, 0), "retry")
        self.assertEqual(_smoke_retry(False, 91, 1), "fail")
        self.assertEqual(_smoke_retry(False, 999, 1), "fail")


if __name__ == "__main__":
    unittest.main()
