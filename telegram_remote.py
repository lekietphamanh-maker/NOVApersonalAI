"""Nova from anywhere: the owner's own private Telegram bot, answered by Nova on this PC.

The owner makes a bot with @BotFather and pastes its token in SETTINGS → Telegram. Nova then asks Telegram for new
messages (long polling): nothing listens on this PC and no router port is opened. The first person to send the pairing
code shown in Settings becomes the owner; after that only the owner's own private chat is answered, and everyone else
is ignored without a reply. Text and voice notes both work (voice is transcribed here by Whisper, never kept), Nova can
send the owner a file from their folders ("send me the report on my desktop"), and when Nova needs a yes or no she asks
in the chat with two buttons.

Telegram's servers carry these messages (bot chats are not end-to-end encrypted). The token is kept in this Windows
user's folder and never written to a log or an error message.
"""
from __future__ import annotations

import io
import json
import os
import re
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import secret_store

API = "https://api.telegram.org"
TOKEN_SHAPE = re.compile(r"^\d{5,12}:[A-Za-z0-9_-]{30,50}$")
POLL_SECONDS = 25
RETRY_SECONDS = (2, 5, 15, 30, 60)
CHECK_IN_SECONDS = 5 * 60  # with the cloud relay: two missed check-ins and it takes over
CODE_TRIES = 5  # wrong codes before a new one is made (a million codes, five guesses each)
ASK_GIVE_UP_SECONDS = 120
MAX_MESSAGE = 4000  # Telegram allows 4,096 characters a message
MAX_VOICE_SECONDS = 300
MAX_FILE_BYTES = 50 * 1024 * 1024  # what a bot may send
SEARCH_DEPTH, SEARCH_LIMIT = 4, 20_000
YES = re.compile(r"^(yes|yeah|yep|sure|ok(ay)?|go( ahead)?|do it|có|ừ|được|đồng ý)[.!]*$", re.IGNORECASE)
NO = re.compile(r"^(no|nope|nah|don'?t|stop|cancel|không|thôi|đừng)[.!]*$", re.IGNORECASE)
SKIPPED_FOLDERS = {"node_modules", ".git", "appdata", "$recycle.bin", "__pycache__", ".venv", "venv"}


TOKEN_SECRET = "telegram_bot_token"


def token_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Alfred" / "telegram_bot_token"


def _plain_token() -> str | None:
    try:
        return token_path().read_text(encoding="utf-8-sig").strip()
    except OSError:
        return None


def stored_token() -> str | None:
    """The bot token, sealed for this account (one in a plain file from an earlier build is sealed on first use)."""
    value = secret_store.load_or_move(TOKEN_SECRET, _plain_token, token_path())
    return value if value and TOKEN_SHAPE.match(value) else None


def save_token(value: str) -> None:
    value = value.strip()
    if not TOKEN_SHAPE.match(value):
        raise ValueError("That doesn't look like a bot token from @BotFather (it looks like 123456789:AA…).")
    secret_store.save(TOKEN_SECRET, value)
    token_path().unlink(missing_ok=True)


def forget_token() -> None:
    secret_store.forget(TOKEN_SECRET)
    token_path().unlink(missing_ok=True)


class TelegramError(RuntimeError):
    """Telegram refused or couldn't be reached. The message never contains the token."""

    def __init__(self, why: str, refused: bool = False, code: int | None = None) -> None:
        super().__init__(why)
        self.refused = refused  # the token itself was refused: polling stops until a new one is saved
        self.code = code


class Bot:
    """Telegram's Bot API over HTTPS. `opener` stands in for urlopen in tests."""

    def __init__(self, token: str, opener: Callable[..., Any] = urlopen) -> None:
        self._token, self._open = token, opener

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 30,
             upload: tuple[str, str, bytes] | None = None) -> Any:
        """upload: (field, file name, bytes) sends a file with the parameters as form fields."""
        if upload is None:
            body, kind = json.dumps(params or {}).encode(), "application/json"
        else:
            body, kind = _form(params or {}, *upload)
        request = Request(f"{API}/bot{self._token}/{method}", body, {"Content-Type": kind})
        try:
            with self._open(request, timeout=timeout) as response:
                answer = json.loads(response.read())
        except HTTPError as exc:
            try:
                answer = json.loads(exc.read())
            except (ValueError, OSError):
                answer = {"ok": False, "error_code": exc.code, "description": exc.reason}
        except (URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise TelegramError(f"couldn't reach Telegram ({type(reason).__name__})") from None
        if not answer.get("ok"):
            code = answer.get("error_code")
            raise TelegramError(f"Telegram said {code}: {str(answer.get('description', ''))[:120]}", refused=code in (401, 404),
                                code=code)
        return answer.get("result")

    def download(self, file_id: str) -> bytes:
        path = self.call("getFile", {"file_id": file_id})["file_path"]
        try:
            with self._open(Request(f"{API}/file/bot{self._token}/{path}"), timeout=60) as response:
                return response.read()
        except (URLError, TimeoutError, OSError) as exc:
            raise TelegramError(f"couldn't download the voice note ({type(exc).__name__})") from None


def _form(params: dict[str, Any], field: str, name: str, data: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
             for key, value in params.items()]
    safe_name = re.sub(r'["\r\n\\]', "_", name)
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{safe_name}"\r\n'
                 "Content-Type: application/octet-stream\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def voice_to_pcm(ogg: bytes, rate: int = 16_000) -> bytes:
    """A Telegram voice note (Ogg Opus) as 16 kHz mono 16-bit PCM, what Nova's recognizers hear."""
    import numpy as np
    import soundfile
    samples, source_rate = soundfile.read(io.BytesIO(ogg), dtype="float32", always_2d=True)
    mono = samples.mean(axis=1)[: int(MAX_VOICE_SECONDS * source_rate)]
    if source_rate != rate and len(mono):
        positions = np.arange(0, len(mono), source_rate / rate)
        mono = np.interp(positions, np.arange(len(mono)), mono)
    return (np.clip(mono, -1, 1) * 32767).astype("<i2").tobytes()


def default_folders() -> list[Path]:
    home = Path.home()
    return [home / name for name in ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music")] + \
           [home / "OneDrive" / name for name in ("Desktop", "Documents", "Pictures")]


def find_file(words: str, folders: list[Path]) -> list[Path]:
    """The owner's files whose names hold every word asked for, newest first. Only in the owner's own folders (no
    AppData, no program folders), a few levels deep."""
    wanted = [word for word in re.findall(r"\w+", words.lower()) if word not in {"the", "my", "a", "file", "on", "in"}]
    if not wanted:
        return []
    found: list[Path] = []
    seen = 0
    for root in folders:
        if not root.is_dir():
            continue
        start = len(root.parts)
        for folder, children, files in os.walk(root):
            if len(Path(folder).parts) - start >= SEARCH_DEPTH:
                children[:] = []
            children[:] = [child for child in children if child.lower() not in SKIPPED_FOLDERS and not child.startswith(".")]
            for name in files:
                seen += 1
                lower = name.lower()
                if all(word in lower for word in wanted):
                    found.append(Path(folder) / name)
            if seen > SEARCH_LIMIT:
                break
    return sorted(found, key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)


class TelegramRemote:
    """ask(text, approve, send_file) runs one Nova turn and returns the answer; approve(summary) asks the owner in the
    chat; transcribe(pcm) hears a voice note. load()/save(data) keep the owner and the pairing between restarts.
    status(text) tells Settings what is happening."""

    def __init__(self, ask: Callable[[str, Callable[[str], bool], Callable[[str], str]], str],
                 transcribe: Callable[[bytes], str], load: Callable[[], dict[str, Any]],
                 save: Callable[[dict[str, Any]], None], status: Callable[[str], None] = lambda _text: None,
                 bot: Callable[[str], Bot] = Bot, folders: Callable[[], list[Path]] = default_folders,
                 relay: Callable[[], Any] = lambda: None, check_in: Callable[[], dict[str, Any]] = dict,
                 on_away: Callable[[dict[str, Any]], None] = lambda _result: None) -> None:
        """relay() is the cloud relay for while the PC is off (cloud_relay.Relay) or None; check_in() what it needs to
        know; on_away(result) hears what it did while the PC was off."""
        self.ask, self.transcribe, self.load, self.save, self.status = ask, transcribe, load, save, status
        self.make_bot, self.folders = bot, folders
        self.relay, self.check_in, self.on_away = relay, check_in, on_away
        self._checked_in = 0.0
        self.bot: Bot | None = None
        self.name = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._busy = threading.Lock()
        self._question: dict[str, Any] | None = None  # the yes/no the owner is being asked: {"id", "event", "yes"}
        self._code: str | None = None
        self._wrong = 0

    # ---------- on and off ----------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def owner(self) -> dict[str, Any] | None:
        owner = (self.load() or {}).get("owner")
        return owner if isinstance(owner, dict) and owner.get("user_id") else None

    def start(self, token: str) -> None:
        self.stop()
        self.bot = self.make_bot(token)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop,), name="NovaTelegram", daemon=True)
        self._thread.start()

    def stop(self, going: bool = False) -> None:
        """Stops at once; a poll already waiting at Telegram ends on its own (its thread then sees the stop).
        going: Nova is closing, so the cloud relay takes Telegram over now."""
        self._stop.set()
        if going and self.running:
            self._check_in(going=True)
        question = self._question
        if question is not None:
            question["event"].set()
        self._thread = None

    def pairing_code(self) -> str:
        """The code the owner sends the bot once (shown in Settings); a new one after too many wrong tries."""
        if self._code is None or self._wrong >= CODE_TRIES:
            self._code, self._wrong = f"{secrets.randbelow(1_000_000):06d}", 0
        return self._code

    def forget_owner(self) -> None:
        self.save({**(self.load() or {}), "owner": None})
        self._code = None

    # ---------- the polling loop ----------

    def _run(self, stop: threading.Event) -> None:
        try:
            me = self.bot.call("getMe", timeout=15)
            self.name = str(me.get("username") or "")
        except TelegramError as exc:
            self.status(f"Telegram: {exc}" + (". Paste a new token." if exc.refused else ""))
            if exc.refused:
                return
        try:  # the cloud relay held Telegram while the PC was off: take it back (polling needs no webhook)
            self.bot.call("deleteWebhook", {"drop_pending_updates": False}, timeout=15)
        except TelegramError:
            pass
        self._check_in()
        self.status(f"Connected as @{self.name}." if self.name else "Connecting…")
        offset, failures = int((self.load() or {}).get("offset") or 0), 0
        while not stop.is_set():
            if time.monotonic() - self._checked_in >= CHECK_IN_SECONDS:
                self._check_in()
            try:
                updates = self.bot.call("getUpdates", {"offset": offset, "timeout": POLL_SECONDS,
                                                       "allowed_updates": ["message", "callback_query"]},
                                        timeout=POLL_SECONDS + 10)
            except TelegramError as exc:
                if exc.refused:
                    self.status(f"Telegram: {exc}. Paste a new token.")
                    return
                failures += 1
                if exc.code == 409:  # an older poll is still open, or the cloud relay just set its webhook: take it back
                    try:
                        self.bot.call("deleteWebhook", {"drop_pending_updates": False}, timeout=15)
                    except TelegramError:
                        pass
                else:
                    self.status(f"Telegram: {exc}; trying again.")
                stop.wait(RETRY_SECONDS[min(failures, len(RETRY_SECONDS)) - 1])
                continue
            if stop.is_set():
                return  # stopped while waiting: whatever came in is read by the next start
            if failures:
                failures = 0
                self.status(f"Connected as @{self.name}.")
            for update in updates or []:
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                try:
                    self.handle(update)
                except TelegramError as exc:
                    self.status(f"Telegram: {exc}")
            if updates:  # Telegram forgets what was read once the next request carries the new offset
                self.save({**(self.load() or {}), "offset": offset})

    def _check_in(self, going: bool = False) -> None:
        """Tells the cloud relay the PC is here (or leaving) and what it needs to stand in; hears what it did."""
        relay, owner = self.relay(), self.owner
        self._checked_in = time.monotonic()
        if relay is None or owner is None:
            return
        try:
            result = relay.sync({**self.check_in(), "owner": owner["user_id"], "going": going}, timeout=5 if going else 20)
        except Exception as exc:  # the relay is a helper: Telegram on the PC works without it
            self.status(f"Connected as @{self.name}. The relay for when the PC is off didn't answer ({exc}).")
            return
        if result.get("away") or result.get("delivered"):
            self.on_away(result)

    # ---------- one update ----------

    def handle(self, update: dict[str, Any]) -> None:
        if "callback_query" in update:
            self._button(update["callback_query"])
            return
        message = update.get("message") or {}
        chat, sender = message.get("chat") or {}, message.get("from") or {}
        if chat.get("type") != "private" or sender.get("is_bot"):
            return  # groups and other bots: never
        owner = self.owner
        if owner is None:
            self._pair(message, chat, sender)
            return
        if sender.get("id") != owner["user_id"]:
            return  # not the owner: no reply at all
        text = str(message.get("text") or message.get("caption") or "").strip()
        question = self._question
        if question is not None and (YES.match(text) or NO.match(text)):
            question["yes"] = bool(YES.match(text))
            question["event"].set()
            return
        if text.startswith("/start") or text == "/help":
            self.send(chat["id"], "Hi, it's Nova. Ask me anything, or send a voice note. Your PC has to be on.")
            return
        if "voice" in message or "audio" in message:
            threading.Thread(target=self._voice, args=(chat["id"], message), name="NovaTelegramVoice", daemon=True).start()
        elif text:
            self._answer(chat["id"], text)

    def _pair(self, message: dict[str, Any], chat: dict[str, Any], sender: dict[str, Any]) -> None:
        if self._code is None:
            return  # pairing isn't open: Settings shows the code only while Telegram is being set up
        sent = re.sub(r"\D", "", str(message.get("text") or ""))
        if sent and self._wrong < CODE_TRIES and secrets.compare_digest(sent, self._code):
            self.save({**(self.load() or {}), "owner": {"user_id": sender["id"], "chat_id": chat["id"],
                                                        "name": str(sender.get("first_name") or "")[:40]}})
            self._code = None
            self.status(f"Paired with {sender.get('first_name') or 'you'}. Connected as @{self.name}.")
            self.send(chat["id"], "Paired. It's Nova: from now on I answer only you here. Ask me anything.")
        elif sent:
            self._wrong += 1
            if self._wrong >= CODE_TRIES:
                self.pairing_code()
                self.status("Too many wrong pairing codes were sent to the bot, so there is a new code.")

    def _button(self, query: dict[str, Any]) -> None:
        owner, question = self.owner, self._question
        if owner is None or (query.get("from") or {}).get("id") != owner["user_id"]:
            return
        self.bot.call("answerCallbackQuery", {"callback_query_id": query.get("id")})
        answer, _, question_id = str(query.get("data") or "").partition(":")
        if question is not None and question_id == question["id"]:
            question["yes"] = answer == "yes"
            question["event"].set()

    # ---------- answering ----------

    def _answer(self, chat_id: int, text: str) -> None:
        if not self._busy.acquire(blocking=False):
            self.send(chat_id, "Still working on your last message. One moment.")
            return
        threading.Thread(target=self._turn, args=(chat_id, text), name="NovaTelegramTurn", daemon=True).start()

    def _turn(self, chat_id: int, text: str) -> None:
        try:
            self._typing(chat_id)
            reply = self.ask(text, lambda summary: self.confirm(chat_id, summary), lambda words: self.send_file(chat_id, words))
            self.send(chat_id, reply or "Done.")
        except TelegramError as exc:
            self.status(f"Telegram: {exc}")
        except Exception as exc:  # Nova's turn failed: say so in the chat rather than going quiet
            self.send(chat_id, f"Something went wrong on the PC: {type(exc).__name__}.")
        finally:
            self._busy.release()

    def _voice(self, chat_id: int, message: dict[str, Any]) -> None:
        note = message.get("voice") or message.get("audio") or {}
        try:
            if int(note.get("duration") or 0) > MAX_VOICE_SECONDS:
                self.send(chat_id, "That voice note is longer than 5 minutes. Send a shorter one.")
                return
            self._typing(chat_id)
            heard = self.transcribe(voice_to_pcm(self.bot.download(str(note.get("file_id")))))
        except TelegramError as exc:
            self.send(chat_id, f"I couldn't get that voice note: {exc}.")
            return
        except Exception as exc:
            self.send(chat_id, f"I couldn't hear that voice note ({type(exc).__name__}). Try typing it.")
            return
        if not heard.strip():
            self.send(chat_id, "I couldn't make out any words in that one. Try again or type it.")
            return
        self.send(chat_id, f"Heard: {heard.strip()}")
        self._answer(chat_id, heard.strip())

    def confirm(self, chat_id: int, summary: str) -> bool:
        """Asks the owner in the chat, with Yes and No buttons (or a typed yes/no). No answer in two minutes is no."""
        question = {"id": secrets.token_hex(4), "event": threading.Event(), "yes": False}
        self._question = question
        try:
            self.bot.call("sendMessage", {"chat_id": chat_id, "text": summary[:MAX_MESSAGE] + "\n\nShould I go ahead?",
                                          "reply_markup": {"inline_keyboard": [[
                                              {"text": "Yes", "callback_data": f"yes:{question['id']}"},
                                              {"text": "No", "callback_data": f"no:{question['id']}"}]]}})
            answered = question["event"].wait(ASK_GIVE_UP_SECONDS)
            return bool(answered and question["yes"] and not self._stop.is_set())
        finally:
            self._question = None

    def send(self, chat_id: int, text: str) -> None:
        text = str(text).strip() or "…"
        for start in range(0, len(text), MAX_MESSAGE):
            self.bot.call("sendMessage", {"chat_id": chat_id, "text": text[start:start + MAX_MESSAGE]})

    def send_file(self, chat_id: int, words: str) -> str:
        """Finds the owner's file by name and sends it to the chat; tells Nova what happened."""
        matches = find_file(words, self.folders())
        if not matches:
            return f"No file named like “{words}” in Desktop, Documents, Downloads, Pictures, Videos or Music."
        chosen = matches[0]
        size = chosen.stat().st_size
        if size > MAX_FILE_BYTES:
            return f"{chosen.name} is {size // 1_048_576} MB; Telegram bots can send up to 50 MB."
        self.bot.call("sendDocument", {"chat_id": chat_id}, timeout=300, upload=("document", chosen.name, chosen.read_bytes()))
        others = "" if len(matches) == 1 else f" (newest of {len(matches)} matches; others: " + \
            ", ".join(path.name for path in matches[1:4]) + ")"
        return f"Sent {chosen.name} from {chosen.parent.name} to the owner's Telegram{others}."

    def _typing(self, chat_id: int) -> None:
        try:
            self.bot.call("sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=10)
        except TelegramError:
            pass
