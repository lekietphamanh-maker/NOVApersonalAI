"""Nova's online brain: Claude in Anthropic's cloud, with the owner's own API key, while this PC is online.

SETTINGS → Claude chooses the model and effort (default Claude Sonnet 5.5 at medium). The answer streams in like the
local model's, so Nova speaks while Claude writes. brain_router decides which turns may come here; this module only
talks to the API, and turns every failure into Unavailable so the local model can answer instead.
"""
from __future__ import annotations

from typing import Any, Callable

MODELS = {"claude-sonnet-5-5": "Claude Sonnet 5.5", "claude-opus-5-5": "Claude Opus 5.5", "claude-haiku-5-5": "Claude Haiku 5.5"}
EFFORTS = ("low", "medium", "high")
DEFAULT_MODEL, DEFAULT_EFFORT = "claude-sonnet-5-5", "medium"
NO_SERVER_FALLBACK = {"claude-haiku-5-5"}  # Haiku 5.5 has no server-side refusal fallback
MAX_TOKENS = 16_000  # a cap, not a target: thinking counts toward it too


class Unavailable(Exception):
    """Claude couldn't answer (offline, key refused, busy, request refused): the local model answers instead."""

    def __init__(self, why: str, offline: bool = False) -> None:
        super().__init__(why)
        self.why = why
        self.offline = offline


def claude_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Nova's tool definitions (Ollama's format) as Claude tools. Inputs stream as they are written; the agent checks
    each one before running it."""
    return [{"name": tool["function"]["name"], "description": tool["function"]["description"],
             "input_schema": tool["function"]["parameters"], "eager_input_streaming": True} for tool in tools]


class CloudBrain:
    def __init__(self, key: str, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT, client: Any = None) -> None:
        import anthropic
        self.model = model if model in MODELS else DEFAULT_MODEL
        self.effort = effort if effort in EFFORTS else DEFAULT_EFFORT
        # A short connect timeout: with no internet the local model should take over within seconds.
        self.client = client or anthropic.Anthropic(api_key=key, max_retries=1, timeout=anthropic.Timeout(120.0, connect=4.0))

    @property
    def name(self) -> str:
        return MODELS[self.model]

    def _params(self, system: list[dict[str, Any]], messages: list[dict[str, Any]],
                tools: list[dict[str, Any]]) -> dict[str, Any]:
        params: dict[str, Any] = {"model": self.model, "max_tokens": MAX_TOKENS, "system": system, "messages": messages,
                                  "tools": list(tools), "output_config": {"effort": self.effort}}
        if self.model not in NO_SERVER_FALLBACK:
            # If Claude declines on a safety classifier, the API retries on a fallback model inside the same call.
            params.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        return params

    def turn(self, system: list[dict[str, Any]], messages: list[dict[str, Any]], tools: list[dict[str, Any]],
             on_text: Callable[[str], None], cancel: Any = None) -> Any:
        """One request, streamed: each piece of text goes to on_text. Returns the final message, or None when cancelled.
        A tool input the SDK can't parse at all raises ValueError (the caller asks again). Web searches are Nova's own
        (DuckDuckGo, free) among the tools: Claude's server-side search costs $10 per 1,000 searches."""
        import anthropic
        try:
            with self.client.beta.messages.stream(**self._params(system, messages, tools)) as stream:
                for event in stream:
                    if cancel is not None and cancel.is_set():
                        return None
                    if event.type == "text":
                        on_text(event.text)
                return stream.get_final_message()
        except anthropic.APIConnectionError as exc:  # also the connect timeout: no internet
            raise Unavailable("this PC is offline", offline=True) from exc
        except anthropic.AuthenticationError as exc:
            raise Unavailable("Claude rejected the API key (SETTINGS → Claude)") from exc
        except anthropic.PermissionDeniedError as exc:
            raise Unavailable(f"the API key can't use {self.name}") from exc
        except anthropic.RateLimitError as exc:
            raise Unavailable("Claude is busy right now (rate limit)") from exc
        except anthropic.BadRequestError as exc:
            raise Unavailable(f"Claude couldn't take the request ({exc.message})") from exc
        except anthropic.APIStatusError as exc:
            raise Unavailable(f"Claude had a problem ({exc.status_code})") from exc
