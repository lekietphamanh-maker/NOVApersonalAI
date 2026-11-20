"""Claude as Nova's online brain, through the real Anthropic SDK talking to a fake Anthropic server that streams
scripted answers: what is sent (and never sent), speaking while Claude writes, tools, refusals, falling back to the
local model offline, and which turns stay local."""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import anthropic

import brain_router
from agent import Agent
from cloud_brain import CloudBrain
from memory import Memory


def sse(blocks: list[dict], stop: str = "end_turn") -> bytes:
    """A streamed Messages API answer: text blocks are {"text": ...}, tool calls {"tool": name, "input": {...}}."""
    events = [("message_start", {"type": "message_start", "message": {
        "id": "msg_fake", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5", "content": [],
        "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 12, "output_tokens": 1}}})]
    for index, block in enumerate(blocks):
        if "text" in block:
            events.append(("content_block_start", {"type": "content_block_start", "index": index,
                                                   "content_block": {"type": "text", "text": ""}}))
            for word in block["text"].split(" "):
                events.append(("content_block_delta", {"type": "content_block_delta", "index": index,
                                                       "delta": {"type": "text_delta", "text": word + " "}}))
        else:
            events.append(("content_block_start", {"type": "content_block_start", "index": index, "content_block": {
                "type": "tool_use", "id": f"toolu_{index}", "name": block["tool"], "input": {}}}))
            events.append(("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {
                "type": "input_json_delta", "partial_json": json.dumps(block["input"])}}))
        events.append(("content_block_stop", {"type": "content_block_stop", "index": index}))
    events.append(("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                                     "usage": {"output_tokens": 30}}))
    events.append(("message_stop", {"type": "message_stop"}))
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


class FakeAnthropic:
    """Answers POST /v1/messages with the next scripted stream and keeps every request it got."""

    def __init__(self) -> None:
        self.script: list[bytes] = []
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:
                pass

            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(body)
                fake.headers.append(dict(self.headers))
                reply = fake.script.pop(0) if fake.script else sse([{"text": "Out of script."}])
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()


class CloudBrainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeAnthropic()
        self.memory = Memory(Path(tempfile.mkdtemp()) / "memory.sqlite3")
        self.memory.add_fact("Loves phở")
        self.agent = Agent(memory=self.memory)
        self.agent.owner_name = "Kai"
        self.agent.private_topics = "personal"  # the strict rule: nothing about the owner goes online
        client = anthropic.Anthropic(api_key="sk-ant-test", base_url=self.fake.url, max_retries=0)
        self.agent.cloud = CloudBrain("sk-ant-test", client=client)  # default: Claude Sonnet 5.5 at medium
        self.local: list[list[dict]] = []
        self.agent._chat = lambda messages, tools: self.local.append(messages) or {
            "message": {"role": "assistant", "content": "Answered on this PC."}}
        self.brains: list[tuple[str, str]] = []
        self.agent.on_brain = lambda label, why: self.brains.append((label, why))

    def tearDown(self) -> None:
        self.fake.close()

    def test_claude_answers_while_it_writes_and_gets_nothing_personal(self) -> None:
        self.fake.script = [sse([{"text": "Mount Everest, at 8,849 metres."}])]
        pieces: list[str] = []
        answer = self.agent.ask("what is the tallest mountain?", lambda *_: True, on_text=pieces.append)
        self.assertEqual(answer, "Mount Everest, at 8,849 metres.")
        self.assertGreater(len(pieces), 3)  # spoken as it came in, not at the end
        self.assertEqual(self.brains, [("Claude Sonnet 5.5", "online")])
        self.assertEqual(self.local, [])
        request, headers = self.fake.requests[0], self.fake.headers[0]
        self.assertEqual(request["model"], "claude-sonnet-5-5")
        self.assertEqual(request["output_config"], {"effort": "medium"})
        self.assertEqual(request["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", headers.get("anthropic-beta", ""))
        self.assertTrue(request["stream"])
        self.assertEqual(request["system"][0]["cache_control"], {"type": "ephemeral"})
        sent = json.dumps(request, ensure_ascii=False)
        for secret in ("Kai", "Loves phở", "Where your owner is"):
            self.assertNotIn(secret, sent)
        names = {tool.get("name") for tool in request["tools"]}
        self.assertIn("calculate", names)
        for personal in ("remember", "forget", "weather", "second_brain", "list_unread_mail", "fitness_status", "daily_brief"):
            self.assertNotIn(personal, names)
        self.assertIn("web_search", names)  # Nova's own free search, run on this PC
        self.assertFalse(any(str(tool.get("type", "")).startswith("web_search") for tool in request["tools"]))  # not Claude's paid one
        self.assertTrue(all(tool.get("eager_input_streaming") for tool in request["tools"] if "input_schema" in tool))

    def test_tools_run_on_this_pc_and_the_result_goes_back(self) -> None:
        self.fake.script = [sse([{"text": "Let me work that out."}, {"tool": "calculate", "input": {"expression": "17*23"}}],
                                stop="tool_use"),
                            sse([{"text": "It's 391."}])]
        answer = self.agent.ask("what's 17 times 23?", lambda *_: True)
        self.assertEqual(answer, "Let me work that out. It's 391.")
        second = self.fake.requests[1]["messages"]
        self.assertEqual(second[-2]["role"], "assistant")
        self.assertEqual(second[-2]["content"][1]["type"], "tool_use")  # the assistant turn goes back unchanged
        self.assertEqual(second[-1]["content"][0]["type"], "tool_result")
        self.assertIn("391", second[-1]["content"][0]["content"])
        self.assertEqual(self.fake.requests[0]["system"], self.fake.requests[1]["system"])  # append-only within a turn

    def test_claude_searches_with_novas_free_search_without_asking_each_time(self) -> None:
        import web_search
        searched: list[str] = []
        original = web_search.search
        web_search.search = lambda query: searched.append(query) or "Web results: [1] Everest is 8,849 m tall."
        self.addCleanup(setattr, web_search, "search", original)
        self.fake.script = [sse([{"tool": "web_search", "input": {"query": "everest height"}}], stop="tool_use"),
                            sse([{"text": "8,849 metres."}])]
        asked: list[str] = []
        answer = self.agent.ask("how tall is everest right now?", lambda name, _details: asked.append(name) or False)
        self.assertEqual(answer, "8,849 metres.")
        self.assertEqual(searched, ["everest height"])
        self.assertEqual(asked, [])  # covered by turning Claude on
        self.assertIn("8,849 m", json.dumps(self.fake.requests[1]["messages"][-1]))

    def test_personal_turns_stay_local_and_out_of_claudes_history(self) -> None:
        answer = self.agent.ask("what's in my email today?", lambda *_: True)
        self.assertEqual(answer, "Answered on this PC.")
        self.assertEqual(self.brains[-1], (self.agent.model, "personal"))
        self.assertEqual(self.fake.requests, [])
        self.fake.script = [sse([{"text": "Paris."}])]
        self.agent.ask("what's the capital of France?", lambda *_: True)
        sent = json.dumps(self.fake.requests[0]["messages"])
        self.assertNotIn("email", sent)
        self.assertNotIn("Answered on this PC", sent)
        self.assertIn("capital of France", sent)

    def test_offline_the_local_model_answers_and_claude_waits_a_while(self) -> None:
        dead = anthropic.Anthropic(api_key="sk-ant-test", base_url="http://127.0.0.1:9", max_retries=0)
        self.agent.cloud = CloudBrain("sk-ant-test", client=dead)
        answer = self.agent.ask("tell me a joke", lambda *_: True)
        self.assertEqual(answer, "Answered on this PC.")
        self.assertEqual(self.brains, [("Claude Sonnet 5.5", "online"), (self.agent.model, "this PC is offline")])
        self.agent.ask("another one", lambda *_: True)
        self.assertEqual(self.brains[-1], (self.agent.model, "offline"))  # not tried again straight away

    def test_a_refusal_is_said_and_the_way_to_ask_locally_offered(self) -> None:
        self.fake.script = [sse([], stop="refusal")]
        answer = self.agent.ask("something Claude won't do", lambda *_: True)
        self.assertIn("privately", answer)

    def test_screen_assist_and_claude_off_stay_local(self) -> None:
        self.agent.cloud = None
        self.agent.ask("hello", lambda *_: True)
        self.assertEqual(self.brains[-1], (self.agent.model, "off"))
        self.assertEqual(self.fake.requests, [])


class FreeCloudTests(unittest.TestCase):
    """The free online brain: a large open model on Ollama Cloud, through the local Ollama, when Claude is off or failed."""

    def setUp(self) -> None:
        self.memory = Memory(Path(tempfile.mkdtemp()) / "memory.sqlite3")
        self.memory.add_fact("Loves phở")
        self.agent = Agent(memory=self.memory)
        self.agent.owner_name = "Kai"
        self.agent.private_topics = "personal"
        self.agent.free_cloud = "gpt-oss:120b-cloud"
        self.calls: list[dict] = []
        self.cloud_error = ""

        def chat(messages, tools, model=None, on_text=None):
            self.calls.append({"messages": [dict(message) for message in messages], "tools": tools, "model": model})
            if model is None:
                return {"message": {"role": "assistant", "content": "Answered on this PC."}}
            if self.cloud_error:
                import agent as agent_module
                raise agent_module.OllamaError(self.cloud_error)
            if len([call for call in self.calls if call["model"]]) == 1 and "17" in json.dumps(messages[-1]):
                return {"message": {"role": "assistant", "content": "Let me check.",
                                    "tool_calls": [{"function": {"name": "calculate", "arguments": {"expression": "17*23"}}}]}}
            return {"message": {"role": "assistant", "content": "It's 391."}}
        self.agent._chat = chat
        self.brains: list[tuple[str, str]] = []
        self.agent.on_brain = lambda label, why: self.brains.append((label, why))

    def test_the_free_brain_answers_online_with_nothing_personal(self) -> None:
        answer = self.agent.ask("what's 17 times 23?", lambda *_: True)
        self.assertEqual(answer, "Let me check.It's 391.")
        self.assertEqual(self.brains, [("Ollama Cloud · gpt-oss:120b", "online")])
        first, second = self.calls[0], self.calls[1]
        self.assertEqual(first["model"], "gpt-oss:120b-cloud")
        sent = json.dumps(first["messages"], ensure_ascii=False)
        for secret in ("Kai", "Loves phở", "Where your owner is"):
            self.assertNotIn(secret, sent)
        self.assertIn("free online brain", first["messages"][0]["content"])
        names = {tool["function"]["name"] for tool in first["tools"]}
        self.assertTrue({"calculate", "web_search"} <= names)
        self.assertFalse(names & {"remember", "weather", "second_brain", "library", "list_unread_mail"})
        self.assertEqual(second["messages"][-1]["role"], "tool")
        self.assertIn("391", second["messages"][-1]["content"])

    def test_personal_stays_on_this_pc(self) -> None:
        self.agent.ask("what's in my email?", lambda *_: True)
        self.assertEqual([call["model"] for call in self.calls], [None])
        self.assertEqual(self.brains, [(self.agent.model, "personal")])

    def test_not_signed_in_falls_back_and_rests(self) -> None:
        problems: list[str] = []
        self.agent.on_free_cloud = problems.append
        self.cloud_error = 'Ollama returned HTTP 401: {"error":"unauthorized"}'
        self.assertEqual(self.agent.ask("tell me a joke", lambda *_: True), "Answered on this PC.")
        self.assertIn("not signed in", problems[0])
        self.assertEqual(self.brains[-1][1], problems[0])
        self.calls.clear()
        self.agent.ask("another joke", lambda *_: True)
        self.assertEqual([call["model"] for call in self.calls], [None])  # resting: not asked again straight away

    def test_claude_first_then_the_free_brain_when_claude_cant(self) -> None:
        from cloud_brain import Unavailable
        self.agent.cloud = CloudBrain("sk-ant-test", client=anthropic.Anthropic(api_key="sk-ant-test", base_url="http://127.0.0.1:9"))

        def busy(*_args, **_kwargs):
            raise Unavailable("Claude is busy right now (rate limit)")
        self.agent.cloud.turn = busy
        self.assertEqual(self.agent.ask("what's 17 times 23?", lambda *_: True), "Let me check.It's 391.")
        self.assertEqual([label for label, _why in self.brains], ["Claude Sonnet 5.5", "Ollama Cloud · gpt-oss:120b"])


class OwnersRuleTests(unittest.TestCase):
    """The default rule: only passwords, codes, bank details and mail are held back, and for those Nova asks out loud.
    Weather, news and everything else go to the chosen brain, which knows the owner like the local model does."""

    def setUp(self) -> None:
        self.fake = FakeAnthropic()
        self.addCleanup(self.fake.close)
        self.memory = Memory(Path(tempfile.mkdtemp()) / "memory.sqlite3")
        self.memory.add_fact("Loves phở")
        self.agent = Agent(memory=self.memory)
        self.assertEqual(self.agent.private_topics, "secrets")
        self.agent.owner_name = "Kai"
        self.agent.location = type("Place", (), {"place": {"name": "Da Nang", "country": "Vietnam"},
                                                  "weather_text": lambda self, elsewhere="": "Da Nang: 27°C, light rain."})()
        self.agent.gmail = type("Mail", (), {"list_unread": lambda self: "1. Boss: Budget (unread)"})()
        client = anthropic.Anthropic(api_key="sk-ant-test", base_url=self.fake.url, max_retries=0)
        self.agent.cloud = CloudBrain("sk-ant-test", client=client)
        self.agent._chat = lambda messages, tools: {"message": {"role": "assistant", "content": "Answered on this PC."}}
        self.asked: list[tuple[str, dict]] = []

    def approve(self, answer: bool):
        return lambda name, details: self.asked.append((name, details)) or answer

    def test_weather_goes_to_claude_who_knows_where_the_owner_is(self) -> None:
        self.fake.script = [sse([{"tool": "weather", "input": {}}], stop="tool_use"), sse([{"text": "Light rain, take an umbrella."}])]
        answer = self.agent.ask("will it rain tomorrow?", self.approve(True))
        self.assertEqual(answer, "Light rain, take an umbrella.")
        self.assertEqual(self.asked, [])  # nothing secret: no question
        first = self.fake.requests[0]
        sent = json.dumps(first["system"], ensure_ascii=False)
        for known in ("Kai", "Loves phở", "Da Nang"):
            self.assertIn(known, sent)
        names = {tool.get("name") for tool in first["tools"]}
        self.assertTrue({"weather", "local_news", "remember", "web_search"} <= names)
        self.assertFalse(names & {"list_unread_mail", "click", "type_text"})  # mail only when sent on purpose; never the screen
        self.assertIn("27°C", json.dumps(self.fake.requests[1]["messages"][-1], ensure_ascii=False))

    def test_mail_asks_first_and_no_keeps_it_on_this_pc(self) -> None:
        answer = self.agent.ask("any new emails?", self.approve(False))
        self.assertEqual(answer, "Answered on this PC.")
        self.assertEqual(self.asked[0][0], "send_online")
        self.assertIn("Should I send it to Claude Sonnet 5.5?", self.asked[0][1]["speak"])
        self.assertEqual(self.fake.requests, [])
        self.fake.script = [sse([{"text": "Paris."}])]
        self.agent.ask("capital of France?", self.approve(True))
        self.assertNotIn("emails", json.dumps(self.fake.requests[0]["messages"]))  # the kept question never goes later

    def test_mail_sent_on_purpose_gets_the_mail_tools_for_that_turn(self) -> None:
        self.fake.script = [sse([{"tool": "list_unread_mail", "input": {}}], stop="tool_use"), sse([{"text": "One from your boss."}])]
        self.assertEqual(self.agent.ask("check my gmail", self.approve(True)), "One from your boss.")
        self.assertIn("list_unread_mail", {tool.get("name") for tool in self.fake.requests[0]["tools"]})
        self.assertIn("Boss: Budget", json.dumps(self.fake.requests[1]["messages"][-1]))
        self.fake.script = [sse([{"text": "Hi."}])]
        self.agent.ask("hello", self.approve(True))
        self.assertNotIn("list_unread_mail", {tool.get("name") for tool in self.fake.requests[-1]["tools"]})

    def test_privately_stays_here_without_asking(self) -> None:
        self.assertEqual(self.agent.ask("privately, what's my bank pin code?", self.approve(True)), "Answered on this PC.")
        self.assertEqual((self.asked, self.fake.requests), ([], []))

    def test_spoken_answers(self) -> None:
        for said, meaning in (("yes", True), ("Yeah, please", True), ("no", False), ("không", False), ("có", True),
                              ("what time is it", None)):
            self.assertEqual(brain_router.spoken_answer(said), meaning, said)
        for said, place in (("send it to Claude", "online"), ("use claude", "online"), ("keep it here", "local"),
                            ("on this PC", "local"), ("privately", "local"), ("maybe", None)):
            self.assertEqual(brain_router.spoken_place(said), place, said)


class AutoTests(unittest.TestCase):
    """Auto: the AI on this PC answers everyday questions, hard ones go to Claude."""

    def setUp(self) -> None:
        self.fake = FakeAnthropic()
        self.addCleanup(self.fake.close)
        self.agent = Agent(memory=Memory(Path(tempfile.mkdtemp()) / "memory.sqlite3"))
        self.agent.cloud = CloudBrain("sk-ant-test", client=anthropic.Anthropic(api_key="sk-ant-test", base_url=self.fake.url, max_retries=0))
        self.agent.auto_route = True
        self.agent._chat = lambda messages, tools: {"message": {"role": "assistant", "content": "Answered on this PC."}}
        self.brains: list[tuple[str, str]] = []
        self.agent.on_brain = lambda label, why: self.brains.append((label, why))

    def test_everyday_here_hard_online_and_asking_still_works(self) -> None:
        asked: list[str] = []
        approve = lambda name, _details: asked.append(name) or False  # noqa: E731
        self.assertEqual(self.agent.ask("what's the capital of France?", approve), "Answered on this PC.")
        self.assertEqual(self.brains[-1], (self.agent.model, "auto"))
        self.fake.script = [sse([{"text": "SQLite for one PC; Postgres when it's shared."}])]
        self.agent.ask("compare postgres and sqlite for a news database, in depth", approve)
        self.assertEqual(self.brains[-1], ("Claude Sonnet 5.5", "hard question"))
        self.fake.script = [sse([{"text": "It's noon."}])]
        self.agent.ask("ask Claude what time it is in Tokyo", approve)
        self.assertEqual(self.brains[-1], ("Claude Sonnet 5.5", "asked"))
        self.agent.ask("read my email", approve)  # everyday and secret: here, without a question
        self.assertEqual((self.brains[-1], asked), ((self.agent.model, "auto"), []))
        self.assertEqual(len(self.fake.requests), 2)


class RouterTests(unittest.TestCase):
    def test_what_counts_as_personal(self) -> None:
        for text in ("read my email", "what's in my second brain", "remember I like jazz", "what's the weather tomorrow", "will it rain tonight", "is it cold outside",
                     "where am I", "what is my wife's birthday", "did I finish that", "privately, how do I...",
                     "my bank password", "đọc thư của tôi", "thời tiết hôm nay", "nhớ là tôi thích cà phê",
                     "what's on my screen", "my heart rate", "lịch của tôi tuần này"):
            self.assertTrue(brain_router.personal(text), text)
        for text in ("what is the tallest mountain", "write a poem about rain", "explain photosynthesis",
                     "17 times 23", "lịch sử Việt Nam", "how do black holes form", "set a timer for 5 minutes",
                     "give me ideas for my game's ending", "what does 'brain' mean in latin"):
            self.assertFalse(brain_router.personal(text), text)

    def test_choosing(self) -> None:
        router = brain_router.Router()
        self.assertEqual(router.choose("hi", cloud_ready=False), ("local", "off"))
        self.assertEqual(router.choose("explain this", cloud_ready=True, screen_on=True), ("local", "screen"))
        self.assertEqual(router.choose("read my email", cloud_ready=True), ("local", "personal"))
        self.assertEqual(router.choose("ask Claude about my plans", cloud_ready=True), ("online", "asked"))
        self.assertEqual(router.choose("explain photosynthesis", cloud_ready=True), ("online", "online"))
        router.offline()
        self.assertEqual(router.choose("explain photosynthesis", cloud_ready=True), ("local", "offline"))
        router._offline_until = time.monotonic() - 1
        self.assertEqual(router.choose("explain photosynthesis", cloud_ready=True), ("online", "online"))


class TalksAndThinksLikeClaudeTests(unittest.TestCase):
    """Both brains share one way of talking and thinking; the local model learns Claude's voice and thinks first on
    hard questions, like Claude's adaptive thinking."""

    def setUp(self) -> None:
        import agent as agent_module
        self.agent_module = agent_module
        self.agent = Agent(memory=Memory(Path(tempfile.mkdtemp()) / "memory.sqlite3"))
        self.payloads: list[dict] = []
        self.refuse_thinking = False

        def fake_http(url: str, payload: dict, timeout: int = 180) -> dict:
            self.payloads.append(payload)
            if payload.get("think") and self.refuse_thinking:
                raise agent_module.OllamaError('Ollama returned HTTP 400: {"error":"\\"qwen2.5:7b\\" does not support thinking"}')
            if len(self.payloads) == 1 and payload["tools"] and "17" in json.dumps(payload["messages"][-1]):
                return {"message": {"role": "assistant", "content": "",
                                    "tool_calls": [{"function": {"name": "calculate", "arguments": {"expression": "17*23"}}}]}}
            return {"message": {"role": "assistant", "content": "Done."}}
        self.original = agent_module._http_json
        agent_module._http_json = fake_http

    def tearDown(self) -> None:
        self.agent_module._http_json = self.original

    def test_which_questions_get_thought_about_first(self) -> None:
        from agent import needs_thinking
        for hard in ("why is the sky blue", "explain recursion", "what's 17*23", "should I buy the red one or the blue one",
                     "tại sao trời màu xanh", "how much would 3 coffees a day cost me in a year",
                     "I have a meeting at nine, a gym class after lunch and two essays due friday, what do I do first"):
            self.assertTrue(needs_thinking(hard), hard)
        for quick in ("hello", "set a timer for 5 minutes", "play some music", "what time is it", "turn the volume up", "thanks"):
            self.assertFalse(needs_thinking(quick), quick)

    def test_the_local_model_thinks_before_a_hard_answer_then_carries_on(self) -> None:
        self.agent.ask("what is 17 times 23, and why?", lambda *_: True)
        self.assertTrue(self.payloads[0]["think"])
        self.assertEqual(self.payloads[0]["options"]["temperature"], 0.6)  # Qwen3 thinks with sampling, not greedy
        self.assertFalse(self.payloads[1]["think"])  # after the tool result: no second pause
        self.payloads.clear()
        self.agent.ask("hello", lambda *_: True)
        self.assertFalse(self.payloads[0]["think"])

    def test_a_model_that_cant_think_answers_anyway(self) -> None:
        self.refuse_thinking = True
        self.assertEqual(self.agent.ask("explain recursion", lambda *_: True), "Done.")
        self.assertEqual([payload["think"] for payload in self.payloads], [True, False])
        self.payloads.clear()
        self.agent.ask("explain recursion again", lambda *_: True)
        self.assertEqual([payload["think"] for payload in self.payloads], [False])  # not asked to think again

    def test_the_local_model_learns_claudes_voice_but_not_from_personal_turns(self) -> None:
        memory = self.agent.memory
        memory.save_message({"role": "user", "content": "how do black holes form?"})
        memory.save_message({"role": "assistant", "content": "Short version: a big star runs out of fuel and collapses.",
                             "brain": "claude"})
        memory.save_message({"role": "user", "content": "read my email", "private": True})
        memory.save_message({"role": "assistant", "content": "You have two new mails.", "private": True})
        self.agent.ask("hello", lambda *_: True)
        prompt = self.payloads[-1]["messages"][0]["content"]
        self.assertIn("How you answered recently through your online brain", prompt)
        self.assertIn("Q: how do black holes form?\nA: Short version: a big star runs out of fuel", prompt)
        self.assertNotIn("two new mails", prompt.split("How you answered recently")[1])

    def test_both_brains_share_one_way_of_talking(self) -> None:
        from agent import CLAUDE_SYSTEM, SYSTEM_PROMPT
        for prompt in (SYSTEM_PROMPT, CLAUDE_SYSTEM):
            self.assertIn("Lead with the answer or the key point", prompt)
            self.assertIn("never make up facts", prompt)
        self.assertIn("think and explain the way you, Claude, naturally do", CLAUDE_SYSTEM)


if __name__ == "__main__":
    unittest.main()
