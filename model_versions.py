"""Custom versions of a local model, made with Ollama (/api/create): a base model plus Nova's own system prompt,
temperature and context length, saved under a new name ("nova-<name>"). The original model is never changed; only
"nova-" versions can be deleted from here. A LoRA adapter trained elsewhere goes in with a Modelfile (docs/MODELS.md).
"""
from __future__ import annotations

import re
from typing import Any, Callable

PREFIX = "nova-"


def version_name(name: str) -> str:
    """"Study buddy" → "nova-study-buddy" (Ollama names: lower case letters, digits, dashes, dots, underscores)."""
    slug = re.sub(r"[^a-z0-9._-]+", "-", str(name).strip().lower()).strip("-.")[:40]
    if not slug:
        raise ValueError("Give the version a name.")
    return slug if slug.startswith(PREFIX) else PREFIX + slug


def create_payload(base: str, name: str, system: str = "", temperature: float | None = None,
                   num_ctx: int | None = None) -> dict[str, Any]:
    if not base or base.startswith(PREFIX + PREFIX):
        raise ValueError("Choose the model to start from.")
    parameters: dict[str, Any] = {}
    if temperature is not None:
        if not 0 <= float(temperature) <= 2:
            raise ValueError("Temperature goes from 0 (steady) to 2 (very free).")
        parameters["temperature"] = round(float(temperature), 2)
    if num_ctx is not None:
        if not 2048 <= int(num_ctx) <= 32768:
            raise ValueError("Context goes from 2048 to 32768 tokens (8 GB of graphics memory fits about 8192 with a 4B model).")
        parameters["num_ctx"] = int(num_ctx)
    payload: dict[str, Any] = {"model": version_name(name), "from": base, "stream": False}
    if system.strip():
        payload["system"] = system.strip()[:4000]
    if parameters:
        payload["parameters"] = parameters
    return payload


def delete(delete_request: Callable[[str, dict], Any], base_url: str, name: str) -> None:
    if not name.split(":")[0].startswith(PREFIX):
        raise ValueError("Only Nova's own versions (nova-…) can be deleted here; original models stay as they are.")
    delete_request(f"{base_url}/api/delete", {"model": name})
