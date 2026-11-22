"""News providers. Each one turns its API's answer into Articles and reports its own errors, so one failing
provider never stops the others."""
from __future__ import annotations
