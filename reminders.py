"""Reminders at a time of day ("at 5 pm call mom", "every Monday at 8 …"), kept in a file so they survive a restart.
A reminder whose time passed while the PC was off is said when Nova starts, once, marked as missed; a repeating one
then moves on to its next time. Timers (timers.py) are the countdown kind and stay as they are."""
from __future__ import annotations

import calendar
import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

REPEATS = ("none", "daily", "weekdays", "weekly", "monthly")
TIME_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")
LATE_MINUTES = 10  # said later than this (the PC was off or asleep): Nova says it was missed


@dataclass
class Reminder:
    id: int
    text: str
    at: str  # local time, "2026-11-20 17:00"
    repeat: str = "none"

    @property
    def when(self) -> datetime:
        return datetime.strptime(self.at, "%Y-%m-%d %H:%M")


def parse_time(text: str) -> datetime:
    """A local date and time the model wrote ("2026-11-20 17:00"), or ValueError saying the form it needs."""
    value = str(text).strip().replace("/", "-")
    for form in TIME_FORMATS:
        try:
            return datetime.strptime(value, form).replace(second=0, microsecond=0)
        except ValueError:
            continue
    raise ValueError(f'"{text}" isn\'t a date and time: give it as YYYY-MM-DD HH:MM, e.g. 2026-11-20 17:00')


def next_time(when: datetime, repeat: str) -> datetime:
    if repeat == "daily":
        return when + timedelta(days=1)
    if repeat == "weekdays":
        when += timedelta(days=1)
        while when.weekday() > 4:
            when += timedelta(days=1)
        return when
    if repeat == "weekly":
        return when + timedelta(days=7)
    if repeat == "monthly":
        year, month = (when.year + 1, 1) if when.month == 12 else (when.year, when.month + 1)
        return when.replace(year=year, month=month, day=min(when.day, calendar.monthrange(year, month)[1]))
    raise ValueError(f"{repeat} doesn't repeat")


class Reminders:
    def __init__(self, path: Path, clock: Callable[[], datetime] = datetime.now) -> None:
        self.path, self.clock = Path(path), clock
        self._lock = threading.Lock()
        self._items: list[Reminder] = self._load()

    def _load(self) -> list[Reminder]:
        try:
            return [Reminder(**item) for item in json.loads(self.path.read_text(encoding="utf-8"))]
        except (OSError, ValueError, TypeError):
            return []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(item) for item in self._items], ensure_ascii=False, indent=1), encoding="utf-8")

    def items(self) -> list[Reminder]:
        with self._lock:
            return sorted(self._items, key=lambda item: item.at)

    def add(self, text: str, when: str, repeat: str = "none") -> Reminder:
        text = " ".join(str(text).split())[:200]
        repeat = repeat if repeat in REPEATS else "none"
        moment = parse_time(when)
        if not text:
            raise ValueError("say what to remind about")
        if moment <= self.clock() and repeat == "none":
            raise ValueError(f"{moment:%A %d %B %H:%M} has already passed")
        while moment <= self.clock():  # "every day at 7" asked at 9: the first one is tomorrow
            moment = next_time(moment, repeat)
        with self._lock:
            reminder = Reminder(max((item.id for item in self._items), default=0) + 1, text, f"{moment:%Y-%m-%d %H:%M}", repeat)
            self._items.append(reminder)
            self._save()
        return reminder

    def cancel(self, words: str = "", reminder_id: int = 0) -> list[Reminder]:
        """Removes the reminders with this id, or whose text has these words (all of them when neither is given)."""
        wanted = str(words).lower().split()
        with self._lock:
            gone = [item for item in self._items
                    if (item.id == reminder_id if reminder_id else all(word in item.text.lower() for word in wanted))]
            self._items = [item for item in self._items if item not in gone]
            self._save()
        return gone

    def upcoming(self, hours: int = 72) -> list[dict[str, object]]:
        """Every time a reminder is due in the next `hours` (repeats expanded), for the cloud relay to say while the PC
        is off. key names one occurrence ("3@2026-11-20 17:00"); due is when, as Unix seconds."""
        end = self.clock() + timedelta(hours=hours)
        times: list[dict[str, object]] = []
        for item in self.items():
            moment = item.when
            while moment <= end and len(times) < 200:
                times.append({"key": f"{item.id}@{moment:%Y-%m-%d %H:%M}", "text": item.text, "due": int(moment.timestamp())})
                if item.repeat == "none":
                    break
                moment = next_time(moment, item.repeat)
        return sorted(times, key=lambda entry: entry["due"])

    def due(self) -> list[tuple[Reminder, bool]]:
        """The reminders whose time has come, each with whether it is late (missed while the PC was off). One-off ones
        are removed; repeating ones move to their next time still ahead."""
        now = self.clock()
        fired: list[tuple[Reminder, bool]] = []
        with self._lock:
            kept: list[Reminder] = []
            for item in self._items:
                if item.when > now:
                    kept.append(item)
                    continue
                fired.append((item, now - item.when > timedelta(minutes=LATE_MINUTES)))
                if item.repeat != "none":
                    moment = item.when
                    while moment <= now:
                        moment = next_time(moment, item.repeat)
                    kept.append(Reminder(item.id, item.text, f"{moment:%Y-%m-%d %H:%M}", item.repeat))
            if fired:
                self._items = kept
                self._save()
        return fired


def spoken(item: Reminder, late: bool) -> str:
    return f"Reminder, missed at {item.when:%H:%M}: {item.text}." if late else f"Reminder: {item.text}."


def describe(item: Reminder) -> str:
    every = {"none": "", "daily": ", every day", "weekdays": ", every weekday", "weekly": f", every {item.when:%A}",
             "monthly": f", on the {item.when.day} of every month"}[item.repeat]
    return f"{item.text}: {item.when:%A %d %B, %H:%M}{every}"
