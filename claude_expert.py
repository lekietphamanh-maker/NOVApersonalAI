"""Optional: send one hard question to Claude in Anthropic's cloud. Off unless a key is configured.

Desktop Edition only. The user approves the exact question text each time; nothing else is sent.
"""
from __future__ import annotations

import os
from pathlib import Path

import secret_store

MODEL = "claude-opus-5-5"
SYSTEM = ("You are helping Nova, a local desktop assistant, answer one hard question for its user. "
          "Answer completely and correctly. Show the key steps briefly. Write plain text that reads well aloud: "
          "no tables. The user's English may be imperfect; answer what they mean.")


def key_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Alfred" / "anthropic_api_key"


def _plain_key() -> str | None:
    try:
        raw = key_path().read_bytes()
    except OSError:
        return None
    # PowerShell's ">" writes UTF-16; Notepad may add a byte-order mark.
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig", errors="ignore")
    return text.strip() or None


def _stored_key() -> str | None:
    """The key, sealed for this account; a plain key file (an earlier build, or typed in by hand) is sealed on first use."""
    return secret_store.load_or_move("anthropic_api_key", _plain_key, key_path())


def available() -> bool:
    if os.environ.get("ALFRED_PORTABLE_EDITION") == "1":
        return False  # no cloud credentials on a USB drive
    return bool(os.environ.get("ANTHROPIC_API_KEY") or _stored_key())


def key() -> str | None:
    """The owner's Anthropic API key, or None (always None in the USB Edition)."""
    return (os.environ.get("ANTHROPIC_API_KEY") or _stored_key()) if available() else None


def key_hint() -> str:
    """'…a1B2': enough to recognise the key, never the key."""
    value = key()
    return f"…{value[-4:]}" if value else ""


def save_key(value: str) -> None:
    """Keep the key in this Windows user's folder (only on this PC; each PC gets its own)."""
    value = value.strip()
    if not value.startswith("sk-ant-") or len(value) < 30 or any(char.isspace() for char in value):
        raise ValueError("That doesn't look like an Anthropic API key (it starts with sk-ant-).")
    secret_store.save("anthropic_api_key", value)
    key_path().unlink(missing_ok=True)


def forget_key() -> None:
    secret_store.forget("anthropic_api_key")
    key_path().unlink(missing_ok=True)


def ask(question: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=_stored_key() or None, timeout=300.0)
    try:
        # Server-side fallback: if Claude declines on a safety classifier, the API retries on a fallback model.
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "high"},
            system=SYSTEM,
            messages=[{"role": "user", "content": question}],
        )
    except anthropic.AuthenticationError:
        return "Claude rejected the API key. Check the key file."
    except anthropic.RateLimitError:
        return "Claude is rate-limiting this key right now; try again in a minute."
    except anthropic.APIStatusError as exc:
        return f"Claude returned an error ({exc.status_code})."
    except anthropic.APIConnectionError:
        return "Could not reach Claude. Check the internet connection."
    if response.stop_reason == "refusal":
        return "Claude declined to answer this question."
    answer = "\n".join(block.text for block in response.content if block.type == "text").strip()
    if response.stop_reason == "max_tokens":
        answer += "\n(Claude's answer was cut off.)"
    return answer or "Claude returned no answer."
