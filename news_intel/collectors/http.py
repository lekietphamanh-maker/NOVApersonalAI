"""One HTTP client for every provider: timeouts, retries with back-off for passing failures (timeouts, 429, 5xx),
polite pacing per host, and API keys kept out of every message and log."""
from __future__ import annotations

import re
import time
from typing import Any

try:
    import httpx2 as httpx  # HTTPX's current line (the Anthropic SDK already ships it)
except ImportError:  # pragma: no cover - plain httpx works the same
    import httpx

USER_AGENT = "NovaNewsDesk/1.0 (personal news assistant)"
RETRY_STATUS = {429, 500, 502, 503, 504}
_SECRETS = re.compile(r"(apikey|api_key|token|key)=[^&\s]+", re.IGNORECASE)


def redact(text: str) -> str:
    return _SECRETS.sub(r"\1=***", str(text))


class FetchError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(redact(message))
        self.status = status


class Fetcher:
    def __init__(self, timeout: float = 20, retries: int = 2, client: Any = None, sleep=time.sleep) -> None:
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        self.retries = retries
        self.sleep = sleep
        self._last: dict[str, float] = {}

    def pace(self, host: str, seconds: float) -> None:
        """Wait so that requests to one host are at least `seconds` apart (GDELT asks for one every 5 s)."""
        wait = self._last.get(host, 0) + seconds - time.monotonic()
        if wait > 0:
            self.sleep(wait)
        self._last[host] = time.monotonic()

    def get(self, url: str, params: dict[str, Any] | None = None, accept: str = "*/*", every: float = 0) -> Any:
        """The response, after up to `retries` more tries for passing failures. Raises FetchError otherwise."""
        host = re.sub(r"^https?://([^/]+).*$", r"\1", url)
        for attempt in range(self.retries + 1):
            if every:
                self.pace(host, every)
            wait = min(30, 2 * 2 ** attempt)  # 2 s, 4 s, …
            try:
                response = self.client.get(url, params=params, headers={"Accept": accept})
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == self.retries:
                    raise FetchError(f"{host}: {type(exc).__name__}: {exc}") from None
            else:
                if response.status_code < 400:
                    return response
                if response.status_code not in RETRY_STATUS or attempt == self.retries:
                    raise FetchError(f"{host} answered HTTP {response.status_code}: {response.text[:200]}",
                                     response.status_code)
                retry_after = response.headers.get("Retry-After", "")
                if retry_after.isdigit() and int(retry_after) <= 60:
                    wait = max(wait, int(retry_after))
                elif response.status_code == 429:  # "too fast": a paced host (GDELT) gets a clearly longer break
                    wait = max(wait, 2 * every)
            self.sleep(wait)
        raise FetchError(f"{host}: no answer")  # pragma: no cover - the loop always returns or raises
