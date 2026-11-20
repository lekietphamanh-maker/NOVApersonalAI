"""Where Nova's tools are looked up: each feature registers its tool definitions with the function that runs them.

A tool is added in one place, its own module: define it, write `run(name, arguments, context)`, and
`register(DEFINITIONS, run)`. tools.execute_tool checks the arguments against the definition and calls `run`; the
ToolContext carries what a tool may need this turn (the owner's approval, and each feature's service, or None when
that feature is off).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ToolContext:
    memory: Any
    approve: Callable[[str, dict[str, Any]], bool]
    screen: Any = None
    creative: Any = None
    claude: bool = False
    gmail: Any = None
    brief: Callable[[], str] | None = None
    said: str = ""
    timers: Any = None
    fitness: Any = None
    notes: Any = None
    location: Any = None
    brain: Any = None
    tv: Any = None
    library: Any = None
    news: Any = None
    skills: Any = None
    deep_work: Callable[[str, str], str] | None = None
    web: Any = None
    reminders: Any = None
    build: Callable[[str, str], str] | None = None
    send_file: Callable[[str], str] | None = None
    calendar: Any = None
    reverse: Callable[[str, str], str] | None = None
    discover: Callable[[str, int], str] | None = None
    drive: Any = None
    world: Callable[[str, str, int], str] | None = None
    route: Callable[[str, str, list[str], str, bool], str] | None = None
    wikipedia: Callable[[str], str] | None = None
    notes_search: Callable[[str], str] | None = None
    obs_password: str = ""
    cloud: Callable[[str, str, dict[str, Any], str], str | None] | None = None  # cloud_tools: Claude does it instead
    optimize: Callable[[str, str, bool], str] | None = None  # prompt_optimizer, on the brain the owner uses


class NotHere(Exception):
    """A tool can't run on this PC right now (what it needs is missing); the message says why. execute_tool then asks
    Claude to do the job in the cloud when it may (cloud_tools)."""


Run = Callable[[str, dict[str, Any], ToolContext], str]
_RUNS: dict[str, Run] = {}
_DEFINITIONS: dict[str, dict[str, Any]] = {}


def register(definitions: list[dict[str, Any]], run: Run, validate: bool = True) -> None:
    """validate=False: the tool checks its own arguments (they aren't checked against its definition first)."""
    for definition in definitions:
        name = definition["function"]["name"]
        if name in _RUNS and _RUNS[name] is not run:
            raise ValueError(f"two tools are called {name}")
        _RUNS[name] = run
        if validate:
            _DEFINITIONS[name] = definition
        else:
            _DEFINITIONS.pop(name, None)


def run_for(name: str) -> Run | None:
    return _RUNS.get(name)


def definitions() -> dict[str, dict[str, Any]]:
    """The tools whose arguments are checked against their definition, by name."""
    return dict(_DEFINITIONS)


def names() -> set[str]:
    return set(_RUNS)
