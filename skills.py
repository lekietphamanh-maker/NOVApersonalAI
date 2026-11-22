"""Skills: a task written down once, as a note in vault/skills/, that Nova runs when you say its phrase, press its
button or its time comes. What a skill makes is saved in vault/outputs/, so Obsidian shows it and Nova finds it again.
After the JARVIS "skill backbone": done by hand twice, make it a skill; when it works every time, put it on a schedule.

A skill note:

    ---
    title: Plan my day
    says: plan my day, what's my plan today
    schedule: daily 07:30          (manual, daily HH:MM, weekdays HH:MM, weekly <day> HH:MM, monthly <1-28> HH:MM)
    tools: weather, library, news  (empty: any tool)
    brain: auto                    (auto, local, or claude-code: long work on the owner's Claude Code plan)
    output: yes                    (save what it makes in outputs/)
    ---
    What to do, in plain words.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
BRAINS = ("auto", "local", "claude-code")
_SCHEDULE = re.compile(r"^(manual|daily|weekdays|weekly\s+(?P<day>[a-z]+)|monthly\s+(?P<date>\d{1,2}))"
                       r"(?:\s+(?P<hour>\d{1,2}):(?P<minute>\d{2}))?$")
EXTRA_WORDS = 5  # "plan my day please, Nova" still runs "plan my day"; a long sentence that mentions it doesn't


@dataclass
class Skill:
    name: str  # the note's file name: plan-today
    title: str
    says: list[str] = field(default_factory=list)
    schedule: str = "manual"
    tools: list[str] = field(default_factory=list)
    brain: str = "auto"
    output: bool = True
    instructions: str = ""


def check_schedule(text: str) -> str:
    """The schedule in its plain form, or ValueError saying how to write it."""
    schedule = " ".join(str(text).lower().split()) or "manual"
    match = _SCHEDULE.match(schedule)
    timed = bool(match and match.group("hour"))
    if (not match or (schedule != "manual") != timed or (match.group("day") and match.group("day") not in DAYS)
            or (match.group("date") and not 1 <= int(match.group("date")) <= 28)
            or (timed and (int(match.group("hour")) > 23 or int(match.group("minute")) > 59))):
        raise ValueError(f'"{text}" isn\'t a schedule: write manual, daily 07:30, weekdays 07:30, weekly sunday 18:00 '
                         "or monthly 1 09:00")
    return schedule


def slot_today(schedule: str, now: datetime) -> datetime | None:
    """When the skill is due today (None: not today, or manual)."""
    match = _SCHEDULE.match(schedule)
    if not match or schedule == "manual":
        return None
    kind = schedule.split()[0]
    if (kind == "weekdays" and now.weekday() > 4) or (kind == "weekly" and DAYS[now.weekday()] != match.group("day")) \
            or (kind == "monthly" and now.day != int(match.group("date"))):
        return None
    return now.replace(hour=int(match.group("hour")), minute=int(match.group("minute")), second=0, microsecond=0)


def parse(name: str, text: str) -> Skill | None:
    """A skill note, or None when it isn't one (no title)."""
    fields: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        head, _, body = text[3:].partition("\n---")
        for line in head.splitlines():
            key, _, value = line.partition(":")
            if key.strip():
                fields[key.strip().lower()] = value.strip()
    title = fields.get("title", "").strip()
    if not title:
        return None
    try:
        schedule = check_schedule(fields.get("schedule", "manual"))
    except ValueError:
        schedule = "manual"  # a typo in a hand-written note: the skill still runs by voice or button
    brain = fields.get("brain", "auto").lower()
    return Skill(name=name, title=title, says=_list(fields.get("says", "")), schedule=schedule,
                 tools=_list(fields.get("tools", "")), brain=brain if brain in BRAINS else "auto",
                 output=fields.get("output", "yes").lower() not in ("no", "false", "off"),
                 instructions=body.strip("\n -").strip())


def render(skill: Skill) -> str:
    return (f"---\ntitle: {skill.title}\nsays: {', '.join(skill.says)}\nschedule: {skill.schedule}\n"
            f"tools: {', '.join(skill.tools)}\nbrain: {skill.brain}\noutput: {'yes' if skill.output else 'no'}\n---\n"
            f"{skill.instructions.strip()}\n")


def _list(text: str) -> list[str]:
    return [item.strip().lower() for item in text.split(",") if item.strip()]


def _words(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.lower())


def slug(title: str) -> str:
    return "-".join(_words(title))[:60] or "skill"


class Skills:
    def __init__(self, vault: Path) -> None:
        self.vault = Path(vault)

    @property
    def folder(self) -> Path:
        return self.vault / "skills"

    @property
    def outputs(self) -> Path:
        return self.vault / "outputs"

    def ensure_defaults(self) -> None:
        """The first time: the folder with a few starting skills (never touched again: they are the owner's now)."""
        if self.folder.exists():
            return
        self.folder.mkdir(parents=True)
        for skill in DEFAULT_SKILLS:
            (self.folder / f"{skill.name}.md").write_text(render(skill), encoding="utf-8")

    def all(self) -> list[Skill]:
        found = []
        for path in sorted(self.folder.glob("*.md")) if self.folder.exists() else []:
            try:
                skill = parse(path.stem, path.read_text(encoding="utf-8"))
            except OSError:
                continue
            if skill is not None:
                found.append(skill)
        return found

    def get(self, name_or_title: str) -> Skill | None:
        wanted = slug(name_or_title)
        return next((skill for skill in self.all() if wanted in (skill.name, slug(skill.title))), None)

    def match(self, said: str) -> Skill | None:
        """The skill whose phrase is what the owner said (a few extra words like "please" are fine)."""
        words = _words(said)
        for skill in self.all():
            for phrase in skill.says:
                wanted = _words(phrase)
                if wanted and len(words) <= len(wanted) + EXTRA_WORDS and _contains(words, wanted):
                    return skill
        return None

    def add(self, title: str, instructions: str, says: str = "", schedule: str = "manual", tools: str = "",
            brain: str = "auto", output: bool = True) -> Skill:
        """A new skill note. ValueError for a missing title or instructions, a bad schedule, or a name already used."""
        title, instructions = " ".join(str(title).split())[:80], str(instructions).strip()[:4000]
        if not title or not instructions:
            raise ValueError("a skill needs a title and what to do")
        skill = Skill(name=slug(title), title=title, says=_list(says) or [title.lower()], schedule=check_schedule(schedule),
                      tools=_list(tools), brain=brain if brain in BRAINS else "auto", output=output, instructions=instructions)
        path = self.folder / f"{skill.name}.md"
        if path.exists():
            raise ValueError(f'there is already a skill called "{skill.name}"')
        self.folder.mkdir(parents=True, exist_ok=True)
        path.write_text(render(skill), encoding="utf-8")
        return skill

    def save_output(self, title: str, text: str, now: datetime | None = None) -> Path:
        """What a skill (or Claude Code) made: outputs/<date> <title>.md, never replacing an earlier one."""
        now = now or datetime.now()
        name = re.sub(r'[\\/:*?"<>|#^\[\]]', " ", title).strip()[:70] or "Output"
        path = self.outputs / f"{now:%Y-%m-%d} {name}.md"
        counter = 1
        while path.exists():
            counter += 1
            path = self.outputs / f"{now:%Y-%m-%d} {name} {counter}.md"
        self.outputs.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {title}\n\nMade by Nova {now:%Y-%m-%d %H:%M}\n\n{text.strip()}\n", encoding="utf-8")
        return path

    def due(self, now: datetime, last_runs: dict[str, str]) -> list[Skill]:
        """Scheduled skills whose time today has come and that haven't run since (a PC that was off catches up the same
        day, never days later)."""
        due = []
        for skill in self.all():
            slot = slot_today(skill.schedule, now)
            last = _when(last_runs.get(skill.name))
            if slot is not None and now >= slot and (last is None or last < slot):
                due.append(skill)
        return due


def _contains(words: list[str], wanted: list[str]) -> bool:
    return any(words[start:start + len(wanted)] == wanted for start in range(len(words) - len(wanted) + 1))


def _when(text: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(text) if text else None
    except ValueError:
        return None


def prompt(skill: Skill) -> str:
    """What the brain is asked when a skill runs."""
    tools = f"\nUse only these tools: {', '.join(skill.tools)}." if skill.tools else ""
    return (f'Run my skill "{skill.title}" now. Do exactly this, then give me the result, short and clear:\n\n'
            f"{skill.instructions}{tools}")


DEFAULT_SKILLS = (
    Skill("plan-today", "Plan my day", ["plan my day", "what's my plan today"], "daily 07:30",
          ["weather", "library", "news", "second_brain"], "auto", True,
          "Make my plan for today: the weather, what in my Library needs me (stalled builds and next steps), and the "
          "top 3 news stories that matter to me. End with the 3 things I should do first. A short list, no essay."),
    Skill("morning-brief", "Morning brief", ["morning brief", "bring up the morning brief"], "manual",
          ["daily_brief", "news", "weather"], "auto", True,
          "Give me my morning brief: the weather, the 5 most important news stories with one line each on why they "
          "matter, and anything new in my interests. Name the source of each story."),
    Skill("tidy-notes", "Tidy my notes", ["tidy my notes", "clean up my notes"], "weekly sunday 18:00",
          ["second_brain"], "auto", True,
          "Tidy my second brain: sum up what was gathered, ingest the new sources into the wiki, then tell me which "
          "topics grew this week and anything that looks duplicated."),
    Skill("weekly-review", "Weekly review", ["weekly review", "review my week"], "weekly friday 17:00",
          ["second_brain", "library"], "auto", True,
          "Review my week from my second brain and my Library: wins, what I learned, what is stuck and why, and my top "
          "3 for next week. Be honest about what slipped."),
)
