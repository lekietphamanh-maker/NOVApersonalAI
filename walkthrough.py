"""Guided walkthroughs: Nova points at each step's control on the user's screen and moves on by itself
when the user has done the step.

The screen-change rule is plip's (github.com/hussainn7/plip-oss, buddy/watch.py, MIT): a step is done
once the window looks different enough from when the step started and has then held still (menus have
finished opening, the page has loaded). Nova's own overlays are excluded from screen capture.
"""
from __future__ import annotations

import base64
import re
import threading
from typing import Callable

from screen_assist import AssistError, ScreenAssist
from screen_elements import ScreenElement, number_elements

GLANCE_EVERY = 0.7   # seconds between looks
CHANGED = 4.0        # mean gray-level change (0-255) that counts as "something happened" (a menu, a new page)
SETTLED = 1.5        # change between two looks that counts as "still"
# Typing changes too few pixels for the mean, but changes them a lot; button hover tints change them a little.
STRONG_LEVEL, STRONG_CHANGED, STRONG_STILL = 40, 60, 20
STEP_TIMEOUT = 180   # a step not done in 3 minutes pauses the walkthrough
MAX_STEPS = 8
_QUOTED = re.compile(r"[\"“”]([^\"“”]{1,80})[\"“”]")
_NUMBERING = re.compile(r"^\s*(?:[-*•]|\d+[.)]|step\s*\d+[:.)]?)\s*", re.IGNORECASE)


def parse_steps(text: str) -> list[str]:
    steps = [_NUMBERING.sub("", line).strip()[:140] for line in str(text).splitlines()]
    return [step for step in steps if step][:MAX_STEPS]


def difference(a: bytes, b: bytes) -> float:
    """Mean absolute gray-level difference of two equal-size thumbnails, 0..255."""
    if not a or not b or len(a) != len(b):
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def strong_pixels(a: bytes, b: bytes) -> int:
    if not a or not b or len(a) != len(b):
        return len(a or b)
    return sum(1 for x, y in zip(a, b) if abs(x - y) > STRONG_LEVEL)


def find_control(elements: tuple[ScreenElement, ...], step: str) -> ScreenElement | None:
    """The control a step names in quotes: an exact name first, then one that starts with or contains it."""
    for wanted in (name.strip().casefold() for name in _QUOTED.findall(step)):
        for matches in (lambda name: name == wanted, lambda name: name.startswith(wanted), lambda name: wanted in name):
            found = next((element for element in elements if element.name and matches(element.name.casefold())), None)
            if found is not None:
                return found
    return None


def speakable_step(step: str) -> str:
    return _QUOTED.sub(r"\1", step)


class Walkthrough:
    def __init__(self, assist: ScreenAssist, hwnd: int, steps: list[str],
                 on_update: Callable[[int, str, str], None]) -> None:
        """on_update(step index, status, pointed control name); status is "step", "done", "paused" or "error"."""
        self.assist, self.hwnd, self.steps, self.on_update = assist, hwnd, steps, on_update
        self.stopped = threading.Event()
        self.skipped = threading.Event()  # the user pressed Next: count the step as done
        self.thread = threading.Thread(target=self._run, name="AlfredWalkthrough", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stopped.set()

    def next(self) -> None:
        self.skipped.set()

    def _run(self) -> None:
        try:
            for index, step in enumerate(self.steps):
                if self.stopped.is_set():
                    return
                self.on_update(index, "step", self._show(index, step))
                if not self._wait_for_change():
                    if not self.stopped.is_set():
                        self.on_update(index, "paused", "")
                    return
            self.assist.request({"cmd": "clear"})
            self.on_update(len(self.steps), "done", "")
        except AssistError as exc:
            self.on_update(0, "error", str(exc))

    def _show(self, index: int, step: str) -> str:
        """Point at the step's control (if it is on screen now) with the step written next to it."""
        self.assist.request({"cmd": "clear"})
        snapshot = self.assist.request({"cmd": "snapshot", "hwnd": self.hwnd})
        target = find_control(number_elements(snapshot["elements"]), step)
        label = f"Step {index + 1}/{len(self.steps)}"
        if target is not None:
            self.assist.request({"cmd": "highlight", "rect": list(target.rect), "label": label, "seconds": None, "style": "box"})
            self.assist.request({"cmd": "note", "rect": list(target.rect), "text": step, "seconds": None})
            return target.name
        left, top, right, _bottom = self.assist.request({"cmd": "glance", "hwnd": self.hwnd})["rect"]
        anchor = [left, top + 48, max(left + 20, right - 330), top + 60]  # top-right corner of the window
        self.assist.request({"cmd": "note", "rect": anchor, "text": f"{label}: {step}", "seconds": None})
        return ""

    def _glance(self) -> bytes:
        return base64.b64decode(self.assist.request({"cmd": "glance", "hwnd": self.hwnd})["glance"])

    def _wait_for_change(self) -> bool:
        baseline = previous = self._glance()
        changed = False
        for _look in range(int(STEP_TIMEOUT / GLANCE_EVERY)):
            if self.stopped.wait(GLANCE_EVERY):
                return False
            if self.skipped.is_set():
                self.skipped.clear()
                return True
            current = self._glance()
            if not changed:
                changed = difference(baseline, current) >= CHANGED or strong_pixels(baseline, current) >= STRONG_CHANGED
            elif difference(previous, current) <= SETTLED and strong_pixels(previous, current) < STRONG_STILL:
                return True
            previous = current
        return False
