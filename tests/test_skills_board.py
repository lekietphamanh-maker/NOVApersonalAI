"""The Skills board lists every tool Nova has (a new tool must be added to it), with the live status of each skill
and the owner's own skills."""
from __future__ import annotations

import unittest

import skills_board
import tools  # noqa: F401 - registers every tool
import tool_registry


class BoardTests(unittest.TestCase):
    def test_every_tool_is_on_the_board(self) -> None:
        self.assertEqual(tool_registry.names() - skills_board.tools_on_board(), set(), "add the new tool to skills_board.CATALOG")
        self.assertEqual(skills_board.tools_on_board() - tool_registry.names(), set(), "a board entry names a tool that doesn't exist")

    def test_status_and_own_skills(self) -> None:
        status = {"wikipedia": (skills_board.CLOUD, "not downloaded: Claude looks it up online"),
                  "google": (skills_board.SETUP, ""), "screen": (skills_board.OFF, "Windows only for now")}
        board = skills_board.board(status, [{"name": "plan-today", "title": "Plan my day", "says": ["plan my day"],
                                             "schedule": "weekdays", "last": "2026-11-20 08:00"}], {"talk": "Ctrl+Alt"})
        by_name = {entry["name"]: entry for entry in board["entries"]}
        self.assertEqual(by_name["Wikipedia"]["state"], "cloud")
        self.assertEqual(by_name["Gmail"]["note"], "SETTINGS → Connections → Connect Google")  # where, when no note
        self.assertEqual(by_name["Calculator"]["state"], "ready")
        own = by_name["Plan my day"]
        self.assertEqual((own["group"], own["skill"], own["say"]), ("Your skills", "plan-today", ["plan my day"]))
        self.assertEqual(sum(board["counts"].values()), len(board["entries"]))
        self.assertEqual(board["hotkeys"], {"talk": "Ctrl+Alt"})


if __name__ == "__main__":
    unittest.main()
