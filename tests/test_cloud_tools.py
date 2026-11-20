"""Tools that can't run on this PC go to Claude: offline Wikipedia missing, the map servers down, code to run. Tools
that act on this PC and private turns never do; a paused server-tool turn is continued; a refusal is said plainly."""
from __future__ import annotations

import subprocess
import unittest
from types import SimpleNamespace

import cloud_tools
from tools import execute_tool

CLAUDE = cloud_tools.Claude(key="sk-ant-test", model="claude-sonnet-5-5", effort="medium")


def block(kind: str, **fields):
    return SimpleNamespace(type=kind, **fields)


class FakeClient:
    def __init__(self, replies: list) -> None:
        self.replies, self.calls = list(replies), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **params):
        self.calls.append(params)
        return self.replies.pop(0)


class ApiTests(unittest.TestCase):
    def test_web_jobs_use_search_and_fetch_and_paused_turns_go_on(self) -> None:
        client = FakeClient([SimpleNamespace(stop_reason="pause_turn", content=[block("server_tool_use", name="web_search")]),
                             SimpleNamespace(stop_reason="end_turn", content=[block("text", text="Trần Hưng Đạo won in 1288.")])])
        answer = cloud_tools.with_api(CLAUDE, "web", "job", client)
        self.assertEqual(answer, "Trần Hưng Đạo won in 1288.")
        first, second = client.calls
        self.assertEqual([tool["type"] for tool in first["tools"]], ["web_search_20260209", "web_fetch_20260209"])
        self.assertEqual((first["fallbacks"], first["output_config"]), ("default", {"effort": "medium"}))
        self.assertEqual(second["messages"][-1]["role"], "assistant")  # the paused turn continued as it was

    def test_code_jobs_use_the_sandbox_and_refusals_are_plain(self) -> None:
        client = FakeClient([SimpleNamespace(stop_reason="refusal", content=[])])
        self.assertEqual(cloud_tools.with_api(CLAUDE, "code", "job", client), "Claude declined this one.")
        self.assertEqual(client.calls[0]["tools"], [{"type": "code_execution_20260521", "name": "code_execution"}])


class RouteToClaudeTests(unittest.TestCase):
    def test_which_jobs_go_where(self) -> None:
        sent: list = []
        api = lambda claude, kind, job: sent.append(("api", kind)) or "done"  # noqa: E731
        plan = lambda claude, job: sent.append(("plan",)) or "done"  # noqa: E731
        self.assertEqual(cloud_tools.run_job("wikipedia", "", {"query": "x"}, "why", CLAUDE, api, plan), "done")
        on_plan = cloud_tools.Claude(key=None, model="claude-sonnet-5-5", effort="medium", command="claude")
        cloud_tools.run_job("route", "", {}, "why", on_plan, api, plan)
        self.assertIsNone(cloud_tools.run_job("run_code", "", {}, "why", on_plan, api, plan))  # the sandbox needs the API
        self.assertIsNone(cloud_tools.run_job("obs", "", {}, "why", CLAUDE, api, plan))  # acts on this PC: never
        self.assertEqual(sent, [("api", "web"), ("plan",)])

    def test_the_plan_may_only_read_the_web(self) -> None:
        seen: dict = {}

        def run(arguments, **options):
            seen.update(arguments=arguments, options=options)
            return subprocess.CompletedProcess(arguments, 0, "Take Võ Văn Kiệt, about 25 minutes.\n", "")
        claude = cloud_tools.Claude(key=None, model="claude-sonnet-5-5", effort="medium", command="claude")
        self.assertEqual(cloud_tools.with_plan(claude, "job", run), "Take Võ Văn Kiệt, about 25 minutes.")
        self.assertEqual(seen["arguments"][-1], "WebSearch,WebFetch")
        self.assertNotIn("ANTHROPIC_API_KEY", seen["options"]["env"])


class ExecuteToolTests(unittest.TestCase):
    def test_missing_offline_wikipedia_is_looked_up_online(self) -> None:
        asked: list = []
        cloud = lambda tool, description, arguments, reason: asked.append((tool, arguments, reason)) or "From Wikipedia: …"  # noqa: E731
        answer = execute_tool("wikipedia", {"query": "Trần Hưng Đạo"}, None, lambda *_: True, cloud=cloud)
        self.assertTrue(answer.startswith("(Done on Claude in the cloud, since offline Wikipedia isn't downloaded"))
        self.assertEqual(asked[0][:2], ("wikipedia", {"query": "Trần Hưng Đạo"}))

    def test_without_claude_it_says_why(self) -> None:
        self.assertEqual(execute_tool("run_code", {"task": "17th prime"}, None, lambda *_: True),
                         "Can't do that on this PC: this PC doesn't run code for Nova.")
        def broken(*_):
            raise OSError("offline")
        self.assertIn("Claude couldn't do it either: offline",
                      execute_tool("run_code", {"task": "x"}, None, lambda *_: True, cloud=broken))


class AgentTests(unittest.TestCase):
    def test_private_turns_keep_tools_here(self) -> None:
        from agent import Agent
        from memory import Memory
        import tempfile
        from pathlib import Path
        agent = Agent(memory=Memory(Path(tempfile.mkdtemp()) / "m.sqlite3"))
        agent.cloud_tools = lambda *_: "x"
        agent.router.is_offline = lambda: False
        self.assertTrue(agent._may_use_cloud("what's the 40th prime"))
        self.assertFalse(agent._may_use_cloud("privately, what's the 40th prime"))
        agent.private_topics = "personal"
        self.assertFalse(agent._may_use_cloud("what's the 40th prime"))


if __name__ == "__main__":
    unittest.main()
