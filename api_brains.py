"""The API brain: any AI provider's API, with the owner's own key. Claude goes through cloud_brain (Anthropic's SDK);
every other provider speaks the OpenAI chat format (OpenAI itself, Gemini, OpenRouter, Groq, DeepSeek, Mistral, xAI,
Together, or any OpenAI-compatible address such as LM Studio on this PC).

OpenAIBrain answers in the same shape as Claude's replies (text and tool_use blocks, a stop reason), so Nova's tool loop
in agent._ask_claude runs unchanged whichever provider answers.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cloud_brain import Unavailable


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    base_url: str
    kind: str = "openai"   # "anthropic" (Claude, through its SDK) or "openai" (the OpenAI chat format)
    hint: str = ""         # where the key comes from


PROVIDERS: tuple[Provider, ...] = (
    Provider("anthropic", "Claude (Anthropic)", "https://api.anthropic.com", "anthropic", "console.anthropic.com → API keys"),
    Provider("openai", "OpenAI (ChatGPT models)", "https://api.openai.com/v1", hint="platform.openai.com → API keys"),
    Provider("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", hint="aistudio.google.com → Get API key"),
    Provider("openrouter", "OpenRouter (hundreds of models)", "https://openrouter.ai/api/v1", hint="openrouter.ai → Keys"),
    Provider("groq", "Groq (very fast)", "https://api.groq.com/openai/v1", hint="console.groq.com → API keys"),
    Provider("deepseek", "DeepSeek", "https://api.deepseek.com/v1", hint="platform.deepseek.com → API keys"),
    Provider("mistral", "Mistral", "https://api.mistral.ai/v1", hint="console.mistral.ai → API keys"),
    Provider("xai", "xAI (Grok)", "https://api.x.ai/v1", hint="console.x.ai → API keys"),
    Provider("together", "Together AI", "https://api.together.xyz/v1", hint="api.together.ai → API keys"),
    Provider("custom", "Custom (any OpenAI-compatible address)", "", hint="the address of the server, e.g. http://localhost:1234/v1"),
)


def provider(key: str) -> Provider:
    return next((item for item in PROVIDERS if item.key == key), PROVIDERS[-1])


@dataclass
class Entry:
    """One API brain the owner added (its key is kept apart, sealed: secret_store, under api_key_<id>)."""
    id: str
    provider: str
    model: str
    base_url: str = ""
    label: str = ""

    @staticmethod
    def new(provider_key: str, model: str, base_url: str = "", label: str = "") -> "Entry":
        found = provider(provider_key)
        url = (base_url or found.base_url).strip().rstrip("/")
        if found.kind == "openai" and not re.match(r"^https?://", url):
            raise ValueError("give the provider's address, starting with https:// (or http:// for a server on this PC)")
        model = " ".join(str(model).split())[:120]
        if not model:
            raise ValueError("choose a model (Load models lists the ones your key can use)")
        return Entry(uuid.uuid4().hex[:8], found.key, model, url, " ".join(str(label).split())[:60] or f"{found.label.split(' (')[0]} · {model}")

    def as_dict(self) -> dict[str, str]:
        return {"id": self.id, "provider": self.provider, "model": self.model, "base_url": self.base_url, "label": self.label}


def entries(saved: Any) -> list[Entry]:
    found = []
    for item in saved if isinstance(saved, list) else []:
        try:
            found.append(Entry(str(item["id"]), str(item["provider"]), str(item["model"]), str(item.get("base_url") or ""),
                               str(item.get("label") or "")))
        except (KeyError, TypeError):
            continue
    return found


def _request(url: str, key: str, body: dict | None = None) -> Request:
    headers = {"Content-Type": "application/json", "User-Agent": "Nova"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers)


def _problem(exc: Exception, name: str) -> Unavailable:
    if isinstance(exc, HTTPError):
        if exc.code in (401, 403):
            return Unavailable(f"{name} rejected the API key (SETTINGS → API brain)")
        if exc.code == 429:
            return Unavailable(f"{name} is busy or out of credit right now (429)")
        try:
            detail = json.loads(exc.read() or b"{}").get("error", {})
            detail = detail.get("message") if isinstance(detail, dict) else str(detail)
        except (ValueError, OSError):
            detail = ""
        return Unavailable(f"{name} couldn't take the request ({exc.code}{f': {detail[:160]}' if detail else ''})")
    return Unavailable("this PC is offline, or the provider's address doesn't answer", offline=True)


def list_models(base_url: str, key: str, opener: Callable[..., Any] = urlopen) -> list[str]:
    """The models the key can use (the OpenAI-format /models list most providers have)."""
    try:
        with opener(_request(f"{base_url.rstrip('/')}/models", key), timeout=20) as response:
            data = json.loads(response.read())
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise _problem(exc, "The provider") from exc
    ids = [str(item.get("id")) for item in data.get("data", []) if isinstance(item, dict) and item.get("id")]
    return sorted(set(ids))[:400]


# ---------- the OpenAI chat format, in and out of Claude's shape ----------

def openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Claude-shaped tools (cloud_brain.claude_tools) as OpenAI function tools."""
    return [{"type": "function", "function": {"name": tool["name"], "description": tool.get("description", ""),
                                              "parameters": tool.get("input_schema") or {"type": "object", "properties": {}}}}
            for tool in tools]


def _field(block: Any, name: str, default: Any = None) -> Any:
    return block.get(name, default) if isinstance(block, dict) else getattr(block, name, default)


def openai_messages(system: Any, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Claude-shaped history (text, tool_use and tool_result blocks) as OpenAI chat messages."""
    text = system if isinstance(system, str) else "\n\n".join(str(_field(part, "text", "")) for part in system or [])
    out: list[dict[str, Any]] = [{"role": "system", "content": text}] if text else []
    for message in messages:
        content, role = message.get("content"), message.get("role")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "assistant":
            said = "".join(str(_field(block, "text", "")) for block in content if _field(block, "type") == "text")
            calls = [{"id": _field(block, "id"), "type": "function",
                      "function": {"name": _field(block, "name"), "arguments": json.dumps(_field(block, "input") or {})}}
                     for block in content if _field(block, "type") == "tool_use"]
            out.append({"role": "assistant", "content": said or None, **({"tool_calls": calls} if calls else {})})
            continue
        for block in content:
            kind = _field(block, "type")
            if kind == "tool_result":
                result = _field(block, "content", "")
                out.append({"role": "tool", "tool_call_id": _field(block, "tool_use_id"),
                            "content": result if isinstance(result, str) else json.dumps(result)})
            elif kind == "text":
                out.append({"role": "user", "content": _field(block, "text", "")})
    return out


STOPS = {"tool_calls": "tool_use", "function_call": "tool_use", "length": "max_tokens", "content_filter": "refusal"}


@dataclass
class OpenAIBrain:
    """An API brain on the OpenAI chat format, streamed. turn() returns Claude's shape: .content blocks, .stop_reason."""
    base_url: str
    key: str
    model: str
    label: str = "API brain"
    opener: Callable[..., Any] = field(default=urlopen, repr=False)
    plan = False
    sees_screen = False  # screenshots stay with Claude or the AI on this PC

    @property
    def name(self) -> str:
        return self.label

    def turn(self, system: Any, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
             on_text: Callable[[str], None], cancel: Any = None) -> Any:
        body = {"model": self.model, "messages": openai_messages(system, messages), "stream": True,
                **({"tools": openai_tools(tools)} if tools else {})}
        text: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        finish = "stop"
        try:
            with self.opener(_request(f"{self.base_url.rstrip('/')}/chat/completions", self.key, body), timeout=180) as response:
                for raw in response:
                    if cancel is not None and cancel.is_set():
                        return None
                    line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else str(raw).strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            text.append(delta["content"])
                            on_text(delta["content"])
                        for call in delta.get("tool_calls") or []:
                            slot = calls.setdefault(int(call.get("index", len(calls))), {"id": "", "name": "", "arguments": ""})
                            slot["id"] = call.get("id") or slot["id"]
                            function = call.get("function") or {}
                            slot["name"] += function.get("name") or ""
                            slot["arguments"] += function.get("arguments") or ""
                        finish = choice.get("finish_reason") or finish
        except (HTTPError, URLError, OSError) as exc:
            raise _problem(exc, self.label) from exc
        blocks: list[Any] = [SimpleNamespace(type="text", text="".join(text))] if text else []
        for index in sorted(calls):
            slot = calls[index]
            try:
                arguments: Any = json.loads(slot["arguments"] or "{}")
            except ValueError:
                arguments = slot["arguments"]  # the loop answers with INVALID_JSON and the model tries again
            blocks.append(SimpleNamespace(type="tool_use", id=slot["id"] or f"call_{index}", name=slot["name"], input=arguments))
        stop = "tool_use" if calls else STOPS.get(finish, "end_turn")
        return SimpleNamespace(content=blocks, stop_reason=stop)


def make_image(base_url: str, key: str, prompt: str, folder: Any, model: str = "gpt-image-1",
               opener: Callable[..., Any] = urlopen) -> Any:
    """An image from the prompt through an OpenAI-format images endpoint, saved as a PNG (Open-Generative-AI's idea,
    on the owner's own API brain). Returns the file's path."""
    import base64
    from datetime import datetime
    from pathlib import Path
    body = {"model": model, "prompt": " ".join(str(prompt).split())[:4000], "size": "1024x1024", "n": 1}
    try:
        with opener(_request(f"{base_url.rstrip('/')}/images/generations", key, body), timeout=240) as response:
            data = json.loads(response.read())
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise _problem(exc, "The image service") from exc
    item = (data.get("data") or [{}])[0]
    if item.get("b64_json"):
        picture = base64.b64decode(item["b64_json"])
    elif item.get("url"):
        with opener(Request(item["url"], headers={"User-Agent": "Nova"}), timeout=120) as response:
            picture = response.read()
    else:
        raise Unavailable("the image service sent no picture")
    target = Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"Image {datetime.now():%Y-%m-%d %H%M%S}.png"
    path.write_bytes(picture)
    return path
