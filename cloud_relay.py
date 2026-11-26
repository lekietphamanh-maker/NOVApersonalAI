"""Telegram while the PC is off: Nova puts a small relay (cloud/worker.js) on the owner's own free Cloudflare account.

Setting it up takes one Cloudflare API token (used once to deploy, never kept). Nova creates a KV store, uploads the
relay with its secrets, turns on its workers.dev address and a once-a-minute schedule. From then on the PC checks in
every few minutes (and once more on the way out) with what the relay needs to stand in: the owner's Telegram id, name,
what Nova remembers, and the reminders of the next three days. It gets back what was said while it was off.

What lives in the owner's Cloudflare account: that check-in, the bot token, the online brain's key (if one was chosen)
and the messages exchanged while the PC was off (until the PC reads them).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import secret_store

CLOUDFLARE = "https://api.cloudflare.com/client/v4"
SCRIPT_NAME = "nova-telegram"
KV_TITLE = "nova-telegram"
COMPATIBILITY_DATE = "2025-09-01"
WORKER_FILE = Path(__file__).resolve().parent / "cloud" / "worker.js"
BRAINS = {"claude": "claude-haiku-5-5", "ollama": "gpt-oss:120b", "none": ""}
TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9_-]{30,80}$")


class RelayError(RuntimeError):
    """Cloudflare or the relay said no, in words the owner can act on. Never carries a token."""


SECRET_NAME = "telegram_relay"


def secret_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Alfred" / "telegram_relay.json"


@dataclass(frozen=True)
class Relay:
    url: str
    secret: str
    brain: str = "none"

    def sync(self, body: dict[str, Any], opener: Callable[..., Any] = urlopen, timeout: float = 20) -> dict[str, Any]:
        """Checks in; returns {"away": [messages while off], "delivered": [reminder keys the relay sent]}."""
        request = Request(f"{self.url}/pc/sync", json.dumps(body).encode(),
                          {"Content-Type": "application/json", "Authorization": f"Bearer {self.secret}",
                           "User-Agent": "Nova"})
        try:
            with opener(request, timeout=timeout) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            raise RelayError(f"the relay said {exc.code}") from None
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise RelayError(f"couldn't reach the relay ({type(exc).__name__})") from None


def _plain() -> str | None:
    try:
        return secret_path().read_text(encoding="utf-8")
    except OSError:
        return None


def load() -> Relay | None:
    """The relay's address and secret, sealed for this account (a plain file from an earlier build is sealed once)."""
    try:
        data = json.loads(secret_store.load_or_move(SECRET_NAME, _plain, secret_path()) or "")
        return Relay(str(data["url"]), str(data["secret"]), str(data.get("brain", "none")))
    except (ValueError, KeyError, TypeError):
        return None


def save(relay: Relay) -> None:
    secret_store.save(SECRET_NAME, json.dumps({"url": relay.url, "secret": relay.secret, "brain": relay.brain}))
    secret_path().unlink(missing_ok=True)


def forget() -> None:
    secret_store.forget(SECRET_NAME)
    secret_path().unlink(missing_ok=True)


class Cloudflare:
    def __init__(self, token: str, opener: Callable[..., Any] = urlopen) -> None:
        self._token, self._open = token.strip(), opener

    def call(self, method: str, path: str, body: Any = None, form: tuple[bytes, str] | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self._token}", "User-Agent": "Nova"}
        data = None
        if form is not None:
            data, headers["Content-Type"] = form
        elif body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        try:
            with self._open(Request(f"{CLOUDFLARE}{path}", data, headers, method=method), timeout=60) as response:
                answer = json.loads(response.read())
        except HTTPError as exc:
            try:
                answer = json.loads(exc.read())
            except (ValueError, OSError):
                answer = {"success": False, "errors": [{"code": exc.code, "message": exc.reason}]}
        except (URLError, TimeoutError, OSError) as exc:
            raise RelayError(f"couldn't reach Cloudflare ({type(exc).__name__})") from None
        if not answer.get("success"):
            errors = answer.get("errors") or [{}]
            raise RelayError(f"Cloudflare said: {errors[0].get('message', 'no')} ({errors[0].get('code', '?')})")
        return answer.get("result")


def _module_upload(metadata: dict[str, Any], script: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\nContent-Type: application/json\r\n\r\n'
            f"{json.dumps(metadata)}\r\n"
            f'--{boundary}\r\nContent-Disposition: form-data; name="worker.js"; filename="worker.js"\r\n'
            f"Content-Type: application/javascript+module\r\n\r\n{script}\r\n--{boundary}--\r\n")
    return body.encode(), f"multipart/form-data; boundary={boundary}"


def deploy(cloudflare_token: str, bot_token: str, brain: str = "none", brain_key: str = "",
           opener: Callable[..., Any] = urlopen, script: str | None = None) -> Relay:
    """Puts the relay on the owner's Cloudflare account (again: the same name is replaced) and returns it."""
    if brain not in BRAINS:
        raise RelayError("Choose Claude, Ollama Cloud or no online brain for while the PC is off.")
    if brain != "none" and not brain_key.strip():
        raise RelayError("That online brain needs its key.")
    if not TOKEN_SHAPE.match(cloudflare_token.strip()):
        raise RelayError("That doesn't look like a Cloudflare API token (Cloudflare → My Profile → API Tokens).")
    cloud = Cloudflare(cloudflare_token, opener)
    accounts = cloud.call("GET", "/accounts")
    if not accounts:
        raise RelayError("This Cloudflare token can't see an account: give it Workers Scripts and Workers KV (Edit).")
    account = f"/accounts/{accounts[0]['id']}"
    try:
        subdomain = (cloud.call("GET", f"{account}/workers/subdomain") or {}).get("subdomain")
    except RelayError:
        subdomain = None
    if not subdomain:  # a new account has no workers.dev name yet
        subdomain = cloud.call("PUT", f"{account}/workers/subdomain", {"subdomain": f"nova-{secrets.token_hex(4)}"})["subdomain"]
    spaces = cloud.call("GET", f"{account}/storage/kv/namespaces?per_page=100") or []
    space = next((item["id"] for item in spaces if item.get("title") == KV_TITLE), None) or \
        cloud.call("POST", f"{account}/storage/kv/namespaces", {"title": KV_TITLE})["id"]
    url = f"https://{SCRIPT_NAME}.{subdomain}.workers.dev"
    relay = Relay(url, secrets.token_urlsafe(32), brain)
    bindings = [{"type": "kv_namespace", "name": "NOVA", "namespace_id": space},
                {"type": "plain_text", "name": "SELF_URL", "text": url},
                {"type": "plain_text", "name": "BRAIN", "text": brain},
                {"type": "plain_text", "name": "BRAIN_MODEL", "text": BRAINS[brain]},
                {"type": "secret_text", "name": "BOT_TOKEN", "text": bot_token},
                {"type": "secret_text", "name": "HOOK_SECRET", "text": secrets.token_urlsafe(32)},
                {"type": "secret_text", "name": "PC_SECRET", "text": relay.secret},
                {"type": "secret_text", "name": "BRAIN_KEY", "text": brain_key.strip() or "-"}]
    metadata = {"main_module": "worker.js", "compatibility_date": COMPATIBILITY_DATE, "bindings": bindings}
    code = script if script is not None else WORKER_FILE.read_text(encoding="utf-8")
    cloud.call("PUT", f"{account}/workers/scripts/{SCRIPT_NAME}", form=_module_upload(metadata, code))
    cloud.call("POST", f"{account}/workers/scripts/{SCRIPT_NAME}/subdomain", {"enabled": True, "previews_enabled": False})
    cloud.call("PUT", f"{account}/workers/scripts/{SCRIPT_NAME}/schedules", [{"cron": "* * * * *"}])
    return relay


def remove(cloudflare_token: str, opener: Callable[..., Any] = urlopen) -> None:
    """Takes the relay (and what it kept) off the owner's Cloudflare account."""
    cloud = Cloudflare(cloudflare_token, opener)
    account = f"/accounts/{cloud.call('GET', '/accounts')[0]['id']}"
    cloud.call("DELETE", f"{account}/workers/scripts/{SCRIPT_NAME}?force=true")
    for item in cloud.call("GET", f"{account}/storage/kv/namespaces?per_page=100") or []:
        if item.get("title") == KV_TITLE:
            cloud.call("DELETE", f"{account}/storage/kv/namespaces/{item['id']}")
