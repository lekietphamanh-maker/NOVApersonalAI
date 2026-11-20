"""Instant commands: the everyday requests Nova does at once, without asking any AI.

"Set a timer for 5 minutes", "volume up", "pause", "next song", "what time is it", "open Spotify". Asking a model for
these costs seconds and sometimes gets them wrong. Only a short request that is wholly one of these counts: "set a
timer for 5 minutes and remind me to call mom" still goes to the model, and so does anything not matched exactly.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
           "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
           "forty five": 45, "forty-five": 45, "sixty": 60, "ninety": 90}
UNITS = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600}
# Programs opened by name, and what Windows starts for each (an App Paths name or a protocol). Only these: an unknown
# name goes to the model, which can look on the screen.
APPS = {"notepad": "notepad", "calculator": "calc", "calc": "calc", "paint": "mspaint", "spotify": "spotify:",
        "chrome": "chrome", "google chrome": "chrome", "edge": "msedge", "microsoft edge": "msedge", "firefox": "firefox",
        "word": "winword", "microsoft word": "winword", "excel": "excel", "powerpoint": "powerpnt", "outlook": "outlook",
        "file explorer": "explorer", "explorer": "explorer", "files": "explorer", "settings": "ms-settings:",
        "task manager": "taskmgr", "vs code": "code", "vscode": "code", "visual studio code": "code",
        "discord": "discord:", "obs": "obs64", "steam": "steam:", "teams": "msteams:", "zalo": "zalo"}
_NUMBER = r"\d+(?:\.\d+)?|" + "|".join(sorted((re.escape(word) for word in NUMBERS), key=len, reverse=True))
_UNIT = r"sec(?:ond)?s?|min(?:ute)?s?|h(?:ou)?rs?"
_LEAD = re.compile(r"^(?:(?:hey |ok |okay )?nova[,!.]?\s+)?(?:can you |could you |please )?", re.IGNORECASE)
_TAIL = re.compile(r"[\s,]*(?:please|thanks|thank you)?[\s.!?]*$", re.IGNORECASE)


@dataclass(frozen=True)
class Instant:
    tool: str                      # a Nova tool, or "time", "date", "open"
    arguments: dict[str, Any] = field(default_factory=dict)
    said: str = ""                 # what Nova says when it's done ("" = the tool's own answer)


def _clean(prompt: str) -> str:
    text = " ".join(str(prompt or "").split())
    return _TAIL.sub("", _LEAD.sub("", text)).lower()


def _seconds(amount: str, unit: str) -> int | None:
    value = float(amount) if re.fullmatch(r"\d+(?:\.\d+)?", amount) else NUMBERS.get(amount)
    size = next((seconds for name, seconds in UNITS.items() if unit.startswith(name[:3]) or unit.startswith(name[0] + "r")), None)
    if value is None or size is None:
        return None
    total = int(value * size)
    return total if 1 <= total <= 24 * 3600 else None


def _timer(text: str) -> Instant | None:
    found = (re.fullmatch(rf"(?:(?:set|start|make)(?: a| an| me a)? )?(?:a |an )?(?:timer|countdown)(?: for)? (?P<n>{_NUMBER}) (?P<u>{_UNIT})"
                          rf"(?: (?:for|called|named) (?:the |my )?(?P<label>[\w' -]{{1,30}}))?", text)
             or re.fullmatch(rf"(?:set |start )?(?:a |an )?(?P<n>{_NUMBER})[ -](?P<u>{_UNIT}) (?:timer|countdown)"
                             rf"(?: for (?:the |my )?(?P<label>[\w' -]{{1,30}}))?", text)
             or re.fullmatch(r"(?:set |start )?(?:a |an )?(?:timer|countdown) for (?P<half>half an hour)", text))
    if found is None:
        return None
    seconds = 1800 if found.groupdict().get("half") else _seconds(found["n"], found["u"])
    if seconds is None:
        return None
    label = (found.groupdict().get("label") or "").strip()
    minutes, rest = divmod(seconds, 60)
    return Instant("set_timer", {"minutes": minutes, "seconds": rest, **({"label": label} if label else {})})


VOLUME = {r"(?:turn (?:it|the volume|the sound|the music) up|volume up|louder|(?:make it )?louder)": ("volume_up", "Louder."),
          r"(?:turn (?:it|the volume|the sound|the music) down|volume down|quieter|softer|(?:make it )?quieter)":
              ("volume_down", "Quieter."),
          r"(?:mute|unmute|mute the sound|unmute the sound)": ("mute", "Done.")}
MEDIA = {r"(?:pause|pause the music|pause it|stop the music|play|play the music|resume|resume the music|keep playing)":
             ("play_pause", "Okay."),
         r"(?:next|next song|next track|skip|skip (?:this|it|the song|this song))": ("next", "Next one."),
         r"(?:previous|previous song|previous track|last song|go back a song|back a song)": ("previous", "Going back.")}


def match(prompt: str) -> Instant | None:
    """The instant command this request is, or None (then the AI answers it as usual)."""
    text = _clean(prompt)
    if not text or len(text.split()) > 10 or re.search(r"\b(and|then|also|after|but|if|when)\b", text):
        return None
    timer = _timer(text)
    if timer is not None:
        return timer
    if re.fullmatch(r"(?:cancel|stop|clear|delete)(?: the| my| all(?: the| my)?)? timers?", text):
        return Instant("cancel_timer", {"label": ""})
    for words, (action, said) in VOLUME.items():
        if re.fullmatch(rf"{words}(?: a (?:bit|little))?", text):
            return Instant("media_control", {"action": action, "times": 3 if action != "mute" else 1}, said)
        if re.fullmatch(rf"{words} a lot", text):
            return Instant("media_control", {"action": action, "times": 10}, said)
    for words, (action, said) in MEDIA.items():
        if re.fullmatch(words, text):
            return Instant("media_control", {"action": action}, said)
    if re.fullmatch(r"(?:what(?:'s| is) the time|what time is it(?: now)?|time|the time|tell me the time)", text):
        return Instant("time")
    if re.fullmatch(r"(?:what(?:'s| is) (?:the date|today'?s date|the date today)|what day is (?:it|today)"
                    r"|what(?:'s| is) today)", text):
        return Instant("date")
    opened = re.fullmatch(r"(?:open|launch|start|run)(?: up)? (?:the |my )?(?P<app>[a-z][a-z .]{1,30}?)(?: app)?", text)
    if opened and opened["app"].strip() in APPS:
        return Instant("open", {"app": opened["app"].strip()})
    return None


def open_app(name: str, run: Callable[..., Any] = subprocess.Popen) -> str:
    """Starts one of the known programs the way Start > Run does (Windows' own App Paths and protocols)."""
    target = APPS[name]
    if sys.platform != "win32":
        raise OSError("opening programs this way works on Windows")
    run(["cmd", "/c", "start", "", target], creationflags=subprocess.CREATE_NO_WINDOW)
    return f"Opening {name.title() if len(name) > 3 else name.upper()}."


def spoken_time(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"It's {now:%H:%M}."


def spoken_date(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"It's {now:%A, %d %B %Y}."
