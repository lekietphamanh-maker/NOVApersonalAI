"""REA auto-fit: what in a reverse-engineered app would make Nova better.

After REA finishes, score_report() reads the report (and its blueprint) against Nova's capabilities — the
skills_board entries and Nova's tool names, as a keyword map from capability areas to the words that show it
(keywords, blueprint parts, mentioned tools and APIs such as spotify, gmail or telegram). Each fit finding says
its score, what it is, which Nova function it would improve, and how. Scoring is transparent and deterministic:
keyword overlap plus explicit mappings, no network, no new dependencies.

The score is 10 per distinct keyword found in the report text, plus 20 per blueprint part that matches any
keyword, capped at 100; a finding needs 20 or more (two matching ideas, or one matching blueprint part).
A report with no overlap returns no findings and a plain message.

Nothing here installs anything. handoff() only PREPARES the Discover-style proposal for a fit: the pinned
study task (read-only study of the source at one commit, license recorded) and a skill-note draft for the
owner to read and approve. Installing code is a separate step Nova asks the owner about first — the study
itself says so, and the button that uses this handoff asks first too.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCORE_PER_KEYWORD = 10
SCORE_PER_PART = 20
SCORE_MIN = 20
SCORE_MAX = 100
MAX_FINDINGS = 5

# area, the Nova function it would improve (a skills_board entry), how it would improve it, keywords that show it.
AREAS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("Trading & finance", "News, brief and weather",
     "Its chart scanner could join the morning brief: prices, movers and price alerts, so Nova tells the owner "
     "what moved before the day starts.",
     ("candlestick", "chart scan", "ticker", "stock", "portfolio", "trading", "forex", "crypto", "dividend",
      "price alert", "market scan", "stock scan")),
    ("Voice & speech", "Hold to talk, or say “Hey Nova”",
     "Its way of hearing speech could make Nova understand the owner better — clearer transcription, fewer missed "
     "words, or a steadier wake word.",
     ("speech recognition", "transcription", "transcribe", "wake word", "text-to-speech", "tts", "voice synthesis",
      "whisper", "dictation", "speech-to-text", "stt")),
    ("Screen reading & automation", "Screen assist and autopilot",
     "Its way of reading a screen and driving the mouse and keyboard could make Nova's screen assist faster and "
     "steadier on apps it struggles with.",
     ("ocr", "ui automation", "screen reader", "screenshot", "mouse control", "keyboard automation", "autopilot",
      "accessibility tree", "screen scraping")),
    ("Documents & spreadsheets", "Word, Excel and PowerPoint",
     "Its way of building documents and sheets could make the files Nova makes richer — better tables, charts and "
     "formatting.",
     ("spreadsheet", "excel", "pivot table", "word document", "docx", "pdf", "document generation", "workbook",
      "powerpoint", "pptx")),
    ("Knowledge & search", "Search my notes by meaning",
     "Its way of finding things by meaning could make Nova find the owner's notes faster, even when the words "
     "don't match.",
     ("semantic search", "embedding", "vector search", "knowledge graph", "wikipedia", "full-text search",
      "retrieval", "rag")),
    ("Calendar, reminders & tasks", "Reminders and tasks",
     "Its way of keeping track of events and to-dos could make Nova's reminders and task list handle repeats and "
     "routines better.",
     ("calendar", "reminder", "schedule", "task list", "todo", "to-do", "recurring event", "planner")),
    ("Mail", "Gmail",
     "Its way of sorting and searching mail could make Nova's Gmail answers quicker — finding the message that "
     "matters instead of listing the inbox.",
     ("email", "gmail", "inbox", "mail client", "imap", "smtp", "mailbox")),
    ("Music & audio", "Instant commands (no AI)",
     "Its way of handling music and sound could make Nova's instant music commands cover more players and playlists.",
     ("spotify", "playlist", "music player", "audio", "podcast", "mp3", "equalizer", "now playing")),
    ("Video & recording", "Screen recording",
     "Its way of capturing video could make Nova's screen recording sharper or easier to start and stop.",
     ("screen recording", "video capture", "screen capture", "webcam", "video editor", "mp4")),
    ("Devices & smart home", "Heart rate",
     "Its way of talking to a device could bring more live readings to Nova — heart rate today, other sensors next.",
     ("bluetooth", "heart rate", "iot", "smart home", "home assistant", "wearable", "sensor", "zigbee")),
    ("Maps & routes", "Fastest route",
     "Its way of finding places and routes could make Nova's fastest-route answers cover more stops and live traffic.",
     ("map", "route", "gps", "navigation", "geocoding", "turn-by-turn", "traffic", "place search", "globe")),
    ("Images & vision", "Make a picture",
     "Its way of seeing and making pictures could make Nova's pictures and camera answers sharper.",
     ("image generation", "text-to-image", "image recognition", "object detection", "camera", "photo", "lens",
      "computer vision")),
    ("Building & electronics", "Building mode",
     "Its way of wiring a board could make Nova's building bench cover more parts and catch more wiring mistakes.",
     ("arduino", "esp32", "circuit", "wiring", "servo", "led", "microcontroller", "raspberry pi", "gpio",
      "breadboard")),
    ("Agent design", "Archmancer",
     "Its agent design could make Nova's own loops, tool use and checks steadier — what Archmancer teaches, "
     "applied to Nova herself.",
     ("agent loop", "tool calling", "prompt injection", "context window", "agent system", "multi-agent",
      "evaluation", "tool use")),
    ("Workflows & skills", "Skills of your own",
     "Its workflow could become a skill of the owner's own — written down once, run by a phrase or a schedule.",
     ("skill", "workflow", "automation", "scheduled task", "prompt template", "repeatable task", "macro")),
    ("Security", "Shannon: break into your own app",
     "Its security checks could give Shannon more to prove — real holes, with the fix, before someone else finds them.",
     ("pentest", "vulnerability", "xss", "sql injection", "csrf", "ssrf", "security scan", "penetration test")),
    ("Messaging", "Telegram",
     "Its way of handling messages could make Nova on Telegram quicker — sending the owner's files and answering "
     "from anywhere.",
     ("telegram", "whatsapp", "messenger", "chat bot", "message thread", "sms", "signal")),
    ("Notes & memory", "Second brain",
     "Its way of keeping notes could make Nova's second brain link what the owner reads and watches more usefully.",
     ("obsidian", "notes", "journal", "note-taking", "linked notes", "daily note", "second brain", "zettelkasten")),
    ("Web search & reading", "Web search and reading pages",
     "Its way of searching and reading the web could make Nova's web answers fuller — more of the page, less guessing.",
     ("web search", "web crawler", "web scraping", "scraper", "readability", "rss", "news feed", "search engine")),
)

REPO_URL = re.compile(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)")

SKILL_FENCE = """```skill
---
title: {title}
says: {says}
schedule: manual
tools: 
brain: auto
output: yes
---
{draft}
```"""


def _clean(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _keyword_pattern(keyword: str) -> "re.Pattern[str]":
    # a trailing "s" is a plural, not a different word ("tickers", "price alerts")
    return re.compile(r"(?<![a-z0-9])" + re.escape(keyword) + r"s?(?![a-z0-9])")


def _matches(text: str, keyword: str) -> bool:
    return _KEYWORD_PATTERNS[keyword].search(text) is not None


# One compiled pattern per keyword, built once at import — score_report() used to recompile them per part.
_KEYWORD_PATTERNS = {word: _keyword_pattern(word) for _area in AREAS for word in _area[3]}


def _short_target(target: str) -> str:
    text = " ".join(str(target or "").split())
    name = re.sub(r"^https?://", "", text).rstrip("/\\")
    return (re.split(r"[\\/]", name)[-1] or name)[:40] or "the target"


def score_report(report: str, blueprint: dict[str, Any] | None = None, target: str = "") -> dict[str, Any]:
    """The fit findings for a REA report, best first, and a plain message when there are none.

    Findings are plain dicts (JSON-safe, so they can be stored with the job): area, score, what, improves, how,
    evidence (the matched keywords), parts (the matching blueprint part ids).
    """
    text = _clean(report)
    name = _short_target(target)
    # Each part's text is cleaned once, not once per area per keyword; keyword patterns are precompiled below.
    part_texts = [(_clean(" ".join([str(part.get("name") or ""), str(part.get("summary") or ""),
                                    " ".join(str(item) for item in part.get("findings") or [])])), part)
                  for part in list((blueprint or {}).get("parts") or [])]
    findings: list[dict[str, Any]] = []
    for area, improves, how, keywords in AREAS:
        found = sorted({word for word in keywords if _matches(text, word)})
        matched_parts = [part for part_text, part in part_texts
                         if any(_matches(part_text, word) for word in keywords)]
        score = min(SCORE_MAX, SCORE_PER_KEYWORD * len(found) + SCORE_PER_PART * len(matched_parts))
        if score < SCORE_MIN:
            continue
        findings.append({"area": area, "score": score,
                         "what": f"{area} in {name}: {', '.join(found[:4]) or 'see the blueprint part'}",
                         "improves": improves, "how": how, "evidence": found,
                         "parts": [str(part.get("id") or "") for part in matched_parts if part.get("id")]})
    findings.sort(key=lambda item: (-item["score"], item["area"]))
    findings = findings[:MAX_FINDINGS]
    if not findings:
        return {"findings": [], "message": "Nothing in this report fits Nova's capabilities closely enough to "
                                           "suggest — no area scored 20 or more (two matching ideas, or one "
                                           "matching blueprint part)."}
    return {"findings": findings,
            "message": f"{len(findings)} thing{'s' if len(findings) != 1 else ''} in this report could make Nova "
                       f"better: {', '.join(f'{item['area']} ({item['score']})' for item in findings)}."}


def fit_summary(findings: list[dict[str, Any]]) -> str:
    """One line for the Library note, "" when there are no fits."""
    if not findings:
        return ""
    return ", ".join(f"{item['area']} ({item['score']})" for item in findings)


def extract_repo(text: str) -> str:
    """A GitHub owner/repo named in the target or report, "" when there is none (so the handoff can pin it)."""
    found = REPO_URL.search(str(text or ""))
    return found.group(1).rstrip(").,") if found else ""


def skill_note_draft(finding: dict[str, Any], target: str) -> str:
    """A DRAFT skill note (Discover's format) for the fit — the owner reads and approves it before it joins
    Nova's skills; it is a proposal, not an installed skill."""
    name = _short_target(target)
    title = f"{finding.get('area', 'Fit')} from {name}"
    says = ", ".join([f"use the {finding.get('area', '').lower()} from {name}",
                      f"what did Rea find that fits Nova in {name}"])
    draft = (f"When the owner asks about the {finding.get('area', '')} Rea found in {name}: "
             f"{finding.get('how', '')}\n"
             f"The capability: {finding.get('what', '')}.\n"
             "Do it with Nova's own tools, on this PC; say what changed and what is still missing.")
    return SKILL_FENCE.format(title=title, says=says, draft=draft)


def study_task(finding: dict[str, Any], target: str, report: str = "", pin: dict[str, Any] | None = None) -> str:
    """What Claude Code is asked, Discover-style: study the fit read-only and plan how Nova could use it.

    The study never runs or installs anything — if installing code would help, the plan says so and Nova asks the
    owner first. Installing code is allowed only after that approval.
    """
    name = _short_target(target)
    if pin:
        source = (f"Study the GitHub repository {pin['repo']} at commit {pin['sha']} "
                  f"({pin.get('url') or 'https://github.com/' + pin['repo']}/tree/{pin['sha']}); "
                  f"its license is {pin.get('license') or 'not stated'}. Read its README and main files from that "
                  "commit only; ")
    else:
        source = (f"Study the capability from Nova's own REA report of {name} at {report or 'outputs/'} "
                  "(read that report only — do not fetch, run or install the target itself); ")
    return (source + "do not run or install anything from it during this study — if installing code would help, say "
            "so in the plan and Nova will ask the owner first. Then write, in Markdown: what the capability does in "
            f"three lines — {finding.get('area', '')}: {finding.get('what', '')}. Whether Nova (the owner's Windows "
            f"voice assistant) could use it to improve {finding.get('improves', '')}, and how: {finding.get('how', '')} "
            "(a) as a Nova skill, when it is a workflow, a prompt or a method Nova can follow with her own tools; "
            "(b) as a change to Nova's own code — which files, what the change is, and what installing it would "
            "need; or (c) not at all, with why. Note anything risky: what it would need access to, and whether the "
            "license allows the use. If (a), end with the skill note in a fenced block marked skill, in this "
            "format:\n```skill\n---\ntitle: <short title>\nsays: <phrases that start it, comma separated>\n"
            "schedule: manual\ntools: \nbrain: auto\noutput: yes\n---\n<what Nova should do, step by step>\n```")


def handoff(finding: dict[str, Any], target: str, report: str = "", pin: dict[str, Any] | None = None) -> dict[str, Any]:
    """The prepared proposal for a fit: the study task and a skill-note draft. It prepares only — it writes no
    files, installs no code and changes nothing in Nova; the owner approves before anything is installed."""
    name = _short_target(target)
    title = f"Rea fit: {finding.get('area', 'Fit')} from {name}"[:80]
    return {"title": title, "study_task": study_task(finding, target, report, pin),
            "skill_note": skill_note_draft(finding, target),
            "repo": (pin or {}).get("repo", ""), "sha": (pin or {}).get("sha", ""),
            "license": (pin or {}).get("license", ""),
            "note": "Prepared only — nothing installed. The study is read-only; if its plan needs code installed, "
                    "Nova asks the owner first and installs it only with their approval."}


def write_fit(folder: Path, fit: dict[str, Any]) -> Path:
    """The findings next to the report (fit.json), best effort — a failure here must never fail the job."""
    path = Path(folder) / "fit.json"
    try:
        path.write_text(json.dumps(fit, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return path
