"""The API brain (any provider's key) and the Cloud brain (an agent signed in with an account): Claude's message shape
in and out of the OpenAI chat format, streamed text and tool calls, plain errors, sealed keys, and the agents' command
lines."""
from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.error import HTTPError

import api_brains
import cloud_agents
import secret_store
from cloud_brain import Unavailable


class Stream(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def sse(*chunks: dict) -> bytes:
    return b"".join(b"data: " + json.dumps(chunk).encode() + b"\n\n" for chunk in chunks) + b"data: [DONE]\n\n"


class FormatTests(unittest.TestCase):
    def test_claude_history_becomes_openai_messages(self) -> None:
        history = [
            {"role": "user", "content": "weather in Hanoi?"},
            {"role": "assistant", "content": [SimpleNamespace(type="text", text="Checking."),
                                              SimpleNamespace(type="tool_use", id="t1", name="weather", input={"city": "Hanoi"})]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "31°C, sunny"}]},
        ]
        messages = api_brains.openai_messages([{"type": "text", "text": "You are Nova."}, {"type": "text", "text": "Now: Friday."}], history)
        self.assertEqual(messages[0], {"role": "system", "content": "You are Nova.\n\nNow: Friday."})
        self.assertEqual(messages[2]["tool_calls"][0]["function"], {"name": "weather", "arguments": '{"city": "Hanoi"}'})
        self.assertEqual(messages[3], {"role": "tool", "tool_call_id": "t1", "content": "31°C, sunny"})
        tool = api_brains.openai_tools([{"name": "weather", "description": "d", "input_schema": {"type": "object"}}])
        self.assertEqual(tool[0]["function"]["parameters"], {"type": "object"})

    def test_a_streamed_answer_with_a_tool_call(self) -> None:
        body = sse({"choices": [{"delta": {"content": "Let me "}}]}, {"choices": [{"delta": {"content": "check."}}]},
                   {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "weather", "arguments": '{"ci'}}]}}]},
                   {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'ty": "Hue"}'}}]}, "finish_reason": "tool_calls"}]})
        sent: list = []

        def opener(request, timeout):
            sent.append((request.full_url, request.get_header("Authorization"), json.loads(request.data)))
            return Stream(body)
        said: list[str] = []
        brain = api_brains.OpenAIBrain("https://api.example.com/v1", "sk-x", "model-a", "Example", opener)
        reply = brain.turn([{"type": "text", "text": "sys"}], [{"role": "user", "content": "hi"}],
                           [{"name": "weather", "description": "", "input_schema": {"type": "object"}}], said.append)
        self.assertEqual("".join(said), "Let me check.")
        self.assertEqual(reply.stop_reason, "tool_use")
        self.assertEqual([(block.type, getattr(block, "input", None)) for block in reply.content],
                         [("text", None), ("tool_use", {"city": "Hue"})])
        url, auth, payload = sent[0]
        self.assertEqual((url, auth, payload["model"], payload["stream"]), ("https://api.example.com/v1/chat/completions", "Bearer sk-x", "model-a", True))

    def test_problems_are_said_plainly(self) -> None:
        def refused(request, timeout):
            raise HTTPError(request.full_url, 401, "no", {}, io.BytesIO(b"{}"))
        with self.assertRaises(Unavailable) as caught:
            api_brains.OpenAIBrain("https://x/v1", "bad", "m", "Groq", refused).turn([], [{"role": "user", "content": "x"}], [], print)
        self.assertIn("Groq rejected the API key", caught.exception.why)
        models = api_brains.list_models("https://x/v1", "k", lambda request, timeout: Stream(json.dumps(
            {"data": [{"id": "b"}, {"id": "a"}, {"id": "a"}]}).encode()))
        self.assertEqual(models, ["a", "b"])

    def test_a_non_object_model_list_is_empty_not_a_crash(self) -> None:
        models = api_brains.list_models("https://x/v1", "k", lambda request, timeout: Stream(json.dumps(
            [{"id": "a"}]).encode()))
        self.assertEqual(models, [])

    def test_entries_need_a_model_and_an_address(self) -> None:
        entry = api_brains.Entry.new("groq", "llama-x")
        self.assertEqual((entry.base_url, entry.label), ("https://api.groq.com/openai/v1", "Groq · llama-x"))
        with self.assertRaises(ValueError):
            api_brains.Entry.new("custom", "m", "localhost:1234")
        with self.assertRaises(ValueError):
            api_brains.Entry.new("openai", " ")


class SecretTests(unittest.TestCase):
    def test_keys_are_kept_and_forgotten(self) -> None:
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": tempfile.mkdtemp()}):
            secret_store.save("api_key_ab12", "sk-secret")
            self.assertEqual(secret_store.load("api_key_ab12"), "sk-secret")
            secret_store.forget("api_key_ab12")
            self.assertIsNone(secret_store.load("api_key_ab12"))
            with self.assertRaises(ValueError):
                secret_store.save("../escape", "x")


class CloudAgentTests(unittest.TestCase):
    def test_an_agent_answers_through_its_command_line(self) -> None:
        seen: dict = {}

        def run(arguments, **options):
            seen.update(arguments=arguments, options=options)
            return subprocess.CompletedProcess(arguments, 0, "Hà Nội is the capital.\n", "")
        item = cloud_agents.agent("gemini")
        said: list[str] = []
        with mock.patch.object(cloud_agents, "find", lambda agent: "/usr/bin/gemini"):
            answer = cloud_agents.CliBrain(item, run).turn("You are Nova.", "capital of Vietnam?", [], None, said.append)
        self.assertEqual((answer, said), ("Hà Nội is the capital.", ["Hà Nội is the capital."]))
        self.assertEqual(seen["arguments"][:2], ["/usr/bin/gemini", "-p"])
        self.assertIn("capital of Vietnam?", seen["options"]["input"])  # the request goes in on stdin, not the command line

    def test_signed_out_and_missing_are_explained(self) -> None:
        item = cloud_agents.agent("codex")
        run = lambda arguments, **options: subprocess.CompletedProcess(arguments, 1, "", "Error: not logged in")  # noqa: E731
        with mock.patch.object(cloud_agents, "find", lambda agent: "codex"):
            with self.assertRaises(Unavailable) as caught:
                cloud_agents.CliBrain(item, run).turn("s", "p", [], None, print)
        self.assertIn("Connect account", caught.exception.why)
        with mock.patch.object(cloud_agents, "find", lambda agent: None):
            with self.assertRaises(Unavailable):
                cloud_agents.CliBrain(item, run).turn("s", "p", [], None, print)
        self.assertTrue(cloud_agents.agent("claude-code").full)
        self.assertEqual(cloud_agents.agent("nonsense").key, "claude-code")


class MoreAgentTests(unittest.TestCase):
    def test_hermes_and_opencode_answer_with_the_request_on_stdin(self) -> None:
        for key, command, expected in (("hermes", "/x/hermes", ["chat", "-Q", "--query-file", "-"]), ("opencode", "/x/opencode", ["run"])):
            seen: dict = {}

            def run(arguments, **options):
                seen.update(arguments=arguments, options=options)
                return subprocess.CompletedProcess(arguments, 0, "Hello.\n", "")
            with mock.patch.object(cloud_agents, "find", lambda agent, command=command: command):
                self.assertEqual(cloud_agents.CliBrain(cloud_agents.agent(key), run).turn("You are Nova.", "hi there", [], None, print), "Hello.")
            self.assertEqual(seen["arguments"], [command, *expected])
            self.assertIn("hi there", seen["options"]["input"])  # a long request never rides on the command line

    def test_hermes_installs_with_its_own_installer_run_without_a_shell(self) -> None:
        item = cloud_agents.agent("hermes")
        for platform, tail in (("linux", ["--non-interactive"]), ("win32", ["-NonInteractive"])):
            fetched, ran = [], []

            def run(arguments, **options):
                ran.append((arguments, options, Path(arguments[arguments.index("-File") + 1] if platform == "win32" else arguments[1]).read_bytes()))
                return subprocess.CompletedProcess(arguments, 0, "done", "")
            with mock.patch.object(cloud_agents.sys, "platform", platform):
                said = cloud_agents.install(item, run, lambda url: fetched.append(url) or b"#installer")
            self.assertEqual(fetched, [item.installer[1 if platform == "win32" else 0]])
            arguments, options, script = ran[0]
            self.assertEqual((arguments[-1:], script, options.get("shell")), (tail, b"#installer", None))
            self.assertEqual(arguments[0], "powershell" if platform == "win32" else "bash")
            self.assertIn("Hermes Agent is installed", said)

    def test_a_failed_installer_says_why_and_installers_are_https_from_the_vendor(self) -> None:
        failing = lambda arguments, **options: subprocess.CompletedProcess(arguments, 1, "", "step 3\ngit is required")  # noqa: E731
        with self.assertRaisesRegex(RuntimeError, "git is required"):
            cloud_agents.install(cloud_agents.agent("hermes"), failing, lambda url: b"x")
        self.assertTrue(all(url.startswith("https://hermes-agent.nousresearch.com/") for url in cloud_agents.agent("hermes").installer))
        self.assertEqual([item.key for item in cloud_agents.AGENTS],
                         ["claude-code", "codex", "gemini", "opencode", "hermes", "antigravity"])

    def test_antigravity_answers_in_words_through_its_json_stream(self) -> None:
        item = cloud_agents.agent("antigravity")
        sent: list = []

        def run(arguments, **options):
            sent.append((arguments, options["input"]))
            stream = "\n".join(json.dumps(event) for event in (
                {"event": "init", "init": {"permission_mode": "request-review"}},
                {"event": "step_update", "step_update": {"text_delta": "Ha"}},
                {"event": "result", "result": {"status": "SUCCESS", "response": "Hanoi.\n"}}))
            return subprocess.CompletedProcess(arguments, 0, stream, "")
        with mock.patch.object(cloud_agents, "find", lambda agent: "agy"):
            self.assertEqual(cloud_agents.CliBrain(item, run).turn("You are Nova.", "capital of Vietnam?", [], None, print), "Hanoi.")
        arguments, request = sent[0]
        self.assertIn("--mode=default", arguments)  # its own default (auto) would edit files and run commands unasked
        self.assertEqual(arguments[arguments.index("--input-format") + 1], "stream-json")
        self.assertIn("capital of Vietnam?", json.loads(request)["message"]["content"])
        signed_out = lambda arguments, **options: subprocess.CompletedProcess(arguments, 1, "", "authentication required")  # noqa: E731
        with mock.patch.object(cloud_agents, "find", lambda agent: "agy"):
            with self.assertRaisesRegex(Unavailable, "Connect account"):
                cloud_agents.CliBrain(item, signed_out).turn("s", "p", [], None, print)
        failed = lambda arguments, **options: subprocess.CompletedProcess(  # noqa: E731
            arguments, 0, json.dumps({"event": "result", "result": {"status": "ERROR", "response": "", "error": "quota"}}), "")
        with mock.patch.object(cloud_agents, "find", lambda agent: "agy"):
            with self.assertRaises(Unavailable):
                cloud_agents.CliBrain(item, failed).turn("s", "p", [], None, print)

    def test_antigravity_installs_from_googles_own_page(self) -> None:
        opened: list[str] = []
        never = lambda *_args, **_options: self.fail("nothing is downloaded or run for Antigravity")  # noqa: E731
        said = cloud_agents.install(cloud_agents.agent("antigravity"), never, never, open_page=opened.append)
        self.assertEqual(opened, ["https://antigravity.google/docs/cli/install"])
        self.assertIn("Connect account", said)


class AgentLoopTests(unittest.TestCase):
    def test_nova_runs_a_tool_for_an_openai_format_brain(self) -> None:
        from agent import Agent
        from memory import Memory
        rounds = [sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {
                       "name": "calculate", "arguments": '{"expression": "6*7"}'}}]}, "finish_reason": "tool_calls"}]}),
                  sse({"choices": [{"delta": {"content": "It's 42."}, "finish_reason": "stop"}]})]
        payloads: list = []

        def opener(request, timeout):
            payloads.append(json.loads(request.data))
            return Stream(rounds.pop(0))
        agent = Agent(memory=Memory(os.path.join(tempfile.mkdtemp(), "m.sqlite3")))
        agent.cloud = api_brains.OpenAIBrain("https://x/v1", "k", "m", "Example", opener)
        answer = agent._ask_claude("what's 6 times 7", lambda name, details: True, None)
        self.assertEqual(answer, "It's 42.")
        tool_message = payloads[1]["messages"][-1]
        self.assertEqual((tool_message["role"], tool_message["tool_call_id"]), ("tool", "c1"))
        self.assertIn("42", tool_message["content"])


if __name__ == "__main__":
    unittest.main()


class LocalAddressTests(unittest.TestCase):
    """Nova only ever talks to the Ollama on this PC, also when Ollama is shared on the LAN (it listens everywhere)."""

    def test_listening_everywhere_still_means_this_pc_and_others_are_refused(self) -> None:
        import agent
        for setting, expected in (("0.0.0.0:11434", "http://127.0.0.1:11434"), ("http://[::]:11500", "http://127.0.0.1:11500"),
                                  ("127.0.0.1:11434", "http://127.0.0.1:11434")):
            with mock.patch.dict(os.environ, {"OLLAMA_HOST": setting, "ALFRED_API_URL": ""}):
                self.assertEqual(agent.local_base_url(), expected)
        with mock.patch.dict(os.environ, {"OLLAMA_HOST": "http://10.0.0.5:11434", "ALFRED_API_URL": ""}):
            with self.assertRaises(agent.OllamaError):
                agent.local_base_url()
