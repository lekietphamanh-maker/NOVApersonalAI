"""Countdown timers shown in Nova's HUD (after plip's timers in the notch)."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable


def describe(seconds: int) -> str:
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    parts = [f"{hours} hour{'s' * (hours != 1)}" if hours else "", f"{minutes} minute{'s' * (minutes != 1)}" if minutes else "",
             f"{seconds} second{'s' * (seconds != 1)}" if seconds else ""]
    return " ".join(part for part in parts if part) or "0 seconds"


class Timers:
    def __init__(self, on_change: Callable[[list[dict[str, Any]]], None], on_done: Callable[[dict[str, Any]], None],
                 clock: Callable[[], float] = time.time) -> None:
        self.on_change, self.on_done, self.clock = on_change, on_done, clock
        self._items: dict[int, dict[str, Any]] = {}
        self._threads: dict[int, threading.Timer] = {}
        self._next_id = 1
        self._lock = threading.Lock()

    def items(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._items.values()]

    def start(self, seconds: int, label: str = "") -> str:
        with self._lock:
            timer_id, self._next_id = self._next_id, self._next_id + 1
            self._items[timer_id] = {"id": timer_id, "label": label, "ends": int((self.clock() + seconds) * 1000), "done": False}
            ring = threading.Timer(seconds, self._ring, args=(timer_id,))
            ring.daemon = True
            self._threads[timer_id] = ring
        ring.start()
        self.on_change(self.items())
        return f"Timer set: {describe(seconds)}" + (f" for {label}." if label else ".")

    def cancel(self, label: str = "") -> str:
        matching = [item["id"] for item in self.items() if not label or label.casefold() in item["label"].casefold()]
        for timer_id in matching:
            self.cancel_id(timer_id)
        return f"Cancelled {len(matching)} timer{'s' * (len(matching) != 1)}." if matching else "There is no such timer."

    def cancel_id(self, timer_id: int) -> None:
        with self._lock:
            self._items.pop(timer_id, None)
            ring = self._threads.pop(timer_id, None)
        if ring is not None:
            ring.cancel()
        self.on_change(self.items())

    def _ring(self, timer_id: int) -> None:
        with self._lock:
            item = self._items.get(timer_id)
            if item is None:
                return
            item["done"] = True
            # A rung timer stays on screen for a minute, or until dismissed.
            dismiss = threading.Timer(60, self.cancel_id, args=(timer_id,))
            dismiss.daemon = True
            self._threads[timer_id] = dismiss
        dismiss.start()
        self.on_change(self.items())
        self.on_done(dict(item))
