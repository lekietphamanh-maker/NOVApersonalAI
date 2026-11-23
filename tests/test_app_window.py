"""Windows Nova opens (file pickers, the browser, apps, the creative window) must show above the HUD.

The Win32 calls live behind app_window._user32(), so these tests run anywhere: a fake user32
records the calls, and the ordering/flag logic is what is really being checked — a window is
pinned topmost for one SetWindowPos and unpinned right after, never left always-on-top.
"""
import unittest
from unittest import mock

import app_window

HWND_TOPMOST, HWND_NOTOPMOST = -1, -2


class FakeUser32:
    """Records the Win32 calls bring_to_front makes, with controllable window state."""

    def __init__(self, iconic: bool = False) -> None:
        self.iconic = iconic
        self.show_window_calls: list[tuple[int, int]] = []
        self.set_window_pos_calls: list[tuple[int, int]] = []
        self.foreground_calls: list[int] = []

    def IsIconic(self, hwnd: int) -> bool:
        return self.iconic

    def ShowWindow(self, hwnd: int, cmd: int) -> bool:
        self.show_window_calls.append((hwnd, cmd))
        return True

    def SetWindowPos(self, hwnd: int, after: int, _x: int, _y: int, _cx: int, _cy: int, flags: int) -> bool:
        self.set_window_pos_calls.append((after, flags))
        return True

    def SetForegroundWindow(self, hwnd: int) -> bool:
        self.foreground_calls.append(hwnd)
        return True


class BringToFrontTests(unittest.TestCase):
    def test_lifts_then_unpins_never_left_topmost(self) -> None:
        fake = FakeUser32()
        with mock.patch.multiple(app_window, _user32=lambda: fake,
                                         is_window=lambda hwnd: bool(hwnd),
                                         is_topmost=lambda hwnd: False):
            self.assertTrue(app_window.bring_to_front(123))
        flags = app_window.SWP_NOMOVE | app_window.SWP_NOSIZE | app_window.SWP_SHOWWINDOW
        self.assertEqual(fake.set_window_pos_calls, [(HWND_TOPMOST, flags), (HWND_NOTOPMOST, flags)])
        self.assertEqual(fake.foreground_calls, [123])

    def test_restores_a_minimised_window_first(self) -> None:
        fake = FakeUser32(iconic=True)
        with mock.patch.multiple(app_window, _user32=lambda: fake,
                                         is_window=lambda hwnd: bool(hwnd),
                                         is_topmost=lambda hwnd: False):
            self.assertTrue(app_window.bring_to_front(77))
        self.assertEqual(fake.show_window_calls, [(77, app_window.SW_RESTORE)])

    def test_a_window_already_topmost_is_left_alone(self) -> None:
        # The smoke test lifts Nova's window and checks it stays topmost; a bring-to-front
        # must never clear a deliberate topmost.
        fake = FakeUser32()
        with mock.patch.multiple(app_window, _user32=lambda: fake,
                                         is_window=lambda hwnd: bool(hwnd),
                                         is_topmost=lambda hwnd: True):
            self.assertTrue(app_window.bring_to_front(55))
        self.assertEqual(fake.set_window_pos_calls, [])
        self.assertEqual(fake.foreground_calls, [])

    def test_a_dead_window_is_ignored(self) -> None:
        fake = FakeUser32()
        with mock.patch.multiple(app_window, _user32=lambda: fake,
                                         is_window=lambda hwnd: False,
                                         is_topmost=lambda hwnd: False):
            self.assertFalse(app_window.bring_to_front(None))
            self.assertFalse(app_window.bring_to_front(999))
        self.assertEqual(fake.set_window_pos_calls, [])

    def test_new_windows_picks_only_what_appeared(self) -> None:
        before = {1, 2, 3}
        after = {1, 2, 3, 4, 5}
        self.assertEqual(sorted(app_window.new_windows(before, after)), [4, 5])
        self.assertEqual(app_window.new_windows(before, after, exclude={4}), [5])
        self.assertEqual(app_window.new_windows(before, before), [])

    def test_snapshot_is_a_set_even_without_win32(self) -> None:
        self.assertIsInstance(app_window.snapshot_windows(), set)

    def test_dialog_on_top_lifts_the_root_then_puts_it_back(self) -> None:
        calls: list[tuple[str, bool]] = []

        class FakeRoot:
            def attributes(self, name: str, value: bool) -> None:
                calls.append((name, value))

        with app_window.dialog_on_top(FakeRoot(), None):
            self.assertEqual(calls, [("-topmost", True)])
        self.assertEqual(calls, [("-topmost", True), ("-topmost", False)])

    def test_dialog_on_top_with_no_root_is_a_plain_no_op(self) -> None:
        with app_window.dialog_on_top(None, None):
            pass
        with app_window.dialog_on_top(None, 999):
            pass


if __name__ == "__main__":
    unittest.main()
