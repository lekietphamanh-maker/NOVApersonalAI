"""What the model on this PC is sent with each question: only the tools the question can use, and the screen only when
the question is about it.

Every tool definition is read by the model before it answers. With all of them (about 6,000 tokens) plus a screen,
an 8 GB graphics card spends seconds on reading alone, and the request no longer fits the context: Ollama then drops
its cached prompt and reads everything again. A small core always comes; each group comes when the words call for it.
The online brains (Claude, Ollama Cloud) still get every tool: they read long prompts quickly.
"""
from __future__ import annotations

import re
from typing import Any

CORE = ("add_task", "calculate", "web_search", "remember", "forget", "set_timer", "cancel_timer", "reminder",
        "media_control", "weather", "skills", "wikipedia", "workplace")  # workplace: only offered while the board is open
# (tool names, the words that call for them). Matched case-insensitively against the owner's request.
GROUPS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("list_unread_mail", "read_mail", "draft_mail"), r"mail|e-?mails?|inbox|gmail|draft|repl(y|ies)|unread|thư"),
    (("calendar_events", "add_event", "find_free_time"), r"calendar|meeting|event|appointment|schedule|agenda|what'?s on|busy|free time|free slot|when am i free|available|book|"
                                       r"tomorrow|today|tonight|this week|next week|monday|tuesday|wednesday|thursday|"
                                       r"friday|saturday|sunday|lịch"),
    (("drive_search", "drive_recent", "drive_read"), r"drive|google docs?|docs?|sheets?|spreadsheet|slides|pdf|files?"),
    (("news", "world", "local_news", "daily_brief"), r"news|headlines?|happening|world|war|earthquakes?|quakes?|storms?|"
                                                     r"hurricane|typhoon|cyclone|wildfires?|volcano|disaster|conflict|"
                                                     r"brief|tin tức"),
    (("set_location", "local_news"), r"weather|forecast|rain|temperature|city|location|live in|moved? to|thời tiết"),
    (("second_brain", "library", "search_my_notes"), r"second brain|notes?|wiki|learn(ed|t)?|watched|read about|obsidian|vault|library|i wrote|i saved|i kept|"
                                  r"projects?|ideas?|repos?"),
    (("mind_map", "add_to_map"), r"map|brainstorm|visuali[sz]e|ideas?"),
    (("optimize_prompt",), r"prompt"),
    (("screen_record",), r"record|recording|screen ?cap|capture (my|the) screen"),
    (("seo_check",), r"\bseo\b|search engine|google rank|meta (tag|description)|site audit"),
    (("make_image",), r"image|picture|photo of|draw|illustration|logo|poster|wallpaper|generate a"),
    (("run_code",), r"statistic|average|median|standard deviation|regression|percent(age)?|compound|interest rate|"
                    r"probabilit|simulat|analy[sz]e (these|this|the) (numbers|data|table)|convert|how many (days|weeks)|"
                    r"code|python|algorithm|prime|factorial|equation|solve"),
    (("creative_mode",), r"camera|creative|holograms?|photo|selfie|lens|kiss ?cam|webcam|3d|reactor"),
    (("show_on_tv",), r"\btv\b|television|big screen"),
    (("deep_work", "build"), r"research|report|explainer|write (me )?(a|an)|essay|build|make (me )?(a|an)|website|"
                             r"\bapp\b|script|program|code|deep work"),
    (("discover", "reverse_engineer"), r"discover|github|suggest|recommend|reverse[- ]engineer|how (does|do) .+ work"),
    (("web",), r"browse|website|web ?page|site|\.com|\.org|\.net|compare|look up|fill (in|out)|form|buy|price|"
               r"order|book(ing)?"),
    (("fitness_status",), r"heart|pulse|bpm|hrv|fitness|workout|exercise"),
    (("ask_claude",), r"claude"),
    (("send_file",), r"send (me )?(the|my|a|that)|telegram"),
    (("make_document",), r"word|document|docx?|excel|spreadsheet|sheet|table|chart|graph|powerpoint|slides?|presentation|"
                         r"deck|report|essay|letter|cv|resume|invoice"),
    (("obs",), r"obs|record(ing)?|stream(ing)?|go live|scene"),
    (("vscode",), r"vs ?code|visual studio|code editor|open (the |my )?(project|code|repo)"),
    (("route",), r"route|directions?|way (to|from)|get (to|from)|fastest|quickest|drive to|ride to|walk to|"
                 r"how far|from .+ to|đường|chỉ đường"),
)
_GROUPS = tuple((names, re.compile(rf"(?<!\w)({words})(?!\w)", re.IGNORECASE)) for names, words in GROUPS)

# Words that point at what's on the screen. Without one, a question isn't about the screen and Nova doesn't read it.
SCREEN_WORDS = re.compile(
    r"(?<!\w)(this|these|those|here|that (one|button|page|link|box|field)|screen|page|window|tab|button|link|menu|"
    r"field|box|icon|click|double[- ]?click|right[- ]?click|type|press|scroll|select(ed)?|highlight(ed)?|copy|paste|"
    r"open|close|install|uninstall|download|fill|form|homework|assignment|worksheet|quiz|test|exam|article|document|"
    r"review|proofread|summari[sz]e|read (it|this|that|out|me)|what('?s| is) (on|this)|in front of me|point|show me|"
    r"where (is|do i|can i)|how do i|walk me through|step by step|do it|go to|log ?in|sign ?in|settings|spreadsheet|"
    r"excel|microsoft word|ms word|powerpoint|chrome|edge|browser|youtube|website|app|program|error|cái này|màn hình|trang này|bấm|mở)"
    r"(?!\w)", re.IGNORECASE)


def about_the_screen(prompt: str) -> bool:
    return bool(SCREEN_WORDS.search(prompt or ""))


def for_question(prompt: str, offered: list[dict[str, Any]], screen: bool = False) -> list[dict[str, Any]]:
    """The tools to send with this question, in the order they were offered (a stable order lets Ollama reuse its
    cached prompt from one question to the next). On a screen job every screen tool comes too."""
    wanted = set(CORE)
    for names, words in _GROUPS:
        if words.search(prompt or ""):
            wanted.update(names)
    from tools import SCREEN_TOOLS
    if screen:
        wanted.update(tool["function"]["name"] for tool in SCREEN_TOOLS)
    return [tool for tool in offered if tool["function"]["name"] in wanted]


def fit(history: list[dict[str, Any]], max_chars: int) -> list[dict[str, Any]]:
    """The newest messages that fit in max_chars, starting with something the owner said (the request is last)."""
    kept: list[dict[str, Any]] = []
    used = 0
    for message in reversed(history):
        size = len(str(message.get("content") or ""))
        if kept and used + size > max_chars:
            break
        kept.append(message)
        used += size
    kept.reverse()
    while len(kept) > 1 and kept[0].get("role") != "user":
        kept.pop(0)
    return kept
