"""News providers. Each one turns its API's answer into Articles and reports its own errors, so one failing
provider never stops the others."""
from __future__ import annotations

from typing import Protocol

from ..models import Article


class Collector(Protocol):
    name: str

    def collect(self) -> list[Article]:
        """Today's articles. Raises nothing for a single failed request: it is recorded in `errors`."""
        ...

    errors: list[str]
