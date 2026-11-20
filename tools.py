"""Nova's tools: validated here; anything that changes, saves, searches or sends asks the user first."""
from __future__ import annotations

import re
from typing import Any, Callable, NamedTuple

import calendar_tools  # noqa: F401  (registers Google Calendar's tools)
import drive_tools  # noqa: F401  (registers Google Drive's tools)
from tool_registry import ToolContext, register, run_for
from tool_registry import definitions as registered_definitions
from memory import Memory
from screen_assist import ScreenSession, send_keys_spec


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": (
                "Save one task the user explicitly asked to add to their personal local task list. "
                "This writes only to the assistant's local SQLite database."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "A short, clear task requested by the user (up to 240 characters).",
                    }
                },
                "required": ["task"],
                "additionalProperties": False,
            },
        },
    }
]



def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required, "additionalProperties": False}}}


_ELEMENT = {"type": "integer", "description": "Element number from the newest SCREEN list."}
_TEXT = {"type": "string"}
# Offered only while screen assist is on. Drawing, reading and scrolling change nothing; clicking, typing, keys and
# opening go through the owner's approval, which on autopilot is a yes without a question (dashboard._confirm_action).
SCREEN_TOOLS: list[dict[str, Any]] = [
    _tool("point_at", "Point at one element on the user's real screen so they can find it. Does not click.",
          {"element": _ELEMENT, "label": {"type": "string", "description": "A 1-4 word label."},
           "style": {"type": "string", "enum": ["box", "arrow", "ring"], "description": "box (default), arrow or ring."}},
          ["element"]),
    _tool("pin_note", "Pin a short sticky note next to an element: a tip, formula or next step. Does not click.",
          {"element": _ELEMENT, "text": _TEXT}, ["element", "text"]),
    _tool("read_screen_text", "Read ALL the text of the user's app, scrolling down through it by itself, e.g. a whole homework sheet, article or document. Use it first whenever the owner asks you to review, check, explain or do what is on their screen.", {}, []),
    _tool("guide", "Teach the user to do something in their app step by step: a checklist on their screen, Nova points at "
          "each step's control and moves on by itself when they do it. One step per line (max 8), each naming the exact "
          "control in double quotes as written in SCREEN or as it will appear, e.g. Click \"File\". Does not click anything.",
          {"steps": _TEXT}, ["steps"]),
    _tool("click", "Click an element in the user's app with the real mouse. button: left (default), right or double.",
          {"element": _ELEMENT, "button": {"type": "string", "enum": ["left", "right", "double"]}}, ["element"]),
    _tool("type_text", "Click a text field, then type text into it.",
          {"element": _ELEMENT, "text": _TEXT}, ["element", "text"]),
    _tool("press_keys", "Press one key or shortcut, e.g. enter, tab, ctrl+l, ctrl+s, pagedown, win.",
          {"keys": _TEXT}, ["keys"]),
    _tool("scroll", "Scroll with the mouse wheel over an element (or the middle of the window when none is given). amount: notches, 1 to 15 (default 3). Changes nothing; look at the new SCREEN afterwards.",
          {"direction": {"type": "string", "enum": ["up", "down"]}, "amount": {"type": "integer"}, "element": _ELEMENT},
          ["direction"]),
    _tool("open_app", "Open a program by name (notepad, chrome, calc), a web address, a file or a folder, like Start > Run. The new window becomes the app you see and work in.", {"target": _TEXT}, ["target"]),
]
# Always offered.
GENERAL_TOOLS: list[dict[str, Any]] = [
    _tool("calculate", "Exact arithmetic: + - * / ^ %, parentheses, sqrt, sin, cos, log, pi... Use it for every calculation.",
          {"expression": _TEXT}, ["expression"]),
    _tool("web_search", "Search the web for current or factual information. The user approves each search.",
          {"query": _TEXT}, ["query"]),
    _tool("web", "Nova's own browser, out of sight: for research, reading whole pages, comparing sites or filling a simple "
          "web form, without touching the owner's screen or mouse. open (target: a web address), search (target: the "
          "words), read (part: the next part of a long page), click (target: a number from the list, or the words on the "
          "link or button), fill (target: a field's number or label; text: what to type, the option to pick, or yes/no "
          "for a tick box), press (target: a key such as Enter), back. Each answer shows the page text and its numbered "
          "links, buttons and fields. A fresh private session: the owner's own logins are not there.",
          {"action": {"type": "string", "enum": ["open", "search", "read", "click", "fill", "press", "back"]},
           "target": _TEXT, "text": _TEXT, "part": {"type": "integer"}}, ["action"]),
    _tool("media_control", "Control music and video on the PC: volume, mute, play/pause, next or previous song or video. "
          "Works with Spotify, YouTube in the browser and most players.",
          {"action": {"type": "string", "enum": ["volume_up", "volume_down", "mute", "play_pause", "next", "previous"]},
           "times": {"type": "integer", "description": "How many steps for volume (each is about 2%). Default 5."}},
          ["action"]),
    _tool("creative_mode", "Creative mode: a mirror view from the webcam with 3D holograms the user moves with their hands. "
          "open it, add a shape, explode or assemble the selected object, clear everything, look: name the "
          "objects the user is showing the camera (use look for 'what am I holding' / 'what is this'), photo: take a "
          "photo after a 3-2-1 countdown (describe=true when they also ask what's in it), lens: a live camera effect "
          "(normal, pixel, ascii, glitch, slitscan, echo), kiss_cam: two faces in the picture for 3 seconds and it "
          "takes a photo (on=false turns it off), style: how holograms look (wire: glowing wireframe, solid). Photos "
          "stay on this PC.",
          {"action": {"type": "string", "enum": ["open", "add", "explode", "assemble", "clear", "look", "photo", "lens",
                                                  "kiss_cam", "style"]},
           "style": {"type": "string", "enum": ["wire", "solid"]},
           "shape": {"type": "string", "enum": ["reactor", "cube", "sphere", "torus", "cone", "cylinder"]},
           "lens": {"type": "string", "enum": ["normal", "pixel", "ascii", "glitch", "slitscan", "echo"]},
           "on": {"type": "boolean"}, "describe": {"type": "boolean"}}, ["action"]),
    _tool("daily_brief", "Today's brief for the user: top headlines, news on their interests, new GitHub repos they may like, "
          "Hacker News and on this day. Use it when they ask what's new, for news or for something fun.", {}, []),
]
# Memory and timers, after plip's (github.com/hussainn7/plip-oss, MIT): memory changes only when the
# user's own words ask for it, so text on a screen or web page can never plant or wipe a fact.
PERSONAL_TOOLS: list[dict[str, Any]] = [
    _tool("remember", "Remember one fact about the user for future chats (their name, preferences, people, routines). "
          "Only when the user's own words ask you to remember it.", {"fact": _TEXT}, ["fact"]),
    _tool("forget", "Forget the remembered facts that contain these words, when the user asks you to forget something.",
          {"what": _TEXT}, ["what"]),
    _tool("set_timer", "Start a countdown timer on Nova's screen; Nova says when it is done. Give minutes and/or seconds.",
          {"minutes": {"type": "integer"}, "seconds": {"type": "integer"},
           "label": {"type": "string", "description": "What it is for, e.g. pasta. Optional."}}, []),
    _tool("cancel_timer", "Cancel the timer with this label, or every timer when no label is given.", {"label": _TEXT}, []),
    _tool("mind_map", "Brainstorm on the user's screen: a topic in a glowing core with ideas around it and sub-ideas "
          "branching out. Use it when the user asks to brainstorm, plan, map out, organize or visualize ideas. "
          "ideas: one per line, 'Idea > sub-idea' for a sub-idea; up to 12 ideas with up to 4 sub-ideas each, a few words each.",
          {"topic": _TEXT, "ideas": _TEXT}, ["topic", "ideas"]),
    _tool("add_to_map", "Add ideas to the user's brainstorm map without replacing it: under an existing idea (give its name) "
          "or, with under empty, as main ideas around the topic. Use it when the user asks to add, expand or grow ideas on the map.",
          {"under": _TEXT, "ideas": {"type": "string", "description": "One idea per line, a few words each, up to 8."}}, ["ideas"]),
    _tool("fitness_status", "The user's live heart rate from their Bluetooth band: now, average, lowest, highest, "
          "and heart rate variability. Use it when they ask about their heart rate, workout or how they are doing.", {}, []),
]
# Shows something big on the TV that shows Nova's dashboard (screens.py).
TV_TOOL = _tool("show_on_tv", "Show something big on the TV next to Nova's dashboard when the owner asks to put it on "
                "the TV / big screen: a title and the text (e.g. your last answer, a list, a recipe).",
                {"title": _TEXT, "text": _TEXT}, ["text"])
# Offered while the second brain is on (Obsidian notes of what the owner reads and watches on this PC).
SECOND_BRAIN_TOOLS: list[dict[str, Any]] = [
    _tool("second_brain", "The owner's second brain: an Obsidian vault with raw/ sources (what they read and watch on "
          "this PC, summed up every 20 minutes, plus clips and files) and a wiki/ of linked topic pages. recall: look "
          "things up to answer 'what did I read / watch / learn about X' (text: the question); add: save a note they "
          "dictate (text); clip: keep the page they are reading ('save this to my second brain'); ingest: turn new "
          "sources in raw/ into wiki pages ('ingest this'); summarize_now; pause or resume watching.",
          {"action": {"type": "string", "enum": ["recall", "add", "clip", "ingest", "summarize_now", "pause", "resume"]},
           "text": _TEXT}, ["action"]),
]
# The owner's library: their projects, repos and ideas to build, by topic, in the second brain vault. This PC only.
LIBRARY_TOOL = _tool(
    "library", "The owner's library of their own projects, repos and ideas to build, sorted by topic (in their second "
    "brain). open: show the Library on screen (text: a topic, project or idea to jump to, optional). add: save a new "
    "project or idea (title, topic, status: idea (default), building, shipped or paused; repo: a web link or a folder; "
    "next: the next step; note). update: change one, found by its title (only what changes; a note is added to its "
    "notes). needs: what needs the owner now (stalled builds, next steps, ideas to decide on). topic: what is in one "
    "topic (text: the topic). Saving or changing asks the owner first.",
    {"action": {"type": "string", "enum": ["open", "add", "update", "needs", "topic"]}, "title": _TEXT, "text": _TEXT,
     "topic": _TEXT, "status": {"type": "string", "enum": ["idea", "building", "shipped", "paused"]}, "repo": _TEXT,
     "next": _TEXT, "note": _TEXT}, ["action"])
# Nova's news database (news_intel): collected every morning, summarized and scored. Not personal: both brains get it.
NEWS_CATEGORIES = ["world", "politics", "business", "finance", "technology", "ai", "science", "health", "entertainment",
                   "sports", "environment", "education", "general"]
NEWS_TOOL = _tool(
    "news", "Nova's news database, collected every morning from GNews, GDELT and news sites (each article with its "
    "summary, key facts and importance). Use it for current events: what happened today or this week, a topic, a "
    "company or person, why something matters, or comparing periods (call it twice). query: names or words to look for "
    "(empty for the top stories); category: optional; days: how far back (1 today, 7 a week, 30 a month); offset_days: "
    "start that many days ago (e.g. 30 for last month). Cite each article you use by title, publisher, date and link.",
    {"query": _TEXT, "category": {"type": "string", "enum": NEWS_CATEGORIES},
     "days": {"type": "integer"}, "offset_days": {"type": "integer"}}, [])
# Offered once Nova has a location store (it starts empty: weather and local_news then ask for a city).
LOCATION_TOOLS: list[dict[str, Any]] = [
    _tool("weather", "The weather where the owner is: now, today and the next two days (temperature, sky, chance of rain, "
          "wind). Use it for weather, temperature, rain, umbrella or what-to-wear questions. Their place is already "
          "known: never ask where they are. place: only for somewhere else they ask about (a trip, another city); "
          "leave it out for their own weather. It doesn't change their saved location.",
          {"place": {"type": "string", "description": "Another city, only when asked about one."}}, []),
    _tool("local_news", "Today's local news headlines where the owner is.", {}, []),
    _tool("set_location", "Change where the owner is, only when they say they are now somewhere new (for example "
          "'I moved to Sydney' or 'I'm in Hanoi this week'). Not for another city's weather (use weather's place) and "
          "not for the place already saved. place: the city, plus the country if they said it. The owner approves it "
          "first.", {"place": _TEXT}, ["place"]),
]
_REMEMBER = re.compile(r"\b(remember|don'?t forget|keep in mind|note (that|this|down)|make a note|save (that|this)|from now on|"
                       r"always|my name is|call me|i (am|live|work|prefer|like|love|hate))\b|nhớ|ghi nhớ", re.IGNORECASE)
_FORGET = re.compile(r"\b(forget|delete|remove|erase|clear|wipe|don'?t remember|stop remembering)\b|quên|xoá|xóa", re.IGNORECASE)
# Offered only when the user has configured a Claude key (Desktop Edition).
CLAUDE_TOOL = _tool("ask_claude", "Send one hard question (math, science, code, essays) to Claude, a stronger cloud AI. "
                    "Include everything it needs in the question. The user approves the exact text first.",
                    {"question": _TEXT}, ["question"])
# Offered only when Gmail is connected (Desktop Edition). Nova can draft but never send.
GMAIL_TOOLS: list[dict[str, Any]] = [
    _tool("list_unread_mail", "List the user's unread Gmail inbox, numbered.", {}, []),
    _tool("read_mail", "Read one mail by its number from the last list.", {"number": {"type": "integer"}}, ["number"]),
    _tool("draft_mail", "Save a Gmail draft for the user to review and send themselves. The user approves the exact text. "
          "To reply, set reply_to_number to the mail's number from the last list (to and subject may then be empty).",
          {"to": _TEXT, "subject": _TEXT, "body": _TEXT, "reply_to_number": {"type": "integer"}}, ["body"]),
]
# Skills (skills.py): tasks written down once in the vault, and Claude Code for long work (claude_code.py).
SKILLS_TOOL = _tool(
    "skills", "The owner's skills: tasks written down once in their vault (skills/), each run by a spoken phrase, a "
    "button or a schedule. list: the skills there are. run: get one skill's instructions (name) and do them now. add: "
    "make a new skill when the owner asks for one (title; instructions: what to do, in plain words; says: phrases that "
    "run it, comma-separated; schedule: manual, daily 07:30, weekdays 07:30, weekly sunday 18:00 or monthly 1 09:00). "
    "save: keep a result in the vault's outputs/ (title, text).",
    {"action": {"type": "string", "enum": ["list", "run", "add", "save"]}, "name": _TEXT, "title": _TEXT,
     "instructions": _TEXT, "says": _TEXT, "schedule": _TEXT, "text": _TEXT}, ["action"])
DEEP_WORK_TOOL = _tool(
    "deep_work", "Hand a big piece of real work to Claude Code, on the owner's Claude plan: an explainer, a research "
    "report, a long document or comparison that needs many minutes of research and writing. It works in the background; "
    "the result is saved in the vault's outputs/ and the owner is told when it is ready. Not for quick questions.",
    {"title": _TEXT, "task": {"type": "string", "description": "Everything Claude Code needs to know to do the work."}},
    ["title", "task"])
BUILD_TOOL = _tool(
    "build", "Build or change a small software project with Claude Code, on the owner's Claude plan: a website, a "
    "script, a small app. It works in the project's own folder (Documents/Nova Projects/<name>), writing and editing "
    "files there only, and Nova opens the result when it is done. The same name goes on with the same project. Put "
    "everything it needs in task; don't ask the owner for details you can decide.",
    {"name": {"type": "string", "description": "A short project name, e.g. portfolio site."},
     "task": {"type": "string", "description": "What to build or change, in full."}}, ["name", "task"])
REMINDER_TOOL = _tool(
    "reminder", "Reminders at a time of day, kept even when the PC restarts (for a countdown like 'in 10 minutes' use "
    "set_timer). add: text and when (the owner's local date and time as YYYY-MM-DD HH:MM, worked out from Now), "
    "repeat: none (default), daily, weekdays, weekly or monthly. list: the reminders ahead. cancel: the ones whose "
    "text has these words (text).",
    {"action": {"type": "string", "enum": ["add", "list", "cancel"]}, "text": _TEXT, "when": _TEXT,
     "repeat": {"type": "string", "enum": ["none", "daily", "weekdays", "weekly", "monthly"]}}, ["action"])
# Offered only while the owner is messaging Nova from Telegram (telegram_remote): the file goes to their own chat.
SEND_FILE_TOOL = _tool(
    "send_file", "Send one of the owner's own files to their Telegram chat, found by its name in Desktop, Documents, "
    "Downloads, Pictures, Videos or Music (newest match first). Use it when they ask you to send them a file.",
    {"name": {"type": "string", "description": "Words from the file's name, e.g. report or budget 2026."}}, ["name"])
REVERSE_TOOL = _tool(
    "reverse_engineer", "Reverse engineer an app, a site, a file or a project the owner is allowed to analyse, with REA "
    "through Claude Code, in the background: how it is built and how a part of it works. The report goes to outputs/ "
    "and the Library. target: a path on this PC, an installed app's name or folder, or a web address. goal: what they "
    "want to know.", {"target": _TEXT, "goal": _TEXT}, ["target"])
DISCOVER_TOOL = _tool(
    "discover", "GitHub projects the owner might like, picked from their interests and their own GitHub. list: the "
    "current suggestions, numbered. add: study suggestion number n (read-only) and propose how Nova could use it; "
    "nothing is installed into Nova. skip: not for me, number n.",
    {"action": {"type": "string", "enum": ["list", "add", "skip"]}, "number": {"type": "integer"}}, ["action"])
WORLD_TOOL = _tool(
    "world", "What's happening on Earth right now, from live public feeds and the news desk: earthquakes, disaster "
    "alerts, storms, wildfires, volcanoes, and news and conflict by country. Nova's World view (a globe) flies to the "
    "place. brief: say what's happening there; show: only open the globe there. place: a country, city or region "
    "(e.g. the Middle East, Japan, Europe), empty for the whole world. days: 1 (default) or up to 7.",
    {"action": {"type": "string", "enum": ["brief", "show"]}, "place": _TEXT, "days": {"type": "integer"}}, ["action"])
ROUTE_TOOL = _tool(
    "route", "The fastest way on real roads from one place to another, through any stops, worked out on this PC from "
    "OpenStreetMap; Nova's screen shows it on a map. start and end: place names (a district, street, landmark or "
    "address). stops: places to pass on the way, comma-separated. mode: motorbike (default), car or walk. "
    "best_order: put the stops in the quickest order (default true).",
    {"start": _TEXT, "end": _TEXT, "stops": _TEXT, "mode": {"type": "string", "enum": ["motorbike", "car", "walk"]},
     "best_order": {"type": "boolean"}}, ["start", "end"])
SKILL_TOOLS = [SKILLS_TOOL, DEEP_WORK_TOOL, BUILD_TOOL, REMINDER_TOOL, SEND_FILE_TOOL, REVERSE_TOOL, DISCOVER_TOOL, WORLD_TOOL,
               ROUTE_TOOL]




def execute_web_tool(arguments: dict[str, Any], approve: Callable[[str, dict[str, Any]], bool], web: Any) -> str:
    action, target, text = str(arguments["action"]), str(arguments.get("target") or "").strip(), str(arguments.get("text") or "")
    if action in ("open", "search", "click", "fill", "press") and not target:
        return f"Not done: {action} needs a target."
    try:
        if action == "open":
            from web_tasks import web_address
            return web.open(web_address(target))
        if action == "search":
            return web.search(target)
        if action == "read":
            return web.read(int(arguments.get("part") or 1))
        if action == "back":
            return web.back()
    except ValueError as exc:
        return f"Not done: {exc}."
    summary = {"click": f"On a web page in Nova's own browser: click {target}",
               "fill": f"On a web page in Nova's own browser: put “{text[:200]}” in {target}",
               "press": f"On a web page in Nova's own browser: press {target}"}[action]
    if not approve("web", {"summary": summary}):
        return "The owner declined; nothing was done."
    if action == "click":
        return web.click(target)
    if action == "fill":
        return web.fill(target, text)
    return web.press(target)


def execute_reminder_tool(arguments: dict[str, Any], reminders: Any) -> str:
    from reminders import describe
    action, text = str(arguments["action"]), str(arguments.get("text") or "")
    if action == "list":
        return "\n".join(f"- {describe(item)}" for item in reminders.items()) or "No reminders ahead."
    if action == "cancel":
        gone = reminders.cancel(text)
        return ("Cancelled: " + "; ".join(describe(item) for item in gone)) if gone else "No reminder matched that."
    try:
        item = reminders.add(text, str(arguments.get("when") or ""), str(arguments.get("repeat") or "none"))
    except ValueError as exc:
        return f"Not set: {exc}."
    return f"Reminder set: {describe(item)}. Nova will say it out loud then."


def execute_skills_tool(arguments: dict[str, Any], approve: Callable[[str, dict[str, Any]], bool], skills: Any) -> str:
    from skills import prompt
    action = str(arguments["action"])
    if action == "list":
        found = skills.all()
        return "\n".join(f"- {skill.title} ({skill.name}): says “{', '.join(skill.says)}”, {skill.schedule}"
                         + (", on Claude Code" if skill.brain == "claude-code" else "") for skill in found) or "No skills yet."
    if action == "run":
        skill = skills.get(str(arguments.get("name") or arguments.get("title") or ""))
        if skill is None:
            return "There is no skill by that name. Use action list to see them."
        if skill.brain == "claude-code":
            return f"This skill is long work: call deep_work with title \"{skill.title}\" and these instructions:\n\n{skill.instructions}"
        return prompt(skill) + "\n\nWhen it is done, call skills with action save to keep the result in outputs/."
    if action == "save":
        text = str(arguments.get("text") or "").strip()
        if not text:
            return "Nothing to save."
        return f"Saved in outputs/{skills.save_output(str(arguments.get('title') or 'Skill result'), text).name}."
    title = str(arguments.get("title") or "")
    if not approve("skills", {"summary": f"Make a new skill: {title}\n\n{arguments.get('instructions', '')}"}):
        return "The owner declined; no skill was made."
    try:
        skill = skills.add(title, str(arguments.get("instructions") or ""), str(arguments.get("says") or ""),
                           str(arguments.get("schedule") or "manual"))
    except ValueError as exc:
        return f"Not made: {exc}."
    return (f"Made the skill “{skill.title}” (skills/{skill.name}.md). Say “{skill.says[0]}” to run it"
            + (f"; it also runs {skill.schedule}." if skill.schedule != "manual" else "."))


def execute_brain_tool(arguments: dict[str, Any], brain: Any) -> str:
    """The second brain's notes for Nova's answers; adding, summing up, pausing."""
    if brain is None:
        return "The second brain is off. The owner can turn it on in SETTINGS → Second brain."
    action = arguments["action"]
    if action == "recall":
        return brain.recall(arguments.get("text", ""))
    if action == "clip":
        return brain.clip()
    if action == "ingest":
        return brain.ingest()
    if action == "add":
        return brain.add_note(arguments.get("text", ""))
    if action == "summarize_now":
        return brain.summarize_now()
    if action == "pause":
        brain.stop()
        return "Paused: Nova stopped reading the screen and listening to videos (what was gathered is being summed up)."
    brain.start()
    return "Resumed: Nova is keeping the second brain again."


def execute_library_tool(arguments: dict[str, Any], approve: Callable[[str, dict[str, Any]], bool], library: Any) -> str:
    """The library through Nova: open it on screen, read what needs the owner, save or change a project (with an OK)."""
    if library is None:
        return "The library is not available here."
    shelf = library.library()
    action = arguments["action"]
    named = " ".join(str(arguments.get("title") or arguments.get("text") or "").split())[:80]
    try:
        if action == "open":
            return library.open(named or str(arguments.get("topic") or ""))
        if action == "needs":
            return shelf.needs_text()
        if action == "topic":
            topic = " ".join(str(arguments.get("text") or arguments.get("topic") or "").split())[:80]
            return shelf.topic_text(topic) if topic else "Say which topic."
        if not named:
            return "Not saved: give the project or idea a title."
        fields = {key: " ".join(str(arguments[key]).split()) if key != "note" else str(arguments[key]).strip()
                  for key in ("status", "topic", "repo", "next", "note") if arguments.get(key)}
        shown = "\n".join(f"{key.capitalize() if key != 'next' else 'Next step'}: {value}" for key, value in fields.items())
        if action == "add":
            fields.setdefault("status", "idea")
            if not approve("library", {"summary": f"Save this to your library:\n\n{named}\n{shown}"}):
                return "The owner declined; nothing was saved."
            project = shelf.save(named, new=True, **fields)
            library.changed()
            return f"Saved {project.title} ({project.status}) under {shelf.topic_name(project.topic)} in the library."
        existing = shelf.find(named)
        if existing is None:
            return f"There is nothing called {named} in the library. Projects: " + (
                ", ".join(project.title for project in shelf.projects()[:15]) or "none yet") + "."
        if not fields:
            return "Say what to change: status, topic, repo, next step or a note."
        if "note" in fields:
            fields["note"] = f"{existing.note}\n\n{fields['note']}".strip()
        if not approve("library", {"summary": f"Change “{existing.title}” in your library:\n\n{shown}"}):
            return "The owner declined; nothing was changed."
        project = shelf.save(existing.title, previous=existing.title, **fields)
        library.changed()
        return f"Updated {project.title}: {project.status}" + (f", next: {project.next}" if project.next else "") + "."
    except ValueError as exc:
        return f"Not saved: {exc}"
    except OSError as exc:
        return f"The library couldn't be written: {exc}"


def execute_location_tool(name: str, arguments: dict[str, Any], approve: Callable[[str, dict[str, Any]], bool],
                          location: Any) -> str:
    """Weather and local news for the saved place; set_location only with the owner's OK."""
    if location is None:
        return "Location is not available here."
    try:
        if name == "weather":
            return location.weather_text(str(arguments.get("place") or ""))
        if name == "local_news":
            return location.news_text()
        place = " ".join(str(arguments["place"]).split())[:80]
        if not place:
            return "Not saved: give a city."
        if location.is_saved(place):  # nothing to ask: it is already the owner's place
            from location import label
            return f"{label(location.place)} is already the owner's saved location; nothing changed."
        summary = (f"Use “{place}” as your location for the weather and local news? Nova looks it up with Open-Meteo; "
                   "the weather then comes from Open-Meteo and local news from Google News. It is kept only in Nova's "
                   "settings on this PC.")
        if not approve(name, {"summary": summary}):
            return "The owner declined; the location was not changed."
        from location import label
        return f"Location saved: {label(location.set_city(place))}."
    except Exception as exc:  # offline, unknown place, service down
        return f"Couldn't get that: {exc}"


def _expected(name: str) -> tuple[set[str], set[str]] | None:
    """The argument names a registered tool takes, and the ones it needs."""
    definition = registered_definitions().get(name)
    if definition is None:
        return None
    parameters = definition["function"]["parameters"]
    return set(parameters["properties"]), set(parameters["required"])


def _invalid_arguments(name: str, arguments: Any) -> str | None:
    allowed, required = _expected(name)
    if not isinstance(arguments, dict) or not required <= set(arguments) <= allowed:
        return f"Tool arguments were invalid; expected {sorted(required)} (optional: {sorted(allowed - required)})."
    if any(not isinstance(value, (str, int)) or (isinstance(value, str) and len(value) > 4000) for value in arguments.values()):
        return "Tool arguments were invalid; values must be short text or numbers."
    return None


LOOKING_TOOLS = {"read_screen_text", "guide", "point_at", "pin_note", "scroll"}  # change nothing: never asked
CLICK_BUTTONS = ("left", "right", "double")
POINT_STYLES = ("box", "arrow", "ring")


class ScreenStep(NamedTuple):
    """A step that changes something on the PC: what the owner is told (or asked), and doing it."""
    summary: str
    run: Callable[[], str]


def execute_screen_tool(name: str, arguments: Any, screen: ScreenSession,
                        approve: Callable[[str, dict[str, Any]], bool]) -> str:
    """Validate against the newest screen. Looking needs no OK; a step that changes something goes through `approve`
    (the dashboard decides whether that means a question: autopilot) and is then done once."""
    text = arguments.get("text", arguments.get("label", ""))
    if not isinstance(text, str) or len(text) > 500:
        return "Text must be at most 500 characters."
    try:
        if name in LOOKING_TOOLS:
            return _look(name, arguments, screen, text)
        step = _screen_step(name, arguments, screen, text)
    except ValueError as exc:
        return f"Not done: {exc}."
    if not approve(name, {"summary": step.summary}):
        return "The user declined; nothing was done."
    return step.run()


def _look(name: str, arguments: dict[str, Any], screen: ScreenSession, text: str) -> str:
    if name == "read_screen_text":
        return "\n\n" + screen.read_text()
    if name == "guide":
        return screen.guide(str(arguments["steps"]))
    element = screen.element(arguments["element"]) if "element" in arguments else None
    if name == "scroll":
        return screen.scroll(element, str(arguments["direction"]), max(1, min(15, int(arguments.get("amount") or 3))))
    if name == "point_at":
        style = arguments.get("style", "box")
        return screen.point_at(element, text, style if style in POINT_STYLES else "box")
    return screen.pin_note(element, text)


def _screen_step(name: str, arguments: dict[str, Any], screen: ScreenSession, text: str) -> ScreenStep:
    """Raises ValueError for anything that can't be done as asked (unknown key, element not on screen, ...)."""
    where = f'in "{screen.window_title}"'
    if name == "press_keys":
        combo = str(arguments["keys"])
        spec = send_keys_spec(combo)
        return ScreenStep(f"Press {combo} {where}", lambda: screen.press_keys(spec, combo))
    if name == "open_app":
        target = str(arguments["target"]).strip()
        if not target or len(target) > 300 or any(ord(character) < 32 for character in target):
            raise ValueError("give a program name, web address, file or folder to open")
        return ScreenStep(f"Open {target}", lambda: screen.open_target(target))
    button = arguments.get("button", "left")
    if button not in CLICK_BUTTONS:
        raise ValueError("button must be left, right or double")
    element = screen.element(arguments["element"])
    if name == "type_text":
        return ScreenStep(f"Type into {element.describe()} {where}:\n\n{text}", lambda: screen.type_text(element, text))
    verb = "Click" if button == "left" else f"{button.capitalize()}-click"
    return ScreenStep(f"{verb} {element.describe()} {where}", lambda: screen.click(element, button))


def execute_personal_tool(name: str, arguments: dict[str, Any], memory: Memory, said: str, timers: Any,
                          fitness: Any = None, notes: Any = None) -> str:
    if name in ("mind_map", "add_to_map"):
        if notes is None:
            return "The brainstorm map is not available here."
        ideas = str(arguments["ideas"]).strip()
        if name == "add_to_map":
            lines = [line.strip(" -*•\t") for line in ideas.splitlines() if line.strip(" -*•\t")][:8]
            return notes.add(" ".join(str(arguments.get("under", "")).split())[:80], lines) if lines else "Not added: no ideas given."
        topic = " ".join(str(arguments["topic"]).split())[:80]
        if not topic or not ideas:
            return "Not shown: give a topic and at least one idea."
        return notes.show(topic, ideas)
    if name == "fitness_status":
        return fitness.summary_text() if fitness is not None else "No heart-rate band is connected."
    if name in ("remember", "forget"):
        guard = _REMEMBER if name == "remember" else _FORGET
        if not guard.search(said):
            return f"Not done: Nova only {name}s things when the user's own words ask for it."
        if name == "remember":
            memory.add_fact(str(arguments["fact"]))
            return f"Remembered: {' '.join(str(arguments['fact']).split())[:200]}"
        forgotten = memory.forget_facts(str(arguments["what"]))
        return f"Forgot: {'; '.join(forgotten)}" if forgotten else "Nothing remembered matched that."
    if timers is None:
        return "Timers are not available here."
    if name == "cancel_timer":
        return timers.cancel(str(arguments.get("label", "")).strip())
    seconds = int(arguments.get("minutes") or 0) * 60 + int(arguments.get("seconds") or 0)
    if not 1 <= seconds <= 24 * 3600:
        return "Not started: a timer must be between 1 second and 24 hours."
    return timers.start(seconds, " ".join(str(arguments.get("label", "")).split())[:40])


def execute_gmail_tool(name: str, arguments: dict[str, Any], approve: Callable[[str, dict[str, Any]], bool], gmail: Any) -> str:
    if gmail is None:
        return "Gmail is not connected. The user can connect it from Nova's dashboard."
    try:
        if name == "list_unread_mail":
            return gmail.list_unread()
        if name == "read_mail":
            return gmail.read(int(arguments["number"]))
        to, subject, body = str(arguments.get("to", "")), str(arguments.get("subject", "")), str(arguments["body"])
        reply_to = int(arguments.get("reply_to_number") or 0)
        target = f"reply to mail {reply_to}" if reply_to else f"to {to or '(no recipient)'}"
        if not approve(name, {"summary": f"Save this Gmail draft ({target}). It will NOT be sent.\n\n"
                                         f"Subject: {subject or '(reply subject)'}\n\n{body}"}):
            return "The user declined; no draft was saved."
        return gmail.draft(to, subject, body, reply_to)
    except ValueError as exc:
        return f"Not done: {exc}."
    except (OSError, RuntimeError, KeyError) as exc:
        return f"Gmail request failed: {exc}"


def execute_general_tool(name: str, arguments: dict[str, Any], approve: Callable[[str, dict[str, Any]], bool],
                         creative: Any = None, claude: bool = False, brief: Callable[[], str] | None = None) -> str:
    if name == "calculate":
        import calculator
        try:
            return f"{arguments['expression']} = {calculator.calculate(str(arguments['expression']))}"
        except (ValueError, ArithmeticError, OverflowError) as exc:
            return f"Could not calculate: {exc}."
    if name == "web_search":
        import web_search
        query = " ".join(str(arguments["query"]).split())[:300]
        if not query:
            return "The search query was empty."
        if not approve(name, {"summary": f"Search the web (DuckDuckGo) for:\n\n{query}"}):
            return "The user declined; no search was made."
        try:
            return web_search.search(query)
        except OSError as exc:
            return f"The web search failed: {exc}. The PC may be offline."
    if name == "media_control":
        import media_keys
        action = str(arguments["action"])
        if action not in media_keys.ACTIONS:
            return f"Unknown media action; choose one of {', '.join(media_keys.ACTIONS)}."
        steps = int(arguments.get("times") or (5 if action.startswith("volume") else 1))
        media_keys.press(action, steps)
        return f"Done: {action.replace('_', ' ')}" + (f" ({steps} steps)" if action.startswith("volume") else "") + "."
    if name == "creative_mode":
        if creative is None:
            return "Creative mode is not available here."
        import creative_mode
        return creative_mode.run_tool(creative, arguments)
    if name == "daily_brief":
        # The user switched the brief on, which is their approval for these fetches.
        return brief() if brief is not None else "The daily brief is not turned on. The user can turn it on in Nova's BRIEF panel."
    if name == "ask_claude" and claude:
        import claude_expert
        question = str(arguments["question"]).strip()
        if not approve(name, {"summary": f"Send this question to Claude (Anthropic's cloud AI):\n\n{question}"}):
            return "The user declined; nothing was sent to Claude."
        return "Claude's answer:\n" + claude_expert.ask(question)
    return f"Tool '{name}' is not available."


def add_task(task: str, memory: Memory) -> str:
    """Store a single bounded task in the local task list."""
    clean_task = " ".join(task.split())
    task_id = memory.add_task(clean_task)
    return f"Saved task #{task_id}: {clean_task}"


def _words(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


# ---------- each tool, registered with what runs it ----------

def _named(tools: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(tool for tool in tools if tool["function"]["name"] == name)


def _run_screen(name: str, arguments: dict[str, Any], context: ToolContext) -> str:
    return execute_screen_tool(name, arguments, context.screen, context.approve) if context.screen is not None else "Screen assist is off."


def _run_build(_name: str, arguments: dict[str, Any], context: ToolContext) -> str:
    if context.build is None:
        return "Claude Code isn't installed on this PC, so nothing can be built."
    project = _words(arguments["name"], 60)
    if not context.approve("build", {"summary": f"Build with Claude Code in Documents/Nova Projects: {project}"}):
        return "The owner declined; nothing was built."
    return context.build(project, str(arguments["task"]))


def _run_reverse(_name: str, arguments: dict[str, Any], context: ToolContext) -> str:
    if context.reverse is None:
        return "Reverse engineering is off: the owner can turn it on in Settings (it needs Claude Code and Node.js)."
    target = _words(arguments["target"], 300)
    if not context.approve("reverse_engineer", {"summary": f"Reverse engineer with REA (Claude Code): {target}"}):
        return "The owner declined; nothing was started."
    return context.reverse(target, _words(arguments.get("goal"), 500))


def _run_world(_name: str, arguments: dict[str, Any], context: ToolContext) -> str:
    if context.world is None:
        return "The World view isn't available here."
    return context.world(str(arguments["action"]), _words(arguments.get("place"), 80), int(arguments.get("days") or 1))


def _run_route(_name: str, arguments: dict[str, Any], context: ToolContext) -> str:
    if context.route is None:
        return "Routes aren't available here."
    stops = [stop for stop in (" ".join(part.split()) for part in str(arguments.get("stops") or "").split(",")) if stop]
    return context.route(_words(arguments["start"], 120), _words(arguments["end"], 120), stops[:4],
                         str(arguments.get("mode") or "motorbike"), arguments.get("best_order") is not False)


def _run_discover(_name: str, arguments: dict[str, Any], context: ToolContext) -> str:
    if context.discover is None:
        return "Discover isn't available here."
    return context.discover(str(arguments["action"]), int(arguments.get("number") or 0))


def _run_send_file(_name: str, arguments: dict[str, Any], context: ToolContext) -> str:
    if context.send_file is None:
        return "Files can only be sent while the owner is messaging from Telegram."
    words = _words(arguments["name"], 120)
    if not context.approve("send_file", {"summary": f"Send your file named like “{words}” to your Telegram chat"}):
        return "The owner declined; nothing was sent."
    return context.send_file(words)


def _run_deep_work(_name: str, arguments: dict[str, Any], context: ToolContext) -> str:
    if context.deep_work is None:
        return "Claude Code isn't installed on this PC."
    title = _words(arguments["title"], 80)
    if not context.approve("deep_work", {"summary": f"Hand this to Claude Code (your Claude plan): {title}"}):
        return "The owner declined; nothing was handed off."
    return context.deep_work(title, str(arguments["task"]))


def _run_news(_name: str, arguments: dict[str, Any], context: ToolContext) -> str:
    if context.news is None:
        return "The news desk is off. The owner can turn it on in BRIEF → News desk."
    try:
        return context.news(str(arguments.get("query") or ""), str(arguments.get("category") or ""),
                            int(arguments.get("days") or 1), int(arguments.get("offset_days") or 0))
    except Exception as exc:  # the database being busy or missing must not break the answer
        return f"The news database couldn't be read: {exc}"


def _run_tv(_name: str, arguments: dict[str, Any], context: ToolContext) -> str:
    return context.tv(str(arguments.get("title", "")), str(arguments["text"])) if context.tv is not None else "No TV here."


def _run_add_task(name: str, arguments: Any, context: ToolContext) -> str:
    if not isinstance(arguments, dict) or set(arguments) != {"task"}:
        return "Tool arguments were invalid; expected only a task string."
    task = arguments.get("task")
    if not isinstance(task, str):
        return "Tool arguments were invalid; task must be text."
    clean_task = " ".join(task.split())
    if not clean_task or len(clean_task) > 240:
        return "Tool arguments were invalid; task must be 1–240 characters."
    if not context.approve(name, {"task": clean_task}):
        return "The user declined to save this task; no task was added."
    try:
        return add_task(clean_task, context.memory)
    except ValueError as exc:
        return f"Task was not saved: {exc}"


register(SCREEN_TOOLS, _run_screen)
register(GMAIL_TOOLS, lambda name, arguments, context: execute_gmail_tool(name, arguments, context.approve, context.gmail))
register(PERSONAL_TOOLS, lambda name, arguments, context: execute_personal_tool(
    name, arguments, context.memory, context.said, context.timers, context.fitness, context.notes))
register(LOCATION_TOOLS, lambda name, arguments, context: execute_location_tool(name, arguments, context.approve, context.location))
register(SECOND_BRAIN_TOOLS, lambda _name, arguments, context: execute_brain_tool(arguments, context.brain))
register([LIBRARY_TOOL], lambda _name, arguments, context: execute_library_tool(arguments, context.approve, context.library))
register([REMINDER_TOOL], lambda _name, arguments, context: execute_reminder_tool(arguments, context.reminders)
         if context.reminders is not None else "Reminders aren't available here.")
register([_named(GENERAL_TOOLS, "web")], lambda _name, arguments, context: execute_web_tool(arguments, context.approve, context.web)
         if context.web is not None else "Nova's browser needs Microsoft Edge on this PC.")
register([SKILLS_TOOL], lambda _name, arguments, context: execute_skills_tool(arguments, context.approve, context.skills)
         if context.skills is not None else "Skills need the second brain's vault.")
register([BUILD_TOOL], _run_build)
register([REVERSE_TOOL], _run_reverse)
register([WORLD_TOOL], _run_world)
register([ROUTE_TOOL], _run_route)
register([DISCOVER_TOOL], _run_discover)
register([SEND_FILE_TOOL], _run_send_file)
register([DEEP_WORK_TOOL], _run_deep_work)
register([NEWS_TOOL], _run_news)
register([TV_TOOL], _run_tv)
register([*(tool for tool in GENERAL_TOOLS if tool["function"]["name"] != "web"), CLAUDE_TOOL], lambda name, arguments, context: execute_general_tool(
    name, arguments, context.approve, context.creative, context.claude, context.brief))
register(TOOLS, _run_add_task, validate=False)


def execute_tool(name: str, arguments: Any, memory: Memory, approve: Callable[[str, dict[str, Any]], bool],
                 screen: ScreenSession | None = None, creative: Any = None, claude: bool = False, gmail: Any = None,
                 brief: Callable[[], str] | None = None, said: str = "", **services: Any) -> str:
    """Check the arguments against the tool's definition, then run it (each tool asks the owner when it must).
    services: what the tools may use this turn, by ToolContext's names (timers, calendar, drive, world, …)."""
    run = run_for(name)
    if run is None:
        return f"Tool '{name}' is not available."
    if _expected(name) is not None:
        problem = _invalid_arguments(name, arguments)
        if problem:
            return problem
    context = ToolContext(memory=memory, approve=approve, screen=screen, creative=creative, claude=claude, gmail=gmail,
                          brief=brief, said=said, **services)
    return run(name, arguments, context)
