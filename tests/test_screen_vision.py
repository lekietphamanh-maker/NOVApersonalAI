"""Seeing the screen with Claude: each SCREEN goes with a numbered screenshot, only the newest picture and list are
sent, a long job sends only its newest steps, and the routing (Claude when it can, the PC's AI otherwise)."""
from __future__ import annotations

import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import Agent
from cloud_brain import Unavailable
from memory import Memory
from screen_assist import ScreenSession
from screen_vision import OLDER_PICTURE, only_newest_screen, recent_steps, with_screenshot

NOTEPAD = [{"role": "Button", "name": "Save", "rect": [100, 50, 180, 74]},
           {"role": "Edit", "name": "", "rect": [10, 100, 900, 600]}]


class ShootingAssist:
    """The helper: snapshots of Notepad, and a new numbered screenshot each time one is asked for."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.shots = 0

    def request(self, payload: dict, timeout: float = 10.0) -> dict:
        self.requests.append(payload)
        if payload["cmd"] == "snapshot":
            return {"ok": True, "window_title": "Untitled - Notepad", "elements": NOTEPAD}
        if payload["cmd"] == "shot":
            self.shots += 1
            return {"ok": True, "image": f"IMG{self.shots}"}
        return {"ok": True}


def tool_use(name: str, arguments: dict, number: int = 1):
    return types.SimpleNamespace(type="tool_use", id=f"t{number}", name=name, input=arguments)


def reply(*blocks, stop: str = "end_turn"):
    return types.SimpleNamespace(content=list(blocks), stop_reason=stop)


def said(text: str):
    return types.SimpleNamespace(type="text", text=text)


class FakeClaude:
    name = "Claude Sonnet 5.5"

    def __init__(self, *replies) -> None:
        self.replies, self.sent = list(replies), []

    def turn(self, system, messages, tools, on_text, cancel=None):
        self.sent.append({"system": system, "messages": messages, "tools": [tool["name"] for tool in tools]})
        answer = self.replies.pop(0)
        if isinstance(answer, Exception):
            raise answer
        for block in answer.content:
            if block.type == "text":
                on_text(block.text)
        return answer


def pictures(messages: list[dict]) -> list[str]:
    found = []
    for message in messages:
        for block in message["content"] if isinstance(message["content"], list) else []:
            inner = block.get("content") if isinstance(block, dict) and block.get("type") == "tool_result" else [block]
            found += [item["source"]["data"] for item in inner if isinstance(item, dict) and item.get("type") == "image"]
    return found


class BookkeepingTests(unittest.TestCase):
    def test_a_screen_with_its_picture_and_only_the_newest_one_is_sent(self) -> None:
        self.assertEqual(with_screenshot("text", None), [{"type": "text", "text": "text"}])
        messages = [{"role": "user", "content": with_screenshot("do it\n\nSCREEN 0123abcd: [1] button \"Save\"", "IMG1")},
                    {"role": "assistant", "content": [tool_use("click", {"element": 1})]},
                    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                                  "content": with_screenshot("Clicked.\n\nSCREEN 89abcdef: [1] button \"Open\"", "IMG2")}]}]
        sent = only_newest_screen(messages)
        self.assertEqual(pictures(sent), ["IMG2"])
        self.assertEqual(sent[0]["content"][1], OLDER_PICTURE)
        self.assertNotIn('button "Save"', sent[0]["content"][0]["text"])  # its element numbers are stale
        self.assertIn('button "Open"', sent[2]["content"][0]["content"][0]["text"])
        self.assertEqual(pictures(messages), ["IMG1", "IMG2"])  # the originals are untouched

    def test_a_long_job_sends_the_request_and_only_the_newest_steps(self) -> None:
        messages = [{"role": "user", "content": "earlier question"}, {"role": "assistant", "content": "earlier answer"},
                    {"role": "user", "content": with_screenshot("install it", "IMG0")}]
        for step in range(40):
            messages += [{"role": "assistant", "content": [tool_use("click", {"element": step}, step)]},
                         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{step}", "content": "ok"}]}]
        sent = recent_steps(messages, request=2, keep=10)
        self.assertEqual([message["role"] for message in sent[:3]], ["user", "assistant", "user"])
        self.assertEqual(sent[3]["role"], "assistant")  # a tool result never loses its call
        self.assertEqual(len(sent), 3 + 10)
        self.assertIn("35 earlier steps of this job are done", sent[2]["content"][-1]["text"])  # 40 steps, the newest 5 kept
        self.assertIn("click(element=34)", sent[2]["content"][-1]["text"])
        short = messages[:8]
        self.assertIs(recent_steps(short, request=2), short)  # short jobs go as they are


@patch("screen_assist.time.sleep", lambda _seconds: None)
class ClaudeDoesTheScreenJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.agent = Agent(model="test", memory=Memory(Path(self.folder.name) / "test.sqlite3"))
        self.agent.screen_vision, self.agent.autopilot, self.agent.private_topics = True, True, "secrets"
        self.assist = ShootingAssist()
        self.screen = ScreenSession(self.assist, lambda: 4242, threading.Event())
        self.local_asked = False
        self.agent._chat = lambda *_args, **_kwargs: (setattr(self, "local_asked", True)
                                                      or {"message": {"role": "assistant", "content": "local answer"}})

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_claude_sees_each_step_and_drives_the_mouse(self) -> None:
        self.agent.cloud = FakeClaude(reply(said("Saving it. "), tool_use("click", {"element": 1}), stop="tool_use"),
                                      reply(said("Done, it's saved.")))
        answer = self.agent.ask("save this file", lambda *_: True, screen=self.screen)
        self.assertEqual(answer, "Saving it. Done, it's saved.")
        first, second = self.agent.cloud.sent
        self.assertEqual(pictures(first["messages"]), ["IMG1"])  # the request came with a numbered screenshot
        self.assertIn('[1] button "Save"', first["messages"][-1]["content"][0]["text"])
        self.assertIn("You can SEE the screen", first["system"][0]["text"])
        self.assertIn("You are on autopilot", first["system"][0]["text"])
        self.assertIn("click", first["tools"])
        self.assertEqual(pictures(second["messages"]), ["IMG2"])  # after the click: the new picture only
        self.assertIn("click", [request["cmd"] for request in self.assist.requests])
        self.assertFalse(self.local_asked)

    def test_privately_or_without_claude_the_pc_does_it(self) -> None:
        self.agent.cloud = FakeClaude()
        self.assertEqual(self.agent.ask("privately save this file", lambda *_: True, screen=self.screen), "local answer")
        self.agent.cloud, self.local_asked = None, False
        self.assertEqual(self.agent.ask("save this file", lambda *_: True, screen=self.screen), "local answer")
        self.agent.cloud, self.agent.screen_vision = FakeClaude(), False
        self.assertEqual(self.agent.ask("save this file", lambda *_: True, screen=self.screen), "local answer")
        self.assertEqual(self.agent.cloud.sent, [])

    def test_claude_unreachable_at_the_start_means_the_pc_does_it(self) -> None:
        self.agent.cloud = FakeClaude(Unavailable("this PC is offline", offline=True))
        self.assertEqual(self.agent.ask("save this file", lambda *_: True, screen=self.screen), "local answer")
        self.assertTrue(self.local_asked)


if __name__ == "__main__":
    unittest.main()
