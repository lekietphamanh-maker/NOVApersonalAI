"""Claude on the owner's Claude plan: Nova's tool server (MCP over HTTP), the Claude Code bridge, and the agent's turn."""
from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import nova_mcp
import plan_brain
from cloud_brain import Unavailable

TIMER = {"type": "function", "function": {"name": "set_timer", "description": "Start a timer.",
                                          "parameters": {"type": "object", "properties": {"minutes": {"type": "number"}}}}}


def post(url: str, body: object, token: str | None) -> tuple[int, object]:
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
    request = urllib.request.Request(url, json.dumps(body).encode(), headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            data = response.read()
            return response.status, json.loads(data) if data else None
    except urllib.error.HTTPError as exc:
        return exc.code, None


class ToolServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = nova_mcp.ToolServer()
        self.addCleanup(self.server.shutdown)

    def test_only_the_current_turn_token_gets_in(self) -> None:
        hello = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}
        self.assertEqual(post(self.server.url, hello, "guess")[0], 401)  # no turn open
        token = self.server.open([TIMER], lambda name, arguments: "done")
        self.assertEqual(post(self.server.url, hello, None)[0], 401)
        self.assertEqual(post(self.server.url, hello, "wrong")[0], 401)
        status, reply = post(self.server.url, hello, token)
        self.assertEqual((status, reply["result"]["protocolVersion"]), (200, "2025-06-18"))
        self.server.close()
        self.assertEqual(post(self.server.url, hello, token)[0], 401)  # the turn is over
        self.assertNotEqual(self.server.open([TIMER], lambda *_: ""), token)
        self.assertTrue(self.server.url.startswith("http://127.0.0.1:"))

    def test_lists_and_runs_only_the_offered_tools(self) -> None:
        ran: list[tuple[str, dict]] = []
        token = self.server.open([TIMER], lambda name, arguments: ran.append((name, arguments)) or "Timer set.")
        self.assertEqual(post(self.server.url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, token)[0], 202)
        _status, listed = post(self.server.url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, token)
        self.assertEqual(listed["result"]["tools"], [{"name": "set_timer", "description": "Start a timer.",
                                                      "inputSchema": TIMER["function"]["parameters"]}])
        _status, called = post(self.server.url, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                                 "params": {"name": "set_timer", "arguments": {"minutes": 5}}}, token)
        self.assertEqual(called["result"], {"content": [{"type": "text", "text": "Timer set."}], "isError": False})
        self.assertEqual(ran, [("set_timer", {"minutes": 5})])
        _status, refused = post(self.server.url, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                                  "params": {"name": "click", "arguments": {}}}, token)
        self.assertTrue(refused["result"]["isError"])
        self.assertEqual(ran, [("set_timer", {"minutes": 5})])  # never reached Nova
        _status, unknown = post(self.server.url, {"jsonrpc": "2.0", "id": 5, "method": "resources/list"}, token)
        self.assertEqual(unknown["error"]["code"], -32601)

    def test_a_failing_tool_is_told_to_claude(self) -> None:
        def broken(_name: str, _arguments: dict) -> str:
            raise ValueError("no such timer")
        token = self.server.open([TIMER], broken)
        _status, called = post(self.server.url, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                 "params": {"name": "set_timer", "arguments": {}}}, token)
        self.assertEqual(called["result"]["content"][0]["text"], "Not done: ValueError: no such timer")
        self.assertTrue(called["result"]["isError"])


def stream(*events: dict) -> str:
    return "".join(json.dumps(event) + "\n" for event in events)


def delta(text: str) -> dict:
    return {"type": "stream_event", "event": {"type": "content_block_delta", "index": 0,
                                              "delta": {"type": "text_delta", "text": text}}}


class KeptInput(io.StringIO):
    def close(self) -> None:
        self.sent = self.getvalue()
        super().close()


class FakeProcess:
    def __init__(self, stdout: str, stderr: str = "", code: int = 0, hang: bool = False) -> None:
        self.stdin = KeptInput()
        self.stdout = io.StringIO(stdout) if not hang else self._hanging()
        self.stderr = io.StringIO(stderr)
        self.returncode: int | None = None
        self._code, self.pid, self.killed = code, 4242, False

    def _hanging(self):
        self._release = threading.Event()
        release = self._release

        class Hanging:
            def __iter__(self):
                release.wait(5)
                return iter(())
        return Hanging()

    def poll(self) -> int | None:
        return None if not self.killed and hasattr(self, "_release") else self._code

    def kill(self) -> None:
        self.killed = True
        self._release.set()

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = self._code
        return self._code


class PlanBrainTests(unittest.TestCase):
    def brain(self, process: FakeProcess, seen: dict) -> plan_brain.PlanBrain:
        def start(arguments, **options):
            seen.update(arguments=arguments, options=options,
                        mcp=json.loads(Path(arguments[arguments.index("--mcp-config") + 1]).read_text()),
                        system=Path(arguments[arguments.index("--system-prompt-file") + 1]).read_text(encoding="utf-8"))
            seen["stdin"] = process.stdin
            return process
        server = nova_mcp.ToolServer()
        self.addCleanup(server.shutdown)
        brain = plan_brain.PlanBrain("claude-opus-5-5", "high", server, command=lambda: "claude", start=start)
        self.addCleanup(brain.close)
        return brain

    def test_streams_the_answer_on_the_plan_with_only_novas_tools(self) -> None:
        seen: dict = {}
        process = FakeProcess(stream({"type": "system", "subtype": "init"}, delta("Your tea "), delta("timer is set."),
                                     {"type": "assistant", "message": {"content": [{"type": "text", "text": "Your tea timer is set."}]}},
                                     {"type": "result", "subtype": "success", "is_error": False, "result": "Your tea timer is set."}))
        brain = self.brain(process, seen)
        pieces: list[str] = []
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-billed", "PATH": os.environ.get("PATH", "")}):
            answer = brain.turn("You are Nova.", "Set a tea timer", [TIMER], lambda *_: "ok", pieces.append, threading.Event())
        self.assertEqual((answer, pieces), ("Your tea timer is set.", ["Your tea ", "timer is set."]))  # no double text
        arguments = seen["arguments"]
        self.assertEqual(arguments[:2], ["claude", "-p"])
        for flag, value in (("--model", "claude-opus-5-5"), ("--effort", "high"), ("--tools", "WebSearch,WebFetch"),
                            ("--allowedTools", "mcp__nova,WebSearch,WebFetch"), ("--output-format", "stream-json")):
            self.assertEqual(arguments[arguments.index(flag) + 1], value)
        self.assertIn("--strict-mcp-config", arguments)
        self.assertNotIn("Set a tea timer", " ".join(arguments))  # the request goes through stdin
        self.assertEqual(seen["stdin"].sent, "Set a tea timer")
        self.assertEqual(seen["system"], "You are Nova.")
        self.assertNotIn("ANTHROPIC_API_KEY", seen["options"]["env"])  # billed to the plan, never the API key
        server = seen["mcp"]["mcpServers"]["nova"]
        self.assertEqual((server["type"], server["url"]), ("http", brain.tools.url))
        self.assertTrue(server["headers"]["Authorization"].startswith("Bearer "))
        self.assertFalse((brain.folder / "mcp.json").exists())  # the token's file is gone after the turn
        self.assertIsNone(brain.tools.current(server["headers"]["Authorization"]))  # and the token no longer works

    def test_whole_messages_count_when_there_are_no_partial_pieces(self) -> None:
        process = FakeProcess(stream({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi there."}]}},
                                     {"type": "result", "is_error": False, "result": "Hi there."}))
        pieces: list[str] = []
        self.assertEqual(self.brain(process, {}).turn("s", "hi", [], lambda *_: "", pieces.append), "Hi there.")
        self.assertEqual(pieces, ["Hi there."])

    def test_failures_become_reasons_the_owner_can_act_on(self) -> None:
        cases = (('{"type":"result","is_error":true,"result":"Claude AI usage limit reached|1763600000"}', "", "limit"),
                 ("", "Invalid API key · Please run /login", "signed in"),
                 ("", "Error: getaddrinfo ENOTFOUND api.anthropic.com", "offline"))
        for stdout, stderr, expected in cases:
            with self.subTest(expected), self.assertRaises(Unavailable) as caught:
                self.brain(FakeProcess(stdout + "\n", stderr, code=1), {}).turn("s", "hi", [], lambda *_: "", lambda _p: None)
            self.assertIn(expected, caught.exception.why)
        self.assertTrue(plan_brain.why_it_failed("ENOTFOUND").offline)
        missing = plan_brain.PlanBrain(command=lambda: None)
        self.addCleanup(missing.close)
        with self.assertRaises(Unavailable) as caught:
            missing.turn("s", "hi", [], lambda *_: "", lambda _p: None)
        self.assertIn("isn't installed", caught.exception.why)

    def test_cancel_stops_claude_code(self) -> None:
        process = FakeProcess("", hang=True)
        cancel = threading.Event()
        threading.Timer(0.3, cancel.set).start()
        with patch.object(plan_brain.sys, "platform", "linux"):
            self.assertIsNone(self.brain(process, {}).turn("s", "hi", [], lambda *_: "", lambda _p: None, cancel))
        self.assertTrue(process.killed)


class AgentPlanTurnTests(unittest.TestCase):
    def agent(self):
        from agent import Agent
        from memory import Memory
        agent = Agent(memory=Memory(Path(tempfile.mkdtemp()) / "memory.sqlite3"))
        agent.router.online = lambda: True
        return agent

    def test_the_plan_brain_gets_the_conversation_and_novas_tools(self) -> None:
        agent = self.agent()
        seen: dict = {}

        class Plan:
            plan, sees_screen, name = True, False, "Claude Sonnet 5.5 (Claude plan)"

            def turn(self, system, request, tools, run, on_text, cancel=None):
                seen.update(system=system, request=request, tools={tool["function"]["name"] for tool in tools})
                seen["ran"] = run("calculate", {"expression": "6*7"})
                on_text("It's 42.")
                return "It's 42."
        agent.cloud = Plan()
        agent.memory.save_message({"role": "user", "content": "hello"})
        agent.memory.save_message({"role": "assistant", "content": "Hi!"})
        answer = agent.ask("what is six times seven", lambda *_: True)
        self.assertEqual(answer, "It's 42.")
        self.assertIn("Owner: hello\nNova: Hi!", seen["request"])
        self.assertTrue(seen["request"].endswith("The owner says: what is six times seven"))
        self.assertIn("mcp__nova__", seen["system"])
        self.assertIn("calculate", seen["tools"])
        self.assertNotIn("click", seen["tools"])  # no screen control through the online brain
        self.assertIn("42", seen["ran"])
        self.assertEqual(agent.memory.recent_messages(limit=2)[-1]["brain"], "claude-plan")

    def test_the_ai_on_this_pc_answers_when_the_plan_cant(self) -> None:
        agent = self.agent()

        class Plan:
            plan, sees_screen, name = True, False, "Claude (Claude plan)"

            def turn(self, *_args, **_kwargs):
                raise Unavailable("your Claude plan's limit is reached for now")
        agent.cloud = Plan()
        brains: list[tuple[str, str]] = []
        agent.on_brain = lambda label, why: brains.append((label, why))
        agent._chat = lambda messages, tools, **_: {"message": {"role": "assistant", "content": "Local answer."}}
        self.assertEqual(agent.ask("tell me a fun fact about octopuses", lambda *_: True), "Local answer.")
        self.assertEqual(brains[-1][1], "your Claude plan's limit is reached for now")


if __name__ == "__main__":
    unittest.main()
