"""What the model on this PC is sent: the screen only for questions about it, a small core of tools plus the groups the
words call for, in a stable order, and earlier conversation trimmed to fit its context."""
from __future__ import annotations

import json
import unittest

import tool_selection as pick
import tools
from agent import CALENDAR_TOOLS, DRIVE_TOOLS

EVERYTHING = [*tools.TOOLS, *tools.GENERAL_TOOLS, *tools.PERSONAL_TOOLS, *tools.LOCATION_TOOLS, *tools.SECOND_BRAIN_TOOLS,
              tools.TV_TOOL, tools.LIBRARY_TOOL, tools.NEWS_TOOL, *tools.SKILL_TOOLS, *CALENDAR_TOOLS, *DRIVE_TOOLS,
              tools.CLAUDE_TOOL, *tools.GMAIL_TOOLS]


def names(selected: list[dict]) -> set[str]:
    return {tool["function"]["name"] for tool in selected}


class ScreenTests(unittest.TestCase):
    def test_only_questions_about_the_screen_read_it(self) -> None:
        for said in ("review this homework", "click the save button", "what's on my screen", "how do I export in excel",
                     "summarize this article", "help me fill in this form", "open notepad and type hello"):
            self.assertTrue(pick.about_the_screen(said), said)
        for said in ("set a timer for 10 minutes", "what's the weather tomorrow", "any new mail?",
                     "explain quantum computing", "remind me at 5 to call mom", "who won the game last night"):
            self.assertFalse(pick.about_the_screen(said), said)


class ToolTests(unittest.TestCase):
    def test_a_small_core_and_the_groups_asked_for(self) -> None:
        plain = names(pick.for_question("tell me a joke", EVERYTHING))
        self.assertEqual(plain, set(pick.CORE))
        mail = names(pick.for_question("draft a reply to Ana's email", EVERYTHING))
        self.assertTrue({"draft_mail", "read_mail"} <= mail)
        self.assertNotIn("drive_read", mail)
        world = names(pick.for_question("what's happening in the world today", EVERYTHING))
        self.assertTrue({"world", "news", "calendar_events"} <= world)
        screen = names(pick.for_question("click save", [*EVERYTHING, *tools.SCREEN_TOOLS], screen=True))
        self.assertTrue({"click", "type_text", "scroll"} <= screen)

    def test_every_tool_can_reach_the_model_on_this_pc(self) -> None:
        import tool_registry
        reachable = set(pick.CORE) | {name for group, _words in pick.GROUPS for name in group}
        screen = {tool["function"]["name"] for tool in tools.SCREEN_TOOLS}
        self.assertEqual(tool_registry.names() - screen - reachable, set())  # a tool in no group never reaches it
        self.assertIn("network", names(pick.for_question("how fast is my internet?", EVERYTHING + tools.GENERAL_TOOLS)))
        self.assertIn("trading", names(pick.for_question("scan the market for day trade setups", EVERYTHING + tools.GENERAL_TOOLS)))
        self.assertNotIn("network", names(pick.for_question("I'm typing a shopping list", EVERYTHING + tools.GENERAL_TOOLS)))

    def test_far_less_to_read_and_a_stable_order(self) -> None:
        everything = len(json.dumps(EVERYTHING)) // 4
        core = len(json.dumps(pick.for_question("tell me a joke", EVERYTHING))) // 4
        self.assertLess(core, everything / 3)  # about 1,200 tokens instead of 6,000
        chosen = pick.for_question("email and calendar", EVERYTHING)
        self.assertEqual(chosen, [tool for tool in EVERYTHING if tool in chosen])  # the order they were offered in

    def test_history_fits_and_starts_with_the_owner(self) -> None:
        history = [{"role": "user", "content": "a" * 3000}, {"role": "assistant", "content": "b" * 3000},
                   {"role": "user", "content": "c" * 2000}, {"role": "assistant", "content": "d" * 2000},
                   {"role": "user", "content": "now"}]
        kept = pick.fit(history, 6000)
        self.assertEqual([message["content"][0] for message in kept], ["c", "d", "n"])
        self.assertEqual(pick.fit(history[-1:], 10), history[-1:])  # the request always stays


if __name__ == "__main__":
    unittest.main()
