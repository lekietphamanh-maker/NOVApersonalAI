"""Keeping what the owner highlighted: the copy, the clipboard change counter, and giving the clipboard back."""
from __future__ import annotations

import sys
import unittest

from selection import MAX_SELECTION, grab_selection


class FakeClipboard:
    def __init__(self, text: str | None) -> None:
        self.text, self.counter, self.writes = text, 1, []

    def read(self) -> str | None:
        return self.text

    def write(self, text: str) -> None:
        self.writes.append(text)
        self.text = text

    def copy_selection(self, selected: str | None):
        def copy() -> None:
            if selected is not None:
                self.text, self.counter = selected, self.counter + 1  # Ctrl+C in the app
        return copy


class GrabSelectionTests(unittest.TestCase):
    def grab(self, clipboard: FakeClipboard, selected: str | None) -> str:
        return grab_selection(clipboard.copy_selection(selected), lambda: clipboard.counter, clipboard.read, clipboard.write,
                              wait=0.2, sleep=lambda _seconds: None)

    def test_the_highlight_comes_back_and_the_owners_clipboard_is_restored(self) -> None:
        clipboard = FakeClipboard("my shopping list")
        self.assertEqual(self.grab(clipboard, "  The key idea is compounding.  "), "The key idea is compounding.")
        self.assertEqual(clipboard.text, "my shopping list")

    def test_nothing_highlighted_means_nothing_kept_and_nothing_touched(self) -> None:
        clipboard = FakeClipboard("my shopping list")
        self.assertEqual(self.grab(clipboard, None), "")
        self.assertEqual((clipboard.text, clipboard.writes), ("my shopping list", []))

    def test_highlighting_the_text_already_on_the_clipboard_still_counts(self) -> None:
        clipboard = FakeClipboard("same words")
        self.assertEqual(self.grab(clipboard, "same words"), "same words")  # the counter moved: it was copied again

    def test_a_picture_on_the_clipboard_is_not_pretended_to_be_text(self) -> None:
        clipboard = FakeClipboard(None)
        self.assertEqual(self.grab(clipboard, "a highlight"), "a highlight")
        self.assertEqual(clipboard.writes, [])  # nothing to give back as text

    def test_a_huge_highlight_is_cut(self) -> None:
        self.assertEqual(len(self.grab(FakeClipboard(""), "x" * (MAX_SELECTION + 500))), MAX_SELECTION)


@unittest.skipUnless(sys.platform == "win32", "the Windows clipboard")
class WindowsClipboardTests(unittest.TestCase):
    def test_text_round_trips_with_unicode_and_the_counter_moves(self) -> None:
        import selection
        selection.write_clipboard_text("old")
        before = selection.clipboard_sequence()
        selection.write_clipboard_text("Chào Nova: học về Obsidian ✓")
        self.assertEqual(selection.read_clipboard_text(), "Chào Nova: học về Obsidian ✓")
        self.assertNotEqual(selection.clipboard_sequence(), before)


if __name__ == "__main__":
    unittest.main()
