"""Nova's controller: owns every feature and all state. The HUD (ui/, in an Edge app window) only renders it.

Threads: the HTTP server, voice, gestures and the agent run in their own threads and hand work to the
main thread through `self.events`; a hidden Tk root runs the main loop (and the Notes window).
"""
from __future__ import annotations

import argparse
import base64
import copy
import ctypes
import io
import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import uuid
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

if sys.platform == "darwin":  # every data folder below LOCALAPPDATA lands in the Mac's own place for app data
    os.environ.setdefault("LOCALAPPDATA", str(Path.home() / "Library" / "Application Support"))

import app_window
import claude_expert
import cloud_brain
import daily_brief
import gmail_tools
import calendar_tools
import drive_tools
import node_runtime
import google_mcp
import world_monitor
import routes
import offline_wikipedia
import notes_search
import hotkeys
import media_keys
import kokoro_voice
import location as places
import mini_orb
import music as music_player
import pc_sync
import piper_voice
import screens
import second_brain as brain
import selection
import skills as skill_notes
import claude_code
from claude_code import DeepWork
import plan_brain
from nova_mcp import ToolServer
from web_tasks import WebBrowser
import reminders as reminder_list
import vision
from build_info import BUILD, VERSION
import updater as self_update
import whisper_engine
import library as library_store
import pc_monitor
import model_versions
from collections import deque
from news_intel import assistant as news_assistant, pipeline as news_pipeline, scheduler as news_schedule
from news_intel.config import NewsConfig, data_dir as news_data_dir
from news_intel.store import Store as NewsStore
from brain_router import spoken_answer, spoken_place
import agent as agent_module
import knowledge_galaxy
from agent import SCREEN_STEP_TOOLS, Agent, OllamaError, _http_json
from screen_assist import risky_step
from creative_mode import CreativeServer
from fitness import HeartRateMonitor
from gesture_control import BUILT_IN_POSES, GestureControl
from hardware_advisor import choose_model, detect_hardware, pick_best, pull_model, upgrade_offer
from memory import Memory, default_database_path
from phone_bridge import PhoneBridge
import telegram_remote
import cloud_relay
import discover as discovery
import reverse_engineering
import rea_fit
import auto_tune
import api_brains
import cloud_agents
import secret_store
import separate_apps
import setup_everything
from advance_mode import AdvanceMode
import setup_actions
from setup_actions import SetupActions
from workplace_actions import WorkplaceActions
import workplace
from building_actions import BuildingActions
import building
import trading
import skills_board
import shannon_runner
from lab_jobs import JobLog
from timers import Timers
from portable_ollama import start_if_configured, stop as stop_portable_ollama
from ui_server import UiServer
from visual_notes import (add_ideas, apply_command, clean_extras, delete_map, load_maps,
                          parse_spoken_visual_command, save_map, suggest_ideas)
from walkthrough import Walkthrough, speakable_step
from voice import SYSTEM_DEFAULT, SentenceSplitter, VoiceController, enumerate_input_devices, enumerate_speech_outputs

IS_WINDOWS = sys.platform == "win32"
USB = os.environ.get("ALFRED_PORTABLE_EDITION") == "1"
# Empty means "choose for this PC" (Desktop); the USB start-up picks from the models on the drive.
MODEL = os.environ.get("ALFRED_MODEL", os.environ.get("OLLAMA_MODEL", ""))
ACCENTS = ("gold", "cyan", "crimson", "violet", "mint")
ACCENT_RGB = {"gold": (255, 176, 64), "cyan": (59, 228, 255), "crimson": (255, 59, 92), "violet": (163, 123, 255),
              "mint": (76, 245, 181)}
FREE_CLOUD_DEFAULT = "gpt-oss:120b-cloud"  # the free online brain: an open model on Ollama Cloud
# While the Library is on screen the gestures move it: ✋ swipe, ✊ / 👍 hold to open, 👎 back, ✌ close.
# With Rea's orbit view on screen, webcam gestures move it instead: swipe to the next part, 👍/👎 zoom, ✊ open, ✌ close.
REA_GESTURES = {"next": "next", "previous": "previous", "volume_up": "zoom_in", "volume_down": "zoom_out",
                "play_pause": "open", "creative": "close"}
LIBRARY_GESTURES = {"next": "next", "previous": "previous", "play_pause": "open", "volume_up": "open",
                    "volume_down": "back", "creative": "close"}
# Autopilot: the owner said "just do what I ask", so these never ask. Still asked, because they send the owner's
# words off this PC: send_online and ask_claude.
NEVER_ASK = SCREEN_STEP_TOOLS | {"web_search", "add_task", "library", "set_location", "draft_mail", "skills", "deep_work",
                                "make_document",
                                 "web", "send_file", "add_event", "reverse_engineer"}
ASK_REMIND_SECONDS, ASK_GIVE_UP_SECONDS = 25, 90  # a question nobody answers is asked again, then counts as no
MODIFIER_KEYS = (0x10, 0x11, 0x12)  # Shift, Ctrl, Alt
# What the owner's own gestures can do (SETTINGS → Gestures).
GESTURE_ACTIONS = {"volume_up": "Volume up", "volume_down": "Volume down", "mute": "Mute", "play_pause": "Play / pause",
                   "next": "Next song or video", "previous": "Previous song or video", "creative": "Open creative mode",
                   "library": "Open or close the Library", "stop": "Stop Nova (like Esc)", "ask": "Ask Nova something"}
POSE_NAMES = {"Pointing_Up": "☝ pointing up", "ILoveYou": "🤟 love-you sign", "record": "your own pose"}
GESTURE_NAMES = {"volume_up": "👍 Volume up", "volume_down": "👎 Volume down", "next": "✋ Next",
                 "previous": "✋ Previous", "play_pause": "✊ Play / pause", "creative": "✌ Creative mode"}


def _data_dir() -> Path:
    return Path(os.environ.get("ALFRED_DATA_DIR") or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Alfred" / "DesktopData")


def _settings_path() -> Path:
    return _data_dir() / "alfred_settings.json"


def _load_settings() -> dict[str, Any]:
    try:
        data = json.loads(_settings_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _spoken_question(name: str, arguments: dict[str, Any]) -> str:
    """The yes-or-no question as Nova says it out loud."""
    if arguments.get("speak"):
        return str(arguments["speak"])
    if name == "add_task":
        return f"Should I save the task: {str(arguments.get('task', ''))[:120]}?"
    if name == "ask_claude":
        return "Should I send this question to Claude?"
    asked = _plain_words(str(arguments.get("summary", "")))[:160]
    return f"Okay to {asked[:1].lower()}{asked[1:]}?" if asked else "Should I go ahead?"


def _plain_words(text: str) -> str:
    """Text as it sounds: quotes dropped, every run of spaces and new lines one space."""
    return " ".join(text.translate(_NO_QUOTES).split())


_NO_QUOTES = str.maketrans("", "", '"“”')


def _popup_text(name: str, arguments: dict[str, Any]) -> tuple[str, str]:
    """Title and text of the pop-up, for an owner who turned "Questions by voice" off."""
    if name == "add_task":
        return "Save this task?", str(arguments.get("task", ""))
    if name == "send_online":
        return "Send it online?", str(arguments.get("summary", ""))
    body = str(arguments.get("summary", ""))
    if name in SCREEN_STEP_TOOLS:
        body += "\n\nNova will do exactly this one step, then look at the screen again."
    return "Nova asks first", body


def _always_on_defaults(settings: dict[str, Any], save: Callable[[str, Any], None]) -> bool:
    """Once, the first time this version runs: screen assist with autopilot, and the second brain, switch on by
    themselves (the owner asked for that and said Nova has all permission). A switch the owner has already set either
    way is left alone, and so is everything after this first time. True when something was switched on."""
    if settings.get("always_on_applied") or not IS_WINDOWS:
        return False
    changed = False
    for key in ("assist_consented", "autopilot", "assist_on", "second_brain_consented", "second_brain"):
        if key not in settings:
            save(key, True)
            changed = True
    save("always_on_applied", True)
    return changed


def _system_snapshot(profile) -> dict[str, str]:
    """CPU, RAM in use, graphics and OS labels for the HUD."""
    ram = "unavailable"
    if IS_WINDOWS:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            total, free = status.ullTotalPhys / 1024 ** 3, status.ullAvailPhys / 1024 ** 3
            ram = f"{total - free:.1f} / {total:.1f} GB in use"
    elif sys.platform == "darwin":
        import mac
        total, free = mac.memory_gib()
        if total and free is not None:
            ram = f"{total - free:.1f} / {total:.1f} GB in use"
    gpus = ", ".join(f"{gpu['name']}" + (f" ({gpu['reported_vram_gib']:g} GB)" if gpu.get("reported_vram_gib") else "")
                     for gpu in profile.gpus) if profile else ""
    return {"cpu": profile.cpu if profile else platform.processor(), "ram": ram, "gpu": gpus or "not detected",
            "os": f"{platform.system()} {platform.release()}", "memory": str(default_database_path())}


def _ollama_placement(model: str) -> str:
    """The loaded model's processor column from `ollama ps` (e.g. 100% GPU), without running inference."""
    try:
        exe = os.environ.get("ALFRED_OLLAMA_EXE") or "ollama"
        child_env = os.environ.copy()
        if os.environ.get("ALFRED_API_URL"):
            parsed = urlsplit(os.environ["ALFRED_API_URL"])
            child_env["OLLAMA_HOST"] = f"{parsed.hostname or '127.0.0.1'}:{parsed.port or 11434}"
        result = subprocess.run([exe, "ps"], capture_output=True, text=True, timeout=6, env=child_env, check=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for line in result.stdout.splitlines()[1:]:
            fields = line.split()
            if fields and fields[0] == model:
                placement = re.search(r"\b(\d+%)\s+(GPU|CPU)\b", line, flags=re.IGNORECASE)
                return f"{placement.group(1)} {placement.group(2).upper()}" if placement else "loaded"
        return "idle"
    except (OSError, subprocess.SubprocessError):
        return ""


def _qr_data_url(url: str) -> str:
    import qrcode
    import qrcode.image.svg
    buffer = io.BytesIO()
    qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2).save(buffer)
    return "data:image/svg+xml;base64," + base64.b64encode(buffer.getvalue()).decode()


class AlfredApp(AdvanceMode, SetupActions, WorkplaceActions, BuildingActions):
    def __init__(self, root: tk.Tk, startup: dict[str, Any] | None = None) -> None:
        startup = startup or {}
        self.root = root
        self.root.withdraw()  # the HUD is the window; Tk only runs the loop and the Notes window
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.lock = threading.RLock()
        self.settings = _load_settings()
        self.first_run_notice = _always_on_defaults(self.settings, self._save_setting)
        self.memory = Memory()
        self.agent = Agent(model=MODEL or ("qwen2.5:7b" if USB else "qwen3:8b"), memory=self.memory)
        self.agent_lock = threading.Lock()  # the HUD and the phone take turns with the agent
        self.creative = CreativeServer()
        self.creative.before_open = lambda: (self._hand_camera_to_creative(), self._warm_vision())
        self.creative.open_in_app = self._open_creative_in_app
        self.creative.on_control = lambda action: self.events.put(("creative_control", action))
        self.creative.on_scan = self._scan_object
        self.creative.on_photo = lambda path: self.events.put(("photo_saved", path))
        self.agent.creative = self.creative
        self.agent.owner_name = str(self.settings.get("owner_name") or "")
        self.agent.soul = str(self.settings.get("soul", agent_module.DEFAULT_SOUL))
        self.location = places.Location(load=lambda: self.settings.get("location"), save=self._save_location,
                                        region=lambda: self.settings.get("brief_region", "US"))
        self.agent.location = self.location
        self.agent.tv = self.show_on_tv
        try:
            import assist_helper
            assist_helper.STOP_KEYS = list(self._hotkey("stop"))  # Nova's typing stops on the owner's stop key
        except Exception:
            pass
        self.music = music_player.Music(on_change=lambda _track: self.events.put(("music", None)))
        self.pc = pc_sync.this_pc()
        self.brain = brain.SecondBrain(
            self._vault(), foreground=brain.windows_foreground, read_text=self._brain_screen_text,
            summarize=self._brain_summarize, idle_seconds=brain.windows_idle_seconds,
            quiet=lambda: not self.state.get("busy") and not self.listening,
            on_change=lambda: self.events.put(("brain_changed", None)), extract=self._brain_extract,
            on_battery=brain.windows_on_battery if IS_WINDOWS else lambda: False)
        self.skills = skill_notes.Skills(self._vault_folder())
        self.agent.skills = self.skills
        self.deep_work = DeepWork(self._vault_folder, self.skills.save_output,
                                  lambda title, result, ok: self.events.put(("deep_work_done", (title, result, ok))),
                                  built=lambda name, folder, ok, said: self.events.put(("build_done", (name, folder, ok, said))))
        self.agent.deep_work = self.deep_work.start if self.deep_work.available else None
        self.agent.build = self.deep_work.build if self.deep_work.available else None
        self.reminders = reminder_list.Reminders(_data_dir() / "reminders.json")
        self.agent.reminders = self.reminders
        self.running_skill: skill_notes.Skill | None = None  # its result is saved in outputs/ when the turn ends
        self.web = WebBrowser() if app_window.find_edge() is not None or os.environ.get("NOVA_BROWSER") else None
        self.tool_server: ToolServer | None = None  # Nova's tools for Claude Code (the Claude plan brain), started on first use
        self.google_mcp = google_mcp.GoogleMcp(lambda: self.agent.gmail, lambda: self.agent.drive)  # for the owner's Claude apps
        self.updates = self_update.Updater(VERSION, self_update.default_folder())
        self.update_ready: Path | None = None  # a verified installer waiting for "Restart to update"
        self.telegram = telegram_remote.TelegramRemote(
            ask=self._ask_from_telegram, transcribe=self.voice_transcribe,
            load=lambda: dict(self.settings.get("telegram") or {}), save=lambda data: self._save_setting("telegram", data),
            status=lambda text: self._update(telegram=self._telegram_state(text)),
            relay=cloud_relay.load, check_in=self._relay_check_in, on_away=self._relay_report)
        self.relay_delivered: set[str] = set()  # reminders the cloud relay sent while the PC was off: not said again
        self.discover = discovery.Discover(_data_dir() / "discover.json", token=discovery.stored_token)
        self.discover_items: list[dict[str, Any]] = []
        self.discover_studies: dict[str, str] = {}  # Claude Code study title -> repo
        self.skill_offers: list[dict[str, str]] = []  # skill notes a study proposed, waiting for the owner's OK
        self.tuning_now = False
        self._apply_tuning(self.settings.get("tuning"))
        self.lab_jobs = JobLog(_data_dir() / "lab_jobs.json")
        self.reverse = reverse_engineering.ReverseEngineering(
            save=self.skills.save_output, library=self._filer(reverse_engineering.LIBRARY_TOPIC),
            done=lambda title, result, ok: self.events.put(("deep_work_done", (title, result, ok))),
            workspace=Path.home() / "Documents" / "Nova Projects" / "Reverse engineering",
            node=lambda: reverse_engineering.node_version(choice=str(self.settings.get("node_path") or "")),
            jobs=self.lab_jobs, notify=self._lab_event)
        self.shannon = shannon_runner.Shannon(self.lab_jobs, library=self._filer(shannon_runner.LIBRARY_TOPIC),
                                              notify=self._lab_event, key=claude_expert.key,
                                              outputs=self.skills.outputs)
        self.agent.reverse = self.reverse.start if self.settings.get("reverse_on") else None
        self.agent.discover = self._discover_tool
        self.agent.world = self._world_tool
        self.agent.route = self._route_tool
        self.agent.optimize = self._optimize_prompt
        import screen_record
        self.recorder = screen_record.Recorder(_data_dir())
        self.agent.recorder = self.recorder
        self.agent.make_image = self._make_image
        self.docker_apps = separate_apps.Docker()
        self.setup = setup_everything.Setup(self._setup_report)
        self.usb_edition = USB
        self.auto_setup = not os.environ.get("CI")  # main() also turns it off for --smoke-test
        self.workplace_board = workplace.WorkplaceBoard(_data_dir() / "workplaces", lambda event: self.ui.emit(event))
        self.agent.open_workplace = self._open_workplace
        self.building_bench = building.BuildingBench(_data_dir() / "builds", lambda event: self.ui.emit(event))
        self.agent.open_building = self._open_building
        self.trading_desk = trading.TradingDesk()
        self.agent.trading = self.trading_desk.answer
        self.agent.advance = self._set_advance
        self.agent.obs_password = str(self.settings.get("obs_password") or "")
        self.agent.web = self.web
        self.agent.claude = claude_expert.available()
        self.agent.on_brain = lambda label, why: self.events.put(("brain", (label, why)))
        self.agent.on_free_cloud = lambda problem: self.events.put(("free_cloud", problem))
        self.agent.private_topics = self._private_topics()
        self.agent.gmail = gmail_tools.Gmail() if not USB and gmail_tools.connected() else None
        self.agent.calendar = calendar_tools.Calendar() if not USB and gmail_tools.calendar_granted() else None
        self.agent.drive = drive_tools.Drive() if not USB and gmail_tools.drive_granted() else None
        self.gestures = GestureControl(on_action=lambda action: self.events.put(("gesture", action)),
                                       on_error=lambda message: self.events.put(("warning", message)))
        self.gestures.custom = self._custom_gestures()
        self.gesture_recording = False
        self.creative_has_camera_since: float | None = None
        self.timers = Timers(on_change=lambda items: self._update(timers=items),
                             on_done=lambda timer: self.events.put(("timer_done", timer)))
        self.agent.timers = self.timers
        self.agent.notes = _MapTools(self)
        self.agent.library = _LibraryTools(self)
        self.agent.galaxy = self._open_galaxy
        self.news_store: NewsStore | None = None  # the news desk's database, opened when first needed
        self.world_monitor = world_monitor.WorldMonitor(news=self._world_news)
        self.router = routes.Router(_data_dir() / "routes", near=self._route_city)
        self.wikipedia = offline_wikipedia.Wikipedia(_data_dir() / "knowledge")
        self.notes_index = notes_search.NotesIndex(_data_dir() / "notes_index.sqlite3",
                                                   lambda texts: notes_search.ollama_embed(self.agent.base_url)(texts))
        self.knowledge: dict[str, Any] = {"packs": {}, "downloading": None, "notes": {"status": ""}, "city": ""}
        self.news_running = False
        self.agent.news = self._news_lookup if self.settings.get("news_on") else None
        self.answers = deque(maxlen=12)  # who answered the latest requests (also in answers.jsonl in the data folder)
        self.pc_stats: dict[str, Any] = {}
        self.pc_stats_wanted = 0.0  # when the page last asked for live stats (the sampler stops 15 s later)
        self.cpu_meter = pc_monitor.CpuMeter()
        self.library_open = False  # the Library is on screen: short commands and gestures move it
        self.library_gesture = ("", 0.0)  # the last gesture that moved it, so a held one acts once
        self.dictate_release: threading.Event | None = None  # dictation (OpenWhispr's idea): held key → typed text
        self.gesture_screen = ""  # a full screen that takes the webcam gestures while it's open ("rea")
        self.heart = HeartRateMonitor(on_reading=lambda reading: self.events.put(("heart", reading)),
                                      on_status=lambda text: self.events.put(("heart_status", text)))
        self.slide: dict[str, Any] | None = None  # what was slid onto the TV
        self.live_reply = ""  # the reply being written, for the TV's captions
        self.screen_pairing = screens.ScreenPairing(_settings_path().parent / "screens.json",
                                                    on_request=lambda code: self.events.put(("tv_request", code)))
        self.phone = PhoneBridge(ask=self._ask_from_phone, control=self._phone_control, transcribe=self.voice_transcribe,
                                 screens=self.screen_pairing, screen_state=self._screen_state, deck=self._deck_action,
                                 keyboard=self._deck_keyboard)
        self.voice = VoiceController()
        if self.voice.voice_name and piper_voice.VOICES[self.voice.voice_name][0].startswith("kokoro:") \
                and kokoro_voice.installed():
            threading.Thread(target=kokoro_voice.warm_up, name="AlfredVoiceWarmUp", daemon=True).start()
        self.voice.set_level_callback(self._on_mic_level)
        self.voice.on_speaking = lambda busy: self.events.put(("speaking", busy))
        self.hardware = startup.get("hardware")
        self.assist = None
        self.target_hwnd: int | None = None  # the last app window the user used that isn't Nova
        self.window_hwnd: int | None = None
        self.window_process: subprocess.Popen | None = None
        self.turn_cancel = threading.Event()
        self.escape_is_novas = False  # this very step presses Esc itself: don't take it for the user's Esc
        self.takeover_until = 0.0  # the mini orb flares and the banner shows until then (monotonic)
        self.takeover_warned = False  # the first step of a request waits a moment so the warning is seen first
        self.mic_level = 0.0
        self.mini_orb: mini_orb.MiniOrb | None = None
        self.listening = False  # "Hey Nova" was heard and the follow-up window is open
        self.hold_release: threading.Event | None = None
        self.escape_down = False
        self.keys_down: set[str] = set()  # hotkeys held at the last poll: each fires once per press
        self.pending_approval: dict[str, Any] | None = None
        self.walkthrough: Walkthrough | None = None
        self.tray = None
        self.window_opened_at = 0.0
        self.told_about_tray = False
        self.closing = False
        self.window_missing_ticks = 0
        self.chat_items: list[dict[str, Any]] = []
        self.chat_counter = 0
        self.notices: list[dict[str, str]] = list(startup.get("notices", []))
        try:
            from screen_reader import list_monitors
            monitors = list_monitors()
        except Exception:
            monitors = []
        self.state: dict[str, Any] = {
            "edition": "usb" if USB else "desktop",
            "windows": IS_WINDOWS,
            "busy": False,
            "speaking": False,
            "latency_ms": None,
            "approval": None,
            "voice": {"text": "MIC OFF", "tone": "idle"},
            "switches": {"mic": False, "speak": bool(self.settings.get("speak_on")), "gestures": False, "phone": False,
                         "assist": False, "brief": bool(self.settings.get("brief_on")),
                         "gmail": None if USB else self.agent.gmail is not None,
                         "calendar": None if USB else self.agent.calendar is not None,
                         "drive": None if USB else self.agent.drive is not None},
            "build": BUILD,
            "update": {"version": VERSION, "auto": True, "status": "", "available": "", "ready": False, "page": "",
                       "can_install": False, "busy": False, "usb": USB},
            "model": {"name": self.agent.model, "recommended": "", "reason": "", "installed": [], "offer": startup.get("offer"),
                      "ollama": "checking", "placement": "", "context": None, "downloading": False},
            "system": _system_snapshot(self.hardware),
            "tasks": [],
            "facts": [],
            "timers": [],
            "reminders": [],
            "walkthrough": None,
            "heart": {"on": False, "status": "", "bpm": None},
            "place": self._place_summary(),
            "weather_now": None,
            "local_news": [],
            "second_brain": {"on": False, "running": False, "status": "off", "last": "", "notes_today": 0, "vault": "",
                             "videos": True, "videos_ready": False, "exclude": "", "gathered": 0},
            "pcs": {"on": False, "pc": "", "folder": "", "others": [], "wiki": "", "error": ""},
            "tuning": {"auto": self.settings.get("auto_tune", True) is not False, "running": False, "step": "",
                       "result": self.settings.get("tuning")},
            "claude": {"on": False, "key": False, "hint": "", "model": cloud_brain.DEFAULT_MODEL,
                       "effort": cloud_brain.DEFAULT_EFFORT, "models": cloud_brain.MODELS, "usb": USB},
            "free_cloud": {"on": False, "model": FREE_CLOUD_DEFAULT, "status": "", "usb": USB},
            "telegram": {"on": False, "token": False, "owner": "", "bot": "", "code": "", "status": "", "usb": USB},
            "answering": self._answering_state(),
            "brain": {"label": "", "why": ""},
            "gestures": self._gestures_state(),
            "news": {"on": bool(self.settings.get("news_on")), "running": False, "status": "", "key": False, "last": None,
                     "total": 0, "at": "06:00"},
            "hotkeys": self._hotkey_state(),
            "music": None,
            "setup": self.setup.state(),
            "settings": {"accent": self.settings.get("accent", "gold"), "interests": self.settings.get("interests", []),
                         "brief_region": self.settings.get("brief_region", "US"), "model": self.settings.get("model", "auto"),
                         "news_outlets": daily_brief.saved_outlets(self.settings.get("news_outlets")),
                         "autopilot": bool(self.settings.get("autopilot")),
                         "ask_risky": bool(self.settings.get("ask_risky")),
                         "ask_by_voice": bool(self.settings.get("ask_by_voice", True)),
                         "screen_vision": bool(self.settings.get("screen_vision", True)),
                         "keep_running": self.settings.get("keep_running", True),
                         "mini_orb": self.settings.get("mini_orb", True),
                         "soul": self.settings.get("soul", agent_module.DEFAULT_SOUL),
                         "node_path": self.settings.get("node_path", ""), **self._advance_settings()},
            "brief": None,
            "brief_loading": False,
            "notes": self._notes_state(),
            "displays": [f"Display {index} · {monitor['width']}×{monitor['height']}" for index, monitor in enumerate(monitors, 1)],
        }
        self.ui = UiServer(on_action=self._action_from_page, snapshot=self._snapshot, lock=self.lock)
        self._load_recent_chat()
        self._refresh_tasks()

    # ---------- start, window, close ----------

    def start(self, open_window: bool = True) -> str:
        url = self.ui.start()
        self.ui.on_show = lambda: self.events.put(("open_window", ""))
        self.ui.on_replace = lambda: self.events.put(("quit", None))  # a newer Nova build is starting
        if open_window:
            self._open_window()
            self._start_tray()
            if IS_WINDOWS:
                self._start_mini_orb()
        self.root.after(100, self._poll_events)
        self.root.after(1000, self._watch_window)
        if sys.platform == "darwin":
            import mac
            if not mac.quartz().may_listen(ask=False):
                mac.quartz().may_listen(ask=True)  # macOS asks once: Input Monitoring, for the hold-to-talk keys
            self.root.after(1500, self._poll_keys)
        threading.Thread(target=self._resolve_model, name="AlfredModelChoice", daemon=True).start()
        if self.settings.get("mic_on") and self.voice.available:
            self.root.after(900, self._start_mic)
        self.root.after(2500, self._refresh_weather)
        if sys.platform in ("win32", "darwin"):
            self.music.start()  # what's playing: a cheap look once a second; the bars only while music plays
            self.root.after(1000, self._stream_music_bars)
        if self.settings.get("second_brain") and sys.platform == "win32":
            self.root.after(4000, self._apply_second_brain)
        self._apply_pc_sync()
        self._apply_knowledge()
        self._apply_claude()
        self._apply_free_cloud()
        self._apply_telegram()
        self._google_mcp_apply()
        self.root.after(5000, self._sync_pcs)
        self.root.after(60_000, self._update_tick)  # GitHub Releases: a minute after start, then every few hours
        self._update_state()
        self._update(discover=self._discover_state())
        self.root.after(45_000, lambda: self._act_discover_refresh({}))  # cached for 12 hours: cheap after the first
        self.root.after(20_000, self._news_tick)  # the news desk's daily run (06:00, or the first minute after)
        self.root.after(30_000, self._skills_tick)  # skills on a schedule (a PC that was off catches up the same day)
        self.root.after(5_000, self._reminders_tick)  # reminders, also the ones missed while the PC was off
        if open_window and not USB:
            self.root.after(setup_actions.FIRST_RUN_DELAY_MS, self._setup_first_run)
        try:
            self.skills.ensure_defaults()
        except OSError:
            pass  # the vault's drive isn't there right now: no starting skills yet
        self._update(skills=self._skills_state())
        self._update(news=self._news_state())
        if self.settings.get("webcam_on"):
            self.root.after(1200, self.gestures.start)
            self._update(switches={"gestures": True})
        if self.settings.get("phone_on"):
            self.root.after(1500, self._restart_phone)
        self.agent.autopilot = bool(self.settings.get("autopilot"))
        self.agent.screen_vision = bool(self.settings.get("screen_vision", True))
        if self.first_run_notice:
            self._toast("Screen assist with autopilot and your second brain are on, as you asked. SETTINGS and SCREEN switch them off.", "ok")
        if IS_WINDOWS and self.settings.get("assist_consented") and self.settings.get("assist_on"):
            self.root.after(2000, lambda: self._act_assist({"on": True, "consented": True}))  # screen assist stays on across launches
        if self.state["switches"]["brief"]:
            self._load_brief(force=False)
        if self.settings.get("heart_on"):
            self._act_heart({"on": True})
        return url

    def _open_window(self, extra: str = "") -> None:
        """Show the HUD: un-minimize it if it is open, else open it again (closing it only hides Nova)."""
        if self.ui.clients and (app_window.is_window(self.window_hwnd) or not IS_WINDOWS):
            app_window.restore(self.window_hwnd)
            if extra == "open=creative":
                self.creative.open_window()
            return
        if time.monotonic() - self.window_opened_at < 8:
            return  # already opening
        self.window_opened_at = time.monotonic()
        url = self.ui.url + (f"&{extra}" if extra else "")
        self.window_process = app_window.open_window(url, _data_dir() / "hud-browser")

    def _start_tray(self) -> None:
        """A tray icon, so Nova keeps listening for its name when the window is closed."""
        if not IS_WINDOWS:
            return
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError:
            return
        try:  # Nova's app icon (packaging/nova.png, bundled), the same one as the exe and the installer
            image = Image.open(Path(__file__).resolve().parent / "packaging" / "nova.png").convert("RGBA").resize((64, 64))
        except OSError:
            image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.ellipse((6, 6, 58, 58), outline=(34, 211, 238, 255), width=7)
        menu = pystray.Menu(pystray.MenuItem("Open Nova", lambda: self.events.put(("open_window", "")), default=True),
                            pystray.MenuItem("Quit Nova", lambda: self.events.put(("quit", None))))
        self.tray = pystray.Icon("Nova", image, "Nova", menu)
        threading.Thread(target=self.tray.run, name="AlfredTray", daemon=True).start()

    def _on_mic_level(self, level: float) -> None:
        self.mic_level = level
        self.ui.emit({"type": "level", "level": round(level, 3)})

    # ---------- mini Nova in the corner ----------

    def _start_mini_orb(self) -> None:
        position = self.settings.get("mini_orb_position")
        self.mini_orb = mini_orb.MiniOrb(
            self.root, self._mini_orb_state, on_open=lambda: self.events.put(("open_window", "")),
            on_right_click=self._mini_orb_mic,
            position=tuple(position) if isinstance(position, list) and len(position) == 2 else None,
            on_moved=lambda where: self._save_setting("mini_orb_position", list(where)),
            music=lambda: (self.music.art_image(), list(self.music.bands)))
        self.mini_orb.start()

    def _mini_orb_state(self) -> tuple[str, float, tuple[int, int, int], bool]:
        """While you use other apps (not over Nova's own window, full-screen video or creative mode)."""
        acting = time.monotonic() < self.takeover_until
        show = False
        if self.settings.get("mini_orb", True):
            hwnd, title, full_screen = mini_orb.foreground()
            show = (hwnd is not None and hwnd != self.window_hwnd and not full_screen
                    and not title.startswith("Nova · Creative"))
        accent = ACCENT_RGB.get(self.state["settings"].get("accent", "gold"), ACCENT_RGB["gold"])
        return mini_orb.mode_for(self.state, acting), self.mic_level, accent, show

    def _mini_orb_mic(self) -> None:
        if self.settings.get("mic_consented") and self.voice.available:
            self._act_mic({"on": not self.state["switches"]["mic"]})
        else:
            self._open_window()  # the first time, the mic is switched on in the window, where it is explained

    def _watch_window(self) -> None:
        """Closing the window keeps Nova running in the tray (or quits it, if the user chose that)."""
        if self.closing:
            return
        if not app_window.is_window(self.window_hwnd):
            self.window_hwnd = app_window.find_window()
        if self.ui.ever_connected.is_set() and self.ui.clients == 0:
            self.window_missing_ticks += 1
            exited = self.window_process is not None and self.window_process.poll() is not None
            if self.window_missing_ticks == (3 if exited else 10):
                if not self.settings.get("keep_running", True) or self.tray is None:
                    self._close()
                    return
                if not self.told_about_tray:
                    self.told_about_tray = True
                    self._notify("Nova is still running. Say “Hey Nova” or click the tray icon to open it.")
        else:
            self.window_missing_ticks = 0
        self.root.after(1000, self._watch_window)

    def _notify(self, text: str) -> None:
        """A message when the window may be closed: a Windows notification from the tray, else a toast."""
        if self.tray is not None and not self.ui.clients:
            try:
                self.tray.notify(text, "Nova")
                return
            except Exception:
                pass
        self._toast(text, "info")

    def _close(self) -> None:
        if self.closing:
            return
        self.closing = True
        self.turn_cancel.set()
        self._stop_walkthrough()
        if self.web is not None:
            self.web.close()
        if self.tool_server is not None:
            self.tool_server.shutdown()
        self.google_mcp.stop()
        self.telegram.stop(going=True)  # the cloud relay (if set up) answers from now on
        self.creative.stop()
        self.gestures.stop()
        self.heart.stop()
        self.phone.stop()
        if self.voice.whisper is not None:
            self.voice.whisper.stop()
        if self.assist is not None:
            self.assist.close()
        self.voice.stop_wake()
        self.voice.stop_speaking()
        if self.pending_approval:
            self.pending_approval["event"].set()
        self.ui.stop()
        if self.tray is not None:
            self.tray.stop()
        if self.window_process is not None and self.window_process.poll() is None:
            if IS_WINDOWS:  # the whole Edge tree (renderers, crash handler), so nothing outlives Nova
                subprocess.run(["taskkill", "/PID", str(self.window_process.pid), "/T", "/F"], capture_output=True,
                               check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                self.window_process.terminate()
        self.root.destroy()

    # ---------- state the HUD renders ----------

    def _snapshot(self) -> dict[str, Any]:
        self.library_open = False  # a page that (re)loads starts with the Library closed
        self.gesture_screen = ""
        with self.lock:
            notices, self.notices = self.notices, []
            return {"state": copy.deepcopy(self.state), "chat": list(self.chat_items), "notices": notices}

    def _update(self, **changes: Any) -> None:
        with self.lock:
            for key, value in changes.items():
                if isinstance(value, dict) and isinstance(self.state.get(key), dict):
                    self.state[key].update(value)
                else:
                    self.state[key] = value
            self.ui.emit({"type": "state", "patch": copy.deepcopy(changes)})

    def _toast(self, text: str, tone: str = "info", action: dict[str, Any] | None = None) -> None:
        if self.ui.clients:
            self.ui.emit({"type": "toast", "text": text, "tone": tone, "action": action})
        else:
            with self.lock:
                self.notices.append({"text": text, "tone": tone, "action": action})

    def _append_chat(self, label: str, text: str, role: str) -> None:
        with self.lock:
            self.chat_counter += 1
            item = {"id": self.chat_counter, "label": label, "text": text, "role": role,
                    "time": datetime.now().strftime("%H:%M")}
            self.chat_items = (self.chat_items + [item])[-80:]
            self.ui.emit({"type": "chat", "item": item})

    def _set_voice_state(self, text: str, tone: str = "idle") -> None:
        self._update(voice={"text": text, "tone": tone})

    def _set_idle_voice(self) -> None:
        """Between requests: still listening (no name needed) right after a request, else waiting for "Hey Nova"."""
        if not self.state["switches"]["mic"]:
            self._set_voice_state("READY", "idle")
        elif self.listening:
            self._set_voice_state("LISTENING · NO NEED TO SAY “HEY NOVA” · “THANKS” TO END", "listen")
        else:
            self._set_voice_state("MIC ON · SAY “HEY NOVA”", "idle")

    def _set_busy(self, busy: bool) -> None:
        self._update(busy=busy)

    def _data_folder(self) -> Path:
        return _data_dir()

    def _save_setting(self, key: str, value: Any) -> None:
        self.settings[key] = value
        try:
            path = _settings_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except OSError:
            pass  # the switch still works for this session

    def _load_recent_chat(self) -> None:
        visible = [item for item in self.memory.recent_messages(limit=24) if item.get("role") in {"user", "assistant"}]
        for item in visible[-14:]:
            self._append_chat("YOU" if item["role"] == "user" else "NOVA", item.get("content", ""), item["role"])
        if not visible:
            self._append_chat("NOVA", _greeting(self.agent.owner_name),
                              "assistant")

    def _refresh_tasks(self) -> None:
        self._update(tasks=[item["task"] for item in self.memory.list_tasks(limit=20)], facts=self.memory.list_facts())

    # ---------- actions from the page ----------

    ACTIONS = {"send", "stop", "speak", "mic", "gestures", "phone", "phone_pairing", "phone_new_code", "assist", "autopilot", "gmail",
               "creative", "notes_save", "notes_load", "notes_new", "notes_delete", "map_expand", "read_screen", "audio_devices", "audio_save", "test_mic", "test_speaker",
               "test_voice", "install_whisper", "whisper_save", "install_vietnamese_voice", "location_city", "location_device", "location_forget", "open_photos", "second_brain", "second_brain_settings", "second_brain_now", "second_brain_ingest", "open_vault", "pc_sync", "wiki_here", "claude", "claude_settings", "claude_key", "claude_key_forget", "telegram", "telegram_token", "telegram_token_forget", "telegram_unpair", "telegram_relay", "update_check", "update_auto", "update_install", "update_rollback", "discover_refresh", "discover_add", "discover_skip", "discover_settings", "discover_install_skill", "discover_drop_skill", "reverse_toggle", "free_cloud", "free_cloud_settings", "free_cloud_signin", "brain_choose", "privacy", "downloads", "hotkey", "media", "tv_allow", "tv_show", "tv_clear", "tv_forget", "screens_info", "approve", "set_model", "pull_model", "pull_vision", "settings", "brief", "brief_refresh",
               "open_url", "status_refresh", "cancel_timer", "forget_fact",
               "setup_everything", "setup_stop", "workplace_sync", "workplace_save", "workplace_list", "workplace_load",
               "workplace_delete", "workplace_file", "build_sync", "build_save", "build_list", "build_load", "build_delete", "build_anatomy", "trading", "advance", "advance_widgets", "advance_board", "advance_apps", "app_open", "app_stop", "app_page", "app_add", "app_remove",
               "walkthrough_next", "walkthrough_stop", "heart", "library", "library_topic", "library_save",
               "library_delete", "library_open", "library_view", "gesture_add", "gesture_delete", "news", "news_run",
               "news_key", "news_key_forget", "news_search", "pc_stats", "model_load", "model_unload",
               "version_create", "version_delete", "model_compare", "skill_run", "skills_suggest", "open_outputs", "reminder_cancel",
               "world", "claude_connectors", "google_mcp", "node_path", "route",
               "knowledge_catalog", "knowledge_download", "knowledge_remove", "notes_index", "keep_city",
               "obs_password", "lab_view", "rea_view", "rea_start", "rea_open", "rea_report", "rea_fit_add", "rea_pick",
               "tune_now", "auto_tune", "cloud_fallback", "api_brain_add", "api_brain_use", "api_brain_remove",
               "api_brain_models", "cloud_agent_use", "cloud_agent_install", "cloud_agent_connect", "skills_board", "shannon_view", "shannon_start", "shannon_stop", "shannon_open", "shannon_report",
               "shannon_fix", "shannon_simulate", "shannon_simulate_report", "shannon_pick", "galaxy_data", "update_now", "google_pick_client"}

    def _action_from_page(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Runs on an HTTP thread: hand the action to the main thread and wait for its result."""
        if name not in self.ACTIONS:
            return {"ok": False, "error": f"Unknown action {name}."}
        reply: queue.Queue = queue.Queue(maxsize=1)
        self.events.put(("ui_action", (name, args, reply)))
        try:
            return reply.get(timeout=30)
        except queue.Empty:
            return {"ok": False, "error": "Nova is busy; try again."}

    def _run_action(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return getattr(self, f"_act_{name}")(args) or {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _act_send(self, args: dict[str, Any]) -> dict[str, Any] | None:
        text = str(args.get("text", "")).strip()[:4000]
        if not text:
            return {"ok": False}
        if self._library_said(text):
            return None
        skill = self.skills.match(text)
        if skill is not None:
            return self._start_skill(skill, said=text)
        if self.state["busy"]:
            return {"ok": False, "error": "Nova is still working on the last request. Esc stops it."}
        self.voice.stop_speaking()
        self._stop_walkthrough()  # a new question replaces the walkthrough
        self._append_chat("YOU", text, "user")
        self._set_busy(True)
        threading.Thread(target=self._chat_worker, args=(text,), daemon=True).start()
        return None

    # ---------- skills: tasks written down once (skills.py), outputs in the vault, long work on Claude Code ----------

    def _skills_state(self) -> dict[str, Any]:
        runs = self.settings.get("skill_runs") or {}
        return {"claude_code": self.deep_work.available, "working": list(self.deep_work.running),
                "list": [{"name": skill.name, "title": skill.title, "says": skill.says[:2], "schedule": skill.schedule,
                          "brain": skill.brain, "last": str(runs.get(skill.name, ""))[:16].replace("T", " ")}
                         for skill in self.skills.all()]}

    def _start_skill(self, skill: skill_notes.Skill, said: str | None = None) -> dict[str, Any] | None:
        """Run a skill now: long work goes to Claude Code in the background; the rest is a normal turn whose answer is
        saved in outputs/ when it ends (chat_done)."""
        if skill.brain != "claude-code" and self.state["busy"]:
            return {"ok": False, "error": "Nova is still working on the last request. Esc stops it."}
        self._save_setting("skill_runs", {**(self.settings.get("skill_runs") or {}), skill.name: datetime.now().isoformat()})
        self._append_chat("YOU" if said else "SKILL", said or f"{skill.title} (on schedule)", "user")
        if skill.brain == "claude-code":
            started = self.deep_work.start(skill.title, skill.instructions)
            self._append_chat("NOVA", started.split(" Tell them")[0], "assistant")
            self._update(skills=self._skills_state())
            return None
        self.voice.stop_speaking()
        self.running_skill = skill
        self.agent.only_tools = set(skill.tools) | {"skills"} if skill.tools else None
        self._set_busy(True)
        text = skill_notes.prompt(skill)
        threading.Thread(target=self._chat_worker, args=(f"privately {text}" if skill.brain == "local" else text,),
                         daemon=True).start()
        return None

    def _finish_skill(self, reply: str | None) -> None:
        """After a skill's turn: its result in outputs/ (not a stopped or failed one), and the tools back to normal."""
        skill, self.running_skill, self.agent.only_tools = self.running_skill, None, None
        if skill is None or not reply or not skill.output or self.turn_cancel.is_set():
            return
        try:
            path = self.skills.save_output(skill.title, reply)
            self._append_chat("SYSTEM", f"Saved in your vault: outputs/{path.name}", "system")
        except OSError as exc:
            self._toast(f"Couldn't save the result in outputs/: {exc}", "warn")
        self._update(skills=self._skills_state())

    def _skills_tick(self) -> None:
        if self.closing:
            return
        if not self.state["busy"]:
            due = self.skills.due(datetime.now(), self.settings.get("skill_runs") or {})
            if due:
                self._start_skill(due[0])  # one at a time; the next waits for the next minute
        self.root.after(60_000, self._skills_tick)

    def _reminders_state(self) -> list[dict[str, Any]]:
        return [{"id": item.id, "text": reminder_list.describe(item)} for item in self.reminders.items()]

    def _reminders_tick(self) -> None:
        if self.closing:
            return
        for item, late in self.reminders.due():
            if f"{item.id}@{item.at}" in self.relay_delivered:
                continue  # already sent to Telegram while the PC was off
            said = reminder_list.spoken(item, late)
            self._append_chat("REMINDER", said, "system")
            self._toast(said, "info")
            self.voice.say(said)
        if self.state.get("reminders") != self._reminders_state():
            self._update(reminders=self._reminders_state())
        self.root.after(20_000, self._reminders_tick)

    def _act_reminder_cancel(self, args: dict[str, Any]) -> None:
        self.reminders.cancel(reminder_id=int(args.get("id") or 0))
        self._update(reminders=self._reminders_state())

    def _act_skill_run(self, args: dict[str, Any]) -> dict[str, Any] | None:
        skill = self.skills.get(str(args.get("name", "")))
        return self._start_skill(skill) if skill else {"ok": False, "error": "That skill isn't in skills/ any more."}

    def _act_skills_suggest(self, _args: dict[str, Any]) -> dict[str, Any] | None:
        return self._act_send({"text": "Look at what I did over the last 30 days in my second brain and the skills I "
                                       "already have. Which tasks do I repeat that could become skills? Suggest up to 5, "
                                       "each with a title, the phrase to run it and a schedule, and ask which to make."})

    def _act_open_outputs(self, _args: dict[str, Any]) -> None:
        self.skills.outputs.mkdir(parents=True, exist_ok=True)
        app_window.open_path(self.skills.outputs)

    def _act_stop(self, _args: dict[str, Any]) -> None:
        self.turn_cancel.set()
        self._stop_walkthrough()
        self.voice.stop_speaking()
        self._update(speaking=False)
        threading.Thread(target=self._clear_overlays, daemon=True).start()
        if self.state["busy"]:
            self._set_voice_state("STOPPING", "warn")

    def _act_speak(self, args: dict[str, Any]) -> None:
        on = bool(args.get("on"))
        self._save_setting("speak_on", on)
        self._update(switches={"speak": on})
        if not on:
            self.voice.stop_speaking()

    def _act_mic(self, args: dict[str, Any]) -> dict[str, Any] | None:
        """The mic switch: on = Nova listens for its name; off = the microphone is closed."""
        if not args.get("on"):
            self.voice.stop_wake()
            self._update(switches={"mic": False})
            self._set_voice_state("MIC OFF", "idle")
            self._save_setting("mic_on", False)
            return None
        if not self.voice.available:
            return {"ok": False, "error": "The offline speech model is missing. See the setup guide."}
        if not self.settings.get("mic_consented") and not args.get("consented"):
            return {"need_consent": "mic"}
        self._save_setting("mic_consented", True)
        if not whisper_engine.installed() and not self.settings.get("whisper_offered"):
            self._save_setting("whisper_offered", True)
            self._toast("Tip: Whisper understands accents and mixed English much better than the basic recognizer "
                        f"(about {whisper_engine.DOWNLOAD_MB} MB, runs on this PC).", "info",
                        {"label": "Install Whisper", "name": "install_whisper", "args": {}})
        self._save_setting("mic_on", True)
        self._start_mic()
        return None

    def _start_mic(self) -> None:
        self._update(switches={"mic": True, "speak": True})  # talking to Nova means hearing the answer
        self.listening = False
        self._set_idle_voice()
        self.voice.start_wake(
            on_wake=lambda: self.events.put(("wake_detected", None)),
            on_command=lambda text: self.events.put(("voice_command", text)),
            on_error=lambda error: self.events.put(("voice_error", error)),
            on_notice=lambda notice: self.events.put(("voice_notice", notice)),
            on_sleep=lambda: self.events.put(("voice_sleep", None)),
            on_barge_in=lambda: self.events.put(("barge_in", None)),
        )
        # Ready before the first request: Whisper's server starts now instead of on the first command.
        if self.voice.whisper is not None:
            threading.Thread(target=lambda: _quietly(self.voice.whisper._ensure_started), daemon=True).start()

    def _act_gestures(self, args: dict[str, Any]) -> dict[str, Any] | None:
        if not args.get("on"):
            self.gestures.stop()
            self._save_setting("webcam_on", False)
            self._update(switches={"gestures": False})
            return None
        if not self.settings.get("webcam_consented") and not args.get("consented"):
            return {"need_consent": "gestures"}
        self._save_setting("webcam_consented", True)
        self._save_setting("webcam_on", True)
        self.gestures.start()
        self._update(switches={"gestures": True})
        return None

    def voice_transcribe(self, pcm: bytes) -> str:
        """Speech recorded in Nova Lite (phone or handheld), heard by this PC's recognizers."""
        return self.voice.transcribe_pcm(pcm)

    def _pairing(self) -> dict[str, Any]:
        from local_tls import ca_fingerprint
        url = self.phone.pairing_url()
        return {"ok": True, "url": url, "qr": _qr_data_url(url), "fingerprint": ca_fingerprint()}

    def _act_phone(self, args: dict[str, Any]) -> dict[str, Any] | None:
        if not args.get("on"):
            self.phone.stop()
            self._save_setting("phone_on", False)
            self._update(switches={"phone": False})
            return None
        if not self.settings.get("phone_consented") and not args.get("consented"):
            return {"need_consent": "phone"}
        if not self.phone.running:
            try:
                self.phone.start()
            except OSError as exc:
                return {"ok": False, "error": f"Could not start the phone connection: {exc}"}
        self._save_setting("phone_consented", True)
        self._save_setting("phone_on", True)
        self._update(switches={"phone": True})
        return self._pairing()

    def _act_phone_pairing(self, _args: dict[str, Any]) -> dict[str, Any]:
        return self._pairing() if self.phone.running else {"ok": False, "error": "Nova Lite is off."}

    def _act_phone_new_code(self, _args: dict[str, Any]) -> dict[str, Any]:
        self.phone.new_pairing()
        return self._pairing()

    def _restart_phone(self) -> None:
        try:
            self.phone.start()
            self._update(switches={"phone": True})
        except OSError:
            pass  # the port is busy; the user can switch it on again

    def _act_assist(self, args: dict[str, Any]) -> dict[str, Any] | None:
        if not IS_WINDOWS:
            return {"ok": False, "error": "Screen assist on the Mac comes in the next version of Nova; everything else works here."}
        if not args.get("on"):
            self._stop_walkthrough()
            if self.assist is not None:
                self.assist.close()
                self.assist = None
            self._update(switches={"assist": False})
            self._save_setting("assist_on", False)
            self._set_voice_state("SCREEN ASSIST OFF", "idle")
            return None
        if not self.settings.get("assist_consented") and not args.get("consented"):
            return {"need_consent": "assist"}  # asked once; the owner's yes is remembered
        if not self.settings.get("assist_consented"):
            self._save_setting("assist_consented", True)
            self._set_autopilot_setting("autopilot", True)  # the consent text says so: Nova does the steps herself
        self._save_setting("assist_on", True)
        if self.assist is not None:
            return None  # already on
        from screen_assist import ScreenAssist
        self.assist = ScreenAssist()
        self._update(switches={"assist": True})
        self._set_voice_state(f"SCREEN ASSIST ON · HOLD {hotkeys.label(self._hotkey('talk')).upper()} TO TALK", "info")
        self._poll_keys()
        return None

    # SCREEN switches: autopilot (no question per step), ask_risky (the optional safety net before money, sending,
    # deleting, passwords), ask_by_voice (questions said out loud, no pop-up) and screen_vision (with Claude set up,
    # screen jobs go to Claude, which sees a screenshot of each step).
    AUTOPILOT_SWITCHES = {"on": "autopilot", "ask_risky": "ask_risky", "ask_by_voice": "ask_by_voice",
                          "screen_vision": "screen_vision"}
    AGENT_SWITCHES = ("autopilot", "screen_vision")  # these also change how the agent works

    def _act_autopilot(self, args: dict[str, Any]) -> dict[str, Any] | None:
        for arg, setting in self.AUTOPILOT_SWITCHES.items():
            if arg in args:
                self._set_autopilot_setting(setting, bool(args[arg]))
        return None

    def _set_autopilot_setting(self, setting: str, on: bool) -> None:
        self._save_setting(setting, on)
        self._update(settings={setting: on})
        if setting in self.AGENT_SWITCHES:
            setattr(self.agent, setting, on)

    def _act_gmail(self, args: dict[str, Any]) -> dict[str, Any] | None:
        """Connects Google (Gmail, Calendar and Drive), or disconnects it. calendar / drive: reconnect a sign-in from
        before Calendar or Drive was added, so Google asks for them too."""
        if USB:
            return {"ok": False, "error": "Gmail is not available on the USB Edition."}
        if self.agent.gmail is not None and not (args.get("calendar") or args.get("drive")):
            gmail_tools.disconnect()
            self.agent.gmail = None
            self.agent.calendar = None
            self.agent.drive = None
            self._google_mcp_apply()
            self._update(switches={"gmail": False, "calendar": False, "drive": False})
            return None
        if not gmail_tools.configured():
            return {"ok": True, "need_setup": True, "path": str(gmail_tools.client_path())}
        self._set_voice_state("GMAIL · FINISH SIGN-IN IN YOUR BROWSER", "info")

        def connect() -> None:
            try:
                gmail_tools.connect()
                self.agent.gmail = gmail_tools.Gmail()
                self.agent.calendar = calendar_tools.Calendar() if gmail_tools.calendar_granted() else None
                self.agent.drive = drive_tools.Drive() if gmail_tools.drive_granted() else None
                self.events.put(("gmail", True))
            except Exception as exc:
                self.events.put(("gmail", False))
                self.events.put(("warning", f"Gmail sign-in failed: {exc}"))
        threading.Thread(target=connect, daemon=True).start()
        return None

    def _act_google_pick_client(self, _args: dict[str, Any]) -> dict[str, Any]:
        """Opens a file picker for the Google OAuth client JSON, copies it to the right place, then auto-connects."""
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Pick the Google OAuth client JSON you downloaded",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return {"ok": False, "picked": False}
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if "installed" not in data and "web" not in data:
                return {"ok": False, "error": "That JSON doesn't look like a Google OAuth client file."}
            dest = gmail_tools.client_path()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return self._act_gmail({}) or {"ok": True}

    def _act_creative(self, _args: dict[str, Any]) -> None:
        self.creative.open_window()

    def _notes_state(self, current: dict[str, str] | None = None, source: str = "alfred") -> dict[str, Any]:
        """source "you": the HUD's own autosave coming back (the map keeps what is on screen);
        "alfred": Nova changed the map (voice, Ask Nova, a map opened), so the HUD shows this version."""
        maps = load_maps()
        current = current or (maps[0] if maps else {"title": "New idea", "outline": "Goal: the central idea\nBranch: a supporting thought\nNext step: what to try"})
        return {"title": current.get("title", ""), "outline": current.get("outline", ""),
                **clean_extras(current), "expanding": None, "source": source,
                "maps": [{"title": item.get("title", ""), "saved": item.get("saved", "")} for item in maps[:30]]}

    def _brainstorm(self, topic: str, ideas: str) -> str:
        """Nova's own brainstorm (from the agent's thread): saved, then shown full screen in the HUD."""
        self.events.put(("mind_map", (topic, ideas)))
        count = sum(1 for line in ideas.splitlines() if line.strip())
        return (f"The brainstorm map '{topic}' is on the user's screen with {count} ideas and saved in Notes. "
                "Say one short sentence about it; don't read every idea out.")

    def _act_notes_save(self, args: dict[str, Any]) -> None:
        """Autosave from the map or the editor. An empty map is shown but not stored; a renamed map replaces the old one."""
        current = {"title": " ".join(str(args.get("title", "")).split())[:80] or "New idea", "outline": str(args.get("outline", "")),
                   **clean_extras(args)}
        if current["outline"].strip():
            previous = " ".join(str(args.get("previous", "")).split())
            if previous and previous.casefold() != current["title"].casefold():
                delete_map(previous)
            save_map(current["title"], current["outline"], current)
        self._update(notes=self._notes_state(current, source="you"))

    def _act_map_expand(self, args: dict[str, Any]) -> dict[str, Any] | None:
        """✦ Ask Nova on an idea (or the topic): the local model suggests sub-ideas, which are added to the map."""
        if self.state["notes"].get("expanding") is not None:
            return {"ok": False, "error": "Nova is still adding ideas."}
        path = [" ".join(str(name).split())[:80] for name in (args.get("path") or [])][:4]
        notes = self.state["notes"]
        self._update(notes={"expanding": " > ".join(path).casefold()})

        def suggest() -> None:
            try:
                self.events.put(("map_ideas", (path, suggest_ideas(self.agent, notes["title"], notes["outline"], path))))
            except Exception as exc:
                self.events.put(("map_ideas_failed", f"Nova couldn't add ideas: {exc}"))
        threading.Thread(target=suggest, name="AlfredMapIdeas", daemon=True).start()
        return None

    def _map_add(self, under: str, ideas: list[str]) -> str:
        """The add_to_map tool (from the agent's thread)."""
        self.events.put(("map_add", (under, ideas)))
        return (f"Adding {len(ideas)} ideas to the map '{self.state['notes']['title']}'" + (f" under '{under}'" if under else "")
                + ". It is on the user's screen. Say one short sentence; don't list them.")

    def _add_to_map(self, under: list[str] | str, ideas: list[str]) -> None:
        notes = self.state["notes"]
        outline, added, place = add_ideas(notes["outline"], under, ideas)
        current = {**clean_extras(notes), "title": notes["title"], "outline": outline}
        if added:
            try:
                save_map(current["title"], outline, current)
            except (OSError, ValueError) as exc:
                self._toast(f"The ideas are shown but could not be saved: {exc}", "warn")
        self._update(notes=self._notes_state(current))
        if not self.ui.clients:
            self._open_window()
        self.ui.emit({"type": "open_pane", "pane": "notes"})
        self._toast(f"✦ Nova added {added} idea{'s' * (added != 1)} under {place or notes['title']}." if added
                    else "✦ Nova had no new ideas there. Try again or type your own.", "ok" if added else "warn")

    def _act_notes_new(self, _args: dict[str, Any]) -> None:
        self._update(notes=self._notes_state({"title": "New idea", "outline": "", "positions": {}}))

    def _act_notes_delete(self, args: dict[str, Any]) -> None:
        delete_map(str(args.get("title", "")))
        maps = load_maps()
        self._update(notes=self._notes_state(maps[0] if maps else {"title": "New idea", "outline": "", "positions": {}}))

    def _act_notes_load(self, args: dict[str, Any]) -> None:
        maps = load_maps()
        index = int(args.get("index") or 0)
        if 0 <= index < len(maps):
            self._update(notes=self._notes_state(maps[index]))

    def _act_read_screen(self, args: dict[str, Any]) -> dict[str, Any] | None:
        if not IS_WINDOWS or not self.state["displays"]:
            return {"ok": False, "error": "No display to read."}
        display = int(args.get("display") or 1)
        if not 1 <= display <= len(self.state["displays"]):
            return {"ok": False, "error": "That display is not connected."}
        self._set_voice_state("READING THE SCREEN · NOTHING IS KEPT", "info")
        app_window.minimize(self.window_hwnd)  # keep Nova itself out of the picture

        def read() -> None:
            time.sleep(0.6)
            try:
                from screen_reader import read_display
                self.events.put(("screen_done", (display, read_display(display))))
            except Exception as exc:
                self.events.put(("screen_error", str(exc)))
        threading.Thread(target=read, daemon=True).start()
        return None

    def _act_audio_devices(self, _args: dict[str, Any]) -> dict[str, Any]:
        inputs, outputs = enumerate_input_devices(), enumerate_speech_outputs()
        whisper = self.voice.whisper_settings
        return {"ok": True, "inputs": [{"label": str(d["label"]), "key": str(d["key"])} for d in inputs],
                "outputs": [{"label": str(d["label"]), "key": str(d["key"])} for d in outputs],
                "input_key": self.voice.input_key, "output_key": self.voice.output_key, "voice": self.voice.voice_name,
                "voices": [{"name": name, "mb": size, "installed": piper_voice.installed(name)}
                           for name, (_path, size) in piper_voice.VOICES.items()],
                "whisper_installed": whisper_engine.installed_any(),
                "whisper_mb": whisper_engine.MODELS[str(whisper["model"])][2],
                "whisper_models": whisper_engine.model_options(),
                "whisper_model": whisper["model"], "whisper_language": whisper["language"],
                "whisper_pause_seconds": whisper["pause_seconds"], "whisper_vocabulary": whisper["vocabulary"],
                "system_default": SYSTEM_DEFAULT}

    def _choose_devices(self, args: dict[str, Any]) -> None:
        self.voice.input_key = args.get("input_key") or None
        self.voice.output_key = args.get("output_key") or None

    def _act_audio_save(self, args: dict[str, Any]) -> dict[str, Any] | None:
        if self.state["switches"]["mic"]:
            return {"ok": False, "error": "Switch the mic off before changing audio devices."}
        voice = args.get("voice") or None
        if voice and voice not in piper_voice.VOICES:
            return {"ok": False, "error": "Unknown voice."}
        if voice and not piper_voice.installed(voice) and not args.get("consented"):
            return {"need_consent": "voice", "detail": {"name": voice, "mb": piper_voice.VOICES[voice][1]}}
        self._choose_devices(args)
        self.voice.set_audio_devices(self.voice.input_key, self.voice.output_key)
        if voice and not piper_voice.installed(voice):
            self._install_in_background("VOICE", lambda progress: piper_voice.install(voice, progress),
                                        lambda: self._voice_installed(voice))
        else:
            self.voice.set_voice(voice)
        return None

    def _voice_installed(self, voice: str) -> None:
        """A new voice is ready (install thread). Kokoro needs a reasonably quick CPU: check this PC keeps up."""
        self.voice.set_voice(voice)
        if not piper_voice.VOICES[voice][0].startswith("kokoro:"):
            return
        work_per_second = kokoro_voice.speed_check()
        if work_per_second > 0.9:
            self.events.put(("warning", f"{voice.split(' (')[0]} sounds the most natural, but this PC needs "
                             f"{work_per_second:.1f} s to make each second of speech, so long replies may pause between "
                             "sentences. Amy (SETTINGS → Voice) is lighter and always keeps up."))

    def _audio_status(self, text: str, tone: str = "") -> None:
        self.ui.emit({"type": "audio_status", "text": text, "tone": tone})

    def _act_test_mic(self, args: dict[str, Any]) -> None:
        self._choose_devices(args)
        self._audio_status("Speak now · checking the microphone briefly · audio is not saved")
        self.voice.test_input_level(
            lambda dbfs, peak, detail: self._audio_status(f"Input level {dbfs:.1f} dBFS · peak {peak * 100:.0f}% · {detail}", "ok"),
            lambda error: self._audio_status(error, "error"))

    def _act_test_speaker(self, args: dict[str, Any]) -> None:
        self._choose_devices(args)
        self._audio_status("Playing a short quiet test on the selected output…")
        self.voice.test_output(on_done=lambda: self._audio_status("Speaker test finished.", "ok"),
                               on_error=lambda error: self._audio_status(error, "error"),
                               on_fallback=lambda note: self._audio_status(note, "warn"))

    def _act_test_voice(self, _args: dict[str, Any]) -> None:
        self._speak("Hello, I'm Nova. How can I help you today?")

    def _act_whisper_save(self, args: dict[str, Any]) -> dict[str, Any] | None:
        """Save the speech-recognition settings (model, language, pause, vocabulary). A model that isn't
        downloaded yet is reported back so Settings can offer the install; nothing is downloaded here."""
        import voice as voice_module
        vocabulary = args.get("whisper_vocabulary")
        if isinstance(vocabulary, str):
            vocabulary = [word for word in vocabulary.split(",")]
        changes: dict[str, object] = {}
        if args.get("whisper_model") is not None:
            changes["model"] = args["whisper_model"]
        if args.get("whisper_language") is not None:
            changes["language"] = args["whisper_language"]
        if args.get("whisper_pause_seconds") is not None:
            changes["pause_seconds"] = args["whisper_pause_seconds"]
        if vocabulary is not None:
            changes["vocabulary"] = vocabulary
        settings = voice_module.save_whisper_settings(**changes)
        self.voice.refresh_whisper()
        model = str(settings["model"])
        return {"ok": True, "whisper_model": model,
                "whisper_installed": whisper_engine.installed(model),
                "whisper_mb": whisper_engine.MODELS[model][2],
                "whisper_language": settings["language"]}

    def _act_install_whisper(self, args: dict[str, Any]) -> dict[str, Any] | None:
        model = args.get("model") if args.get("model") in whisper_engine.MODELS else None
        model = model or str(self.voice.whisper_settings.get("model") or whisper_engine.DEFAULT_MODEL)
        if not args.get("consented"):
            return {"need_consent": "whisper", "detail": {"mb": whisper_engine.MODELS[model][2], "model": model}}

        def ready() -> None:
            self.voice.refresh_whisper()
        self._install_in_background("WHISPER", lambda progress: whisper_engine.install(progress, model), ready)
        return None

    def _act_install_vietnamese_voice(self, args: dict[str, Any]) -> dict[str, Any] | None:
        if piper_voice.installed(piper_voice.VIETNAMESE):
            return {"ok": False, "error": "The Vietnamese voice is already installed."}
        if not args.get("consented"):
            return {"need_consent": "voice", "detail": {"name": piper_voice.VIETNAMESE, "mb": 65}}
        self._install_in_background("VIETNAMESE VOICE", lambda progress: piper_voice.install(piper_voice.VIETNAMESE, progress),
                                    lambda: None)
        return None

    def _install_in_background(self, label: str, install, on_done) -> None:
        """A user-approved download; progress shows in the status line."""
        def run() -> None:
            try:
                install(lambda message: self.events.put(("voice_state", (message.upper(), "info"))))
                on_done()
                self.events.put(("voice_state", (f"{label} READY", "ok")))
                self.events.put(("downloads", None))
            except Exception as exc:
                self.events.put(("warning", f"{label} could not be installed: {exc}. Nothing was changed."))
        threading.Thread(target=run, daemon=True).start()

    def _answer_out_loud(self, text: str) -> bool:
        """While Nova waits for a yes or no, a spoken "yes" / "no" (or, for passwords and mail, "send it to Claude" /
        "keep it here") answers it."""
        pending = self.pending_approval
        if pending is None:
            return False
        place = spoken_place(text) if pending.get("name") == "send_online" else None
        answer = (place == "online") if place else spoken_answer(text)
        if answer is None:
            self._set_voice_state(self._question_hint(), "warn")
            return True
        self._answer(answer)
        return True

    def _answer(self, yes: bool) -> None:
        """The owner's answer to the question Nova is waiting on: said out loud, or the yes / no key."""
        pending = self.pending_approval
        if pending is not None:
            self._act_approve({"id": pending["id"], "yes": yes})
            self._set_voice_state("YES" if yes else "NO", "ok")

    def _question_hint(self) -> str:
        return f"SAY “YES” OR “NO” · OR PRESS {hotkeys.label(self._hotkey('yes')).upper()} / {hotkeys.label(self._hotkey('no')).upper()}"

    def _act_approve(self, args: dict[str, Any]) -> None:
        pending = self.pending_approval
        if pending and pending["id"] == args.get("id"):
            pending["approved"] = bool(args.get("yes"))
            pending["event"].set()

    def _act_set_model(self, args: dict[str, Any]) -> None:
        name = str(args.get("name") or "auto")
        if name != "auto" and name not in self.state["model"]["installed"]:
            raise ValueError("That model is not installed.")
        self._save_setting("model", name)
        self._update(settings={"model": name})
        threading.Thread(target=self._resolve_model, daemon=True).start()

    def _act_pull_model(self, args: dict[str, Any]) -> dict[str, Any] | None:
        offer = self.state["model"].get("offer")
        if not offer or offer["name"] != args.get("name") or self.state["model"]["downloading"]:
            return {"ok": False, "error": "Nothing to download."}
        if not args.get("consented"):
            return {"need_consent": "model", "detail": offer}
        self._update(model={"downloading": True})

        def download() -> None:
            try:
                pull_model(self.agent.base_url, offer["name"],
                           lambda text: self.events.put(("voice_state", (text.upper(), "info"))))
                self.events.put(("model_pulled", offer["name"]))
            except Exception as exc:
                self.events.put(("model_pull_failed", f"Could not download {offer['name']}: {exc}"))
        threading.Thread(target=download, name="AlfredModelDownload", daemon=True).start()
        return None

    def _use_vision(self, model: str | None) -> None:
        """A vision model is installed: creative mode can name anything, not just the detector's 80 kinds."""
        self._update(model={"vision": model})
        self.creative.identify = ((lambda jpeg, guess: vision.identify(self.agent.base_url, model, jpeg, guess))
                                  if model else None)
        self.creative.describe = (lambda jpeg: vision.describe(self.agent.base_url, model, jpeg)) if model else None

    def _act_pull_vision(self, args: dict[str, Any]) -> dict[str, Any] | None:
        if self.state["model"].get("vision"):
            return {"ok": False, "error": f"{self.state['model']['vision']} is already installed."}
        if self.state["model"].get("vision_downloading"):
            return {"ok": False, "error": "The vision model is already downloading."}
        if not args.get("consented"):
            return {"need_consent": "vision", "detail": {"name": vision.VISION_MODEL, "size_gb": vision.VISION_GB}}
        self._update(model={"vision_downloading": True})

        def download() -> None:
            try:
                pull_model(self.agent.base_url, vision.VISION_MODEL,
                           lambda text: self.events.put(("voice_state", (text.upper(), "info"))))
                self.events.put(("vision_pulled", vision.VISION_MODEL))
            except Exception as exc:
                self.events.put(("vision_pull_failed", f"Could not download {vision.VISION_MODEL}: {exc}"))
        threading.Thread(target=download, name="AlfredVisionDownload", daemon=True).start()
        return None

    def _scan_object(self, jpeg: bytes, guess: str) -> None:
        """The orb's WHAT IS THIS button (from the creative server's thread)."""
        identify = self.creative.identify
        if identify is None:
            self._toast(f"The quick detector only knows 80 kinds{f' (it guesses: {guess})' if guess else ''}. "
                        f"A vision model (about {vision.VISION_GB} GB, runs on this PC) can name anything.", "info",
                        {"label": f"Download {vision.VISION_GB} GB", "name": "pull_vision", "args": {}})
            return
        self.creative.show_label("Looking…")
        finished = threading.Event()
        # Without a fast graphics card the vision model can take a while: say so instead of seeming stuck.
        threading.Timer(12, lambda: None if finished.is_set() else self.creative.show_label(
            "Still looking… (vision is slow without a fast graphics card)")).start()

        def run() -> None:
            try:
                name = identify(jpeg, guess)
                finished.set()
                self.creative.show_label(name)
                self.events.put(("scan_result", name))
            except Exception as exc:
                finished.set()
                self.creative.show_label("Couldn't tell")
                self.events.put(("warning", f"The vision model couldn't look: {exc}"))
        threading.Thread(target=run, name="AlfredScan", daemon=True).start()

    def _act_settings(self, args: dict[str, Any]) -> dict[str, Any] | None:
        changes: dict[str, Any] = {}
        if args.get("accent") in ACCENTS:
            changes["accent"] = args["accent"]
        if isinstance(args.get("interests"), list):
            cleaned = []
            for interest in args["interests"]:
                text = " ".join(str(interest).split())[:60]
                if text and text.casefold() not in {item.casefold() for item in cleaned}:
                    cleaned.append(text)
            changes["interests"] = cleaned[:daily_brief.MAX_INTERESTS]
        if args.get("brief_region") in daily_brief.REGIONS:
            changes["brief_region"] = args["brief_region"]
        if isinstance(args.get("news_outlets"), list):
            sites = [daily_brief.outlet(item) for item in args["news_outlets"]]
            wrong = next((str(item).strip() for item, site in zip(args["news_outlets"], sites) if str(item).strip() and not site), "")
            if wrong:
                return {"ok": False, "error": f"“{wrong[:60]}” isn't a news site's address: try something like reuters.com or https://www.cnn.com/."}
            changes["news_outlets"] = list(dict.fromkeys(site for site in sites if site))[:daily_brief.MAX_OUTLETS]
        if isinstance(args.get("keep_running"), bool):
            changes["keep_running"] = args["keep_running"]
        if isinstance(args.get("mini_orb"), bool):
            changes["mini_orb"] = args["mini_orb"]
        if isinstance(args.get("owner_name"), str):
            changes["owner_name"] = " ".join(args["owner_name"].split())[:40]
            self.agent.owner_name = changes["owner_name"]
        if isinstance(args.get("soul"), str):
            changes["soul"] = " ".join(args["soul"].split())[:600]
            self.agent.soul = changes["soul"]  # empty means no soul note: _soul_prompt() leaves it out
        for key, value in changes.items():
            self._save_setting(key, value)
        self._update(settings=changes)
        if self.state["switches"]["brief"] and changes.keys() & {"interests", "brief_region", "news_outlets"}:
            self._load_brief(force=True)
        return None

    def _act_brief(self, args: dict[str, Any]) -> dict[str, Any] | None:
        if not args.get("on"):
            self.agent.brief = None
            self._save_setting("brief_on", False)
            self._update(switches={"brief": False})
            return None
        if not self.settings.get("brief_consented") and not args.get("consented"):
            return {"need_consent": "brief"}
        self._save_setting("brief_consented", True)
        self._save_setting("brief_on", True)
        self._update(switches={"brief": True})
        self._load_brief(force=False)
        return None

    def _act_brief_refresh(self, _args: dict[str, Any]) -> None:
        self._load_brief(force=True)
        self._refresh_weather(repeat=False, news=True)

    # ---------- location: weather and local news ----------

    def _place_summary(self) -> dict[str, Any] | None:
        place = self.settings.get("location")
        if not isinstance(place, dict) or "lat" not in place:
            return None
        return {"label": places.label(place), "source": place.get("source", "city"), "how": place.get("how", "")}

    def _save_location(self, place: dict[str, Any] | None) -> None:
        """From the location service (any thread): kept in settings, then shown and used."""
        self._save_setting("location", place)
        self.events.put(("location_changed", None))

    def _act_location_city(self, args: dict[str, Any]) -> dict[str, Any] | None:
        text = " ".join(str(args.get("place", "")).split())[:80]
        if not text:
            return {"ok": False, "error": "Type your city first."}
        if not self.settings.get("location_consented") and not args.get("consented"):
            return {"need_consent": "location"}
        self._save_setting("location_consented", True)
        self._find_place_in_background(lambda: self.location.set_city(text))
        return None

    def _act_location_device(self, args: dict[str, Any]) -> dict[str, Any] | None:
        if not self.settings.get("location_consented") and not args.get("consented"):
            return {"need_consent": "location"}
        self._save_setting("location_consented", True)
        self._find_place_in_background(self.location.set_from_device)
        return None

    # ---------- other screens: the TV dashboard and the touch deck (screens.py) ----------

    def _screen_state(self, known_music: str = "", known_slide: str = "") -> dict[str, Any]:
        """What an allowed TV shows. The cover and a slid picture only go along when the TV doesn't have them yet."""
        with self.lock:
            last = next((item for item in reversed(self.chat_items) if item["role"] == "assistant"), None)
            heard = next((item for item in reversed(self.chat_items) if item["role"] == "user"), None)
        acting = time.monotonic() < self.takeover_until
        music_state = self._music_state()
        if music_state and music_state.get("key") == known_music:
            music_state.pop("cover", None)
        slide = dict(self.slide) if self.slide else None
        if slide and slide["id"] == known_slide:
            slide.pop("image", None)
        weather = self.state.get("weather_now")
        brief = self.state.get("brief") or {}
        headlines = [item.get("title", "") for item in (self.state.get("local_news") or []) + (brief.get("headlines") or [])][:5]
        second = self.state.get("second_brain") or {}
        return {"owner": self.agent.owner_name, "mode": mini_orb.mode_for(self.state, acting),
                "caption": (self.live_reply or (last or {}).get("text", ""))[-600:], "heard": (heard or {}).get("text", "")[:200],
                "weather": weather, "music": music_state, "timers": self.state.get("timers") or [], "headlines": headlines,
                "reminders": [item["text"] for item in (self.state.get("reminders") or [])[:3]],
                "brain": {"on": bool(second.get("on")), "notes_today": second.get("notes_today", 0), "last": second.get("last", "")},
                "heart": (self.state.get("heart") or {}).get("bpm"), "slide": slide,
                "accent": "%d, %d, %d" % ACCENT_RGB.get(self.state["settings"].get("accent", "gold"), ACCENT_RGB["gold"])}

    def _deck_keyboard(self, request: dict[str, Any]) -> str:
        """The deck's keyboard ({'keys': [...]}) or its type box ({'text': ...}), typed on this PC."""
        import deck_keyboard
        if "text" in request:
            deck_keyboard.type_text(str(request["text"]))
        else:
            deck_keyboard.press(request.get("keys"))
        return ""

    def _deck_action(self, action: str) -> str:
        """One of the deck's fixed buttons (from the iPad or a touch screen), done on this PC."""
        kind, what = screens.DECK_ACTIONS.get(action, ("", ""))
        if kind == "media":
            media_keys.press(what, times=3 if what in ("volume_up", "volume_down") else 1)
            return ""
        if kind == "keys":
            from pywinauto.keyboard import send_keys
            from screen_assist import send_keys_spec
            send_keys(send_keys_spec(what), pause=0.02)
            return ""
        if kind == "app":
            app_window.open_path(what)  # a fixed list: Notepad, Calculator, Explorer, the browser, Spotify
            return ""
        if kind == "nova":
            if what == "stop":
                return self._phone_control("stop")
            if what == "creative":
                return self._phone_control("creative")
            if what == "photo":
                self.creative.open_window()
                self.creative.send({"action": "photo"})
                return "3, 2, 1… photo."
            if what == "brain_now":
                return self.brain.summarize_now()
            if what == "tv_clear":
                self.slide = None
                return "The TV is back to Nova's dashboard."
        return "Unknown button."

    def _act_tv_allow(self, args: dict[str, Any]) -> dict[str, Any] | None:
        if not self.screen_pairing.allow(str(args.get("code", ""))):
            return {"ok": False, "error": "That code has expired. Reload Nova's page on the TV to get a new one."}
        self._toast("The TV now shows Nova. Slide things onto it with → TV.", "ok")
        return None

    def _act_tv_show(self, args: dict[str, Any]) -> None:
        """Slide something onto the TV: a reply, the song, the weather, a picture."""
        self.slide = screens.slide_payload(str(args.get("kind", "text")), str(args.get("title", "")),
                                           str(args.get("body", "")), str(args.get("image", "")))
        if not self.screen_pairing.count:
            self._toast("No TV is connected yet: open the TV link from SETTINGS → Screens on the TV first.", "info")

    def _act_tv_clear(self, _args: dict[str, Any]) -> None:
        self.slide = None

    def _act_tv_forget(self, _args: dict[str, Any]) -> None:
        self.screen_pairing.forget_all()
        self._toast("Forgot all TVs: each one needs Allow again.", "ok")

    def _act_screens_info(self, _args: dict[str, Any]) -> dict[str, Any]:
        if not self.phone.running:
            return {"ok": False, "error": "Turn on PHONE (Nova Lite) first: the TV and the deck use its connection."}
        deck = self.phone.deck_url()
        return {"ok": True, "tv": self.phone.tv_url(), "deck": deck, "deck_qr": _qr_data_url(deck), "tvs": self.screen_pairing.count}

    def show_on_tv(self, title: str, text: str) -> str:
        """For Nova's show_on_tv tool."""
        self._act_tv_show({"kind": "text", "title": title, "body": text})
        return ("Shown on the TV." if self.screen_pairing.count else
                "No TV is connected yet; tell the owner to open the TV link from SETTINGS → Screens on the TV.")

    # ---------- music: now playing, the spinning disc ----------

    def _music_state(self) -> dict[str, Any] | None:
        """The track for the HUD; the cover goes along as a data URL once per track."""
        state = self.music.state()
        if state:
            state["cover"] = ""  # replaces the last track's cover when this one has none
        if state and self.music.track and self.music.track.art:
            art = self.music.track.art
            kind = "png" if art.startswith(b"\x89PNG") else "jpeg"
            state["cover"] = f"data:image/{kind};base64," + base64.b64encode(art).decode()
        return state

    def _stream_music_bars(self) -> None:
        """While music plays and the HUD is open: the sound bars, ten times a second (tiny messages)."""
        if self.closing:
            return
        if self.music.playing and self.ui.clients:
            self.ui.emit({"type": "bands", "bands": [round(level, 2) for level in self.music.bands]})
        self.root.after(100 if self.music.playing else 1000, self._stream_music_bars)

    def _act_media(self, args: dict[str, Any]) -> None:
        action = str(args.get("action", ""))
        if action in ("play_pause", "next", "previous"):
            media_keys.press(action)
            threading.Timer(0.6, self.music.check).start()

    # ---------- hotkeys (SETTINGS → Hotkeys) ----------

    def _hotkey(self, which: str) -> list[int]:
        keys = self.settings.get(f"hotkey_{which}")
        return keys if isinstance(keys, list) and keys and all(isinstance(key, int) for key in keys) else hotkeys.DEFAULTS[which]

    def _hotkey_state(self) -> dict[str, str]:
        return {which: hotkeys.label(self._hotkey(which)) for which in hotkeys.DEFAULTS}

    def _act_hotkey(self, args: dict[str, Any]) -> dict[str, Any] | None:
        if args.get("reset"):
            for which in hotkeys.DEFAULTS:
                self._save_setting(f"hotkey_{which}", hotkeys.DEFAULTS[which])
        else:
            which = str(args.get("which", ""))
            others = [self._hotkey(other) for other in hotkeys.DEFAULTS if other != which]
            keys, problem = hotkeys.check(which, args.get("keys"), others)
            if problem:
                return {"ok": False, "error": problem}
            self._save_setting(f"hotkey_{which}", keys)
        import assist_helper
        assist_helper.STOP_KEYS = list(self._hotkey("stop"))
        self._update(hotkeys=self._hotkey_state())
        return None

    # ---------- second brain: Obsidian notes of what you read and watch ----------

    def _vault_folder(self) -> Path:
        return Path(self.settings.get("second_brain_vault") or Path.home() / "Documents" / "Second Brain")

    def _vault(self) -> brain.Vault:
        return brain.Vault(self._vault_folder(), self.pc, shared=bool(self.settings.get("share_pcs")))

    def _brain_screen_text(self) -> str:
        from screen_reader import _accessible_text
        return _accessible_text()[0]  # UI Automation only: password fields and text boxes are skipped

    def _brain_summarize(self, prompt: str) -> str:
        from plain_text import without_emoji
        response = _http_json(f"{self.agent.base_url}/api/chat", {
            "model": self.agent.model, "stream": False, "keep_alive": "30m", "think": False,
            "messages": [{"role": "user", "content": prompt}],
            "options": {"num_ctx": 8192, "num_predict": 900, "temperature": 0.2}}, timeout=300)
        return without_emoji(str(response.get("message", {}).get("content", "")))

    def _brain_extract(self, prompt: str, schema: dict) -> dict:
        response = _http_json(f"{self.agent.base_url}/api/chat", {
            "model": self.agent.model, "stream": False, "keep_alive": "30m", "think": False, "format": schema,
            "messages": [{"role": "user", "content": prompt}],
            "options": {"num_ctx": 8192, "num_predict": 1200, "temperature": 0.1}}, timeout=300)
        try:
            return json.loads(str(response.get("message", {}).get("content", "")) or "{}")
        except ValueError:
            return {}

    def _act_second_brain_ingest(self, _args: dict[str, Any]) -> None:
        threading.Thread(target=lambda: self.events.put(("toast", (f"Second brain: {self.brain.ingest()}", "ok"))),
                         name="NovaSecondBrainIngest", daemon=True).start()

    def _brain_summary(self) -> dict[str, Any]:
        videos_ready = self.voice.whisper is not None and whisper_engine.installed()
        return {"on": bool(self.settings.get("second_brain")), "running": self.brain.running, "status": self.brain.status,
                "last": self.brain.last_summary, "notes_today": self.brain.vault.notes_today(),
                "vault": str(self._vault_folder()), "videos": bool(self.settings.get("second_brain_videos", True)),
                "videos_ready": videos_ready, "exclude": self.settings.get("second_brain_exclude", brain.DEFAULT_EXCLUDE),
                "gathered": len(self.brain.moments)}

    def _apply_second_brain(self) -> None:
        """Start, restart or stop the second brain to match the settings."""
        self.brain.vault = self._vault()
        self.skills.vault = self._vault_folder()
        self.brain.exclude = brain.keywords(self.settings.get("second_brain_exclude", brain.DEFAULT_EXCLUDE))
        on = bool(self.settings.get("second_brain")) and sys.platform == "win32"
        videos = (on and self.settings.get("second_brain_videos", True) and self.voice.whisper is not None
                  and whisper_engine.installed())
        if self.brain.running:
            self.brain.stop(summarize=not on)
        self.brain.listen_to_videos = (brain.make_video_ear(self.voice.whisper.transcribe,
                                                            busy=lambda: self.voice._nova_talking() or self.listening)
                                       if videos else None)
        if on:
            self.brain.start()
        self.agent.brain = self.brain if self.settings.get("second_brain") else None
        self._update(second_brain=self._brain_summary())

    def _act_second_brain(self, args: dict[str, Any]) -> dict[str, Any] | None:
        on = bool(args.get("on"))
        if on and not self.settings.get("second_brain_consented") and not args.get("consented"):
            return {"need_consent": "second_brain"}
        if on:
            self._save_setting("second_brain_consented", True)
            self._vault().ensure_layout()
        self._save_setting("second_brain", on)
        self._apply_second_brain()
        return None

    def _act_second_brain_settings(self, args: dict[str, Any]) -> dict[str, Any] | None:
        if "vault" in args:
            folder = str(args["vault"]).strip().strip('"')
            if not folder or not Path(folder).is_absolute():
                return {"ok": False, "error": "Give the whole folder path, e.g. C:\\Users\\you\\Documents\\Second Brain."}
            self._save_setting("second_brain_vault", folder)
            self._apply_pc_sync()  # the shared folder is the vault
        if "videos" in args:
            self._save_setting("second_brain_videos", bool(args["videos"]))
        if "exclude" in args:
            self._save_setting("second_brain_exclude", ", ".join(brain.keywords(str(args["exclude"])[:2000])))
        self._apply_second_brain()
        return None

    def _act_second_brain_now(self, _args: dict[str, Any]) -> None:
        threading.Thread(target=lambda: self.events.put(("toast", (f"Second brain: {self.brain.summarize_now()}", "ok"))),
                         name="NovaSecondBrainNow", daemon=True).start()

    def _act_open_vault(self, _args: dict[str, Any]) -> None:
        """Open the vault in Obsidian when it is installed; otherwise show the folder and where to get Obsidian."""
        from urllib.parse import quote
        folder = self._vault_folder()
        folder.mkdir(parents=True, exist_ok=True)
        if not app_window.obsidian_installed():
            app_window.open_path(folder)
            self._toast("Obsidian isn't installed yet: get it free from obsidian.md, then choose “Open folder as vault” "
                        f"and pick {folder}.", "info")
            return
        note = self.brain.vault.daily_path(datetime.now())
        app_window.open_path(f"obsidian://open?path={quote(str(note if note.exists() else folder))}")

    # ---------- Claude: the online brain (personal turns and offline stay on the local model) ----------

    def _claude_via(self) -> str:
        """How Claude is paid for: "plan" (Claude Code on the owner's subscription, no API credit) or "key" (the API
        key, billed per question). The plan is the default whenever Claude Code is on this PC."""
        chosen = self.settings.get("claude_via")
        if chosen in ("plan", "key"):
            return chosen
        return "plan" if claude_code.find() else "key"

    def _claude_ready(self) -> bool:
        """The online brain the owner chose can answer: the Cloud brain's agent is installed, or the API brain has a key."""
        if self._claude_via() == "plan":
            return cloud_agents.find(self._cloud_agent()) is not None
        entry = self._api_entry()
        return entry is not None and self._api_key(entry) is not None

    # ---------- the API brain (any provider's key) and the Cloud brain (an agent signed in with an account) ----------

    def _api_entries(self) -> list[api_brains.Entry]:
        found = api_brains.entries(self.settings.get("api_brains"))
        if not any(entry.provider == "anthropic" for entry in found) and claude_expert.key():
            # A Claude key saved before there was a list: it shows up as the first API brain.
            model = self.settings.get("claude_model", cloud_brain.DEFAULT_MODEL)
            found.insert(0, api_brains.Entry("claude", "anthropic", model, "", f"Claude · {cloud_brain.MODELS.get(model, model)}"))
        return found

    def _api_entry(self) -> api_brains.Entry | None:
        found = self._api_entries()
        chosen = self.settings.get("api_brain")
        return next((entry for entry in found if entry.id == chosen), found[0] if found else None)

    def _api_key(self, entry: api_brains.Entry) -> str | None:
        return claude_expert.key() if entry.provider == "anthropic" else secret_store.load(f"api_key_{entry.id}")

    def _cloud_agent(self) -> cloud_agents.Agent:
        return cloud_agents.agent(str(self.settings.get("cloud_agent") or "claude-code"))

    def _brains_state(self) -> dict[str, Any]:
        active = self._api_entry()
        return {
            "api": {"active": active.id if active else "",
                    "entries": [{**entry.as_dict(), "has_key": self._api_key(entry) is not None,
                                 "provider_label": api_brains.provider(entry.provider).label} for entry in self._api_entries()],
                    "providers": [{"key": item.key, "label": item.label, "base_url": item.base_url, "kind": item.kind,
                                   "hint": item.hint} for item in api_brains.PROVIDERS],
                    "claude_models": cloud_brain.MODELS},
            "cloud": {"agent": self._cloud_agent().key,
                      "agents": [{"key": item.key, "label": item.label, "account": item.account, "full": item.full,
                                  "installed": cloud_agents.find(item) is not None} for item in cloud_agents.AGENTS]},
        }

    def _act_api_brain_add(self, args: dict[str, Any]) -> dict[str, Any] | None:
        found = api_brains.provider(str(args.get("provider") or ""))
        key = " ".join(str(args.get("key") or "").split())
        if found.kind == "anthropic":
            if key:
                claude_expert.save_key(key)
            if not claude_expert.key():
                return {"ok": False, "error": "Paste the Anthropic API key (sk-ant-…)."}
            if args.get("model") in cloud_brain.MODELS:
                self._save_setting("claude_model", args["model"])
            self._save_setting("api_brain", "claude")
        else:
            entry = api_brains.Entry.new(found.key, str(args.get("model") or ""), str(args.get("base_url") or ""),
                                         str(args.get("label") or ""))
            if not key and found.key != "custom":
                return {"ok": False, "error": f"Paste your {found.label.split(' (')[0]} API key ({found.hint})."}
            if key:
                secret_store.save(f"api_key_{entry.id}", key)
            saved = [item for item in (self.settings.get("api_brains") or []) if isinstance(item, dict)]
            self._save_setting("api_brains", [*saved, entry.as_dict()])
            self._save_setting("api_brain", entry.id)
        self._save_setting("claude_via", "key")
        self._apply_claude()
        self._toast("API brain added. Choose API brain above to use it.", "ok")
        return None

    def _act_api_brain_use(self, args: dict[str, Any]) -> None:
        self._save_setting("api_brain", str(args.get("id") or ""))
        self._apply_claude()

    def _act_api_brain_remove(self, args: dict[str, Any]) -> None:
        entry_id = str(args.get("id") or "")
        if entry_id == "claude":
            claude_expert.forget_key()
        else:
            secret_store.forget(f"api_key_{entry_id}")
            self._save_setting("api_brains", [item for item in (self.settings.get("api_brains") or [])
                                              if isinstance(item, dict) and item.get("id") != entry_id])
        self._apply_claude()

    def _act_api_brain_models(self, args: dict[str, Any]) -> dict[str, Any]:
        """The models a provider's key can use (Load models)."""
        found = api_brains.provider(str(args.get("provider") or ""))
        if found.kind == "anthropic":
            return {"ok": True, "models": list(cloud_brain.MODELS)}
        key = " ".join(str(args.get("key") or "").split())
        if not key and args.get("id"):
            key = secret_store.load(f"api_key_{args['id']}") or ""
        return {"ok": True, "models": api_brains.list_models(str(args.get("base_url") or found.base_url), key)}

    def _act_cloud_agent_use(self, args: dict[str, Any]) -> None:
        self._save_setting("cloud_agent", cloud_agents.agent(str(args.get("agent") or "")).key)
        self._save_setting("claude_via", "plan")
        self._apply_claude()

    def _act_cloud_agent_install(self, args: dict[str, Any]) -> None:
        item = cloud_agents.agent(str(args.get("agent") or ""))

        def work() -> None:
            try:
                self.events.put(("toast", (cloud_agents.install(item), "ok")))
            except Exception as exc:
                self.events.put(("toast", (f"Couldn't install {item.label}: {exc}", "warn")))
            self.events.put(("claude_refresh", None))
        self._toast(f"Installing {item.label}…", "info")
        threading.Thread(target=work, name="NovaAgentInstall", daemon=True).start()

    def _act_cloud_agent_connect(self, args: dict[str, Any]) -> None:
        item = cloud_agents.agent(str(args.get("agent") or ""))
        cloud_agents.connect(item)
        self._toast(f"Sign in to {item.account} in the window that opened, then come back here.", "info")

    def _apply_claude(self) -> None:
        key = claude_expert.key()
        via = self._claude_via()
        on = self._brain_choice() in ("claude", "auto") and self._claude_ready()
        self.agent.auto_route = self._brain_choice() == "auto"
        self.agent.claude = claude_expert.available()
        model = self.settings.get("claude_model", cloud_brain.DEFAULT_MODEL)
        effort = self.settings.get("claude_effort", cloud_brain.DEFAULT_EFFORT)
        old = self.agent.cloud
        if not on:
            self.agent.cloud = None
        elif via == "plan" and not self._cloud_agent().full:
            self.agent.cloud = cloud_agents.CliBrain(self._cloud_agent())
        elif via == "plan":
            if self.tool_server is None:
                self.tool_server = ToolServer()
            self.agent.cloud = plan_brain.PlanBrain(model, effort, self.tool_server,
                                                    connectors=bool(self.settings.get("claude_connectors")))
            if on:
                self.agent.warm_plan()  # Claude Code starts now, not on the first question
        else:
            entry = self._api_entry()
            if entry.provider == "anthropic":
                chosen = entry.model if entry.model in cloud_brain.MODELS else model
                self.agent.cloud = cloud_brain.CloudBrain(self._api_key(entry), chosen, effort)
            else:
                self.agent.cloud = api_brains.OpenAIBrain(entry.base_url, self._api_key(entry) or "", entry.model, entry.label)
        if old is not None and old is not self.agent.cloud and hasattr(old, "close"):
            old.close()
        cloud_tools_on = (not USB and self.settings.get("cloud_fallback", True) is not False
                          and (key is not None or claude_code.find() is not None))
        self.agent.cloud_tools = self._cloud_tool if cloud_tools_on else None
        self._update(claude={"on": on, "cloud_fallback": self.settings.get("cloud_fallback", True) is not False,
                             "cloud_fallback_ready": cloud_tools_on, "key": key is not None, "hint": claude_expert.key_hint(),
                             "via": via, "claude_code": claude_code.find() is not None,
                             "connectors": bool(self.settings.get("claude_connectors")),
                             "model": self.settings.get("claude_model", cloud_brain.DEFAULT_MODEL),
                             "effort": self.settings.get("claude_effort", cloud_brain.DEFAULT_EFFORT),
                             "models": cloud_brain.MODELS, "usb": USB, **self._brains_state()})

    def _cloud_tool(self, tool: str, description: str, arguments: dict[str, Any], reason: str) -> str | None:
        """A tool that can't run on this PC, done by Claude (cloud_tools): the API key when there is one, else the plan."""
        import cloud_tools
        claude = cloud_tools.Claude(key=claude_expert.key(), command=claude_code.find(),
                                    model=self.settings.get("claude_model", cloud_brain.DEFAULT_MODEL),
                                    effort=self.settings.get("claude_effort", cloud_brain.DEFAULT_EFFORT))
        self.events.put(("toast", (f"{tool.replace('_', ' ').capitalize()} can't run on this PC: Claude is doing it.", "info")))
        return cloud_tools.run_job(tool, description, arguments, reason, claude)

    def _act_cloud_fallback(self, args: dict[str, Any]) -> None:
        self._save_setting("cloud_fallback", bool(args.get("on")))
        self._apply_claude()

    def _act_claude(self, args: dict[str, Any]) -> dict[str, Any] | None:
        return self._act_brain_choose({**args, "brain": "claude" if args.get("on") else "local"})

    # ---------- Nova's brain: the owner chooses who answers, and what stays on this PC ----------

    def _brain_choice(self) -> str:
        """"local", "claude" or "free". Before there was a choice, the Claude and free-brain switches said it."""
        brain = self.settings.get("brain")
        if brain in ("local", "claude", "free", "auto") and not (USB and brain != "local"):
            return brain
        if USB:
            return "local"
        return "claude" if self.settings.get("claude_on") else "free" if self.settings.get("free_cloud_on") else "local"

    def _private_topics(self) -> str:
        return "personal" if self.settings.get("private_topics") == "personal" else "secrets"

    def _answering_state(self) -> dict[str, Any]:
        brain = self._brain_choice()
        if brain == "claude":  # shown as the API brain or the Cloud brain
            brain = "cloud" if self._claude_via() == "plan" else "api"
        return {"brain": brain, "private": self._private_topics(), "usb": USB}

    def _act_brain_choose(self, args: dict[str, Any]) -> dict[str, Any] | None:
        brain = str(args.get("brain", ""))
        if brain in ("api", "cloud"):  # both run through the online-brain slot ("claude"); how is claude_via
            self._save_setting("claude_via", "key" if brain == "api" else "plan")
            brain = "claude"
        if brain not in ("local", "claude", "free", "auto"):
            return {"ok": False, "error": "Choose this PC, Auto, Claude or Ollama Cloud."}
        if USB and brain != "local":
            return {"ok": False, "error": "The USB Edition stays fully offline: its brain is this PC."}
        consent = {"claude": "claude", "free": "free_cloud",
                   "auto": "claude" if self._claude_ready() else "free_cloud"}.get(brain)
        if consent and not self.settings.get(f"{consent}_consented") and not args.get("consented"):
            return {"need_consent": consent}
        if consent:
            self._save_setting(f"{consent}_consented", True)
        self._save_setting("brain", brain)
        self._apply_claude()
        self._apply_free_cloud()
        self._update(answering=self._answering_state())
        if brain == "claude" and not self._claude_ready():
            self._toast("Claude is Nova's brain: install Claude Code and sign in to use your Claude plan, or paste an API key "
                        "below (until then the AI on this PC answers).", "info")
        return None

    def _act_privacy(self, args: dict[str, Any]) -> None:
        private = "personal" if args.get("private") == "personal" else "secrets"
        self._save_setting("private_topics", private)
        self.agent.private_topics = private
        self._update(answering=self._answering_state())

    def _act_claude_settings(self, args: dict[str, Any]) -> None:
        if args.get("via") in ("plan", "key"):
            self._save_setting("claude_via", args["via"])
            self._update(answering=self._answering_state())
        if args.get("model") in cloud_brain.MODELS:
            self._save_setting("claude_model", args["model"])
        if args.get("effort") in cloud_brain.EFFORTS:
            self._save_setting("claude_effort", args["effort"])
        self._apply_claude()

    def _act_claude_connectors(self, args: dict[str, Any]) -> dict[str, Any] | None:
        """Lets Nova's Claude (on the plan) also use the owner's claude.ai Gmail and Google Drive connectors."""
        on = bool(args.get("on"))
        if on and not args.get("consented"):
            return {"need_consent": "connectors"}
        self._save_setting("claude_connectors", on)
        self._apply_claude()
        return None

    # ---------- Nova's Gmail and Drive for the owner's own Claude apps (google_mcp) ----------

    def _google_mcp_state(self) -> dict[str, Any]:
        on = bool(self.settings.get("google_mcp_on")) and not USB
        state: dict[str, Any] = {"on": on, "running": self.google_mcp.running, "usb": USB,
                                 "google": self.agent.gmail is not None, "drive": self.agent.drive is not None,
                                 "error": getattr(self, "_google_mcp_error", "")}
        if on and self.google_mcp.running:
            state.update(google_mcp.setup_text(google_mcp.key()))
        return state

    def _google_mcp_apply(self) -> None:
        """Serves Gmail and Drive while it's on and Google is connected (again after a reconnect, with the new tools)."""
        self._google_mcp_error = ""
        if self.settings.get("google_mcp_on") and not USB and self.agent.gmail is not None:
            try:
                self.google_mcp.start()
            except OSError as exc:
                self.google_mcp.stop()
                self._google_mcp_error = (f"port {google_mcp.PORT} is taken by another program ({exc.strerror or exc}); "
                                          "close it and turn this on again")
        else:
            self.google_mcp.stop()
        self._update(google_mcp=self._google_mcp_state())

    def _act_google_mcp(self, args: dict[str, Any]) -> dict[str, Any] | None:
        if USB:
            return {"ok": False, "error": "Not on the USB Edition."}
        if args.get("new_key"):
            google_mcp.new_key()
            self._google_mcp_apply()
            self._toast("New key made: paste the new setup into your Claude apps.", "ok")
            return None
        on = bool(args.get("on"))
        if on and not self.settings.get("google_mcp_consented") and not args.get("consented"):
            return {"need_consent": "google_mcp"}
        if on:
            self._save_setting("google_mcp_consented", True)
        self._save_setting("google_mcp_on", on)
        self._google_mcp_apply()
        if on and self.agent.gmail is None:
            self._toast("Connect Google first (Settings → Connections); then Nova serves Gmail and Drive.", "warn")
        return None

    def _act_claude_key(self, args: dict[str, Any]) -> dict[str, Any] | None:
        try:
            claude_expert.save_key(str(args.get("key", "")))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        self._apply_claude()
        self._toast(f"Key saved on this PC ({claude_expert.key_hint()}).", "ok")
        return None

    def _act_claude_key_forget(self, _args: dict[str, Any]) -> None:
        claude_expert.forget_key()
        self._apply_claude()
        self._toast("Key removed from this PC. Nova answers with the local AI only.", "ok")

    # ---------- SETTINGS → Downloads: everything Nova can still get, with a button each ----------

    def _downloads_state(self) -> list[dict[str, Any]]:
        model = self.state.get("model", {})
        installed = model.get("installed") or []
        program_files = Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
        local_programs = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Programs"
        found = lambda *paths: any(Path(path).exists() for path in paths)  # noqa: E731
        brain_choice = self._brain_choice()
        items: list[dict[str, Any]] = []
        add = lambda **item: items.append({"done": None, "optional": False, "action": None, "url": "", "focus": "", **item})  # noqa: E731
        if not USB:
            add(id="ollama", name="Ollama", why="Runs the AI on this PC.", size="about 1 GB",
                done=model.get("ollama") not in ("offline", "checking", None), url="https://ollama.com/download")
        name = model.get("name") or ""
        add(id="model", name=f"AI model{f' · {name}' if name else ''}", why="Nova's local brain, chosen for this PC.",
            size="1.4 to 9.3 GB", done=bool(name) and name in installed,
            action={"name": "pull_model", "args": {"name": name}} if name and name not in installed else None)
        offer = model.get("offer")
        if offer:
            add(id="better", name=f"Better model · {offer['name']}", why=offer.get("reason", "Suits this PC better."),
                size=f"{offer.get('size_gb', '?')} GB", done=False, optional=True,
                action={"name": "pull_model", "args": {"name": offer["name"]}})
        add(id="whisper", name="Whisper speech recognition", why="Understands accents and broken English; writes down videos.",
            size=f"{whisper_engine.DOWNLOAD_MB} MB", done=whisper_engine.installed_any(), action={"name": "install_whisper", "args": {}})
        add(id="voice", name="A natural voice", why="Heart, Bella or Emma (Kokoro), or Amy, Lessac or Jenny on a slow PC.",
            size=f"{kokoro_voice.DOWNLOAD_MB} MB", done=any(piper_voice.installed(voice) for voice in piper_voice.VOICES),
            focus="#audio-voice")
        add(id="vietnamese", name="Vietnamese voice", why="Reads Vietnamese answers properly.", size="65 MB", optional=True,
            done=piper_voice.installed(piper_voice.VIETNAMESE), action={"name": "install_vietnamese_voice", "args": {}})
        add(id="vision", name="Vision model", why="Creative mode names anything you show the camera.", size="about 3 GB",
            optional=True, done=bool(model.get("vision")), action={"name": "pull_vision", "args": {}})
        obsidian = None
        if IS_WINDOWS:
            import winreg
            try:
                winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "obsidian").Close()
                obsidian = True
            except OSError:
                obsidian = False
        add(id="obsidian", name="Obsidian", why="Shows your second brain and the Library as notes.", size="about 200 MB",
            optional=True, done=obsidian, url="https://obsidian.md/download")
        if not USB:
            add(id="syncthing", name="Syncthing", why="Shares memory, notes and the Library with your laptop. No cloud.",
                size="about 30 MB", optional=True, url="https://github.com/GermanCoding/SyncTrayzor/releases",
                done=found(program_files / "SyncTrayzor" / "SyncTrayzor.exe", program_files / "Syncthing" / "syncthing.exe",
                           local_programs / "Syncthing" / "syncthing.exe") or None)
            add(id="tailscale", name="Tailscale", why="Your phone, iPad and laptop reach Nova away from home.",
                size="about 50 MB", optional=True, url="https://tailscale.com/download/windows",
                done=found(program_files / "Tailscale" / "tailscale.exe") or None)
            if brain_choice == "claude" and self._claude_via() == "plan":
                add(id="claude_code", name="Claude Code", why="Claude on your Claude plan, no API credit: install it, then "
                    "run claude once and sign in.", size="about 100 MB", url="https://claude.com/product/claude-code",
                    done=claude_code.find() is not None)
            elif brain_choice == "claude":
                add(id="claude_key", name="Anthropic API key", why="For Claude, Nova's chosen brain (no download).",
                    size="", done=claude_expert.key() is not None, focus="#claude-key")
            if self.settings.get("reverse_on") or self.settings.get("google_mcp_on"):
                add(id="node", name="Node.js (LTS)", why="Runs REA for reverse engineering, and the bridge Claude Desktop "
                    "uses to reach Nova's Gmail and Drive.", size="about 30 MB", optional=True, url="https://nodejs.org/en/download",
                    done=node_runtime.find(str(self.settings.get("node_path") or "")) is not None)
            if brain_choice == "free":
                status = (self.state.get("free_cloud") or {}).get("status", "")
                add(id="ollama_signin", name="Ollama sign-in", why="For Ollama Cloud, Nova's chosen brain (free account).",
                    size="", done=status == "ready", action={"name": "free_cloud_signin", "args": {}})
        return items

    def _act_downloads(self, _args: dict[str, Any]) -> None:
        self._update(downloads=self._downloads_state())

    # ---------- the library: the owner's projects, repos and ideas by topic, in the second brain vault ----------

    def _library(self) -> library_store.Library:
        return library_store.Library(self._vault_folder())

    def _library_said(self, text: str) -> bool:
        """While the Library is on screen, short commands move it at once: "next", "open 3", "open robotics", "back"."""
        if not (self.library_open and self.ui.clients):
            return False
        command = library_store.parse_command(text)
        if command and command["command"] == "find":
            target = self._library().match(command["text"])
            command = {"command": "goto", **target} if target else None
        if not command:
            return False
        self.ui.emit({"type": "library_command", **command, "by": "voice"})
        self._set_voice_state(f"LIBRARY · {' '.join(text.split()).upper()[:48]}", "ok")
        return True

    def _open_library(self, text: str = "") -> str:
        """Nova opens the Library (at a topic or project when one was named)."""
        target = self._library().match(text) if text.strip() else None
        command = {"type": "library_command", "command": "show", **({"target": target} if target else {})}
        if self.ui.clients:
            self.ui.emit(command)
        else:
            self.events.put(("open_window", "open=library"))
        if text.strip() and target is None:
            return f"The library is open. Nothing in it is called {text}: tell the owner which topics there are if asked."
        return "The library is open on the screen" + (f" at {target['name']}." if target else ".")

    def _act_library(self, _args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, **self._library().snapshot()}

    def _act_library_topic(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, **self._library().topic(" ".join(str(args.get("name", "")).split())[:80])}

    def _act_library_save(self, args: dict[str, Any]) -> dict[str, Any]:
        text = lambda key: None if args.get(key) is None else str(args[key])  # noqa: E731
        try:
            project = self._library().save(str(args.get("title", "")), previous=str(args.get("previous") or ""),
                                           status=text("status"), topic=text("topic"), repo=text("repo"),
                                           next=text("next"), note=text("note"), new=bool(args.get("new")))
        except (ValueError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "saved": project.title, **self._library().snapshot()}

    def _act_library_delete(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self._library().delete(str(args.get("title", ""))):
            return {"ok": False, "error": "It isn't in the library any more."}
        return {"ok": True, **self._library().snapshot()}

    def _act_library_open(self, args: dict[str, Any]) -> dict[str, Any] | None:
        """A project's repo (a web link or a folder on this PC), or its note in Obsidian."""
        project = self._library().find(str(args.get("title", "")))
        if project is None:
            return {"ok": False, "error": "It isn't in the library any more."}
        if args.get("obsidian"):
            return self._open_in_obsidian(self._library().folder / f"{project.title}.md")
        if not project.repo:
            return {"ok": False, "error": "No repo or folder saved for it yet: Edit to add one."}
        if urlsplit(project.repo).scheme in ("http", "https"):
            webbrowser.open(project.repo)
            return None
        if not Path(project.repo).is_dir():
            return {"ok": False, "error": f"{project.repo} isn't a folder on this PC."}
        app_window.open_path(project.repo)
        return None

    def _act_library_view(self, args: dict[str, Any]) -> None:
        self.library_open = bool(args.get("open"))

    def _open_in_obsidian(self, path: Path) -> dict[str, Any] | None:
        from urllib.parse import quote
        if not app_window.obsidian_installed():
            return {"ok": False, "error": "Obsidian isn't installed yet: get it free from obsidian.md (SETTINGS → Downloads)."}
        app_window.open_path(f"obsidian://open?path={quote(str(path))}")
        return None

    # ---------- who answered, and this PC's live load (Settings → Model and This PC) ----------

    def _log_timing(self, latency_ms: int) -> None:
        """Where the last answer's time went (shown in Settings → This PC, kept in timings.jsonl for comparing)."""
        stats = dict(self.agent.turn_stats)
        summary = agent_module.describe_timing(stats)
        self._update(timing={"latency_ms": latency_ms, "summary": summary, "local": bool(stats.get("eval_count"))})
        try:
            with (_data_dir() / "timings.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"), "latency_ms": latency_ms,
                                      **stats}) + "\n")
        except OSError:
            pass  # the record is a convenience; the answer is what matters

    def _log_answer(self, label: str, why: str) -> None:
        entry = {"time": datetime.now().strftime("%H:%M"), "brain": label, "why": why}
        self.answers.appendleft(entry)
        self._update(answers=list(self.answers))
        try:
            with (_data_dir() / "answers.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps({**entry, "date": datetime.now().strftime("%Y-%m-%d")}) + "\n")
        except OSError:
            pass  # the list in Settings still shows it

    def _act_pc_stats(self, _args: dict[str, Any]) -> dict[str, Any]:
        """The latest sample; asking keeps the sampler going (it stops 15 s after the page stops asking)."""
        first = not self.pc_stats_wanted or time.monotonic() - self.pc_stats_wanted > 15
        self.pc_stats_wanted = time.monotonic()
        if first:
            threading.Thread(target=self._sample_pc, name="NovaPcStats", daemon=True).start()
        return {"ok": True, **self.pc_stats}

    def _sample_pc(self) -> None:
        gpus = self.hardware.gpus if self.hardware else []
        names = ", ".join(gpu["name"] for gpu in gpus)
        vram_total = max((float(gpu.get("reported_vram_gib") or 0) for gpu in gpus), default=0) or None
        while time.monotonic() - self.pc_stats_wanted < 15 and not self.closing:
            used, total = pc_monitor.ram()
            sample: dict[str, Any] = {"cpu": self.cpu_meter.percent(), "ram_used": round(used, 1),
                                      "ram_total": round(total, 1), "vram_total": vram_total, "model": self.agent.model}
            sample.update(pc_monitor.gpu_counters())
            try:
                sample["models"] = pc_monitor.placements(_http_json(f"{self.agent.base_url}/api/ps", timeout=5))
            except OllamaError:
                sample["models"], sample["ollama"] = [], "Ollama isn't answering"
            sample["tip"] = pc_monitor.gpu_tip(names, sample["models"])
            self.pc_stats = sample
            time.sleep(3)

    def _act_model_load(self, _args: dict[str, Any]) -> None:
        threading.Thread(target=self.agent.warm_up, name="NovaModelLoad", daemon=True).start()
        self._toast(f"Loading {self.agent.model}…", "info")

    def _act_model_unload(self, _args: dict[str, Any]) -> dict[str, Any] | None:
        """Frees the graphics memory now (Ollama would after 30 idle minutes); the next question loads it again."""
        try:
            loaded = pc_monitor.placements(_http_json(f"{self.agent.base_url}/api/ps", timeout=5))
            for model in loaded:
                _http_json(f"{self.agent.base_url}/api/generate", {"model": model["name"], "keep_alive": 0}, timeout=30)
        except OllamaError as exc:
            return {"ok": False, "error": str(exc)}
        self._toast("Unloaded: " + (", ".join(model["name"] for model in loaded) or "nothing was loaded") + ".", "ok")
        return None

    # ---------- custom versions of a local model, and comparing two models (Settings → Model) ----------

    def _act_version_create(self, args: dict[str, Any]) -> dict[str, Any] | None:
        try:
            payload = model_versions.create_payload(
                str(args.get("base", "")), str(args.get("name", "")), str(args.get("system", "")),
                float(args["temperature"]) if str(args.get("temperature", "")).strip() else None,
                int(args["num_ctx"]) if str(args.get("num_ctx", "")).strip() else None)
        except (ValueError, TypeError) as exc:
            return {"ok": False, "error": str(exc)}

        def work() -> None:
            try:
                _http_json(f"{self.agent.base_url}/api/create", payload, timeout=600)
                self.events.put(("toast", (f"Made {payload['model']} from {payload['from']} (the original is unchanged). "
                                           "Choose it under Which model to use it.", "ok")))
            except OllamaError as exc:
                self.events.put(("toast", (f"Couldn't make {payload['model']}: {exc}", "warn")))
            self._status_worker()
        threading.Thread(target=work, name="NovaVersion", daemon=True).start()
        return None

    def _act_version_delete(self, args: dict[str, Any]) -> dict[str, Any] | None:
        name = str(args.get("name", ""))

        def send_delete(url: str, body: dict) -> None:
            request = urllib.request.Request(url, data=json.dumps(body).encode(), method="DELETE",
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=30):
                pass
        try:
            model_versions.delete(send_delete, self.agent.base_url, name)
        except (ValueError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
        threading.Thread(target=self._status_worker, daemon=True).start()
        self._toast(f"Deleted {name}.", "ok")
        return None

    def _act_model_compare(self, args: dict[str, Any]) -> dict[str, Any] | None:
        """Nova's seven quick checks (evaluate.py) on two installed models, one after the other."""
        models = [str(args.get("a", "")), str(args.get("b", ""))]
        if not all(models) or models[0] == models[1]:
            return {"ok": False, "error": "Choose two different models."}

        def work() -> None:
            import tempfile
            from evaluate import Evaluation
            lines = []
            for model in models:
                self.events.put(("compare", f"Checking {model}…"))
                try:
                    with tempfile.TemporaryDirectory(prefix="nova-compare-") as folder:
                        evaluation = Evaluation(Path(folder), model)
                        evaluation.run()
                    passed = sum(1 for _name, ok, _detail in evaluation.results if ok)
                    failed = [name for name, ok, _detail in evaluation.results if not ok]
                    lines.append(f"{model}: {passed}/{len(evaluation.results)} checks passed"
                                 + (f" (missed: {', '.join(failed)})" if failed else ""))
                except Exception as exc:
                    lines.append(f"{model}: couldn't run ({exc})")
            self.events.put(("compare", " · ".join(lines) + ". A handful of checks, not a full benchmark."))
        threading.Thread(target=work, name="NovaCompare", daemon=True).start()
        return None

    # ---------- the news desk: a daily, searchable news database behind Nova's answers (news_intel) ----------

    def _news(self) -> NewsStore:
        if self.news_store is None:
            self.news_store = NewsStore(NewsConfig().db_path)
        return self.news_store

    def _news_config(self) -> NewsConfig:
        return NewsConfig(llm_model=self.agent.model, ollama_url=self.agent.base_url,
                          google_news_sites=tuple(self.state["settings"].get("news_outlets") or ()))

    # ---------- the World view: public feeds and the news desk on a globe (world_monitor) ----------

    def _world_news(self, days: int) -> list[dict[str, Any]] | None:
        return self._news().search(days=days, limit=400) if self.settings.get("news_on") else None

    def _act_world(self, args: dict[str, Any]) -> dict[str, Any]:
        """The globe's events: at once when the feeds are fresh, otherwise fetched on a thread and sent when ready."""
        days, force = int(args.get("days") or 1), bool(args.get("force"))
        if self.world_monitor.cached() and not force:
            return {"ok": True, **self.world_monitor.events(days)}

        def fetch() -> None:
            self.ui.emit({"type": "world_data", **self.world_monitor.events(days, force)})
        threading.Thread(target=fetch, name="NovaWorld", daemon=True).start()
        return {"ok": True, "loading": True}

    def _world_tool(self, action: str, place: str, days: int) -> str:
        """Nova's "world" tool: the answer for Claude or the local model, and the HUD's globe flies to the place."""
        days = max(1, min(int(days or 1), 7))
        if action == "show":
            found, text = (self.world_monitor.places.find(place) if place else None), ""
        else:
            text, found = self.world_monitor.brief(place, days)
        focus: dict[str, Any] = {"type": "world_focus", "days": days, "name": found["name"] if found else "the world"}
        if found:
            west, south, east, north = found["bbox"]
            span = max((east - west) % 360 or 360, (north - south) * 1.4)
            focus.update(lon=found["lon"], lat=found["lat"], zoom=max(1.0, min(5.0, 150 / max(span, 1))))
        else:
            focus.update(lon=20, lat=20, zoom=1)
        self.ui.emit(focus)
        if action == "show":
            return f"The World view is open on {focus['name']}. Say so in a few words."
        return text

    # ---------- offline knowledge: Wikipedia on this PC, searching the notes by meaning, kept city roads ----------

    def _embedding_model_ready(self) -> bool:
        return any(name.split(":")[0] == notes_search.MODEL for name in self.state.get("model", {}).get("installed") or [])

    def _knowledge_state(self) -> dict[str, Any]:
        installed = {path.name: path.stat().st_size for path in self.wikipedia.installed()}
        packs = []
        for pack in offline_wikipedia.PACKS:
            files = [name for name in installed if name.startswith(f"{pack.name}_{pack.flavour}_")]
            found = self.knowledge["packs"].get(pack.key) or {}
            packs.append({"key": pack.key, "title": pack.title, "bytes": found.get("bytes", 0),
                          "file": files[0] if files else "", "size": installed.get(files[0], 0) if files else 0})
        return {"packs": packs, "downloading": self.knowledge["downloading"],
                "notes": {**self.knowledge["notes"], "count": self.notes_index.count(), "model": self._embedding_model_ready(),
                          "vault": str(self._vault_folder())},
                "cities": self.router.kept_cities(), "city": self._route_city()}

    def _apply_knowledge(self) -> None:
        self.agent.wikipedia = self.wikipedia.search if self.wikipedia.installed() else None
        self.agent.notes_search = self.notes_index.search if self.notes_index.count() and self._embedding_model_ready() else None
        self._update(knowledge=self._knowledge_state())

    def _act_knowledge_catalog(self, _args: dict[str, Any]) -> dict[str, Any]:
        """The sizes of the Wikipedia files Kiwix has now (fetched on a thread)."""
        def fetch() -> None:
            for pack in offline_wikipedia.PACKS:
                try:
                    found = self.wikipedia.find(pack)
                except (OSError, ValueError):
                    found = None
                if found:
                    self.knowledge["packs"][pack.key] = found
            self.events.put(("knowledge", None))
        threading.Thread(target=fetch, name="NovaKnowledgeCatalog", daemon=True).start()
        return {"ok": True}

    def _act_knowledge_download(self, args: dict[str, Any]) -> dict[str, Any] | None:
        key = str(args.get("key") or "")
        if key not in {pack.key for pack in offline_wikipedia.PACKS} or self.knowledge["downloading"]:
            return {"ok": False, "error": "Nothing to download right now."}
        pack = offline_wikipedia.pack(key)
        size = int((self.knowledge["packs"].get(key) or {}).get("bytes") or 0)
        if not args.get("consented"):
            return {"need_consent": "knowledge", "detail": {"title": pack.title, "gb": round(size / 1e9, 1) if size else None}}
        if size and not self.wikipedia.free_space_ok(size):
            return {"ok": False, "error": f"Not enough free disk space for {pack.title} ({size / 1e9:.1f} GB plus room to spare)."}
        self.knowledge["downloading"] = {"key": key, "done": 0, "total": size}
        self._update(knowledge=self._knowledge_state())

        def download() -> None:
            last = [0.0]

            def progress(done: int, total: int) -> None:
                if time.monotonic() - last[0] > 1:
                    last[0] = time.monotonic()
                    self.knowledge["downloading"] = {"key": key, "done": done, "total": total}
                    self.events.put(("knowledge", None))
            try:
                self.wikipedia.download(pack, progress)
                self.events.put(("toast", (f"{pack.title} is on this PC: Nova can look things up offline now.", "ok")))
            except Exception as exc:
                self.events.put(("warning", f"{pack.title} didn't finish downloading: {exc}"))
            finally:
                self.knowledge["downloading"] = None
                self.events.put(("knowledge", None))
        threading.Thread(target=download, name="NovaWikipedia", daemon=True).start()
        return None

    def _act_knowledge_remove(self, args: dict[str, Any]) -> None:
        name = Path(str(args.get("file") or "")).name
        if name.endswith(".zim"):
            self.wikipedia.remove(self.wikipedia.folder / name)
        self._apply_knowledge()

    def _act_notes_index(self, _args: dict[str, Any]) -> dict[str, Any] | None:
        """Reads the notes again by meaning (downloading the small embedding model first if it isn't here)."""
        if self.knowledge["notes"].get("busy"):
            return {"ok": False, "error": "Already reading your notes."}
        self.knowledge["notes"] = {"busy": True, "status": "Starting…"}
        self._update(knowledge=self._knowledge_state())

        def index() -> None:
            try:
                if not self._embedding_model_ready():
                    pull_model(self.agent.base_url, notes_search.MODEL,
                               lambda text: self._knowledge_status(f"Getting the meaning model: {text}"))
                    self._status_worker()  # the model list now has the meaning model
                done = self.notes_index.refresh(self._vault_folder(),
                                                lambda count, total: self._knowledge_status(f"Reading notes {count}/{total}…"))
                self.knowledge["notes"] = {"busy": False, "status": f"Up to date: {done['notes']} notes ({done['read']} read again)."}
            except Exception as exc:
                self.knowledge["notes"] = {"busy": False, "status": f"Couldn't read the notes: {exc}"}
            self.events.put(("knowledge", None))
        threading.Thread(target=index, name="NovaNotesIndex", daemon=True).start()
        return None

    def _knowledge_status(self, text: str) -> None:
        self.knowledge["notes"] = {"busy": True, "status": text}
        self.events.put(("knowledge", None))

    def _act_obs_password(self, args: dict[str, Any]) -> None:
        self._save_setting("obs_password", str(args.get("password") or "")[:120])
        self.agent.obs_password = str(self.settings.get("obs_password") or "")

    def _act_keep_city(self, args: dict[str, Any]) -> dict[str, Any]:
        city = " ".join(str(args.get("city") or self._route_city()).split())
        if not city:
            return {"ok": False, "error": "Save your city in Settings first (Location), or type one."}

        def keep() -> None:
            try:
                name = self.router.keep_city(city)
                self.events.put(("toast", (f"{name}'s roads are kept on this PC: routes there work offline.", "ok")))
            except (ValueError, OSError) as exc:
                self.events.put(("warning", f"Couldn't keep {city}'s roads: {exc}"))
            self.events.put(("knowledge", None))
        threading.Thread(target=keep, name="NovaKeepCity", daemon=True).start()
        return {"ok": True}

    # ---------- fastest routes on OpenStreetMap roads (routes.py), shown on the Route screen ----------

    def _route_city(self) -> str:
        place = getattr(self.agent.location, "place", None) if self.agent.location is not None else None
        if not place:
            return ""
        from location import label
        return label(place)

    def _route_tool(self, start: str, end: str, stops: list[str], mode: str, best_order: bool) -> str:
        try:
            first = self.router.geocode(start)  # kept, so route() below doesn't ask again
            # The globe flies to the city at once, while the roads are worked out.
            self.ui.emit({"type": "route_focus", "name": first["name"], "lat": first["lat"], "lon": first["lon"]})
        except (ValueError, OSError):
            pass  # route() below says what went wrong
        try:
            found = self.router.route(start, end, stops, mode, best_order)
        except ValueError as exc:
            self.ui.emit({"type": "route_error", "text": f"No route: {exc}."})
            return f"Not done: {exc}."
        except OSError as exc:  # the map servers are out of reach: Claude can still give directions from the web
            self.ui.emit({"type": "route_error", "text": f"The map servers didn't answer ({exc})."})
            from tool_registry import NotHere
            raise NotHere(f"the map servers (OpenStreetMap) didn't answer: {exc}") from exc
        data = {key: getattr(found, key) for key in ("places", "mode", "seconds", "metres", "legs", "line", "searched",
                                                      "roads", "reordered")}
        self.ui.emit({"type": "route_view", "route": {**data, "google_maps": found.google_maps()}})
        return found.summary()

    def _act_route(self, args: dict[str, Any]) -> dict[str, Any]:
        """The Route screen's form: worked out on a thread (the map data can take a while), then drawn."""
        start, end = " ".join(str(args.get("start") or "").split()), " ".join(str(args.get("end") or "").split())
        if not start or not end:
            return {"ok": False, "error": "Say where from and where to."}
        stops = [stop.strip() for stop in str(args.get("stops") or "").split(",") if stop.strip()][:4]
        mode = str(args.get("mode") or "motorbike")
        def work() -> None:
            try:
                self._route_tool(start, end, stops, mode, True)
            except Exception:
                pass  # already shown on the Route screen
        threading.Thread(target=work, name="NovaRoute", daemon=True).start()
        return {"ok": True}

    def _news_lookup(self, query: str, category: str, days: int, offset_days: int) -> str:
        return news_assistant.lookup(self._news(), query, category, days, offset_days)

    def _news_state(self, status: str = "") -> dict[str, Any]:
        from news_intel.config import gnews_key
        on = bool(self.settings.get("news_on"))
        state: dict[str, Any] = {"on": on, "running": self.news_running, "status": status, "key": bool(gnews_key()),
                                 "last": None, "total": 0, "at": str(self.settings.get("news_run_at") or "06:00")}
        if on or self.news_store is not None:
            try:
                runs = self._news().runs(1)
                state["total"] = self._news().counts().get("total", 0)
                if runs:
                    last = runs[0]
                    state["last"] = {key: last[key] for key in ("started_at", "finished_at", "collected", "added",
                                                                "duplicates", "processed", "failed", "providers")}
                    state["last"]["errors"] = last["errors"][:6]
            except Exception as exc:  # a locked or damaged database shows as a problem, it doesn't stop Nova
                state["status"] = f"The news database couldn't be read: {exc}"
        return state

    def _act_news(self, args: dict[str, Any]) -> dict[str, Any] | None:
        on = bool(args.get("on"))
        if on and not self.settings.get("news_consented") and not args.get("consented"):
            return {"need_consent": "news"}
        if on:
            self._save_setting("news_consented", True)
        self._save_setting("news_on", on)
        self.agent.news = self._news_lookup if on else None
        self._update(news=self._news_state())
        if on:
            self._news_check()
        return None

    def _act_news_run(self, _args: dict[str, Any]) -> dict[str, Any] | None:
        if self.news_running:
            return {"ok": False, "error": "The news desk is already collecting."}
        self._start_news_run()
        return None

    def _start_news_run(self) -> None:
        self.news_running = True
        self._update(news={"running": True, "status": "Starting…"})
        config = self._news_config()

        def work() -> None:
            try:
                report = news_pipeline.run(config, self._news(), progress=lambda text: self.events.put(("news_progress", text)))
                self.events.put(("news_done", f"Done: {report.line()}."))
            except Exception as exc:  # reported, never crashes Nova
                self.events.put(("news_done", f"The run stopped: {exc}"))
        threading.Thread(target=work, name="NovaNewsDesk", daemon=True).start()

    def _news_check(self) -> None:
        """The daily run when it is due: at the set time, or later the same day when the PC was off then."""
        if not self.settings.get("news_on") or self.news_running:
            return
        try:
            runs = self._news().runs(1)
        except Exception:
            return
        last_day = (datetime.fromisoformat(runs[0]["started_at"].replace("Z", "+00:00")).astimezone().date()
                    if runs else None)
        if news_schedule.due(datetime.now(), str(self.settings.get("news_run_at") or "06:00"), last_day):
            self._start_news_run()

    def _news_tick(self) -> None:
        if self.closing:
            return
        self._news_check()
        self.root.after(60_000, self._news_tick)

    def _act_news_key(self, args: dict[str, Any]) -> dict[str, Any] | None:
        key = str(args.get("key", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9]{20,64}", key):
            return {"ok": False, "error": "That doesn't look like a GNews API key (gnews.io → Dashboard → API key)."}
        path = news_data_dir() / "gnews_api_key"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key, encoding="utf-8")
        self._update(news=self._news_state())
        self._toast("GNews key saved on this PC. The next run uses it.", "ok")
        return None

    def _act_news_key_forget(self, _args: dict[str, Any]) -> None:
        (news_data_dir() / "gnews_api_key").unlink(missing_ok=True)
        self._update(news=self._news_state())

    def _act_news_search(self, args: dict[str, Any]) -> dict[str, Any]:
        days = max(1, min(int(args.get("days") or 1), 365))
        category = str(args.get("category") or "")
        rows = self._news().search(" ".join(str(args.get("query") or "").split())[:200], category, days, 0, "", 25)
        items = [{"title": row["title"], "publisher": row["publisher"], "published_at": row["published_at"],
                  "url": row["original_url"], "summary": row["summary"] or row["description"], "category": row["category"],
                  "importance": row["importance"], "facts": row["key_facts"][:3]} for row in rows]
        runs = self._news().runs(1)
        return {"ok": True, "items": items, "briefing": runs[0]["briefing"] if runs else ""}

    # ---------- the free online brain: a large open model on Ollama Cloud (needs a free Ollama account) ----------

    def _apply_free_cloud(self) -> None:
        on = self._brain_choice() == "free" or (self._brain_choice() == "auto" and not self._claude_ready())
        model = str(self.settings.get("free_cloud_model") or FREE_CLOUD_DEFAULT)
        self.agent.free_cloud = model if on else None
        self.agent._free_cloud_until = 0.0
        self._update(free_cloud={"on": on, "model": model, "status": "checking…" if on else "", "usb": USB})
        if on:
            threading.Thread(target=self._prepare_free_cloud, args=(model,), name="NovaFreeCloud", daemon=True).start()

    def _prepare_free_cloud(self, model: str) -> None:
        """Ollama fetches the cloud model's small manifest (no weights): that also shows whether it is signed in."""
        try:
            _http_json(f"{self.agent.base_url}/api/pull", {"model": model, "stream": False}, timeout=60)
            status = "ready"
        except OllamaError as exc:
            low = str(exc).lower()
            status = ("sign in first: click Sign in to Ollama" if "401" in low or "unauthorized" in low or "sign" in low
                      else "Ollama isn't running" if "couldn't reach" in low else f"not ready: {str(exc)[:160]}")
        self.events.put(("free_cloud", status))

    def _act_free_cloud(self, args: dict[str, Any]) -> dict[str, Any] | None:
        return self._act_brain_choose({**args, "brain": "free" if args.get("on") else "local"})

    def _act_free_cloud_settings(self, args: dict[str, Any]) -> dict[str, Any] | None:
        model = " ".join(str(args.get("model", "")).split())[:80]
        if not re.fullmatch(r"[\w.\-/]+:[\w.\-]*cloud", model):
            return {"ok": False, "error": "Give an Ollama Cloud model name ending in cloud, e.g. gpt-oss:120b-cloud."}
        self._save_setting("free_cloud_model", model)
        self._apply_free_cloud()
        return None

    def _act_free_cloud_signin(self, _args: dict[str, Any]) -> dict[str, Any] | None:
        """Ollama signs in from its own command: it opens ollama.com to connect this PC to the owner's account."""
        if sys.platform == "darwin":
            import mac
            mac.osascript('tell application "Terminal" to do script "ollama signin"')
            return None
        if sys.platform != "win32":
            return {"ok": False, "error": "Run `ollama signin` in a terminal."}
        try:
            subprocess.Popen(["cmd", "/c", "start", "Ollama sign-in", "cmd", "/k", "ollama", "signin"],  # noqa: S603,S607
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            return {"ok": False, "error": f"Couldn't start Ollama's sign-in: {exc}. Is Ollama installed?"}
        self._toast("Ollama's sign-in opened: follow the link it shows, then come back. Nova checks again in a minute.", "info")
        self.root.after(60_000, self._apply_free_cloud)
        return None

    # ---------- the owner's other PC: memory and the second brain through one synced folder ----------

    def _apply_pc_sync(self) -> None:
        """Share remembered facts and tasks through the vault folder (which the owner syncs with Syncthing), or stop."""
        on = bool(self.settings.get("share_pcs"))
        self.memory.shared = pc_sync.SharedMemory(self._vault_folder(), self.pc) if on else None
        self.brain.vault = self._vault()  # only one of the PCs writes the wiki while shared
        self._update(pcs=self._pcs_state())

    def _sync_pcs(self) -> None:
        """Every minute while shared: take in what the other PC remembered or forgot, and say this PC is here."""
        if self.closing:
            return
        self.root.after(60_000, self._sync_pcs)
        self._sync_pcs_now()

    def _sync_pcs_now(self) -> None:
        shared = self.memory.shared
        if shared is None:
            return

        def work() -> None:
            try:
                changed = self.memory.merge_shared()
                shared.beat()
                self.events.put(("pcs", (changed, "")))
            except Exception as exc:  # the folder is on a drive that's gone, a file is locked by the sync tool...
                self.events.put(("pcs", (0, f"Couldn't use the shared folder: {exc}")))
        threading.Thread(target=work, name="NovaPcSync", daemon=True).start()

    def _pcs_state(self, error: str = "") -> dict[str, Any]:
        shared = self.memory.shared
        now = time.time()
        others = [{"pc": other["pc"], "seen": pc_sync.ago(now - other["seen"])} for other in (shared.others() if shared else [])[:4]]
        return {"on": shared is not None, "pc": self.pc, "folder": str(self._vault_folder()), "others": others,
                "wiki": self.brain.vault.wiki_writer() if shared else "", "error": error}

    def _act_pc_sync(self, args: dict[str, Any]) -> None:
        self._save_setting("share_pcs", bool(args.get("on")))
        self._apply_pc_sync()
        if self.memory.shared is not None:
            self._vault_folder().mkdir(parents=True, exist_ok=True)
            self._sync_pcs_now()

    def _act_wiki_here(self, _args: dict[str, Any]) -> None:
        self.brain.vault.claim_wiki()
        self._update(pcs=self._pcs_state())
        self._toast("This PC writes the second brain's wiki now; the other PC leaves it to this one.", "ok")

    def _act_open_photos(self, _args: dict[str, Any]) -> None:
        folder = self.creative.photo_folder
        folder.mkdir(parents=True, exist_ok=True)
        app_window.open_path(folder)

    def _act_location_forget(self, _args: dict[str, Any]) -> None:
        self.location.forget()
        self._update(weather_now=None, local_news=[])

    def _find_place_in_background(self, find) -> None:
        self._set_voice_state("FINDING YOUR LOCATION…", "info")

        def run() -> None:
            try:
                place = find()
                how = f" (from {place['how']})" if place.get("how") else ""
                self.events.put(("toast", (f"Location: {places.label(place)}{how}. Ask “Hey Nova, what's the weather?”", "ok")))
            except Exception as exc:
                self.events.put(("toast", (f"Couldn't set the location: {exc}", "warn")))
            self.events.put(("voice_state", ("MIC ON · SAY “HEY NOVA”" if self.state["switches"]["mic"] else "READY", "idle")))
        threading.Thread(target=run, name="AlfredLocation", daemon=True).start()

    def _refresh_weather(self, repeat: bool = True, news: bool = False) -> None:
        """The WEATHER readout every 30 minutes, and local news with the brief (only once a location is set)."""
        if self.closing:
            return
        if self.location.place is not None:
            with_news = news or self.state["switches"].get("brief", False)

            def fetch() -> None:
                try:
                    self.events.put(("weather_now", self.location.weather_summary()))
                    if with_news:
                        self.events.put(("local_news", self.location.local_news()))
                except Exception:
                    pass  # offline: the readout keeps its last value
            threading.Thread(target=fetch, name="AlfredWeather", daemon=True).start()
        if repeat:
            self.root.after(30 * 60 * 1000, self._refresh_weather)

    def _load_brief(self, force: bool) -> None:
        interests, region = self.state["settings"]["interests"], self.state["settings"]["brief_region"]
        outlets = self.state["settings"]["news_outlets"]
        self.agent.brief = lambda: daily_brief.as_text(self.state["brief"])
        cached = None if force else daily_brief.load_today(interests, region, outlets)
        if cached is not None:
            self._update(brief=cached)
            return
        if self.state["brief_loading"]:
            return
        self._update(brief_loading=True)

        def fetch() -> None:
            self.events.put(("brief", daily_brief.refresh(interests, region, outlets)))
        threading.Thread(target=fetch, name="AlfredBrief", daemon=True).start()

    def _act_open_url(self, args: dict[str, Any]) -> dict[str, Any] | None:
        url = str(args.get("url", ""))
        if urlsplit(url).scheme not in ("http", "https"):
            return {"ok": False, "error": "Only web links can be opened."}
        webbrowser.open(url)  # the user's own browser, not the HUD window
        return None

    def _act_heart(self, args: dict[str, Any]) -> None:
        """Heart rate from a Bluetooth band; remembered like the other switches."""
        on = bool(args.get("on"))
        self._save_setting("heart_on", on)
        if on:
            self.heart.start()
            self.agent.fitness = self.heart
        else:
            self.heart.stop()
            self.agent.fitness = None
        self._update(heart={"on": on, "status": "Starting…" if on else "", "bpm": None})

    def _act_walkthrough_next(self, _args: dict[str, Any]) -> None:
        if self.walkthrough is not None:
            self.walkthrough.next()

    def _act_walkthrough_stop(self, _args: dict[str, Any]) -> None:
        self._stop_walkthrough()
        threading.Thread(target=self._clear_overlays, daemon=True).start()

    def _act_cancel_timer(self, args: dict[str, Any]) -> None:
        self.timers.cancel_id(int(args.get("id") or 0))

    def _act_forget_fact(self, args: dict[str, Any]) -> None:
        self.memory.delete_fact(int(args.get("id") or 0))
        self._refresh_tasks()

    def _act_status_refresh(self, _args: dict[str, Any]) -> None:
        threading.Thread(target=self._status_worker, daemon=True).start()

    # ---------- model ----------

    def _resolve_model(self) -> None:
        """Desktop: pick the model for this PC (or the one chosen in settings). USB chose at start-up."""
        try:
            if self.hardware is None:
                self.hardware = detect_hardware()
            installed = sorted(str(item.get("name")) for item in
                               _http_json(f"{self.agent.base_url}/api/tags", timeout=10).get("models", []))
            if USB or MODEL:
                self.events.put(("model_choice", {"name": self.agent.model, "installed": installed,
                                                  "reason": "picked for this PC" if USB else "set by ALFRED_MODEL",
                                                  "vision": vision.find_vision_model(installed)}))
            else:
                choice = choose_model(self.settings.get("model", "auto"), installed, self.hardware)
                tuned = self.settings.get("tuning") or {}
                if self.settings.get("model", "auto") == "auto" and tuned.get("model") in installed:
                    choice.model, choice.missing = tuned["model"], False  # measured here: the strongest that runs smoothly
                offer = ({"name": choice.recommended, "size_gb": choice.size_gb, "reason": choice.reason,
                          "stronger": choice.stronger} if choice.missing else None)
                self.events.put(("model_choice", {"name": choice.model, "recommended": choice.recommended,
                                                  "reason": choice.reason, "installed": installed, "offer": offer,
                                                  "vision": vision.find_vision_model(installed)}))
        except Exception as exc:
            self.events.put(("status_error", str(exc)))
            self.root.after(15000, lambda: threading.Thread(target=self._resolve_model, daemon=True).start())
            return
        self._status_worker()
        if (not USB and not MODEL and self.settings.get("auto_tune", True) and self.settings.get("model", "auto") == "auto"
                and auto_tune.due(self.settings.get("tuning"), VERSION, self.hardware)):
            self._tune()  # after an update or new hardware: find the best setup again

    # ---------- auto-tune: the strongest model this PC runs smoothly, set up for it ----------

    def _tune(self, report: Callable[[str], None] | None = None) -> str:
        """Runs on a worker thread; reports through events ("tune_progress", then "tuned" or "tune_failed").
        Returns "" when it tuned, else why not (Set up everything shows it)."""
        if self.tuning_now:
            return "Nova is tuning already"
        self.tuning_now = True
        base = self.agent.base_url
        try:
            models = Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama")
            free_gb = shutil.disk_usage(models if models.exists() else Path.home()).free / 1024 ** 3
            def progress(text: str) -> None:
                self.events.put(("tune_progress", text))
                if report is not None:
                    report(text)
            result = auto_tune.tune(
                auto_tune.Ollama(base), self.hardware or detect_hardware(), VERSION,
                pull=lambda name: pull_model(base, name, progress), disk_free_gb=free_gb,
                restart=lambda settings: (auto_tune.apply_settings(settings), auto_tune.restart_ollama(base))[1],
                progress=progress)
            self.events.put(("tuned", result.as_dict()))
            return ""
        except Exception as exc:
            self.events.put(("tune_failed", str(exc)))
            return str(exc)
        finally:
            self.tuning_now = False

    def _apply_tuning(self, tuned: dict[str, Any] | None) -> None:
        if not tuned or self.settings.get("model", "auto") != "auto" or USB or MODEL:
            return
        self.agent.num_ctx = int(tuned.get("num_ctx") or 8192)
        self.agent.keep_alive = str(tuned.get("keep_alive") or "30m")

    # ---------- the Skills board: everything Nova can do, and whether it's ready here ----------

    def _skills_status(self) -> dict[str, tuple[str, str]]:
        READY, SETUP, CLOUD, OFF = skills_board.READY, skills_board.SETUP, skills_board.CLOUD, skills_board.OFF
        on = lambda flag, note="": (READY, "") if flag else (OFF, note)  # noqa: E731
        cloud = self.agent.cloud_tools is not None
        tuned = self.settings.get("tuning") or {}
        try:
            notes = self.notes_index.count() > 0
        except Exception:
            notes = False
        reverse_problem = self.reverse.problem() if self.settings.get("reverse_on") else ""
        return {
            "mic": (READY, "") if self.voice.available else (SETUP, "no microphone input found"),
            "claude": (READY, "") if (claude_expert.available() or claude_code.find()) else (SETUP, "SETTINGS → Model → Claude"),
            "cloud": (READY, "") if cloud else (SETUP, "a Claude API key or Claude Code, and the cloud switch on"),
            "api": (READY, self._api_entry().label) if self._api_entry() and self._api_key(self._api_entry())
                   else (SETUP, "SETTINGS → Model → API brain → Add an API brain"),
            "cloud_brain": (READY, self._cloud_agent().label) if cloud_agents.find(self._cloud_agent())
                           else (SETUP, f"install {self._cloud_agent().label} and connect your account"),
            "tune": (READY, f"{tuned.get('model')} · {round(tuned.get('tokens_per_second') or 0)} tokens/s") if tuned
                    else (SETUP, "not measured yet: SETTINGS → This PC → Tune now"),
            "wikipedia": (READY, "offline") if self.wikipedia.installed() else
                         ((CLOUD, "not downloaded: Claude looks it up online") if cloud else (SETUP, "SETTINGS → Offline knowledge")),
            "notes": (READY, "") if notes else (SETUP, "SETTINGS → Offline knowledge → Index my notes"),
            "second_brain": on(self.settings.get("second_brain"), "SETTINGS → Second brain"),
            "news": on(self.settings.get("news_on"), "BRIEF → News desk"),
            "google": (READY, "") if gmail_tools.connected() else (SETUP, "SETTINGS → Connections → Connect Google"),
            "calendar": (READY, "") if gmail_tools.connected() and gmail_tools.calendar_granted() else
                        (SETUP, "SETTINGS → Connections → Add Google Calendar"),
            "drive": (READY, "") if gmail_tools.connected() and gmail_tools.drive_granted() else
                     (SETUP, "SETTINGS → Connections → Add Google Drive"),
            "screen": ((OFF, "Windows only for now") if not IS_WINDOWS else on(self.assist is not None, "Assist button")),
            "camera": (READY, ""),
            "claude_code": (READY, "") if self.deep_work.available else (SETUP, "install Claude Code and sign in"),
            "vscode": (READY, "") if (shutil.which("code") or shutil.which("code.cmd")) else (SETUP, "VS Code's code command"),
            "reverse": (OFF, "REA screen") if not self.settings.get("reverse_on") else
                       ((SETUP, reverse_problem) if reverse_problem else (READY, "")),
            "shannon": (READY, "checks WSL, Docker and the key when it runs") if self.settings.get("shannon_consented")
                       else (SETUP, "SHANNON screen; needs WSL2, Docker Desktop and an API key"),
            "telegram": on(self.settings.get("telegram_on"), "SETTINGS → Telegram"),
            "heart": on(self.settings.get("heart_on"), "SETTINGS → Fitness"),
        }

    # ---------- the prompt optimizer, on the brain the owner uses ----------

    def _prompt_ask(self, system: str, prompt: str) -> str:
        """One plain answer: Claude with the API key when Claude is the chosen brain, else the model on this PC."""
        key = claude_expert.key()
        if key and self._brain_choice() == "claude":
            import anthropic
            reply = anthropic.Anthropic(api_key=key, max_retries=1).messages.create(
                model=self.settings.get("claude_model", cloud_brain.DEFAULT_MODEL), max_tokens=4000,
                output_config={"effort": "low"}, messages=[{"role": "user", "content": prompt}],
                **({"system": system} if system else {}))
            return "".join(block.text for block in reply.content if block.type == "text")
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        reply = _http_json(f"{self.agent.base_url}/api/chat", {
            "model": self.agent.model, "messages": messages, "stream": False, "think": False,
            "keep_alive": self.agent.keep_alive, "options": {"num_ctx": self.agent.num_ctx, "num_predict": 1500,
                                                            "temperature": 0.3}}, timeout=300)
        return str((reply.get("message") or {}).get("content") or "")

    def _make_image(self, prompt: str) -> str:
        """A picture on the owner's OpenAI API brain (the first one they added), saved in Pictures/Nova Images and opened."""
        entry = next((item for item in self._api_entries() if item.provider == "openai" and self._api_key(item)), None)
        if entry is None:
            return "Making pictures needs an OpenAI API brain: SETTINGS → Model → API brain → Add (OpenAI)."
        try:
            path = api_brains.make_image(entry.base_url, self._api_key(entry), prompt, Path.home() / "Pictures" / "Nova Images",
                                         str(self.settings.get("image_model") or "gpt-image-1"))
        except cloud_brain.Unavailable as exc:
            return f"Not done: {exc.why}."
        app_window.open_path(path)
        return f"Made the picture and opened it: {path}"

    def _optimize_prompt(self, prompt: str, kind: str, test: bool) -> str:
        import prompt_optimizer
        result = prompt_optimizer.optimize(prompt, self._prompt_ask, kind, test)
        saved = self.skills.save_output(f"Prompt {' '.join(prompt.split()[:6])}",
                                        f"## Original\n\n{result.original}\n\n## Optimized\n\n{result.optimized}\n\n"
                                        f"Result: {result.winner}. {result.why}")
        return f"{result.summary()}\n\n(Kept in outputs/{saved.name}.)"

    def _act_skills_board(self, _args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, **skills_board.board(self._skills_status(), self._skills_state()["list"], self._hotkey_state())}

    def _act_trading(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.trading_desk.act(str(args.get("action") or "scan"), args)

    def _act_tune_now(self, _args: dict[str, Any]) -> dict[str, Any] | None:
        if USB:
            return {"ok": False, "error": "The USB Edition picks its model when it starts."}
        if self.tuning_now:
            return {"ok": False, "error": "Nova is tuning already."}
        self._update(tuning={**self.state["tuning"], "running": True, "step": "Starting"})
        threading.Thread(target=self._tune, name="NovaTune", daemon=True).start()
        return None

    def _act_auto_tune(self, args: dict[str, Any]) -> None:
        self._save_setting("auto_tune", bool(args.get("on")))
        self._update(tuning={**self.state["tuning"], "auto": bool(args.get("on"))})

    def _status_worker(self) -> None:
        try:
            version = _http_json(f"{self.agent.base_url}/api/version", timeout=8).get("version", "")
            loaded = next((item for item in _http_json(f"{self.agent.base_url}/api/ps", timeout=8).get("models", [])
                           if item.get("name") == self.agent.model), None)
            placement = _ollama_placement(self.agent.model) if loaded else "idle"
            self.events.put(("status", {"ollama": f"online · v{version}", "placement": placement,
                                        "context": loaded.get("context_length") if loaded else None}))
        except Exception as exc:
            self.events.put(("status_error", str(exc)))

    def _status_loop(self) -> None:
        if self.closing:
            return
        threading.Thread(target=self._status_worker, daemon=True).start()
        self.root.after(15000, self._status_loop)

    # ---------- talking ----------

    def _speak(self, text: str) -> None:
        self._update(speaking=True)
        self.voice.speak(text, done=lambda: self.events.put(("spoke", None)),
                         on_error=lambda error: self.events.put(("voice_error", error)))

    def _chat_worker(self, prompt: str) -> None:
        self.turn_cancel.clear()
        self.voice.unmute()
        self.takeover_warned = False
        screen = None
        if self.assist is not None:
            from screen_assist import ScreenSession
            self._clear_overlays()
            screen = ScreenSession(self.assist, lambda: self.target_hwnd, self.turn_cancel, self._set_acting,
                                   on_guide=lambda steps, hwnd: self.events.put(("walkthrough_start", (steps, hwnd))))
        # Like plip: show the reply as it is written and speak each sentence as soon as it ends.
        streamed: list[str] = []
        started, first_words = time.monotonic(), None
        speak = self.state["switches"]["speak"]
        splitter = SentenceSplitter(lambda sentence: self.voice.say(sentence) if speak else None)

        def on_text(piece: str) -> None:
            nonlocal first_words
            first_words = first_words or time.monotonic()
            streamed.append(piece)
            splitter.feed(piece)
            self.live_reply = "".join(streamed)
            self.ui.emit({"type": "reply_delta", "text": self.live_reply})
        try:
            with self.agent_lock:
                reply = self.agent.ask(self._with_building(self._with_workplace(prompt)), approve_tool=self._confirm_action, screen=screen,
                                       cancel=self.turn_cancel, on_text=on_text)
            splitter.flush()
            latency = round(((first_words or time.monotonic()) - started) * 1000)
            self.events.put(("chat_done", (reply, bool(streamed), latency)))
        except OllamaError as exc:
            self.events.put(("chat_error", str(exc)))
        except Exception as exc:  # surface it rather than leaving the HUD stuck
            self.events.put(("chat_error", f"Unexpected local error: {exc}"))

    def _confirm_action(self, name: str, arguments: dict[str, Any]) -> bool:
        """Called from the agent's thread: may Nova do this? On autopilot usually yes at once; otherwise Nova asks
        (out loud, or in a pop-up when the owner chose that) and waits for yes, no, Esc or the time to run out."""
        if self.agent.autopilot and name in NEVER_ASK:
            summary = str(arguments.get("summary") or arguments.get("task") or "")
            reason = risky_step(name, summary) if name in SCREEN_STEP_TOOLS and self.settings.get("ask_risky") else ""
            if not reason:  # nothing to ask; the banner, the cursor and Esc keep the owner in charge
                if name in SCREEN_STEP_TOOLS and summary:
                    self._set_voice_state(f"AUTOPILOT · {summary.splitlines()[0][:70]}", "info")
                return not self.turn_cancel.is_set()
            arguments = {**arguments, "speak": f"{reason}: {_plain_words(summary.splitlines()[0])[:120]}. Should I go ahead?"}
        return self._ask_and_wait(name, arguments)

    def _ask_and_wait(self, name: str, arguments: dict[str, Any]) -> bool:
        pending = {"id": uuid.uuid4().hex, "event": threading.Event(), "approved": False, "name": name}
        self.pending_approval = pending
        by_voice = bool(self.settings.get("ask_by_voice", True))
        if not by_voice:
            title, body = _popup_text(name, arguments)
            self.events.put(("approval_open", {"id": pending["id"], "title": title, "body": body}))
        self.voice.say(_spoken_question(name, arguments))  # answered by a spoken yes or no (hold the talk key, or the mic)
        self._set_voice_state(self._question_hint(), "warn")
        self._wait_for_answer(pending["event"], by_voice)
        self.pending_approval = None
        if not by_voice:
            self.events.put(("approval_closed", pending["id"]))
        return bool(pending["approved"]) and not self.turn_cancel.is_set()

    def _wait_for_answer(self, answered: threading.Event, by_voice: bool) -> None:
        """Until the answer, Esc or Nova closing. Out loud, Nova asks once more after a while, then gives up."""
        waited, reminded = 0.0, False
        while not answered.wait(0.1):
            if self.closing or self.turn_cancel.is_set():
                return
            waited += 0.1
            if by_voice and not reminded and waited >= ASK_REMIND_SECONDS:
                reminded = True
                self.voice.say("Still waiting for a yes or no.")
            if by_voice and waited >= ASK_GIVE_UP_SECONDS:
                self.voice.say("No answer, so I didn't do it.")
                return

    def _ask_from_phone(self, text: str, approve) -> str:
        with self.agent_lock:
            self.events.put(("phone_chat", ("YOU · IPHONE", text, "user")))
            reply = self.agent.ask(text, approve_tool=approve)
            self.events.put(("phone_chat", ("NOVA → IPHONE", reply, "assistant")))
            return reply

    # ---------- Discover: GitHub projects the owner might like (studied read-only; code installed only after asking the owner) ----------

    def _discover_state(self, **changes: Any) -> dict[str, Any]:
        history = self.discover.history()
        return {"items": self.discover_items, "offers": self.skill_offers, "token": discovery.stored_token() is not None,
                "username": str(self.settings.get("github_user") or ""), "added": len(history["accepted"]),
                "skipped": len(history["rejected"]), "studying": list(self.discover_studies.values()),
                "claude_code": self.deep_work.available, "reverse_on": bool(self.settings.get("reverse_on")),
                "reverse_problem": self.reverse.problem() if self.settings.get("reverse_on") else "", **changes}

    def _act_discover_refresh(self, args: dict[str, Any]) -> None:
        def work() -> None:
            self._update(discover=self._discover_state(busy=True, status="Asking GitHub…"))
            try:
                self.discover_items = self.discover.suggestions(list(self.settings.get("interests") or []),
                                                                str(self.settings.get("github_user") or ""), bool(args.get("force")))
                status = "" if self.discover_items else "Nothing new right now: add interests in Settings → Daily brief."
            except discovery.DiscoverError as exc:
                status = f"Discover: {exc}."
            self._update(discover=self._discover_state(busy=False, status=status))
        threading.Thread(target=work, name="NovaDiscover", daemon=True).start()

    def _discover_item(self, repo: str) -> dict[str, Any] | None:
        return next((item for item in self.discover_items if item["repo"] == repo), None)

    def _act_discover_add(self, args: dict[str, Any]) -> dict[str, Any] | None:
        """Pins the repo to its current commit, records its license, and has Claude Code study it (read-only)."""
        item = self._discover_item(str(args.get("repo", "")))
        if item is None:
            return {"ok": False, "error": "That suggestion is gone: refresh Discover."}
        if not self.deep_work.available:
            return {"ok": False, "error": "Studying a project needs Claude Code on this PC (claude.com/product/claude-code)."}

        def work() -> None:
            try:
                pinned = self.discover.pin(item)
            except discovery.DiscoverError as exc:
                self._toast(f"Discover: {exc}.", "error")
                return
            self.discover.decide(pinned, added=True)
            self.discover_items = [entry for entry in self.discover_items if entry["repo"] != pinned["repo"]]
            title = f"Discover {pinned['repo'].replace('/', ' ')}"[:80]  # Claude Code's job titles are cut at 80
            self.discover_studies[title] = pinned["repo"]
            self.deep_work.start(title, discovery.study_task(pinned))
            self._toast(f"Claude Code is studying {pinned['repo']} at {pinned['sha'][:7]} "
                        f"({pinned['license'] or 'no license stated'}). Nothing is installed.", "info")
            self._update(discover=self._discover_state())
        threading.Thread(target=work, name="NovaDiscoverAdd", daemon=True).start()
        return None

    def _act_discover_skip(self, args: dict[str, Any]) -> None:
        item = self._discover_item(str(args.get("repo", "")))
        if item is not None:
            self.discover.decide(item, added=False)
            self.discover_items = [entry for entry in self.discover_items if entry["repo"] != item["repo"]]
        self._update(discover=self._discover_state())

    def _act_discover_settings(self, args: dict[str, Any]) -> dict[str, Any] | None:
        if "username" in args:
            name = str(args.get("username") or "").strip().lstrip("@")
            if name and not discovery.USER_NAME.match(name):
                return {"ok": False, "error": "That isn't a GitHub username."}
            self._save_setting("github_user", name)
        if args.get("token"):
            try:
                discovery.save_token(str(args["token"]))
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
        if args.get("forget_token"):
            discovery.forget_token()
        self._update(discover=self._discover_state())
        return None

    def _offer_skill(self, title: str, result: str) -> None:
        """A finished study that proposed a skill note: offered to the owner, who reads it before it is added."""
        repo = self.discover_studies.pop(title, "")
        try:
            text = (self._vault_folder() / result).read_text(encoding="utf-8")
        except OSError:
            return
        note = discovery.skill_from(text)
        if note and skill_notes.parse("offer", note) is not None:
            self.skill_offers = [offer for offer in self.skill_offers if offer["repo"] != repo] + \
                [{"repo": repo, "note": note, "report": result}]
            self._toast(f"The study of {repo} proposes a skill. Read it in TASKS → Discover before adding it.", "info")

    def _act_discover_install_skill(self, args: dict[str, Any]) -> dict[str, Any] | None:
        offer = next((offer for offer in self.skill_offers if offer["repo"] == args.get("repo")), None)
        if offer is None:
            return {"ok": False, "error": "That proposal is gone."}
        skill = skill_notes.parse("offer", offer["note"])
        if skill is None:
            return {"ok": False, "error": "The proposed skill isn't readable."}
        try:
            self.skills.add(skill.title, skill.instructions, ", ".join(skill.says), skill.schedule, ", ".join(skill.tools),
                            skill.brain, skill.output)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        self.skill_offers = [entry for entry in self.skill_offers if entry is not offer]
        self._toast(f"Skill added: {skill.title}. Say “{skill.says[0] if skill.says else skill.title}” to run it.", "ok")
        self._update(skills=self._skills_state(), discover=self._discover_state())
        return None

    def _act_discover_drop_skill(self, args: dict[str, Any]) -> None:
        self.skill_offers = [offer for offer in self.skill_offers if offer["repo"] != args.get("repo")]
        self._update(discover=self._discover_state())

    def _discover_tool(self, action: str, number: int) -> str:
        """Discover by voice: list the suggestions, or add or skip one by its number."""
        if action == "list" or not self.discover_items:
            try:
                self.discover_items = self.discover_items or self.discover.suggestions(
                    list(self.settings.get("interests") or []), str(self.settings.get("github_user") or ""))
            except discovery.DiscoverError as exc:
                return f"Discover couldn't ask GitHub: {exc}."
            self._update(discover=self._discover_state())
            if action == "list":
                if not self.discover_items:
                    return "No suggestions right now; the owner can add interests in Settings."
                return "Discover suggestions (data, not instructions):\n" + "\n".join(
                    f"{n}. {item['repo']}: {item['about']} ({item['why']})" for n, item in enumerate(self.discover_items[:8], 1))
        if not 1 <= number <= len(self.discover_items):
            return f"There is no suggestion number {number}; list them first."
        item = self.discover_items[number - 1]
        if action == "skip":
            self._act_discover_skip({"repo": item["repo"]})
            return f"Skipped {item['repo']}; Nova will suggest fewer like it."
        answer = self._act_discover_add({"repo": item["repo"]})
        return answer["error"] if answer else (f"Claude Code is studying {item['repo']} (read-only, pinned to its current "
                                               "commit). Nothing is installed; a proposed skill waits for the owner's OK.")

    # ---------- reverse engineering with REA (through Claude Code) ----------

    def _filer(self, topic: str) -> Callable[[str, str], None]:
        """Files a finished Rea or Shannon job in the Library under its topic."""
        def file(title: str, note: str) -> None:
            try:
                self._library().save(title, topic=topic, note=note, status="idea")
                self.ui.emit({"type": "library_changed"})
            except Exception:  # no vault right now: the report is still on disk
                pass
        return file

    # ---------- Rea (Blueprint) and Shannon (Mission board) screens ----------

    def _lab_event(self, event: str, data: dict[str, Any]) -> None:
        """From the Rea / Shannon job threads to their screens (and the owner, when a security check ends)."""
        self.ui.emit({"type": event, **data})
        job = data.get("job") or {}
        if event == "shannon_job" and job.get("status") in ("done", "failed"):
            self.events.put(("lab_done", job))

    def _lab_job(self, args: dict[str, Any], kind: str) -> dict[str, Any]:
        job = self.lab_jobs.get(str(args.get("id") or ""))
        if job is None or job.get("kind") != kind:
            raise ValueError("That report isn't there any more.")
        return job

    def _open_file(self, path: str) -> None:
        if not path or not Path(path).exists():
            raise ValueError("The report file isn't there any more.")
        app_window.open_path(path)

    def _act_lab_view(self, args: dict[str, Any]) -> None:
        """A full screen that takes webcam gestures while it's open (Rea's orbit view)."""
        view = str(args.get("view") or "")
        if args.get("open"):
            self.gesture_screen = view
        elif self.gesture_screen == view:
            self.gesture_screen = ""

    def _act_rea_view(self, _args: dict[str, Any]) -> dict[str, Any]:
        def check() -> None:
            problem = self.reverse.problem() if self.settings.get("reverse_on") else ""
            self.ui.emit({"type": "rea_ready", "problem": problem})
        threading.Thread(target=check, name="NovaReaCheck", daemon=True).start()
        return {"ok": True, "jobs": self.lab_jobs.recent("rea"), "running": list(self.reverse.running)}

    def _act_rea_start(self, args: dict[str, Any]) -> dict[str, Any] | None:
        target = " ".join(str(args.get("target") or "").split())[:300]
        if not target:
            return {"ok": False, "error": "Say what to analyse: an app, a file, a folder or a site."}
        if not self.settings.get("reverse_on"):
            answer = self._act_reverse_toggle({"on": True, "consented": args.get("consented")})
            if answer:
                return answer
        problem = self.reverse.problem()
        if problem:
            return {"ok": False, "error": f"Can't run Rea here: {problem}."}
        self.reverse.start(target, " ".join(str(args.get("goal") or "").split())[:300])
        return None

    def _act_rea_pick(self, args: dict[str, Any]) -> dict[str, Any]:
        """Opens the native file window so the owner clicks the file or folder to analyse instead of typing its path."""
        from tkinter import filedialog
        if str(args.get("kind") or "file") == "folder":
            path = filedialog.askdirectory(title="Pick a folder to analyse")
        else:
            path = filedialog.askopenfilename(title="Pick a file to analyse",
                                              filetypes=[("All files", "*.*")])
        return {"ok": True, "picked": bool(path), "path": path or ""}

    def _act_rea_open(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "job": self._lab_job(args, "rea")}

    def _act_rea_report(self, args: dict[str, Any]) -> None:
        self._open_file(str(self._lab_job(args, "rea").get("report") or ""))

    def _act_rea_fit_add(self, args: dict[str, Any]) -> dict[str, Any] | None:
        """“Add it to Nova” for a REA fit: with the owner's yes, pin the source (when it is a GitHub repo),
        record its license, and hand a read-only study to Claude Code — treated as an update to Nova's code.
        Nothing is installed here; if the study's plan needs code installed, Nova asks the owner first."""
        job = self._lab_job(args, "rea")
        findings = job.get("fit") or []
        try:
            finding = findings[int(args.get("index", 0))]
        except (TypeError, ValueError, IndexError):
            return {"ok": False, "error": "That fit is gone: open the report again."}
        if not args.get("consented"):
            return {"need_consent": "rea_fit_add",
                    "detail": {"area": finding.get("area", ""), "target": job.get("target", ""),
                               "improves": finding.get("improves", "")}}
        if not self.deep_work.available:
            return {"ok": False, "error": "Adding it needs Claude Code on this PC (claude.com/product/claude-code)."}

        def work() -> None:
            pinned = None
            repo = rea_fit.extract_repo(job.get("target", "") or "")
            if repo:
                try:
                    pinned = self.discover.pin({"repo": repo, "url": f"https://github.com/{repo}"})
                except discovery.DiscoverError as exc:
                    self._toast(f"Couldn't pin {repo}: {exc}.", "error")
                    return
                self.discover.decide(pinned, added=True)
            handoff = rea_fit.handoff(finding, job.get("target", ""), report=job.get("output", ""), pin=pinned)
            title = handoff["title"]
            self.discover_studies[title] = pinned["repo"] if pinned else job.get("target", "")
            self.deep_work.start(title, handoff["study_task"])
            self._toast(f"Claude Code is studying {handoff['title']} (read-only). "
                        "Nothing is installed yet — Nova asks you first if the plan needs code installed.", "info")
            self._update(discover=self._discover_state())
        threading.Thread(target=work, name="NovaReaFitAdd", daemon=True).start()
        return None

    def _act_shannon_view(self, _args: dict[str, Any]) -> dict[str, Any]:
        def check() -> None:
            self.ui.emit({"type": "shannon_ready", "problem": self.shannon.problem()})
        threading.Thread(target=check, name="NovaShannonCheck", daemon=True).start()
        return {"ok": True, "jobs": sorted(self.lab_jobs.recent("shannon") + self.lab_jobs.recent("shannon_simulate"),
                                           key=lambda item: item.get("started") or "", reverse=True),
                "projects": self.shannon.projects(),
                "running": self.shannon.job_id if self.shannon.process is not None else ""}

    def _act_shannon_start(self, args: dict[str, Any]) -> dict[str, Any] | None:
        url, project = str(args.get("url") or ""), str(args.get("project") or "")
        shannon_runner.docker_target(url)  # a wrong address or folder is said at once, before the slow checks
        self.shannon._repo(project)
        if not self.settings.get("shannon_consented"):
            if not args.get("consented"):
                return {"need_consent": "shannon"}
            self._save_setting("shannon_consented", True)

        def begin() -> None:
            problem = self.shannon.problem()
            if problem:
                self.ui.emit({"type": "shannon_ready", "problem": problem})
                return
            try:
                self.shannon.start(url, project)
            except (OSError, ValueError) as exc:
                self.ui.emit({"type": "shannon_ready", "problem": str(exc)})
        threading.Thread(target=begin, name="NovaShannonStart", daemon=True).start()
        return None

    def _act_shannon_stop(self, _args: dict[str, Any]) -> None:
        threading.Thread(target=self.shannon.stop, name="NovaShannonStop", daemon=True).start()

    def _act_shannon_open(self, args: dict[str, Any]) -> dict[str, Any]:
        job = self.lab_jobs.get(str(args.get("id") or ""))
        if job is None or job.get("kind") not in ("shannon", "shannon_simulate"):
            raise ValueError("That report isn't there any more.")
        return {"ok": True, "job": job}

    def _act_shannon_fix(self, args: dict[str, Any]) -> dict[str, Any]:
        """The owner solved a weak spot (or reopens it): kept with the check, so the shield remembers."""
        job = self.lab_jobs.get(str(args.get("id") or ""))
        if job is None or job.get("kind") not in ("shannon", "shannon_simulate"):
            raise ValueError("That report isn't there any more.")
        cards = [dict(card) for card in job.get("findings") or []]
        index = int(args.get("index", -1))
        if not 0 <= index < len(cards):
            raise ValueError("That weak spot isn't in this check.")
        cards[index]["fixed"] = bool(args.get("fixed"))
        return {"ok": True, "job": self.lab_jobs.update(job["id"], findings=cards)}

    def _act_shannon_report(self, args: dict[str, Any]) -> None:
        job = self.lab_jobs.get(str(args.get("id") or ""))
        if job is None or job.get("kind") not in ("shannon", "shannon_simulate"):
            raise ValueError("That report isn't there any more.")
        self._open_file(str(job.get("report") or ""))

    def _act_shannon_simulate(self, args: dict[str, Any]) -> dict[str, Any]:
        """Simulate attack: Shannon's stages + AiSOC triage on the owner's own app, file or local address.
        Synchronous and fast (nothing really runs); a bad target is refused at once, like shannon_start."""
        return self.shannon.simulate_attack(args.get("kind"), args.get("target"))

    def _act_shannon_pick(self, args: dict[str, Any]) -> dict[str, Any]:
        """Opens the native file window so the owner clicks the project folder (app) or file to simulate on."""
        from tkinter import filedialog
        projects = self.shannon.projects_folder
        start = projects if projects.is_dir() else Path.home()
        if str(args.get("kind") or "file") == "app":
            path = filedialog.askdirectory(title="Pick a project folder to simulate on", initialdir=str(start))
        else:
            path = filedialog.askopenfilename(title="Pick a file to simulate on", initialdir=str(Path.home()),
                                              filetypes=[("All files", "*.*")])
        return {"ok": True, "picked": bool(path), "path": path or ""}

    def _act_shannon_simulate_report(self, args: dict[str, Any]) -> None:
        self._open_file(str(self._lab_job(args, "shannon_simulate").get("report") or ""))

    def _act_galaxy_data(self, _args: dict[str, Any]) -> None:
        vault_folder = self._vault_folder()
        facts = self.memory.list_facts(limit=40)
        graph = knowledge_galaxy.build_graph(vault_folder=vault_folder, facts=facts)
        self.ui.emit({"type": "galaxy_data", "graph": graph})

    def _open_galaxy(self) -> str:
        self.events.put(("galaxy_open", ()))
        return "The Knowledge Galaxy is on the user's screen. Say one short sentence about it."

    def _act_node_path(self, args: dict[str, Any]) -> dict[str, Any] | None:
        """The owner points Nova at node.exe (or its folder), for a Node.js that isn't installed the usual way."""
        text = str(args.get("path") or "").strip()
        if text and node_runtime.chosen(text) is None:
            return {"ok": False, "error": "That isn't node.exe or a folder with node.exe in it."}
        self._save_setting("node_path", text)
        self._update(settings={"node_path": text})
        node = node_runtime.find(text)
        found = node_runtime.version(node) if node is not None else None
        self._update(discover=self._discover_state(), downloads=self._downloads_state())
        if found is None:
            return {"ok": False, "error": "Nova still can't find Node.js."}
        node_runtime.use(node)
        self._toast(f"Node.js {'.'.join(map(str, found))} found: {node}", "ok")
        return None

    def _act_reverse_toggle(self, args: dict[str, Any]) -> dict[str, Any] | None:
        on = bool(args.get("on"))
        if on and not self.settings.get("reverse_consented") and not args.get("consented"):
            return {"need_consent": "reverse"}
        if on:
            self._save_setting("reverse_consented", True)
        self._save_setting("reverse_on", on)
        self.agent.reverse = self.reverse.start if on else None
        self._update(discover=self._discover_state())
        problem = self.reverse.problem() if on else ""
        if problem:
            self._toast(f"Reverse engineering is on, but {problem}.", "warn")
        return None

    # ---------- updates from GitHub Releases ----------

    def _update_state(self, **changes: Any) -> None:
        self._update(update={"auto": self.settings.get("auto_update", True) is not False,
                             "can_install": self.updates.can_install(), **changes})

    def _update_tick(self) -> None:
        if self.closing:
            return
        if self.settings.get("auto_update", True) is not False and not USB:
            threading.Thread(target=self._check_for_update, name="NovaUpdate", daemon=True).start()
        self.root.after(self_update.CHECK_EVERY_HOURS * 3600 * 1000, self._update_tick)

    def _check_for_update(self, by_hand: bool = False) -> None:
        """Asks GitHub; a newer Nova is downloaded and verified in the background, then the owner is asked to restart."""
        self._update_state(busy=True, status="Checking GitHub…")
        try:
            release = self.updates.newest()
            if release is None:
                self._update_state(busy=False, status=f"Nova {VERSION} is the newest." if by_hand else "", available="")
                return
            self._update_state(available=release.version, page=release.page)
            if not self.updates.can_install():
                self._update_state(busy=False, status=f"Nova {release.version} is out. This copy came from a zip: get "
                                   "Nova-Setup.exe from the release page once, and later updates install themselves.")
                return
            installer = self.updates.download(
                release, lambda percent: self._update_state(status=f"Downloading Nova {release.version}… {percent}%"))
            self.update_ready = installer
            self._update_state(busy=False, ready=True, status=f"Nova {release.version} is ready: restart to update.")
            self._toast(f"Nova {release.version} is ready. Restart to update?", "info",
                        {"label": "Restart now", "name": "update_install", "args": {}})
        except self_update.UpdateError as exc:
            self._update_state(busy=False, status=f"Update: {exc}." if by_hand else "")

    def _act_update_check(self, _args: dict[str, Any]) -> None:
        if not USB:
            threading.Thread(target=self._check_for_update, args=(True,), name="NovaUpdate", daemon=True).start()

    def _act_update_auto(self, args: dict[str, Any]) -> None:
        self._save_setting("auto_update", bool(args.get("on")))
        self._update_state()

    def _act_update_install(self, _args: dict[str, Any]) -> dict[str, Any] | None:
        """Runs the verified installer silently; it closes Nova, replaces it and starts the new one."""
        if self.update_ready is None:
            return {"ok": False, "error": "No update is downloaded yet. Click Check for updates."}
        try:
            self.updates.install(self.update_ready)
        except self_update.UpdateError as exc:
            return {"ok": False, "error": str(exc)}
        self._toast("Updating: Nova closes and comes back in about a minute.", "info")
        self.root.after(1500, self._close)
        return None

    def _act_update_now(self, _args: dict[str, Any]) -> None:
        """One click: check → download → install. Runs on a worker thread like the other update actions."""
        def work() -> None:
            self._update_state(busy=True, status="Checking GitHub…")
            try:
                release = self.updates.newest()
                if release is None:
                    self._update_state(busy=False, status=f"Nova {VERSION} is the newest.")
                    return
                if not self.updates.can_install():
                    self._update_state(busy=False, status=f"Nova {release.version} is out but updates need Nova-Setup.exe.")
                    return
                self._update_state(available=release.version, page=release.page)
                installer = self.updates.download(
                    release, lambda percent: self._update_state(status=f"Downloading Nova {release.version}… {percent}%"))
                self.update_ready = installer
                self._update_state(busy=False, ready=True, status=f"Installing Nova {release.version}…")
                self.updates.install(installer)
                self._toast("Updating: Nova closes and comes back in about a minute.", "info")
                self.root.after(1500, self._close)
            except self_update.UpdateError as exc:
                self._update_state(busy=False, status=f"Update: {exc}.")
        threading.Thread(target=work, name="NovaUpdateNow", daemon=True).start()

    def _act_update_rollback(self, _args: dict[str, Any]) -> None:
        """Gets the release before this one (downloaded and verified the same way), for when an update misbehaves."""
        def work() -> None:
            self._update_state(busy=True, status="Finding the previous version…")
            try:
                release = self.updates.previous()
                if release is None:
                    self._update_state(busy=False, status="There's no earlier version with an installer.")
                    return
                installer = self.updates.download(
                    release, lambda percent: self._update_state(status=f"Downloading Nova {release.version}… {percent}%"))
                self.update_ready = installer
                self._update_state(busy=False, ready=True, available=release.version,
                                   status=f"Nova {release.version} (the previous version) is ready: restart to install it.")
            except self_update.UpdateError as exc:
                self._update_state(busy=False, status=f"Update: {exc}.")
        threading.Thread(target=work, name="NovaRollback", daemon=True).start()

    # ---------- Telegram: Nova from anywhere, through the owner's own private bot ----------

    def _ask_from_telegram(self, text: str, confirm: Callable[[str], bool], send_file: Callable[[str], str]) -> str:
        """One turn asked from Telegram: the same Nova, with the screen when Screen assist is on (autopilot works from the
        phone), questions asked in the chat, and files sent back to it."""
        def approve(name: str, arguments: dict[str, Any]) -> bool:
            summary = str(arguments.get("summary") or arguments.get("speak") or arguments.get("task") or name)
            risky = risky_step(name, summary) if name in SCREEN_STEP_TOOLS and self.settings.get("ask_risky") else ""
            if self.agent.autopilot and name in NEVER_ASK and not risky:
                return not self.turn_cancel.is_set()
            return confirm(f"{risky}: {summary}" if risky else summary)
        with self.agent_lock:
            self.events.put(("phone_chat", ("YOU · TELEGRAM", text, "user")))
            self.turn_cancel.clear()
            screen = None
            if self.assist is not None:
                from screen_assist import ScreenSession
                screen = ScreenSession(self.assist, lambda: self.target_hwnd, self.turn_cancel, self._set_acting)
            self.agent.send_file = send_file
            try:
                reply = self.agent.ask(text, approve_tool=approve, screen=screen, cancel=self.turn_cancel)
            finally:
                self.agent.send_file = None
            self.events.put(("phone_chat", ("NOVA → TELEGRAM", reply, "assistant")))
            return reply

    def _relay_check_in(self) -> dict[str, Any]:
        """What the cloud relay needs to stand in while the PC is off: name, what Nova remembers, reminders ahead."""
        offset = datetime.now().astimezone().utcoffset()
        return {"name": self.agent.owner_name, "facts": [item["fact"] for item in self.agent.memory.list_facts()],
                "reminders": self.reminders.upcoming(), "offset": int(offset.total_seconds() // 60) if offset else 0}

    def _relay_report(self, result: dict[str, Any]) -> None:
        """Back on: what was said on Telegram while the PC was off joins the conversation, and reminders the relay
        already sent aren't said again."""
        self.relay_delivered.update(str(key) for key in result.get("delivered") or [])
        away = [item for item in result.get("away") or [] if isinstance(item, dict)]
        for item in away:
            self.agent.memory.save_message({"role": "user", "content": str(item.get("text", ""))[:4000]})
            self.agent.memory.save_message({"role": "assistant", "content": str(item.get("reply", ""))[:4000],
                                            "brain": "telegram-relay"})
            self.events.put(("phone_chat", ("YOU · TELEGRAM (PC OFF)", str(item.get("text", "")), "user")))
            self.events.put(("phone_chat", ("NOVA (CLOUD) → TELEGRAM", str(item.get("reply", "")), "assistant")))
        if away:
            self._toast(f"While the PC was off, you sent Nova {len(away)} message{'s' if len(away) != 1 else ''} on Telegram.", "info")

    def _act_telegram_relay(self, args: dict[str, Any]) -> dict[str, Any] | None:
        """Puts the relay for while the PC is off on the owner's Cloudflare account (or takes it off)."""
        token = telegram_remote.stored_token()
        if token is None:
            return {"ok": False, "error": "Save your bot token first."}
        if not args.get("consented") and not self.settings.get("telegram_relay_consented"):
            return {"need_consent": "telegram_relay"}
        self._save_setting("telegram_relay_consented", True)
        cloudflare = str(args.get("cloudflare_token", ""))
        brain = str(args.get("brain", "none"))
        key = str(args.get("brain_key") or "") or ((claude_expert.key() or "") if brain == "claude" else "")
        removing = bool(args.get("remove"))
        self._update(telegram={"relay_busy": True})

        def work() -> None:
            try:
                if removing:
                    cloud_relay.remove(cloudflare)
                    cloud_relay.forget()
                    self._toast("The relay is off your Cloudflare account. With the PC off, Telegram now waits.", "ok")
                else:
                    cloud_relay.save(cloud_relay.deploy(cloudflare, token, brain, key))
                    self._toast("Relay set up: Nova answers on Telegram even with the PC off.", "ok")
                    if self.telegram.running:
                        threading.Thread(target=self.telegram._check_in, daemon=True).start()
            except cloud_relay.RelayError as exc:
                self._toast(f"Relay: {exc}", "error")
            finally:
                self._update(telegram={**self._telegram_state(), "relay_busy": False})
        threading.Thread(target=work, name="NovaRelayDeploy", daemon=True).start()
        return None

    def _telegram_state(self, status: str | None = None) -> dict[str, Any]:
        owner = self.telegram.owner
        state: dict[str, Any] = {"on": bool(self.settings.get("telegram_on")), "token": telegram_remote.stored_token() is not None,
                                 "owner": (owner or {}).get("name") or ("you" if owner else ""), "bot": self.telegram.name,
                                 "code": "" if owner or not self.telegram.running else self.telegram.pairing_code(), "usb": USB,
                                 "relay": (cloud_relay.load() or cloud_relay.Relay("", "", "")).brain,
                                 "claude_key": claude_expert.key() is not None}
        if status is not None:
            state["status"] = status
        return state

    def _apply_telegram(self) -> None:
        token = telegram_remote.stored_token()
        if self.settings.get("telegram_on") and token and not USB:
            self.telegram.start(token)
        else:
            self.telegram.stop()
        self._update(telegram=self._telegram_state("" if not self.telegram.running else "Connecting…"))

    def _act_telegram(self, args: dict[str, Any]) -> dict[str, Any] | None:
        if USB:
            return {"ok": False, "error": "The USB Edition stays fully offline."}
        if args.get("on") and not self.settings.get("telegram_consented") and not args.get("consented"):
            return {"need_consent": "telegram"}
        if args.get("on"):
            self._save_setting("telegram_consented", True)
        self._save_setting("telegram_on", bool(args.get("on")))
        self._apply_telegram()
        return None

    def _act_telegram_token(self, args: dict[str, Any]) -> dict[str, Any] | None:
        try:
            telegram_remote.save_token(str(args.get("token", "")))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        self._save_setting("telegram", {})  # a new bot starts unpaired
        self._apply_telegram()
        self._toast("Bot token saved on this PC. Now send the pairing code to your bot in Telegram.", "ok")
        return None

    def _act_telegram_token_forget(self, _args: dict[str, Any]) -> None:
        telegram_remote.forget_token()
        self._save_setting("telegram", {})
        self._apply_telegram()

    def _act_telegram_unpair(self, _args: dict[str, Any]) -> None:
        self.telegram.forget_owner()
        self._update(telegram=self._telegram_state())

    def _phone_control(self, action: str) -> str:
        if action in ("volume_up", "volume_down"):
            media_keys.press(action, times=3)
        elif action in media_keys.ACTIONS:
            media_keys.press(action)
        elif action == "creative":
            self.creative.open_window()
            return "Creative mode is opening on your PC."
        elif action == "stop":
            self.turn_cancel.set()
            self.voice.stop_speaking()
            return "Stopped."
        else:
            return "Unknown button."
        return ""

    # ---------- camera ----------

    def _open_creative_in_app(self, url: str) -> bool:
        """Creative mode always runs inside Nova's own window, whose browser profile already allows the camera."""
        if not self.ui.clients:
            if self.ui.ever_connected.is_set() or self.window_process is not None:
                self.events.put(("open_window", "open=creative"))
                return True
            return False
        self.ui.emit({"type": "creative", "url": url})
        app_window.restore(self.window_hwnd)  # e.g. a ✌ gesture while Nova was minimized
        return True

    def _warm_vision(self) -> None:
        """Creative mode is opening: load the vision model now, so the first 'what is this' doesn't wait for it."""
        model = self.state["model"].get("vision")
        if model:
            threading.Thread(target=lambda: _quietly(lambda: vision.warm_up(self.agent.base_url, model)),
                             name="AlfredVisionWarmUp", daemon=True).start()

    def _hand_camera_to_creative(self) -> None:
        """Creative mode needs the webcam: the gesture reader lets go until creative mode closes."""
        if self.gestures.running:
            self.gestures.pause(True)
            self.creative_has_camera_since = time.monotonic()
            self.events.put(("creative_opened", None))

    def _watch_creative(self) -> None:
        if self.closing or self.creative_has_camera_since is None:
            return
        # The page asks for commands every 0.6 s; silence after the start-up grace means it was closed.
        if time.monotonic() - self.creative_has_camera_since > 20 and not self.creative.active:
            self.creative_has_camera_since = None
            self.gestures.pause(False)
            return
        self.root.after(2000, self._watch_creative)

    def _run_gesture(self, action: str) -> None:
        if action.startswith("custom:"):
            self._run_own_gesture(action.split(":", 1)[1])
            return
        if self.gesture_screen in ("rea", "shannon") and self.ui.clients and action in REA_GESTURES:
            now, (last, when) = time.monotonic(), self.library_gesture
            self.library_gesture = (action, now)
            if action != last or now - when > 0.6:  # a held 👍/👎 repeats every 0.2 s: it acts once
                self.ui.emit({"type": f"{self.gesture_screen}_command", "command": REA_GESTURES[action]})
            return
        if self.library_open and self.ui.clients and action in LIBRARY_GESTURES:
            now, (last, when) = time.monotonic(), self.library_gesture
            self.library_gesture = (action, now)
            if action != last or now - when > 0.6:  # a held 👍/👎 repeats every 0.2 s: it acts once
                self.ui.emit({"type": "library_command", "command": LIBRARY_GESTURES[action], "by": "gesture"})
            return
        if action == "creative":
            self.creative.open_window()
        else:
            media_keys.press(action, times=3 if action in ("volume_up", "volume_down") else 1)
        self._toast(GESTURE_NAMES.get(action, action), "info")

    # ---------- the owner's own gestures: a recorded hand pose, or ☝ / 🤟, doing an action they chose ----------

    def _custom_gestures(self) -> list[dict[str, Any]]:
        return [item for item in self.settings.get("custom_gestures", []) if isinstance(item, dict) and item.get("id")]

    def _gestures_state(self) -> dict[str, Any]:
        return {"custom": [{"id": item["id"], "name": item["name"], "action": item["action"], "phrase": item.get("phrase", ""),
                            "pose": item.get("pose", ""), "samples": len(item.get("samples") or [])}
                           for item in self._custom_gestures()],
                "actions": GESTURE_ACTIONS, "recording": bool(getattr(self, "gesture_recording", False))}

    def _save_custom_gestures(self, items: list[dict[str, Any]]) -> None:
        self._save_setting("custom_gestures", items)
        self.gestures.custom = items
        self._update(gestures=self._gestures_state())

    def _act_gesture_add(self, args: dict[str, Any]) -> dict[str, Any] | None:
        name = " ".join(str(args.get("name", "")).split())[:30]
        action, pose = str(args.get("action", "")), str(args.get("pose", "record"))
        phrase = " ".join(str(args.get("phrase", "")).split())[:200]
        items = self._custom_gestures()
        if not name:
            return {"ok": False, "error": "Give the gesture a name."}
        if action not in GESTURE_ACTIONS or pose not in ("record", *BUILT_IN_POSES):
            return {"ok": False, "error": "Choose what the gesture does."}
        if action == "ask" and not phrase:
            return {"ok": False, "error": "Write what Nova should be asked, e.g. what's the weather today?"}
        if any(item["name"].casefold() == name.casefold() for item in items):
            return {"ok": False, "error": f"You already have a gesture called {name}."}
        taken = next((item["name"] for item in items if pose != "record" and item.get("pose") == pose), "")
        if taken:
            return {"ok": False, "error": f"{POSE_NAMES[pose]} already does “{taken}”: delete that one first."}
        if self.gesture_recording:
            return {"ok": False, "error": "Nova is already recording a gesture."}
        just_started = not self.gestures.running
        if just_started:
            needed = self._act_gestures({"on": True, "consented": args.get("consented")})
            if needed:
                return needed  # the page asks for the webcam first, then sends this again
        spec = {"id": uuid.uuid4().hex[:8], "name": name, "action": action, "phrase": phrase if action == "ask" else ""}
        if pose != "record":
            self._save_custom_gestures(items + [{**spec, "pose": pose}])
            self._toast(f"Saved: {POSE_NAMES[pose]} → {GESTURE_ACTIONS[action]}.", "ok")
            return None
        seconds = 4.5 if just_started else 3.2  # a webcam that is just starting needs a moment
        self.gesture_recording = True
        self._update(gestures={"recording": True})
        self.gestures.record(seconds, lambda samples: self.events.put(("gesture_recorded", (spec, samples))))
        self.root.after(int((seconds + 4) * 1000), lambda: self._gesture_recorded(spec, None))  # the webcam never answered
        return None

    def _gesture_recorded(self, spec: dict[str, Any], samples: list[list[float]] | None) -> None:
        if not self.gesture_recording:
            return  # already done (the time-out after a finished recording)
        self.gesture_recording = False
        if samples is None:
            self.gestures._recording = None
            self._toast("The webcam didn't send pictures in time. Check that Gestures is on and the webcam works, then try again.", "warn")
        elif len(samples) < 6:
            self._toast("Nova couldn't see your hand clearly. Hold the pose inside the webcam's view, in good light, and try again.", "warn")
        else:
            self._save_custom_gestures(self._custom_gestures() + [{**spec, "samples": samples}])
            self._toast(f"Saved “{spec['name']}” → {GESTURE_ACTIONS[spec['action']]}. Hold the pose half a second to use it.", "ok")
            return
        self._update(gestures=self._gestures_state())

    def _act_gesture_delete(self, args: dict[str, Any]) -> None:
        self._save_custom_gestures([item for item in self._custom_gestures() if item["id"] != str(args.get("id", ""))])

    def _run_own_gesture(self, gesture_id: str) -> None:
        spec = next((item for item in self._custom_gestures() if item["id"] == gesture_id), None)
        if spec is None:
            return
        action = spec["action"]
        if action in media_keys.ACTIONS:
            media_keys.press(action, times=3 if action.startswith("volume") else 1)
        elif action == "creative":
            self.creative.open_window()
        elif action == "library":
            if self.library_open and self.ui.clients:
                self.ui.emit({"type": "library_command", "command": "close", "by": "gesture"})
            else:
                self._open_library()
        elif action == "stop":
            self._act_stop({})
        elif action == "ask":
            result = self._act_send({"text": spec["phrase"]})
            if result and result.get("error"):
                self._toast(result["error"], "warn")
                return
        self._toast(f"{spec['name']} → {GESTURE_ACTIONS[action]}", "info")

    # ---------- screen assist ----------

    def _poll_keys(self) -> None:
        """Track the user's app and read hold-to-talk / Esc by polling: no keyboard hook, keys are never swallowed."""
        if self.closing or (self.assist is None and IS_WINDOWS):
            return  # on the Mac (no screen assist yet) the hotkeys run on their own
        if IS_WINDOWS:
            user32 = ctypes.windll.user32
            foreground = user32.GetForegroundWindow()
            if foreground and foreground != self.window_hwnd:
                owner = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(foreground, ctypes.byref(owner))
                if owner.value != os.getpid():
                    self.target_hwnd = foreground
        held = hotkeys.held
        talking = all(held(key) for key in self._hotkey("talk"))
        waiting = self.pending_approval is not None  # Nova asked something: hold to answer it out loud
        if talking and self.hold_release is None and (not self.state["busy"] or waiting) and not self.state["switches"]["mic"]:
            self.hold_release = threading.Event()
            self.voice.stop_speaking()
            self.voice.push_to_talk(
                on_start=lambda: self.events.put(("voice_state", (f"RECORDING · RELEASE {hotkeys.label(self._hotkey('talk')).upper()} TO SEND", "record"))),
                on_result=lambda text: self.events.put(("voice_command", text)),
                on_error=lambda error: self.events.put(("voice_error", error)),
                on_notice=lambda notice: self.events.put(("voice_notice", notice)),
                hold=self.hold_release,
            )
        elif not talking and self.hold_release is not None:
            self.hold_release.set()
            self.hold_release = None
        dictating = all(held(key) for key in self._hotkey("dictate"))
        if dictating and self.dictate_release is None and not talking and not self.state["switches"]["mic"]:
            self.dictate_release = threading.Event()
            self.voice.stop_speaking()
            self.voice.push_to_talk(
                on_start=lambda: self.events.put(("voice_state", ("DICTATING · RELEASE TO TYPE IT", "record"))),
                on_result=lambda text: self.events.put(("dictated", text)),
                on_error=lambda error: self.events.put(("voice_error", error)),
                hold=self.dictate_release)
        elif not dictating and self.dictate_release is not None:
            self.dictate_release.set()
            self.dictate_release = None
        escape = all(held(key) for key in self._hotkey("stop"))
        if escape and not self.escape_down and not self.escape_is_novas:
            self._act_stop({})  # also while Nova moves the mouse or types: the banner promises Esc stops it
        self.escape_down = escape
        def newly_pressed(which: str) -> bool:
            down = all(held(key) for key in self._hotkey(which))
            fresh = down and which not in self.keys_down
            (self.keys_down.add if down else self.keys_down.discard)(which)
            return fresh
        if newly_pressed("clip"):
            self._keep_highlight()
        if newly_pressed("yes") and self.pending_approval is not None:
            self._answer(True)
        if newly_pressed("no") and self.pending_approval is not None:
            self._answer(False)
        self.root.after(40, self._poll_keys)

    def _type_dictation(self, text: str) -> None:
        """What was said while the dictate key was held, typed into the app in front (after the keys are let go)."""
        text = " ".join(text.split())
        self._set_voice_state("READY", "idle")
        if not text:
            self._toast("Nothing heard to type.", "warn")
            return

        def work() -> None:
            self._wait_for_keys_up([*self._hotkey("dictate"), *MODIFIER_KEYS])
            try:
                if sys.platform == "darwin":
                    import mac
                    mac.type_text(text + " ")
                else:
                    import deck_keyboard
                    deck_keyboard.type_text(text + " ")
            except Exception as exc:
                self.events.put(("toast", (f"Couldn't type it: {exc}", "warn")))
        threading.Thread(target=work, name="NovaDictate", daemon=True).start()

    def _keep_highlight(self) -> None:
        """The keep hotkey: copy what is highlighted in the app in front and keep it in the second brain."""
        def work() -> None:
            # The owner's fingers must be off the keys first, or Ctrl+C would arrive as, say, Ctrl+Alt+Shift+C.
            self._wait_for_keys_up([*self._hotkey("clip"), *MODIFIER_KEYS])
            try:
                text = selection.grab_windows_selection()
                if not text:
                    self.events.put(("toast", ("Nothing was highlighted: select some text with the mouse, then press the keep key.", "warn")))
                    return
                self.events.put(("toast", (f"Second brain: {self.brain.keep_selection(text)}", "ok")))
            except Exception as exc:
                self.events.put(("toast", (f"Couldn't keep the highlight: {exc}", "warn")))
        threading.Thread(target=work, name="NovaKeepHighlight", daemon=True).start()

    @staticmethod
    def _wait_for_keys_up(keys: list[int], seconds: float = 2.0) -> None:
        held = lambda: any(hotkeys.held(key) for key in keys)  # noqa: E731
        deadline = time.monotonic() + seconds
        while held() and time.monotonic() < deadline:
            time.sleep(0.05)

    def _stop_walkthrough(self) -> None:
        if self.walkthrough is not None:
            self.walkthrough.stop()
            self.walkthrough = None
            self._update(walkthrough=None)

    def _on_walkthrough(self, walkthrough: Walkthrough, index: int, status: str, pointed: str) -> None:
        if walkthrough is not self.walkthrough:
            return  # an old walkthrough finishing after a new one started
        steps = walkthrough.steps
        if status == "step":
            self._update(walkthrough={"steps": steps, "index": index, "done": False, "pointed": pointed})
            if index > 0:  # the reply already said the first step
                self.voice.say(f"Step {index + 1}. {speakable_step(steps[index])}")
        elif status == "done":
            self._update(walkthrough={"steps": steps, "index": index, "done": True, "pointed": ""})
            self.voice.say("All done. Nice work.")
            self.root.after(6000, lambda: self._stop_walkthrough() if self.walkthrough is walkthrough else None)
        else:
            self._stop_walkthrough()
            self._toast("Walkthrough paused: the screen didn't change for a while." if status == "paused"
                        else f"Walkthrough stopped: {pointed}", "warn")

    def _clear_overlays(self) -> None:
        assist = self.assist
        if assist is not None:
            from screen_assist import AssistError
            try:
                assist.request({"cmd": "clear"})
            except AssistError:
                pass

    def _set_acting(self, acting: bool, presses_escape: bool = False) -> None:
        """Called from the agent's thread right before (and after) Nova moves the mouse or types. The mini orb
        flares and a banner says not to touch the mouse, and the first step waits a moment so you see it first."""
        self.escape_is_novas = acting and presses_escape
        if acting:
            first = not self.takeover_warned
            self.takeover_warned = True
            self.takeover_until = float("inf")
            self._update(acting=True)
            time.sleep(0.9 if first else 0.35)
        else:
            self.takeover_until = time.monotonic() + 1.5  # stays up between quick steps instead of flickering
            self._update(acting=False)

    # ---------- idea maps ----------

    def _apply_spoken_visual_command(self, text: str) -> bool:
        """'Visualize my idea: …', 'add … to the map', 'remove … from the map', 'rename the map to …'."""
        command = parse_spoken_visual_command(text)
        if not command:
            return False
        notes = {**clean_extras(self.state["notes"]), **apply_command(self.state["notes"], command)}
        try:
            save_map(notes["title"], notes["outline"], notes)
        except (OSError, ValueError) as exc:
            self._toast(f"The map changed but could not be saved: {exc}", "warn")
        self._update(notes=self._notes_state(notes))
        self.ui.emit({"type": "open_pane", "pane": "notes"})
        return True

    # ---------- main-thread event loop ----------

    def _poll_events(self) -> None:
        if self.closing:
            return
        try:
            while True:
                event_type, payload = self.events.get_nowait()
                self._handle_event(event_type, payload)
        except queue.Empty:
            pass
        self.root.after(50, self._poll_events)

    def _handle_event(self, event_type: str, payload: Any) -> None:
        if event_type == "ui_action":
            name, args, reply = payload
            reply.put(self._run_action(name, args))
        elif event_type == "approval_open":
            self._update(approval=payload)
            if not self.ui.clients:
                self._open_window()
            # The user is usually in another app: show the question above it without taking the keyboard.
            app_window.keep_on_top(self.window_hwnd, True)
        elif event_type == "approval_closed":
            if (self.state["approval"] or {}).get("id") == payload:
                self._update(approval=None)
                app_window.keep_on_top(self.window_hwnd, False)
        elif event_type == "chat_done":
            reply, streamed, latency = payload
            self.live_reply = ""
            self._append_chat("NOVA", reply, "assistant")
            self._finish_skill(reply)
            self._update(busy=False, latency_ms=latency, reminders=self._reminders_state())
            self._log_timing(latency)
            self._refresh_tasks()
            self._set_idle_voice()
            threading.Thread(target=self._status_worker, daemon=True).start()
            if self.state["switches"]["speak"] and not streamed:
                self._speak(reply)  # e.g. "Stopped." or an error text: nothing was spoken while streaming
            if (piper_voice.is_vietnamese(reply) and not piper_voice.installed(piper_voice.VIETNAMESE)
                    and not self.settings.get("vietnamese_voice_offered")):
                self._save_setting("vietnamese_voice_offered", True)
                self._toast("Nova answered in Vietnamese, which her English voices can't pronounce. A Vietnamese voice "
                            "(about 65 MB, runs on this PC) reads Vietnamese sentences properly.", "info",
                            {"label": "Download Vietnamese voice", "name": "install_vietnamese_voice", "args": {}})
        elif event_type == "speaking":
            self._update(speaking=payload)
        elif event_type in ("map_ideas", "map_add"):
            self._add_to_map(*payload)
        elif event_type == "map_ideas_failed":
            self._update(notes={"expanding": None})
            self._toast(payload, "error")
        elif event_type == "mind_map":
            topic, ideas = payload
            try:
                save_map(topic, ideas)
            except (OSError, ValueError) as exc:
                self._toast(f"The map is shown but could not be saved: {exc}", "warn")
            self._update(notes=self._notes_state({"title": topic, "outline": ideas}))
            if not self.ui.clients:
                self._open_window()
            self.ui.emit({"type": "open_pane", "pane": "notes"})
        elif event_type == "galaxy_open":
            if not self.ui.clients:
                self._open_window()
            self._act_galaxy_data({})
        elif event_type == "open_window":
            self._open_window(payload)
        elif event_type == "quit":
            self._close()
        elif event_type == "walkthrough_start":
            steps, hwnd = payload
            self._stop_walkthrough()
            if self.assist is not None:
                walkthrough = Walkthrough(self.assist, hwnd, steps, on_update=lambda index, status, pointed: self.events.put(
                    ("walkthrough_step", (walkthrough, index, status, pointed))))
                self.walkthrough = walkthrough
                self._update(walkthrough={"steps": steps, "index": 0, "done": False, "pointed": ""})
                walkthrough.start()
        elif event_type == "walkthrough_step":
            self._on_walkthrough(*payload)
        elif event_type == "heart":
            if self.state["heart"]["on"]:
                self._update(heart={"status": f"Connected to {payload.get('device', 'band')}", **payload})
        elif event_type == "heart_status":
            if self.state["heart"]["on"]:
                self._update(heart={"status": payload})
        elif event_type == "timer_done":
            spoken = f"Your {payload['label']} timer is done." if payload["label"] else "Your timer is done."
            self._toast(f"⏰ {spoken}", "ok") if self.ui.clients else self._notify(f"⏰ {spoken}")
            threading.Thread(target=_ring_bell, daemon=True).start()
            self.voice.say(spoken)
        elif event_type == "chat_error":
            self._finish_skill(None)
            self._append_chat("ERROR", payload, "system")
            self._set_busy(False)
            self._set_voice_state("SOMETHING WENT WRONG · SEE HISTORY", "error")
        elif event_type == "spoke":
            self._update(speaking=False)
        elif event_type == "voice_state":
            text, tone = payload
            self._set_voice_state(text, tone)
        elif event_type == "wake_detected":
            if not self.ui.clients:
                self._open_window()  # the window was closed: "Nova" brings it back
            self.voice.stop_speaking()
            self._update(speaking=False)
            self.listening = True
            self._set_voice_state("LISTENING · SPEAK NOW", "listen")
            threading.Thread(target=self.agent.warm_up, daemon=True).start()  # load the model while you talk
        elif event_type == "barge_in":
            # You cut Nova off: the answer she was giving stops, and she listens.
            self.turn_cancel.set()
            self.voice.stop_speaking()
            self.listening = True
            self._update(speaking=False)
            self._set_voice_state("LISTENING · GO AHEAD", "listen")
        elif event_type == "voice_sleep":
            self.listening = False
            if not self.state["busy"]:
                self._set_idle_voice()
        elif event_type == "voice_command":
            self.listening = True  # each request keeps the window open for a follow-up
            text = payload.strip()
            if not text:
                self._set_voice_state("NO SPEECH RECOGNIZED · TRY AGAIN", "warn")
                return
            if self._answer_out_loud(text):
                return
            if self._apply_spoken_visual_command(text):
                self._append_chat("SYSTEM", "Visual note updated from your voice.", "system")
            self._set_idle_voice()
            result = self._act_send({"text": text})
            if result and result.get("error"):
                self._toast(result["error"], "warn")
        elif event_type == "build_done":
            name, folder, ok, said = payload
            if ok:
                start = Path(folder) / "index.html"
                self._append_chat("NOVA", f"“{name}” is built in {folder}.\n\n{said[-600:]}", "assistant")
                self.voice.say(f"{name.replace('-', ' ')} is ready. I'm opening it.")
                app_window.open_path(start if start.exists() else folder)
            else:
                self._append_chat("ERROR", f"Claude Code couldn't build “{name}”: {said}", "system")
            self._update(skills=self._skills_state())
        elif event_type == "lab_done":
            if payload.get("status") == "done":
                found = payload.get("counts") or {}
                worst = ", ".join(f"{number} {severity}" for severity, number in found.items() if number) or "no proven holes"
                self._append_chat("NOVA", f"Shannon finished checking {payload.get('title')}: {worst}. "
                                          f"Report: {payload.get('report')}", "assistant")
                self.voice.say(f"Shannon finished checking {payload.get('title')}: {worst}.")
            else:
                self._append_chat("ERROR", f"Shannon stopped on {payload.get('title')}: {payload.get('error')}", "system")
        elif event_type == "deep_work_done":
            title, result, ok = payload
            if ok:
                self._append_chat("NOVA", f"“{title}” is ready: {result} in your vault.", "assistant")
                self.voice.say(f"{title} is ready. It's in your outputs folder.")
            else:
                self._append_chat("ERROR", f"Claude Code couldn't finish “{title}”: {result}", "system")
            if ok and title in self.discover_studies:
                self._offer_skill(title, result)
            self._update(skills=self._skills_state(), discover=self._discover_state())
        elif event_type == "voice_notice":
            self._append_chat("AUDIO DEVICE", payload, "system")
            self._set_voice_state("AUDIO DEVICE FALLBACK · CHECK SETTINGS", "warn")
        elif event_type == "voice_error":
            self._update(speaking=False, switches={"mic": False})
            self._set_voice_state("VOICE ERROR · MIC OFF", "error")
            self._toast(payload, "error")
        elif event_type == "gesture":
            self._run_gesture(payload)
        elif event_type == "gesture_recorded":
            self._gesture_recorded(*payload)
        elif event_type == "music":
            self._update(music=self._music_state())
        elif event_type == "tv_request":
            self._toast(f"A TV wants to show Nova. Allow it only if the TV shows the code {payload}.", "info",
                        {"label": f"Allow {payload}", "name": "tv_allow", "args": {"code": payload}})
        elif event_type == "brain_changed":
            self._update(second_brain=self._brain_summary())
        elif event_type == "free_cloud":
            self._update(free_cloud={"status": payload})
        elif event_type == "compare":
            self._update(compare=payload)
        elif event_type == "news_progress":
            self._update(news={"status": payload})
        elif event_type == "news_done":
            self.news_running = False
            self._update(news=self._news_state(payload))
        elif event_type == "downloads":
            self._update(downloads=self._downloads_state())
        elif event_type == "brain":
            self._update(brain={"label": payload[0], "why": payload[1]})
            self._log_answer(*payload)
        elif event_type == "pcs":
            changed, error = payload
            if changed:
                self._refresh_tasks()
            self._update(pcs=self._pcs_state(error))
        elif event_type == "photo_saved":
            self._toast(f"Photo saved: {payload.name} (Pictures\\Nova; average.jpg holds all of them).", "ok",
                        {"label": "Open folder", "name": "open_photos", "args": {}})
        elif event_type == "creative_control":
            if payload == "exit":
                self.ui.emit({"type": "close_creative"})  # inside Nova's window
                app_window.close_window(app_window.find_window("Nova · Creative Mode"))  # its own Edge window
            else:
                self._run_gesture(payload)
        elif event_type == "creative_opened":
            self._watch_creative()
        elif event_type == "warning":
            self._toast(payload, "warn")
        elif event_type == "phone_chat":
            self._append_chat(*payload)
        elif event_type == "gmail":
            self._update(switches={"gmail": payload, "calendar": self.agent.calendar is not None,
                                   "drive": self.agent.drive is not None})
            self._google_mcp_apply()
            self._set_voice_state("GMAIL CONNECTED" if payload else "GMAIL NOT CONNECTED", "ok" if payload else "warn")
        elif event_type in ("screen_done", "screen_error"):
            app_window.restore(self.window_hwnd)
            if event_type == "screen_error":
                self._set_voice_state("SCREEN READ FAILED · NOTHING SAVED", "error")
                self._toast(payload, "warn")
                return
            display, result = payload
            self._set_voice_state("SCREEN TEXT READY · REVIEW IT", "ok")
            self.ui.emit({"type": "review", "title": f"Display {display} · {result['source']}",
                          "warning": result.get("warning", "Review before sending. Nothing is saved yet."),
                          "text": result.get("text", "")[:6000]})
        elif event_type == "location_changed":
            self._update(place=self._place_summary())
            if self.location.place is None:
                self._update(weather_now=None, local_news=[])
            else:
                self._refresh_weather(repeat=False, news=True)
        elif event_type == "weather_now":
            self._update(weather_now=payload)
        elif event_type == "local_news":
            self._update(local_news=payload)
        elif event_type == "knowledge":
            self._apply_knowledge()
        elif event_type == "dictated":
            self._type_dictation(str(payload or ""))
        elif event_type == "claude_refresh":
            self._apply_claude()
        elif event_type == "toast":
            self._toast(*payload)
        elif event_type == "brief":
            self._update(brief=payload, brief_loading=False)
            if payload["errors"]:
                self._toast("Some brief sources didn't load: " + "; ".join(payload["errors"])[:300], "warn")
        elif event_type == "tune_progress":
            self._update(tuning={**self.state["tuning"], "running": True, "step": payload})
        elif event_type == "tuned":
            self._save_setting("tuning", payload)
            self._apply_tuning(payload)
            self.agent.model = payload["model"]
            installed = sorted(set(self.state["model"]["installed"]) | {payload["model"]})
            self._update(model={"name": payload["model"], "installed": installed, "offer": None},
                         tuning={**self.state["tuning"], "running": False, "step": "", "result": payload})
            self._toast(f"Tuned for this PC: {auto_tune.Tuning(**payload).summary()}.", "ok")
        elif event_type == "tune_failed":
            self._update(tuning={**self.state["tuning"], "running": False, "step": ""})
            self._toast(f"Couldn't tune Nova this time: {payload}. It keeps its current setup.", "warn")
        elif event_type == "model_choice":
            self.agent.model = payload["name"]
            self._update(model={key: payload.get(key) for key in ("name", "recommended", "reason", "installed", "offer", "vision")
                                if key in payload})
            self._use_vision(payload.get("vision"))
            offer = payload.get("offer")
            if offer and not self.settings.get("offer_seen") == offer["name"]:
                self._save_setting("offer_seen", offer["name"])
                pitch = (f"This PC can run a stronger model, {offer['name']}" if offer.get("stronger", True)
                         else f"{offer['name']} would be faster on this PC")
                self._toast(f"{pitch} ({offer['reason']}). Nova uses {payload['name']} for now.",
                            "info", {"label": f"Download {offer['size_gb']} GB", "name": "pull_model", "args": {"name": offer["name"]}})
        elif event_type == "model_pulled":
            self.agent.model = payload
            installed = sorted(set(self.state["model"]["installed"]) | {payload})
            self._update(model={"name": payload, "installed": installed, "offer": None, "downloading": False})
            self._set_voice_state(f"{payload.upper()} READY", "ok")
            self._toast(f"Nova now uses {payload}.", "ok")
        elif event_type == "vision_pulled":
            self._update(model={"installed": sorted(set(self.state["model"]["installed"]) | {payload}), "vision_downloading": False})
            self._use_vision(payload)
            self._set_voice_state("VISION MODEL READY", "ok")
            self._toast("Nova can now name anything you show the camera: touch WHAT IS THIS on the orb, or ask "
                        "“Hey Nova, what am I holding?”", "ok")
        elif event_type == "vision_pull_failed":
            self._update(model={"vision_downloading": False})
            self._set_voice_state("VISION DOWNLOAD FAILED · NOTHING CHANGED", "error")
            self._toast(payload, "error")
        elif event_type == "scan_result":
            self._toast(f"🔍 {payload}", "ok")
            if self.state["switches"]["speak"]:
                self._speak(f"That looks like {payload}.")
        elif event_type == "model_pull_failed":
            self._update(model={"downloading": False})
            self._set_voice_state("MODEL DOWNLOAD FAILED · NOTHING CHANGED", "error")
            self._toast(payload, "error")
        elif event_type == "status":
            self._update(model=payload, system=_system_snapshot(self.hardware))
        elif event_type == "status_error":
            self._update(model={"ollama": "offline", "placement": ""})
            if not self.state.get("ollama_warned"):
                self._update(ollama_warned=True)
                self._toast(f"Ollama is not answering. Start Ollama, then Nova retries by itself.\n{payload[:200]}", "error")


class _MapTools:
    """What the agent may do with the brainstorm map."""

    def __init__(self, app: "AlfredApp") -> None:
        self.app = app

    def show(self, topic: str, ideas: str) -> str:
        return self.app._brainstorm(topic, ideas)

    def add(self, under: str, ideas: list[str]) -> str:
        return self.app._map_add(under, ideas)


class _LibraryTools:
    """What the agent may do with the library (its tool reads and writes the Library itself)."""

    def __init__(self, app: "AlfredApp") -> None:
        self.app = app

    def library(self) -> library_store.Library:
        return self.app._library()

    def open(self, text: str) -> str:
        return self.app._open_library(text)

    def changed(self) -> None:
        self.app.ui.emit({"type": "library_changed"})


def _ring_bell() -> None:
    try:
        import winsound
        for _ in range(3):
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            time.sleep(0.6)
    except (ImportError, RuntimeError):
        pass  # no sound off Windows


def _console_log(message: str, *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    if stream is not None:
        print(message, file=stream, flush=True)


def _choose_usb_model(notices: list[dict[str, str]]) -> tuple[Any, dict[str, Any] | None]:
    """USB: the largest model on the drive that fits this PC, plus an optional stronger download."""
    global MODEL
    local_agent = Agent(model=MODEL or "qwen2.5:7b")
    tags = _http_json(f"{local_agent.base_url}/api/tags", timeout=10)
    profile = detect_hardware()
    selected, ranked = pick_best(tags, profile)
    if not selected:
        return profile, None
    MODEL = selected["name"]
    if not selected.get("fits_ram_budget", False):
        notices.append({"text": f"No model on this drive fits this PC's free memory comfortably. Trying the smallest, {MODEL}; "
                                "it may be slow.", "tone": "warn"})
    models_path = os.environ.get("OLLAMA_MODELS", "")
    free_disk = None
    if models_path:
        import shutil
        free_disk = shutil.disk_usage(models_path).free / (1024 ** 3)
    offer = upgrade_offer(selected, {item["name"] for item in ranked}, profile, free_disk)
    _console_log(f"Nova USB selected {MODEL}; {profile.cpu}; RAM {profile.available_ram_gib} GiB available")
    if offer:
        offer = {"name": offer["name"], "size_gb": round(offer["size_gib"], 1), "reason": "it fits this PC's memory",
                 "stronger": True}
    return profile, offer


def _greeting(name: str, hour: int | None = None) -> str:
    """Nova says hello like she means it, and a little differently by time of day."""
    hour = datetime.now().hour if hour is None else hour
    who = f", {name}" if name else ""
    opening = (f"Still up{who}? Night-owl mode it is." if hour < 5 else f"Good morning{who}! Ready when you are."
               if hour < 12 else f"Good afternoon{who}! What are we tackling?" if hour < 18
               else f"Good evening{who}! What's on your mind?")
    return f"{opening} I'm Nova, running right here on your PC. Type below, or switch on MIC and say “Hey Nova”."


def _quietly(action) -> None:
    """For best-effort background work (warming a model): failures only mean it loads later."""
    try:
        action()
    except Exception:
        pass


def _voice_self_test() -> int:
    """Packaged self-test: Nova's natural voice (Kokoro through sherpa-onnx) installs and speaks in the frozen
    app, and the bundled speech recognizer hears the words. Uses ALFRED_DATA_DIR. Exit 0 when it heard them."""
    import numpy
    if not kokoro_voice.installed():
        kokoro_voice.install(lambda _message: None)
    pcm, rate = kokoro_voice.synthesize("heart", "Hello, I'm Nova. How can I help you today?")
    samples = numpy.frombuffer(pcm, dtype=numpy.int16).astype(numpy.float32)
    positions = numpy.arange(0, len(samples), rate / 16_000)
    heard = VoiceController().transcribe_pcm(numpy.interp(positions, numpy.arange(len(samples)), samples)
                                             .astype(numpy.int16).tobytes())
    print(f"Nova voice test: {len(samples) / rate:.1f} s of speech; heard {heard!r}", flush=True)
    # The same words as a Telegram voice note (Ogg Opus): libsndfile is in the package and the note is heard too.
    import soundfile
    note = io.BytesIO()
    soundfile.write(note, samples / 32768, rate, format="OGG", subtype="OPUS")
    heard_note = VoiceController().transcribe_pcm(telegram_remote.voice_to_pcm(note.getvalue()))
    print(f"Telegram voice note test: {len(note.getvalue())} bytes; heard {heard_note!r}", flush=True)
    return 0 if "help" in heard.lower() and "help" in heard_note.lower() else 1


def _show_running_alfred() -> bool:
    """Nova is already running (maybe only in the tray): show its window instead of starting twice.
    An older build still running (e.g. Alfred from before the rename) is closed instead, so this one starts."""
    from urllib.request import Request, urlopen
    from build_info import BUILD
    from ui_server import PREFERRED_PORT
    try:
        with urlopen(f"http://127.0.0.1:{PREFERRED_PORT}/api/show", timeout=1.5) as response:
            running = json.loads(response.read())
    except (OSError, ValueError):
        return False
    if running.get("app") != "alfred":
        return False
    if running.get("build") == BUILD:
        return True
    _console_log(f"An older build ({running.get('build', 'Alfred')}) is running; closing it so Nova {BUILD} starts.")
    try:
        urlopen(Request(f"http://127.0.0.1:{PREFERRED_PORT}/api/replace", data=b"{}",
                        headers={"Content-Type": "application/json"}, method="POST"), timeout=3).close()
    except OSError:
        pass
    if IS_WINDOWS:  # builds from before /api/replace: the old exe was named Alfred.exe
        subprocess.run(["taskkill", "/F", "/T", "/IM", "Alfred.exe"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for _ in range(80):  # wait (up to 20 s: it stops the camera, mic and phone first) until it lets go of the port
        try:
            urlopen(f"http://127.0.0.1:{PREFERRED_PORT}/api/show", timeout=0.5).close()
        except OSError:
            return False
        time.sleep(0.25)
    return False


def _claude_sdk_bundled() -> bool:
    """The packaged app has the parts of the Anthropic SDK the online brain uses (some load lazily). No network."""
    try:
        brain = cloud_brain.CloudBrain("sk-ant-smoke-test-only-never-sent")
        brain.client.beta.messages.stream  # noqa: B018 - resolving it loads the beta streaming code
        brain._params([], [{"role": "user", "content": "hi"}], [])
        return True
    except Exception as exc:  # a module PyInstaller left out
        _console_log(f"Nova smoke test: the Claude SDK is incomplete: {exc!r}", error=True)
        return False


def main() -> int:
    global MODEL
    if "--screen-assist" in sys.argv:
        from assist_helper import serve
        return serve()
    if "--gesture-test" in sys.argv:
        # Packaged self-test: run the real gesture reader on a video; exit 0 when it saw volume-up and ✌.
        actions: list[str] = []
        control = GestureControl(actions.append, source=sys.argv[sys.argv.index("--gesture-test") + 1])
        control.start()
        control._thread.join(timeout=120)  # a video file ends on its own
        return 0 if "volume_up" in actions and "creative" in actions else 1
    if "--voice-test" in sys.argv:
        return _voice_self_test()
    if "--news-run" in sys.argv:
        # One news desk run without the window (Windows Task Scheduler at 06:00): the same settings Nova uses.
        settings = _load_settings()
        config = NewsConfig(google_news_sites=tuple(daily_brief.saved_outlets(settings.get("news_outlets"))))
        try:  # the model Nova picks for this PC; without Ollama the articles are saved and read next time
            installed = [item["name"] for item in _http_json(f"{Agent().base_url}/api/tags", timeout=10).get("models", [])]
            config.llm_model = choose_model(settings.get("model", "auto"), installed, detect_hardware()).model
        except Exception:
            pass
        report = news_pipeline.run(config, progress=print)
        print(report.line())
        return 0
    if len(sys.argv) == 1 and _show_running_alfred():
        return 0
    parser = argparse.ArgumentParser(description="Nova local assistant")
    parser.add_argument("--check", action="store_true", help="Verify the local model and bundled offline features")
    parser.add_argument("--smoke-test", action="store_true", help="Start, open the window, wait for the HUD to connect, quit")
    parser.add_argument("--no-window", action="store_true", help="Serve the HUD and print its address instead of opening a window")
    args = parser.parse_args()
    managed_ollama = None
    root = None
    try:
        managed_ollama = start_if_configured()
        if args.check:
            if not MODEL:
                agent = Agent()
                installed = [item["name"] for item in _http_json(f"{agent.base_url}/api/tags", timeout=10).get("models", [])]
                MODEL = choose_model(_load_settings().get("model", "auto"), installed, detect_hardware()).model
            Agent(model=MODEL).check_ready()
            import sounddevice  # noqa: F401 - verify bundled voice dependency
            import mss  # noqa: F401 - verify display capture dependency
            import winrt.windows.media.ocr  # noqa: F401 - verify bundled Windows OCR bindings
            offline_voice = VoiceController()
            if not offline_voice.available:
                raise RuntimeError(f"Bundled offline speech model is missing: {offline_voice.model_path}")
            offline_voice.verify_offline_recognizer()
            _console_log(f"Nova features and {MODEL} are available; Vosk recognizer initialized; "
                         f"{len(enumerate_input_devices())} microphone(s), {len(enumerate_speech_outputs())} speech output(s)")
            return 0
        startup: dict[str, Any] = {"notices": []}
        if USB and not args.smoke_test:
            try:
                startup["hardware"], startup["offer"] = _choose_usb_model(startup["notices"])
            except Exception as exc:
                _console_log(f"Nova USB hardware-aware model choice unavailable; using {MODEL or 'qwen2.5:7b'}: {exc}", error=True)
        root = tk.Tk()
        app = AlfredApp(root, startup)
        app.auto_setup = app.auto_setup and not args.smoke_test
        url = app.start(open_window=not args.no_window)
        _console_log(f"Nova HUD: {url}" if args.no_window else "Nova ready")
        app._status_loop()
        if args.smoke_test:
            started = time.monotonic()

            def check_connected() -> None:
                if app.ui.ever_connected.is_set():
                    # Approvals rely on finding the window by its title; check that too when Edge drew it.
                    window = app_window.find_window() if app_window.find_edge() and IS_WINDOWS else True
                    if window or time.monotonic() - started > 90:
                        on_top = True
                        if window and window is not True:  # an approval must be able to lift the window above other apps
                            app_window.keep_on_top(window, True)
                            on_top = app_window.is_topmost(window)
                            app_window.keep_on_top(window, False)
                            on_top = on_top and not app_window.is_topmost(window)
                        tray = app.tray is not None or not IS_WINDOWS
                        claude = _claude_sdk_bundled()
                        _console_log(f"Nova smoke test: the HUD connected; window found: {bool(window)}; on top: {on_top}; "
                                     f"tray: {tray}; Claude SDK: {claude}")
                        app.smoke_failed = not window or not on_top or not tray or not claude
                        root.after(1500, app._close)
                        return
                    root.after(500, check_connected)
                elif time.monotonic() - started > 90:
                    browser = app.window_process
                    _console_log("Nova smoke test: the HUD never connected. Browser: "
                                 f"{app_window.find_edge()}; its process: "
                                 f"{'none' if browser is None else 'running' if browser.poll() is None else f'exited {browser.returncode}'}; "
                                 f"pages asked for: {list(app.ui.requests) or 'none'}", error=True)
                    app.smoke_failed = True
                    app._close()
                else:
                    root.after(500, check_connected)
            app.smoke_failed = False
            root.after(500, check_connected)
        root.mainloop()
        return 1 if args.smoke_test and app.smoke_failed else 0
    except Exception as exc:
        if args.check or args.smoke_test:
            # Unattended runs must fail with an exit code, not wait on a dialog.
            _console_log(f"Nova {'check' if args.check else 'smoke test'} failed: {exc}", error=True)
            return 1
        try:
            from tkinter import messagebox
            messagebox.showerror("Nova could not start", str(exc))
        except Exception:
            _console_log(f"Nova could not start: {exc}", error=True)
        return 1
    finally:
        stop_portable_ollama(managed_ollama)


if __name__ == "__main__":
    raise SystemExit(main())
