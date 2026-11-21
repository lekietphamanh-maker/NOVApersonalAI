"""The Skills board: everything Nova can do, so nothing is forgotten. Each entry says what it does, what to say, and
whether it's ready here, needs setting up (and where), runs on Claude in the cloud, or is off.

Every tool Nova has must belong to an entry (a test checks it), so a new feature shows up on the board.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Entry:
    group: str
    name: str
    what: str
    say: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    needs: str = ""          # a key of the live status (see dashboard._skills_status); "" = always ready
    where: str = ""          # where to turn it on or set it up


CATALOG: tuple[Entry, ...] = (
    Entry("Talk", "Hold to talk, or say “Hey Nova”", "Hold Ctrl+Alt (Control+Option on a Mac) anywhere and speak; "
          "or turn the mic on and start with “Hey Nova”. Interrupt her any time.",
          ("Hey Nova, what's on today?",), needs="mic", where="Mic button at the bottom"),
    Entry("Talk", "Instant commands (no AI)", "Done in milliseconds without the model: timers, volume, music, the "
          "time and date, opening known apps.", ("timer for 10 minutes", "volume up a lot", "next song",
                                                  "open Spotify", "what time is it"),
          ("set_timer", "cancel_timer", "media_control", "open_app")),
    Entry("Talk", "Remember and forget", "Keeps a fact only when you ask, forgets it when you ask.",
          ("remember that my sister's birthday is May 3", "forget my sister's birthday"), ("remember", "forget")),
    Entry("Talk", "Reminders and tasks", "Reminders at a time (spoken on time, kept across restarts) and a task list.",
          ("remind me at 5 pm to call mom", "every weekday at 8 remind me to stretch", "add buy milk to my tasks"),
          ("reminder", "add_task")),
    Entry("Brains", "Ask Claude", "A hard question goes to Claude; personal ones stay on this PC unless you say yes.",
          ("ask Claude to explain transformers simply",), ("ask_claude",), "claude", "SETTINGS → Model → Claude"),
    Entry("Brains", "API brain", "Any AI with your API key answers: Claude, OpenAI, Gemini, OpenRouter, Groq, DeepSeek, "
          "Mistral, xAI, Together or your own server. Add several and pick one.", needs="api",
          where="SETTINGS → Model → API brain → Add an API brain"),
    Entry("Brains", "Cloud brain", "An AI you sign in to with an account, no key: Claude Code (Claude plan, uses Nova's "
          "tools), Codex (ChatGPT plan) or Gemini CLI (Google account).", needs="cloud_brain",
          where="SETTINGS → Model → Cloud brain → Install, Connect account"),
    Entry("Brains", "Claude does what this PC can't", "When a tool can't run here (no offline Wikipedia, map servers "
          "down, code to run), Claude does it in the cloud and Nova says so.",
          ("work out the compound interest on 10 million at 7% for 5 years",), ("run_code",), "cloud",
          "SETTINGS → Claude → the cloud switch"),
    Entry("Brains", "Auto-tune", "The strongest model this PC runs smoothly, measured after every update.",
          needs="tune", where="SETTINGS → This PC → Tune now"),
    Entry("Brains", "Prompt optimizer", "Rewrites a prompt so an AI answers it better, tests both on the same model, "
          "and shows which won.", ("optimize this prompt: write me a cover letter",), ("optimize_prompt",)),
    Entry("Knowledge", "Web search and reading pages", "Searches the web (only the search words leave the PC) and "
          "reads whole pages in Nova's own hidden browser.", ("search the web for the best budget laptop 2026",
                                                               "read this article and sum it up"), ("web_search", "web")),
    Entry("Knowledge", "Wikipedia", "Answers from the real articles, offline once downloaded (else Claude looks it up).",
          ("who was Trần Hưng Đạo",), ("wikipedia",), "wikipedia", "SETTINGS → Offline knowledge"),
    Entry("Knowledge", "Search my notes by meaning", "Finds what you wrote about something, even in other words.",
          ("what did I write about sleeping better",), ("search_my_notes",), "notes",
          "SETTINGS → Offline knowledge → Index my notes"),
    Entry("Knowledge", "Second brain", "Notes in Obsidian of what you read and watch, summed up into linked pages.",
          ("what did I learn about Rust this week",), ("second_brain",), "second_brain", "SETTINGS → Second brain"),
    Entry("Knowledge", "Library", "Your projects, repos and ideas by topic on the gold shelf.",
          ("open my library", "add an idea: a habit tracker for my bike rides"), ("library",)),
    Entry("Knowledge", "News, brief and weather", "A daily news desk with sources, the morning brief, weather and "
          "local news.", ("what happened today", "will it rain tomorrow", "read me the brief"),
          ("news", "local_news", "daily_brief", "weather", "set_location"), "news", "BRIEF → News desk"),
    Entry("Knowledge", "World", "A live globe: earthquakes, storms, fires and news by country.",
          ("what's happening in Japan this week",), ("world",)),
    Entry("Knowledge", "Knowledge Galaxy", "A 3D star map of everything Nova knows: wiki topics, memory facts, "
          "skills and sources orbiting as stars you can search and explore.",
          ("show me the galaxy", "open the star map", "what does Nova know"),
          ("knowledge_galaxy",), where="GALAXY in the top bar"),
    Entry("Knowledge", "Calculator", "Exact arithmetic, on this PC.", ("what's 18% of 2.4 million",), ("calculate",)),
    Entry("Google", "Gmail", "Reads and drafts mail (never sends).", ("any new emails", "draft a reply to Minh"),
          ("list_unread_mail", "read_mail", "draft_mail"), "google", "SETTINGS → Connections → Connect Google"),
    Entry("Google", "Calendar", "Your events, adds new ones, and finds free time to suggest (cal.diy's idea).",
          ("what's my week look like", "add dentist Friday at 3", "when am I free for an hour this week"),
          ("calendar_events", "add_event", "find_free_time"), "calendar", "SETTINGS → Connections → Add Google Calendar"),
    Entry("Google", "Drive", "Searches and reads your Drive files, read-only.", ("find my budget in Drive",),
          ("drive_search", "drive_recent", "drive_read"), "drive", "SETTINGS → Connections → Add Google Drive"),
    Entry("Screen", "Screen assist and autopilot", "Reads the app you're in, points, and drives the mouse and keyboard "
          "step by step. Esc stops her.", ("where's the save button", "open notepad and type hello",
                                            "review my homework"),
          ("click", "type_text", "press_keys", "scroll", "read_screen_text", "point_at", "pin_note", "guide"),
          "screen", "Assist button at the bottom"),
    Entry("Make", "Word, Excel and PowerPoint", "Real files, made and opened: documents, sheets with charts, decks.",
          ("make an Excel sheet of my November spending with a bar chart",), ("make_document",)),
    Entry("Make", "Mind maps", "Brainstorm maps you can edit by hand or by voice.", ("brainstorm a birthday party",),
          ("mind_map", "add_to_map")),
    Entry("Make", "Creative mode", "Webcam mirror with hand-controlled holograms, lenses and a photo booth.",
          ("open the camera",), ("creative_mode",), "camera", "CAMERA button"),
    Entry("Make", "Skills of your own", "Tasks written down once and run by a phrase or a schedule.",
          ("plan my day", "make a skill that sums up my week every Sunday"), ("skills",)),
    Entry("Make", "Long work and builds with Claude Code", "Explainers and reports in the background; apps and sites "
          "built in Documents/Nova Projects.", ("build me a portfolio website", "write a report on solid-state batteries"),
          ("deep_work", "build"), "claude_code", "Install Claude Code and sign in"),
    Entry("Make", "Discover", "GitHub projects picked for you, studied read-only.", ("what should I add to Nova",),
          ("discover",)),
    Entry("Make", "Make a picture", "A picture from a description, on your OpenAI API brain (Open-Generative-AI's idea).",
          ("make a picture of a neon Saigon street at night, cinematic",), ("make_image",)),
    Entry("Make", "Screen recording", "Records the whole screen to an MP4 until you say stop (Cap's idea).",
          ("record my screen", "stop recording"), ("screen_record",)),
    Entry("Knowledge", "SEO check", "Checks a page like a search engine would and says what to fix first (open-seo's idea).",
          ("check the SEO of my portfolio site",), ("seo_check",)),
    Entry("Talk", "Dictation", "Hold Ctrl+Win (Control+Command on a Mac), speak, let go: your words are typed where the "
          "cursor is, in any app (OpenWhispr's idea).", needs="mic", where="SETTINGS → Hotkeys"),
    Entry("Make", "Workplace", "A board for notes, sketch notes you draw on, pictures and files (text, code, PDF, Word). "
          "Select something and Nova explains it: she highlights the key words, adds her note beside it, points at "
          "things and looks at pictures. Closing asks whether to save.", ("workplace mode", "explain this",
                                                                          "highlight what matters in these notes",
                                                                          "what's in this picture?"),
          ("workplace",), where="WORKPLACE in the top bar"),
    Entry("Make", "Building mode", "A 3D electronics bench on a screen of its own: place a board (Arduino, ESP32, Pico, Blue Pill, "
          "Raspberry Pi 4) and parts, wire them pin to pin and press Run. Describe what you want and Nova builds it: she picks the "
          "board and parts, wires them, the bench checks the wiring (short circuits, 5 V into a 3.3 V pin), and the parts list "
          "and build steps appear beside it. Projects are saved by name.",
          ("building mode", "build me a blinking LED on an Uno", "a servo that follows a knob on an ESP32", "is my circuit wired right?"),
          ("building",), where="BUILD in the top bar"),
    Entry("Apps", "Advance mode", "A red HUD: the orb on the left; your Library, what Nova can do, your widgets (add, "
          "remove, reorder) and separate apps on the right. Rea and Shannon open in their own windows; OpenProject runs "
          "in Docker; AppFlowy, Cap, VoiceStudio and your own apps open from there.", ("advance mode on", "exit advance mode"),
          where="ADVANCE in the top bar"),
    Entry("Apps", "OBS", "Record, stream (asks first) and switch scenes through OBS's own remote control.",
          ("start recording", "switch to the gaming scene"), ("obs",), "", "OBS → Tools → WebSocket Server Settings"),
    Entry("Apps", "VS Code", "Opens your projects and files, at a line.", ("open my portfolio in VS Code",), ("vscode",),
          "vscode", "Install VS Code (its code command)"),
    Entry("Knowledge", "Archmancer", "Agent-system architecture knowledge: how to design, build, debug or review "
          "AI agent systems (loops, tools, models, context, trust, evaluation, delivery). From lehoanganhtai13/archmancer.",
          ("how should I design an agent loop for my app", "search archmancer for prompt injection",
           "what does archmancer say about tool authorization"),
          ("archmancer",)),
    Entry("Places", "Fastest route", "The globe flies to the city, then the search spreads through the streets and the "
          "fastest way lights up; stops in the best order.",
          ("fastest way from District 12 to District 7 via Ben Thanh",), ("route",)),
    Entry("Labs", "Rea: reverse engineering", "How an app or site is built, as a blueprint of its parts (REA through "
          "Claude Code).", ("reverse engineer notion.so and tell me how its sync works",), ("reverse_engineer",),
          "reverse", "REA screen (asks you to agree the first time)"),
    Entry("Labs", "Shannon: break into your own app", "An AI pentester that proves real holes in your app, with the fix.",
          needs="shannon", where="SHANNON screen; needs WSL2, Docker Desktop and an API key"),
    Entry("Other screens", "TV dashboard", "Shows things on the TV's browser.", ("show the weather on the TV",),
          ("show_on_tv",)),
    Entry("Other screens", "Telegram", "Nova from anywhere by text or voice note; sends you your own files.",
          ("send me the report on my desktop",), ("send_file",), "telegram", "SETTINGS → Telegram"),
    Entry("Other screens", "Heart rate", "Live heart rate from a Bluetooth band.", ("how's my heart rate",),
          ("fitness_status",), "heart", "SETTINGS → Fitness"),
)

READY, SETUP, CLOUD, OFF = "ready", "setup", "cloud", "off"


def board(status: dict[str, tuple[str, str]], own_skills: list[dict[str, Any]], hotkeys: dict[str, str]) -> dict[str, Any]:
    """The board as the screen draws it. status: need → (READY|SETUP|CLOUD|OFF, a short note)."""
    entries = []
    for entry in CATALOG:
        state, note = status.get(entry.needs, (READY, "")) if entry.needs else (READY, "")
        entries.append({"group": entry.group, "name": entry.name, "what": entry.what, "say": list(entry.say),
                        "state": state, "note": note or (entry.where if state != READY else ""), "where": entry.where})
    for skill in own_skills:
        entries.append({"group": "Your skills", "name": skill.get("title") or skill.get("name"),
                        "what": f"Runs {skill.get('schedule') or 'when you ask'}"
                                + (f" · last {skill['last']}" if skill.get("last") else ""),
                        "say": list(skill.get("says") or []), "state": READY, "note": "", "where": "TASKS → Skills",
                        "skill": skill.get("name")})
    counts = {state: sum(item["state"] == state for item in entries) for state in (READY, SETUP, CLOUD, OFF)}
    return {"entries": entries, "counts": counts, "hotkeys": hotkeys}


def tools_on_board() -> set[str]:
    return {tool for entry in CATALOG for tool in entry.tools}
