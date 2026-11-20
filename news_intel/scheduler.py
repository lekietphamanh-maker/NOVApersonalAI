"""When the daily run is due: at the set time (06:00 by default), once a day. A PC that was off or asleep at 06:00
catches up as soon as Nova runs. Nova checks this every minute; without Nova, use Windows Task Scheduler with
`python -m news_intel run` (see docs/NEWS.md)."""
from __future__ import annotations

from datetime import date, datetime, time


def run_time(text: str) -> time:
    try:
        hours, minutes = (int(part) for part in str(text).split(":")[:2])
        return time(hours % 24, minutes % 60)
    except (ValueError, TypeError):
        return time(6, 0)


def due(now: datetime, at: str, last_run_day: date | None) -> bool:
    """now is local time; last_run_day the local day of the last finished run."""
    return now.time() >= run_time(at) and last_run_day != now.date()
