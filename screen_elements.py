"""The controls of the user's window, numbered for the model.

The model picks "element 12" from this list; it never supplies coordinates. All
rectangles are physical desktop pixels measured by Windows UI Automation.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

MAX_ELEMENTS = 50
# Lower = kept first when a window has more controls than the model should read.
_ROLE_PRIORITY = {
    "Edit": 0, "ComboBox": 0, "Document": 0,
    "Button": 1, "Hyperlink": 1, "CheckBox": 1, "RadioButton": 1, "TabItem": 1, "SplitButton": 1,
    "MenuItem": 2, "ListItem": 2, "TreeItem": 2, "Slider": 2, "Spinner": 2, "DataItem": 2,
}
# Fields are often unnamed but still worth targeting; an unnamed button cannot be described.
_USEFUL_WITHOUT_NAME = {"Edit", "ComboBox", "Document"}


@dataclass(frozen=True)
class ScreenElement:
    element_id: int
    role: str
    name: str
    rect: tuple[int, int, int, int]  # left, top, right, bottom

    @property
    def center(self) -> tuple[int, int]:
        left, top, right, bottom = self.rect
        return (left + right) // 2, (top + bottom) // 2

    def describe(self) -> str:
        return f'{self.role} "{self.name}"' if self.name else self.role


@dataclass(frozen=True)
class ScreenContext:
    hwnd: int
    window_title: str
    elements: tuple[ScreenElement, ...]
    capture_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    captured_at: float = field(default_factory=time.time)

    def element(self, element_id: Any) -> ScreenElement | None:
        return next((item for item in self.elements if item.element_id == element_id), None)

    def prompt_text(self) -> str:
        lines = [f'[{item.element_id}] {item.describe()}' for item in self.elements]
        listing = "\n".join(lines) if lines else "(no controls found; the app may not expose UI Automation)"
        return f'SCREEN {self.capture_id}: window "{self.window_title}"\n{listing}'


def number_elements(raw_elements: Iterable[dict[str, Any]], limit: int = MAX_ELEMENTS) -> tuple[ScreenElement, ...]:
    """Drop noise and duplicates, keep the most useful roles, number in reading order."""
    seen_rects: set[tuple[int, int, int, int]] = set()
    kept: list[tuple[str, str, tuple[int, int, int, int]]] = []
    for item in raw_elements:
        role = str(item.get("role", ""))
        name = " ".join(str(item.get("name", "")).split())[:60]
        rect = tuple(int(value) for value in item["rect"])
        if role not in _ROLE_PRIORITY or (not name and role not in _USEFUL_WITHOUT_NAME):
            continue
        if rect[2] - rect[0] < 6 or rect[3] - rect[1] < 6 or rect in seen_rects:
            continue
        seen_rects.add(rect)
        kept.append((role, name, rect))

    if len(kept) > limit:
        kept = sorted(kept, key=lambda item: _ROLE_PRIORITY[item[0]])[:limit]
    # Reading order: rows of roughly 8 px, then left to right, so the numbers look sane.
    kept.sort(key=lambda item: (item[2][1] // 8, item[2][0]))
    return tuple(ScreenElement(index, role.lower(), name, rect) for index, (role, name, rect) in enumerate(kept, start=1))
