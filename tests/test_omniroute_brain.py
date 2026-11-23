"""OmniRoute as an optional Nova brain: the provider entry (default address and model, no key needed),
adding it without a key, and a gateway that isn't running failing fast so the local model answers instead."""
from __future__ import annotations

import io
import json
import os
import tempfile
import types
import unittest
from urllib.error import HTTPError, URLError

import api_brains
import dashboard
from cloud_brain import Unavailable

GATEWAY = "http://localhost:20128/v1"


class Stream(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def sse(*chunks: dict) -> bytes:
    return b"".join(b"data: " + json.dumps(chunk).encode() + b"\n\n" for chunk in chunks) + b"data: [DONE]\n\n"


class ProviderTests(unittest.TestCase):
    def test_omniroute_is_registered_with_its_defaults(self) -> None:
        found = api_brains.provider("omniroute")
        self.assertEqual((found.key, found.base_url, found.default_model), ("omniroute", GATEWAY, "auto"))
        self.assertTrue(found.key_optional)
        self.assertIn("OmniRoute", found.label)
        self.assertIn("omniroute.online", found.hint)
        self.assertTrue(found.note)

    def test_adding_omniroute_without_a_model_picks_auto(self) -> None:
        entry = api_brains.Entry.new("omniroute", "")
        self.assertEqual((entry.model, entry.base_url, entry.label), ("auto", GATEWAY, "OmniRoute · auto"))
        self.assertEqual(api_brains.Entry.new("omniroute", "gpt-4").model, "gpt-4")

    def test_other_providers_still_need_a_model(self) -> None:
        with self.assertRaises(ValueError):
            api_brains.Entry.new("openai", " ")


def fake_app(**extra: object) -> types.SimpleNamespace:
    settings: dict = {}
    app = types.SimpleNamespace(
        settings=settings,
        _save_setting=lambda key, value: settings.__setitem__(key, value),
        _apply_claude=lambda: None,
        _toast=lambda *args: None,
    )
    for key, value in extra.items():
        setattr(app, key, value)
    # The actions call the app's own helpers; a fake app needs them bound, the way
    # test_dashboard_self_update.py binds its helpers onto its fake.
    for name in ("_api_entries", "_api_entry", "_api_key", "_claude_via", "_claude_ready", "_cloud_agent",
                 "_brains_state"):
        method = getattr(dashboard.AlfredApp, name)
        setattr(app, name, lambda *args, _method=method, **kwargs: _method(app, *args, **kwargs))
    return app


class DashboardTests(unittest.TestCase):
    def test_adding_omniroute_needs_no_key(self) -> None:
        app = fake_app()
        result = dashboard.AlfredApp._act_api_brain_add(app, {"provider": "omniroute", "model": "", "key": ""})
        self.assertIsNone(result)  # added: no error, and no key was asked for
        saved = app.settings["api_brains"]
        self.assertEqual(len(saved), 1)
        self.assertEqual((saved[0]["provider"], saved[0]["model"], saved[0]["base_url"]),
                         ("omniroute", "auto", GATEWAY))
        self.assertEqual(app.settings["api_brain"], saved[0]["id"])

    def test_keyless_omniroute_counts_as_ready(self) -> None:
        entry = api_brains.Entry.new("omniroute", "")
        app = fake_app()
        app.settings.update({"claude_via": "key", "api_brains": [entry.as_dict()], "api_brain": entry.id})
        self.assertTrue(dashboard.AlfredApp._claude_ready(app))

    def test_a_keyed_provider_without_a_key_still_isnt_ready(self) -> None:
        import secret_store
        entry = api_brains.Entry.new("groq", "llama-x")
        secret_store.forget(f"api_key_{entry.id}")
        app = fake_app()
        app.settings.update({"claude_via": "key", "api_brains": [entry.as_dict()], "api_brain": entry.id})
        self.assertFalse(dashboard.AlfredApp._claude_ready(app))

    def test_the_settings_list_marks_the_key_optional(self) -> None:
        app = fake_app()
        app.settings.update({"claude_via": "key"})
        providers = dashboard.AlfredApp._brains_state(app)["api"]["providers"]
        found = next(item for item in providers if item["key"] == "omniroute")
        self.assertTrue(found["key_optional"])
        self.assertEqual(found["default_model"], "auto")
        self.assertIn("npm install -g omniroute", found["note"])


class GatewayDownTests(unittest.TestCase):
    def test_a_missing_gateway_fails_fast_with_a_plain_message(self) -> None:
        calls: list = []

        def refused(request, timeout):
            calls.append((request.full_url, timeout))
            raise URLError("connection refused")

        brain = api_brains.OpenAIBrain(GATEWAY, "", "auto", "OmniRoute · auto", refused)
        with self.assertRaises(Unavailable) as caught:
            brain.turn([], [{"role": "user", "content": "hi"}], [], print)
        self.assertTrue(caught.exception.offline)
        self.assertIn("OmniRoute · auto isn't answering", caught.exception.why)
        self.assertIn("http://localhost:20128/v1", caught.exception.why)
        # The first connection attempt is the short probe, not the long turn timeout.
        self.assertEqual(calls, [(f"{GATEWAY}/models", 8.0)])

    def test_a_wedged_gateway_times_out_fast_too(self) -> None:
        def wedged(request, timeout):
            raise TimeoutError("timed out")

        brain = api_brains.OpenAIBrain(GATEWAY, "", "auto", "OmniRoute · auto", wedged)
        with self.assertRaises(Unavailable) as caught:
            brain.turn([], [{"role": "user", "content": "hi"}], [], print)
        self.assertTrue(caught.exception.offline)
        self.assertIn("isn't answering", caught.exception.why)

    def test_the_first_turn_probes_then_answers(self) -> None:
        calls: list = []

        def gateway(request, timeout):
            calls.append((request.full_url, timeout))
            if request.full_url.endswith("/models"):
                return Stream(json.dumps({"data": [{"id": "auto"}]}).encode())
            return Stream(sse({"choices": [{"delta": {"content": "Hello."}, "finish_reason": "stop"}]}))

        said: list[str] = []
        brain = api_brains.OpenAIBrain(GATEWAY, "", "auto", "OmniRoute · auto", gateway)
        reply = brain.turn([], [{"role": "user", "content": "hi"}], [], said.append)
        self.assertEqual("".join(said), "Hello.")
        self.assertEqual(reply.stop_reason, "end_turn")
        self.assertEqual(calls, [(f"{GATEWAY}/models", 8.0), (f"{GATEWAY}/chat/completions", 180)])
        # The next turn skips the probe: the gateway already proved it is up.
        brain.turn([], [{"role": "user", "content": "again"}], [], said.append)
        self.assertEqual(len(calls), 3)

    def test_a_server_that_answers_without_a_models_list_still_works(self) -> None:
        def minimal(request, timeout):
            if request.full_url.endswith("/models"):
                raise HTTPError(request.full_url, 404, "no", {}, io.BytesIO(b"{}"))
            return Stream(sse({"choices": [{"delta": {"content": "Hi."}, "finish_reason": "stop"}]}))

        said: list[str] = []
        brain = api_brains.OpenAIBrain(GATEWAY, "", "auto", "OmniRoute · auto", minimal)
        reply = brain.turn([], [{"role": "user", "content": "hi"}], [], said.append)
        self.assertEqual(("".join(said), reply.stop_reason), ("Hi.", "end_turn"))

    def test_a_server_that_answers_html_at_models_still_works(self) -> None:
        def html_server(request, timeout):
            if request.full_url.endswith("/models"):
                return Stream(b"<html><body>not an api</body></html>")
            return Stream(sse({"choices": [{"delta": {"content": "Hi."}, "finish_reason": "stop"}]}))

        said: list[str] = []
        brain = api_brains.OpenAIBrain(GATEWAY, "", "auto", "OmniRoute · auto", html_server)
        reply = brain.turn([], [{"role": "user", "content": "hi"}], [], said.append)
        self.assertEqual(("".join(said), reply.stop_reason), ("Hi.", "end_turn"))

    def test_a_server_that_answers_a_json_array_at_models_still_works(self) -> None:
        def array_server(request, timeout):
            if request.full_url.endswith("/models"):
                return Stream(json.dumps([{"id": "auto"}]).encode())
            return Stream(sse({"choices": [{"delta": {"content": "Hi."}, "finish_reason": "stop"}]}))

        said: list[str] = []
        brain = api_brains.OpenAIBrain(GATEWAY, "", "auto", "OmniRoute · auto", array_server)
        reply = brain.turn([], [{"role": "user", "content": "hi"}], [], said.append)
        self.assertEqual(("".join(said), reply.stop_reason), ("Hi.", "end_turn"))

    def test_a_remote_brain_is_not_probed(self) -> None:
        calls: list = []

        def remote(request, timeout):
            calls.append(request.full_url)
            return Stream(sse({"choices": [{"delta": {"content": "Hi."}, "finish_reason": "stop"}]}))

        brain = api_brains.OpenAIBrain("https://api.example.com/v1", "sk-x", "m", "Example", remote)
        brain.turn([], [{"role": "user", "content": "hi"}], [], print)
        self.assertEqual(calls, ["https://api.example.com/v1/chat/completions"])


class FallbackTests(unittest.TestCase):
    def test_the_local_model_answers_when_omniroute_isnt_running(self) -> None:
        from agent import Agent
        from memory import Memory

        def refused(request, timeout):
            raise URLError("connection refused")

        agent = Agent(memory=Memory(os.path.join(tempfile.mkdtemp(), "m.sqlite3")))
        agent.cloud = api_brains.OpenAIBrain(GATEWAY, "", "auto", "OmniRoute · auto", refused)
        agent._chat = lambda messages, tools: {"message": {"content": "Answered on this PC.", "tool_calls": []}}
        answer = agent.ask("explain how photosynthesis works, step by step", lambda name, details: True)
        self.assertEqual(answer, "Answered on this PC.")
        self.assertIn("OmniRoute · auto isn't answering", agent._fallback)
        self.assertTrue(agent.router.is_offline())  # the gateway is not tried again for a while


if __name__ == "__main__":
    unittest.main()
