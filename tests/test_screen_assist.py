"""Screen assist logic that runs anywhere: element numbering, key parsing, approval policy, memory."""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import Agent
from memory import Memory
from screen_assist import ScreenSession, risky_step, send_keys_spec
from screen_elements import number_elements
from tools import execute_tool

NOTEPAD = [
    {"role": "Button", "name": "Save", "rect": [100, 50, 180, 74]},
    {"role": "Edit", "name": "", "rect": [10, 100, 900, 600]},
]


class FakeAssist:
    """Stands in for the helper process; records every request."""

    def __init__(self, *snapshots: list[dict]) -> None:
        self.snapshots = list(snapshots)
        self.requests: list[dict] = []
        self.pages: list[str] = ["(nothing)"]  # what each "text" read returns, one string per page down

    def request(self, payload: dict, timeout: float = 10.0) -> dict:
        self.requests.append(payload)
        if payload["cmd"] == "snapshot":
            elements = self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0]
            return {"ok": True, "window_title": "Untitled - Notepad", "elements": elements}
        if payload["cmd"] == "type":
            return {"ok": True, "value": payload["text"]}
        if payload["cmd"] == "text":
            page = self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]
            return {"ok": True, "window_title": "Essay - Browser", "text": page}
        return {"ok": True}

    def commands(self) -> list[str]:
        return [request["cmd"] for request in self.requests]


def session_for(assist: FakeAssist) -> ScreenSession:
    session = ScreenSession(assist, lambda: 4242, threading.Event())
    session.observe()
    return session


@patch("screen_assist.time.sleep", lambda _seconds: None)
class ScreenToolPolicyTests(unittest.TestCase):
    def test_numbering_drops_noise_and_keeps_reading_order(self) -> None:
        elements = number_elements([
            {"role": "Edit", "name": "", "rect": [10, 100, 900, 600]},
            {"role": "Button", "name": "Save", "rect": [100, 50, 180, 74]},
            {"role": "Button", "name": "", "rect": [200, 50, 280, 74]},       # unnamed button
            {"role": "Button", "name": "Tiny", "rect": [0, 0, 3, 3]},         # too small
            {"role": "Button", "name": "Again", "rect": [100, 50, 180, 74]},  # same box
            {"role": "Pane", "name": "Body", "rect": [0, 0, 999, 999]},       # not a control
        ])
        self.assertEqual([(item.element_id, item.role, item.name) for item in elements],
                         [(1, "button", "Save"), (2, "edit", "")])

    def test_key_combos(self) -> None:
        self.assertEqual(send_keys_spec("ctrl+shift+t"), "^+t")
        self.assertEqual(send_keys_spec("Enter"), "{ENTER}")
        self.assertEqual(send_keys_spec("win"), "{VK_LWIN}")
        self.assertEqual(send_keys_spec("win+r"), "{VK_LWIN down}r{VK_LWIN up}")
        self.assertEqual(send_keys_spec("cmd+l"), "^l")
        self.assertEqual(send_keys_spec("alt+f4"), "%{F4}")
        for bad in ("", "ctrl+", "hyper+a", "ctrl+notakey", "{ENTER}", "^c"):
            with self.assertRaises(ValueError, msg=bad):
                send_keys_spec(bad)

    def test_drawing_needs_no_approval(self) -> None:
        assist = FakeAssist(NOTEPAD)
        result = execute_tool("point_at", {"element": 1, "label": "Save"}, None, lambda *_: self.fail("asked"), session_for(assist))
        self.assertIn("Pointed at", result)
        self.assertEqual(assist.requests[-1]["rect"], (100, 50, 180, 74))

    def test_declined_click_does_nothing(self) -> None:
        assist = FakeAssist(NOTEPAD)
        asked: list[dict] = []
        result = execute_tool("click", {"element": 1}, None, lambda _name, arguments: asked.append(arguments) or False,
                              session_for(assist))
        self.assertIn("declined", result)
        self.assertEqual(asked, [{"summary": 'Click button "Save" in "Untitled - Notepad"'}])
        self.assertEqual(assist.commands(), ["snapshot"])

    def test_approved_click_rechecks_the_screen_then_clicks_the_center(self) -> None:
        assist = FakeAssist(NOTEPAD)
        result = execute_tool("click", {"element": 1}, None, lambda *_: True, session_for(assist))
        self.assertEqual(assist.commands(), ["snapshot", "snapshot", "highlight", "click", "snapshot"])
        self.assertEqual((assist.requests[3]["x"], assist.requests[3]["y"], assist.requests[3]["hwnd"]), (140, 62, 4242))
        self.assertIn("Clicked", result)
        self.assertIn("\n\nSCREEN", result)  # the model sees the new state

    def test_control_that_moved_is_not_clicked(self) -> None:
        moved = [{**NOTEPAD[0], "rect": [300, 50, 380, 74]}, NOTEPAD[1]]
        assist = FakeAssist(NOTEPAD, moved)
        result = execute_tool("click", {"element": 1}, None, lambda *_: True, session_for(assist))
        self.assertTrue(result.startswith("Not done: that control moved"))
        self.assertNotIn("click", assist.commands())

    def test_typing_reports_the_read_back_value(self) -> None:
        assist = FakeAssist(NOTEPAD)
        result = execute_tool("type_text", {"element": 2, "text": "hello"}, None, lambda *_: True, session_for(assist))
        self.assertIn("now contains: 'hello'", result)

    def test_unknown_element_and_bad_keys_never_ask(self) -> None:
        session = session_for(FakeAssist(NOTEPAD))
        never = lambda *_: self.fail("approval requested for an invalid action")
        self.assertIn("not on the newest screen", execute_tool("click", {"element": 9}, None, never, session))
        self.assertIn("unknown key", execute_tool("press_keys", {"keys": "ctrl+nope"}, None, never, session))
        self.assertIn("invalid", execute_tool("click", {"element": 1, "x": 5}, None, never, session))

    def test_only_a_step_that_presses_escape_hides_escape_from_the_stop_key(self) -> None:
        calls: list[tuple[bool, bool]] = []
        session = ScreenSession(FakeAssist(NOTEPAD), lambda: 4242, threading.Event(),
                                on_acting=lambda acting, presses_escape=False: calls.append((acting, presses_escape)))
        session.observe()
        execute_tool("press_keys", {"keys": "esc"}, None, lambda *_: True, session)
        execute_tool("click", {"element": 1}, None, lambda *_: True, session)
        self.assertEqual(calls, [(True, True), (False, False), (True, False), (False, False)])

    def test_stopped_turn_does_not_act(self) -> None:
        assist = FakeAssist(NOTEPAD)
        session = session_for(assist)
        session.cancel.set()
        self.assertIn("Stopped", execute_tool("click", {"element": 1}, None, lambda *_: True, session))
        self.assertNotIn("click", assist.commands())


class AgentScreenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.memory = Memory(Path(self.folder.name) / "test.sqlite3")
        self.agent = Agent(model="test", memory=self.memory)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_screen_reaches_the_model_but_never_memory(self) -> None:
        seen: list[list[dict]] = []
        replies = iter([
            {"message": {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "point_at", "arguments": {"element": 1, "label": "Save"}}}]}},
            {"message": {"role": "assistant", "content": "It's the Save button, top left."}},
        ])
        self.agent._chat = lambda messages, tools: seen.append([dict(m) for m in messages]) or next(replies)
        reply = self.agent.ask("where's the save button", lambda *_: False, screen=session_for(FakeAssist(NOTEPAD)))
        self.assertEqual(reply, "It's the Save button, top left.")
        self.assertIn('[1] button "Save"', seen[0][-1]["content"])
        stored = " ".join(message["content"] for message in self.memory.recent_messages(50))
        self.assertNotIn("SCREEN", stored)
        self.assertIn("where's the save button", stored)

    def test_cancelled_turn_never_calls_the_model(self) -> None:
        cancel = threading.Event()
        cancel.set()
        self.agent._chat = lambda *_args, **_kwargs: self.fail("model called after Esc")
        self.assertTrue(self.agent.ask("do it", lambda *_: True, screen=session_for(FakeAssist(NOTEPAD)), cancel=cancel).startswith("Stopped"))


@patch("screen_assist.time.sleep", lambda _seconds: None)
class AutopilotStepsTests(unittest.TestCase):
    def test_what_still_asks_on_autopilot(self) -> None:
        asks = [("click", 'Click button "Pay now" in "Shop"'), ("click", 'Click button "Send" in "Mail"'),
                ("click", 'Click button "Delete" in "Files"'), ("click", 'Click button "Submit" in "Quiz"'),
                ("click", 'Click link "Continue" in "PayPal: Checkout"'),
                ("type_text", 'Type into edit "Card number" in "Shop":\n\n4111'),
                ("type_text", 'Type into edit "Password" in "Sign in":\n\nhunter2'),
                ("press_keys", 'Press shift+delete in "Files"'), ("press_keys", 'Press alt+f4 in "Essay"'),
                ("open_app", "Open powershell"), ("open_app", "Open C:\\Users\\me\\Downloads\\setup.bat"),
                ("open_app", "Open \\\\evil.example\\share\\setup.msi"), ("open_app", "Open C:\\Users\\me\\Downloads\\invoice.scr"),
                ("open_app", "Open C:\\Users\\me\\Downloads\\update.exe"), ("open_app", "Open rundll32 javascript:x")]
        for name, summary in asks:
            self.assertTrue(risky_step(name, summary), summary)

    def test_what_autopilot_just_does(self) -> None:
        free = [("click", 'Click button "Next" in "ArtGuard Setup"'), ("click", 'Click button "Install" in "Setup"'),
                ("click", 'Click link "Download for Windows" in "GitHub - repo"'),
                ("type_text", 'Type into edit "Search" in "Browser":\n\ndelete the password and pay the bank'),
                ("press_keys", 'Press ctrl+l in "Browser"'), ("press_keys", 'Press enter in "Browser"'),
                ("open_app", "Open https://github.com/someone/repo"), ("open_app", "Open notepad")]
        for name, summary in free:
            self.assertEqual(risky_step(name, summary), "", summary)

    def test_scrolling_needs_no_approval_and_uses_the_wheel(self) -> None:
        assist = FakeAssist(NOTEPAD)
        never = lambda *_: self.fail("asked before scrolling")
        self.assertIn("Scrolled down 3", execute_tool("scroll", {"direction": "down"}, None, never, session_for(assist)))
        scroll = next(request for request in assist.requests if request["cmd"] == "scroll")
        self.assertEqual((scroll["clicks"], "x" in scroll, scroll["hwnd"]), (-3, False, 4242))  # window middle, wheel down
        assist = FakeAssist(NOTEPAD)
        execute_tool("scroll", {"direction": "up", "amount": 99, "element": 2}, None, never, session_for(assist))
        scroll = next(request for request in assist.requests if request["cmd"] == "scroll")
        self.assertEqual((scroll["clicks"], scroll["x"], scroll["y"]), (15, 455, 350))  # capped at 15, over the field

    def test_right_and_double_click_and_opening_ask_like_any_step(self) -> None:
        assist = FakeAssist(NOTEPAD)
        asked: list[dict] = []
        approve = lambda _name, details: asked.append(details) or True  # noqa: E731
        execute_tool("click", {"element": 1, "button": "double"}, None, approve, session_for(assist))
        execute_tool("open_app", {"target": " notepad "}, None, approve, session_for(assist))
        self.assertEqual([item["summary"] for item in asked], ['Double-click button "Save" in "Untitled - Notepad"', "Open notepad"])
        self.assertEqual(next(r for r in assist.requests if r["cmd"] == "click")["button"], "double")
        self.assertEqual(next(r for r in assist.requests if r["cmd"] == "open")["target"], "notepad")
        never = lambda *_: self.fail("asked about a bad step")
        self.assertIn("button must be", execute_tool("click", {"element": 1, "button": "middle"}, None, never, session_for(assist)))
        self.assertIn("give a program", execute_tool("open_app", {"target": "  "}, None, never, session_for(assist)))
        self.assertIn("give a program", execute_tool("open_app", {"target": "a\nb"}, None, never, session_for(assist)))

    def test_reading_pages_down_until_nothing_new_then_back_up(self) -> None:
        assist = FakeAssist(NOTEPAD)
        assist.pages = ["Title\nIntro", "Intro\nBody one\nBody two", "Body two\nConclusion", "Body two\nConclusion"]
        text = session_for(assist).read_text()
        self.assertIn('SCREEN TEXT of "Essay - Browser"', text)
        self.assertEqual(text.split("\n")[1:], ["Title", "Intro", "Body one", "Body two", "Conclusion"])
        keys = [request["keys"] for request in assist.requests if request["cmd"] == "keys"]
        self.assertEqual(keys, ["{PGDN}"] * 3 + ["{PGUP}"] * 2)  # the last page down did nothing: two pages back up

    def test_a_long_article_ends_where_the_owner_was(self) -> None:
        assist = FakeAssist(NOTEPAD)
        assist.pages = [f"Paragraph {number}" for number in range(30)]  # longer than Nova reads
        session_for(assist).read_text()
        keys = [request["keys"] for request in assist.requests if request["cmd"] == "keys"]
        self.assertEqual(keys.count("{PGDN}"), keys.count("{PGUP}"))  # every page down is undone

    def test_a_short_window_is_read_once_and_not_scrolled_back(self) -> None:
        assist = FakeAssist(NOTEPAD)
        assist.pages = ["Question 1: What is 6 times 7?"]
        text = session_for(assist).read_text()
        self.assertIn("Question 1", text)
        self.assertEqual([request["keys"] for request in assist.requests if request["cmd"] == "keys"], ["{PGDN}"])


@patch("screen_assist.time.sleep", lambda _seconds: None)
class AgentAutopilotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.agent = Agent(model="test", memory=Memory(Path(self.folder.name) / "test.sqlite3"))

    def tearDown(self) -> None:
        self.folder.cleanup()

    def ask(self, replies: list[dict]) -> tuple[str, list[list[dict]]]:
        seen: list[list[dict]] = []
        queued = iter(replies)
        self.agent._chat = lambda messages, tools: seen.append([dict(m) for m in messages]) or next(queued)
        return self.agent.ask("install it", lambda *_: True, screen=session_for(FakeAssist(NOTEPAD))), seen

    def test_the_prompt_says_whether_to_ask(self) -> None:
        for autopilot, present, absent in ((True, "You are on autopilot", "approves every action"),
                                           (False, "approves every action", "You are on autopilot")):
            self.agent.autopilot = autopilot
            _reply, seen = self.ask([{"message": {"role": "assistant", "content": "ok"}}])
            system = seen[0][0]["content"]
            self.assertIn(present, system)
            self.assertNotIn(absent, system)
            self.assertNotIn("@APPROVAL@", system)
            self.assertIn("call read_screen_text first, without asking", system)

    def test_with_screen_assist_off_nova_says_how_to_turn_it_on(self) -> None:
        seen: list[list[dict]] = []
        self.agent._chat = lambda messages, tools: seen.append([dict(m) for m in messages]) or {"message": {"role": "assistant", "content": "ok"}}
        self.agent.ask("review this homework", lambda *_: True)
        self.assertIn("press Assist at the bottom of Nova", seen[0][0]["content"])

    def test_a_long_job_sends_the_model_only_the_newest_work_and_a_digest_of_the_rest(self) -> None:
        messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "install ArtGuard"}]
        for step in range(100):
            messages += [{"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "click", "arguments": {"element": step}}}]},
                         {"role": "tool", "tool_name": "click", "content": f"Clicked {step}"}]
        sent = Agent._recent_window(messages, turn_start=1)
        self.assertEqual([m["content"] for m in sent[:2]], ["sys", "install ArtGuard"])  # the request always stays
        self.assertLessEqual(len(sent), 2 + 1 + 30)
        self.assertEqual(sent[2]["role"], "system")
        self.assertIn("click(element=", sent[2]["content"])
        self.assertEqual(sent[3]["role"], "assistant")  # cut at a call: no result without its call
        self.assertEqual(sent[-1]["content"], "Clicked 99")
        short = messages[:12]
        self.assertIs(Agent._recent_window(short, turn_start=1), short)  # a short job is sent as it is

    def test_the_same_step_three_times_is_not_run_a_third_time(self) -> None:
        click = {"message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "click", "arguments": {"element": 1}}}]}}
        reply, seen = self.ask([click, click, click, {"message": {"role": "assistant", "content": "I'm stuck on Save."}}])
        self.assertEqual(reply, "I'm stuck on Save.")
        tool_results = [message["content"] for message in seen[-1] if message.get("role") == "tool"]
        self.assertEqual(len(tool_results), 3)
        self.assertTrue(tool_results[0].startswith("Clicked") and tool_results[1].startswith("Clicked"))
        self.assertTrue(tool_results[2].startswith("Not run: you have done this exact step three times"))


if __name__ == "__main__":
    unittest.main()
