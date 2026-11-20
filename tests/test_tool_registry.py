"""The tool registry: every tool a brain can be offered has something that runs it, names never clash, arguments are
checked against the definition before a tool runs, and an unknown service name fails loudly."""
from __future__ import annotations

import unittest

import tool_registry
import tools
from agent import CALENDAR_TOOLS, DRIVE_TOOLS


class RegistryTests(unittest.TestCase):
    def test_every_offered_tool_runs_somewhere(self) -> None:
        offered = [*tools.TOOLS, *tools.SCREEN_TOOLS, *tools.GENERAL_TOOLS, tools.CLAUDE_TOOL, *tools.GMAIL_TOOLS,
                   *tools.PERSONAL_TOOLS, *tools.LOCATION_TOOLS, *tools.SECOND_BRAIN_TOOLS, tools.TV_TOOL,
                   tools.LIBRARY_TOOL, tools.NEWS_TOOL, *tools.SKILL_TOOLS, *CALENDAR_TOOLS, *DRIVE_TOOLS]
        names = {tool["function"]["name"] for tool in offered}
        self.assertEqual(sorted(names - tool_registry.names()), [])
        self.assertEqual(len(names), len(offered))  # no two definitions share a name

    def test_a_second_tool_with_the_same_name_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            tool_registry.register([tools.WORLD_TOOL], lambda *_: "another world")

    def test_arguments_are_checked_before_the_tool_runs(self) -> None:
        ran: list = []
        answer = tools.execute_tool("world", {"action": "brief", "planet": "Mars"}, None, lambda *_: True,
                                    world=lambda *args: ran.append(args) or "ran")
        self.assertIn("invalid", answer)
        self.assertEqual(ran, [])
        self.assertIn("not available", tools.execute_tool("no_such_tool", {}, None, lambda *_: True))

    def test_a_misspelled_service_fails_loudly(self) -> None:
        with self.assertRaises(TypeError):
            tools.execute_tool("world", {"action": "show"}, None, lambda *_: True, wrold=lambda *_: "")


if __name__ == "__main__":
    unittest.main()
