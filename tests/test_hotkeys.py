"""Changing Nova's hotkeys: readable names, and no combo that would fire while you type or clash with the other."""
import unittest
import unittest.mock

import hotkeys


class HotkeyTests(unittest.TestCase):
    """The names Windows shows (a Mac says Control+Option instead: tests.test_mac)."""

    def setUp(self) -> None:
        patcher = unittest.mock.patch.object(hotkeys.sys, "platform", "win32")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_names_read_like_the_keyboard(self) -> None:
        self.assertEqual(hotkeys.label([0x12, 0x11]), "Ctrl+Alt")
        self.assertEqual(hotkeys.label([0x20, 0x10, 0x11]), "Ctrl+Shift+Space")
        self.assertEqual(hotkeys.label([0x77]), "F8")
        self.assertEqual(hotkeys.label([0x1B]), "Esc")

    def test_what_can_and_cannot_be_a_hotkey(self) -> None:
        stop, talk = hotkeys.DEFAULTS["stop"], hotkeys.DEFAULTS["talk"]
        self.assertEqual(hotkeys.check("talk", [0x11, 0x20], [stop]), ([0x11, 0x20], ""))   # Ctrl+Space
        self.assertEqual(hotkeys.check("talk", [0x77], [stop]), ([0x77], ""))               # F8
        self.assertEqual(hotkeys.check("talk", [0x91], [stop]), ([0x91], ""))               # Scroll Lock
        for typing in ([0x41], [0x20], [0x10, 0x41], [0x10]):                             # A, Space, Shift+A, Shift
            keys, problem = hotkeys.check("talk", typing, [stop])
            self.assertEqual(keys, [])
            self.assertIn("type", problem)
        self.assertIn("another hotkey", hotkeys.check("stop", [0x12, 0x11], [talk])[1])
        self.assertEqual(hotkeys.check("stop", [0x13], [talk]), ([0x13], ""))              # Pause stops Nova
        self.assertTrue(hotkeys.check("stop", [1, 2, 3, 4], [talk])[1])                    # four keys
        self.assertTrue(hotkeys.check("stop", "Esc", [talk])[1])                           # not key codes
        self.assertTrue(hotkeys.check("launch", [0x11], [talk])[1])

    def test_the_keep_key_is_checked_against_both_others(self) -> None:
        talk, stop = hotkeys.DEFAULTS["talk"], hotkeys.DEFAULTS["stop"]
        self.assertEqual(hotkeys.DEFAULTS["clip"], [0x78])
        self.assertEqual(hotkeys.label(hotkeys.DEFAULTS["clip"]), "F9")
        self.assertEqual(hotkeys.check("clip", [0x79], [talk, stop]), ([0x79], ""))                    # F10
        self.assertIn("already", hotkeys.check("clip", [0x1B], [talk, stop])[1])                       # Esc is stop
        self.assertIn("includes Ctrl+Alt", hotkeys.check("clip", [0x11, 0x12, 0x53], [talk, stop])[1])  # would also start talking
        self.assertIn("type", hotkeys.check("clip", [0x53], [talk, stop])[1])                          # S alone
        self.assertEqual(hotkeys.check("clip", [0x11, 0x10, 0x53], [talk, stop])[1], "")               # Ctrl+Shift+S is fine

    def test_yes_and_no_keys(self) -> None:
        self.assertEqual((hotkeys.label(hotkeys.DEFAULTS["yes"]), hotkeys.label(hotkeys.DEFAULTS["no"])), ("F8", "F10"))
        others = [keys for which, keys in hotkeys.DEFAULTS.items() if which != "yes"]
        self.assertEqual(hotkeys.check("yes", [0x76], others), ([0x76], ""))      # F7
        self.assertIn("already", hotkeys.check("yes", [0x79], others)[1])          # F10 is "no"
        self.assertIn("type", hotkeys.check("no", [0x4E], others)[1])             # N alone would fire while typing


if __name__ == "__main__":
    unittest.main()
