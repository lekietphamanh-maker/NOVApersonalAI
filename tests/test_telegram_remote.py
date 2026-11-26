"""Nova on Telegram: the token, pairing with the owner only, strangers ignored, answers, yes/no buttons, voice notes
and sending the owner's files. Telegram itself is a stand-in here."""
from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import telegram_remote as remote

TOKEN = "123456789:AAH" + "x" * 32
OWNER, STRANGER = 1001, 2002


class FakeBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.uploads: list[tuple[str, str, bytes]] = []

    def call(self, method: str, params: dict | None = None, timeout: float = 30, upload=None):
        self.calls.append((method, params or {}))
        if upload is not None:
            self.uploads.append(upload)
        return {"username": "nova_test_bot"} if method == "getMe" else True

    def sent(self, chat_id: int = OWNER) -> list[str]:
        return [params["text"] for method, params in self.calls if method == "sendMessage" and params["chat_id"] == chat_id]


def message(text: str, sender: int = OWNER, chat_type: str = "private", **extra) -> dict:
    return {"update_id": 1, "message": {"chat": {"id": sender, "type": chat_type},
                                        "from": {"id": sender, "first_name": "Sam", "is_bot": False}, "text": text, **extra}}


def wait_for(condition, seconds: float = 3) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


class TokenTests(unittest.TestCase):
    def test_only_a_botfather_token_is_kept(self) -> None:
        with patch.dict(os.environ, {"LOCALAPPDATA": tempfile.mkdtemp()}):
            self.assertIsNone(remote.stored_token())
            with self.assertRaises(ValueError):
                remote.save_token("sk-ant-not-a-bot-token")
            remote.save_token(f"  {TOKEN}\n")
            self.assertEqual(remote.stored_token(), TOKEN)
            remote.forget_token()
            self.assertIsNone(remote.stored_token())

    def test_errors_never_carry_the_token(self) -> None:
        def offline(request, timeout):
            raise URLError(OSError(f"failed {request.full_url}"))
        with self.assertRaises(remote.TelegramError) as caught:
            remote.Bot(TOKEN, offline).call("getMe")
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertFalse(caught.exception.refused)

        def refused(request, timeout):
            raise HTTPError(request.full_url, 401, "Unauthorized", {},
                            io.BytesIO(b'{"ok":false,"error_code":401,"description":"Unauthorized"}'))
        with self.assertRaises(remote.TelegramError) as caught:
            remote.Bot(TOKEN, refused).call("getMe")
        self.assertTrue(caught.exception.refused)
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_requests_go_to_the_bot_api(self) -> None:
        seen = {}

        class Answer(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def opener(request, timeout):
            seen.update(url=request.full_url, body=json.loads(request.data))
            return Answer(b'{"ok":true,"result":{"username":"nova_test_bot"}}')
        self.assertEqual(remote.Bot(TOKEN, opener).call("sendMessage", {"chat_id": 1, "text": "hi"}),
                         {"username": "nova_test_bot"})
        self.assertEqual(seen["url"], f"https://api.telegram.org/bot{TOKEN}/sendMessage")
        self.assertEqual(seen["body"], {"chat_id": 1, "text": "hi"})


class RemoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved: dict = {}
        self.statuses: list[str] = []
        self.asked: list[str] = []
        self.answer = lambda text, confirm, send_file: f"Answer to {text}"
        self.bot = FakeBot()
        self.remote = remote.TelegramRemote(
            ask=lambda text, confirm, send_file: self.asked.append(text) or self.answer(text, confirm, send_file),
            transcribe=lambda pcm: "what time is it", load=lambda: dict(self.saved),
            save=lambda data: self.saved.update(data), status=self.statuses.append)
        self.remote.bot = self.bot

    def pair(self) -> None:
        self.remote.handle(message(self.remote.pairing_code()))

    def test_the_first_to_send_the_code_becomes_the_only_one_answered(self) -> None:
        self.remote.handle(message("hello", sender=STRANGER))
        self.assertEqual(self.bot.calls, [])  # pairing isn't open until Settings shows a code
        code = self.remote.pairing_code()
        self.remote.handle(message("000000" if code != "000000" else "111111", sender=STRANGER))
        self.assertIsNone(self.remote.owner)
        self.remote.handle(message(f"/start {code}"))
        self.assertEqual(self.remote.owner, {"user_id": OWNER, "chat_id": OWNER, "name": "Sam"})
        self.assertIn("Paired", self.bot.sent()[0])
        self.remote.handle(message("what's on my desktop?", sender=STRANGER))
        self.remote.handle(message(code, sender=STRANGER))
        self.assertEqual(self.bot.sent(STRANGER), [])  # strangers get no reply at all
        self.assertEqual(self.asked, [])

    def test_five_wrong_codes_make_a_new_one(self) -> None:
        with patch.object(remote.secrets, "randbelow", side_effect=[111111, 222222]):
            self.assertEqual(self.remote.pairing_code(), "111111")
            for _ in range(remote.CODE_TRIES):
                self.remote.handle(message("333333", sender=STRANGER))
            self.assertEqual(self.remote.pairing_code(), "222222")
        self.assertIn("new code", self.statuses[-1])
        self.remote.handle(message("111111"))
        self.assertIsNone(self.remote.owner)
        self.remote.handle(message("222222"))
        self.assertEqual(self.remote.owner["user_id"], OWNER)

    def test_groups_and_bots_are_never_answered(self) -> None:
        self.pair()
        self.remote.handle(message("hi", chat_type="group"))
        bot_message = message("hi")
        bot_message["message"]["from"]["is_bot"] = True
        self.remote.handle(bot_message)
        self.assertEqual(self.asked, [])

    def test_the_owner_gets_an_answer_and_one_message_at_a_time(self) -> None:
        self.pair()
        release = threading.Event()

        def slow(text, confirm, send_file):
            release.wait(3)
            return f"Answer to {text}"
        self.answer = slow
        self.remote.handle(message("is my PC on?"))
        self.assertTrue(wait_for(lambda: self.asked == ["is my PC on?"]))
        self.remote.handle(message("and the weather?"))
        self.assertTrue(wait_for(lambda: "Still working on your last message. One moment." in self.bot.sent()))
        release.set()
        self.assertTrue(wait_for(lambda: "Answer to is my PC on?" in self.bot.sent()))
        self.assertIn(("sendChatAction", {"chat_id": OWNER, "action": "typing"}), self.bot.calls)

    def test_yes_and_no_are_asked_in_the_chat(self) -> None:
        self.pair()
        results: list[bool] = []
        self.answer = lambda text, confirm, send_file: str(results.append(confirm("Send it to Claude?")) or "ok")
        self.remote.handle(message("check my mail online"))
        self.assertTrue(wait_for(lambda: any(params.get("reply_markup") for method, params in self.bot.calls)))
        buttons = next(params for method, params in self.bot.calls if params.get("reply_markup"))
        self.assertIn("Send it to Claude?", buttons["text"])
        yes = buttons["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        self.remote.handle({"update_id": 2, "callback_query": {"id": "q1", "from": {"id": STRANGER}, "data": yes}})
        time.sleep(0.1)
        self.assertEqual(results, [])  # a stranger's tap does nothing
        self.remote.handle({"update_id": 3, "callback_query": {"id": "q2", "from": {"id": OWNER}, "data": yes}})
        self.assertTrue(wait_for(lambda: results == [True]))
        self.remote.handle(message("check it again"))
        self.assertTrue(wait_for(lambda: len([1 for _m, params in self.bot.calls if params.get("reply_markup")]) == 2))
        self.remote.handle(message("no"))  # typing no works too
        self.assertTrue(wait_for(lambda: results == [True, False]))

    def test_a_voice_note_is_heard_here_then_answered(self) -> None:
        self.pair()
        self.bot.download = lambda file_id: b"ogg"
        with patch.object(remote, "voice_to_pcm", lambda ogg: b"\0\0" * 16000):
            self.remote.handle(message("", voice={"file_id": "v1", "duration": 3}))
            self.assertTrue(wait_for(lambda: "Answer to what time is it" in self.bot.sent()))
        self.assertIn("Heard: what time is it", self.bot.sent())
        self.remote.handle(message("", voice={"file_id": "v2", "duration": 900}))
        self.assertTrue(wait_for(lambda: any("longer than 5 minutes" in text for text in self.bot.sent())))


class VoiceTests(unittest.TestCase):
    def test_an_ogg_opus_voice_note_becomes_16_khz_speech(self) -> None:
        import numpy as np
        import soundfile
        tone = (np.sin(np.arange(48_000) / 48_000 * 2 * np.pi * 440) * 0.5).astype("float32")
        note = io.BytesIO()
        soundfile.write(note, tone, 48_000, format="OGG", subtype="OPUS")
        pcm = remote.voice_to_pcm(note.getvalue())
        samples = np.frombuffer(pcm, "<i2")
        self.assertAlmostEqual(len(samples), 16_000, delta=400)  # one second at 16 kHz
        self.assertGreater(np.abs(samples).max(), 8000)


class FileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        (self.root / "Desktop" / "node_modules").mkdir(parents=True)
        (self.root / "Documents" / "School").mkdir(parents=True)
        (self.root / "Desktop" / "Report final.pdf").write_bytes(b"%PDF new")
        old = self.root / "Documents" / "School" / "report draft.pdf"
        old.write_bytes(b"%PDF old")
        os.utime(old, (time.time() - 3600, time.time() - 3600))
        (self.root / "Desktop" / "node_modules" / "report.js").write_text("x")

    def test_the_newest_file_with_those_words_in_the_owners_folders(self) -> None:
        folders = [self.root / "Desktop", self.root / "Documents"]
        self.assertEqual([path.name for path in remote.find_file("the report", folders)], ["Report final.pdf", "report draft.pdf"])
        self.assertEqual([path.name for path in remote.find_file("report draft", folders)], ["report draft.pdf"])
        self.assertEqual(remote.find_file("my file", folders), [])

    def test_send_file_uploads_it_to_the_owners_chat(self) -> None:
        bot = FakeBot()
        telegram = remote.TelegramRemote(ask=lambda *_: "", transcribe=lambda _p: "", load=dict, save=lambda _d: None,
                                         folders=lambda: [self.root / "Desktop", self.root / "Documents"])
        telegram.bot = bot
        result = telegram.send_file(OWNER, "report")
        self.assertIn("Sent Report final.pdf", result)
        self.assertIn("report draft.pdf", result)
        self.assertEqual(bot.uploads, [("document", "Report final.pdf", b"%PDF new")])
        self.assertIn("No file named", telegram.send_file(OWNER, "taxes"))
        body, kind = remote._form({"chat_id": 5}, "document", 'a"b.pdf', b"DATA")
        self.assertIn(b'filename="a_b.pdf"', body)
        self.assertTrue(kind.startswith("multipart/form-data; boundary="))


class PollingTests(unittest.TestCase):
    def test_polls_until_stopped_and_remembers_what_was_read(self) -> None:
        saved: dict = {}
        updates = [[{"update_id": 41, "message": message("x", sender=STRANGER)["message"]}], []]

        class PollingBot(FakeBot):
            def call(self, method, params=None, timeout=30, upload=None):
                if method == "getUpdates":
                    if updates:
                        return updates.pop(0)
                    time.sleep(0.05)
                    return []
                return super().call(method, params, timeout, upload)
        telegram = remote.TelegramRemote(ask=lambda *_: "", transcribe=lambda _p: "", load=lambda: dict(saved),
                                         save=saved.update, bot=lambda token: PollingBot())
        telegram.start(TOKEN)
        self.assertTrue(wait_for(lambda: saved.get("offset") == 42))
        self.assertEqual(telegram.name, "nova_test_bot")
        first = telegram._thread
        telegram.start(TOKEN)  # a new token or off and on again: the old poller ends, only one polls
        self.assertTrue(wait_for(lambda: not first.is_alive()))
        second = telegram._thread
        self.assertTrue(second.is_alive())
        telegram.stop()
        self.assertFalse(telegram.running)
        self.assertTrue(wait_for(lambda: not second.is_alive()))


if __name__ == "__main__":
    unittest.main()


class SealedTokenTests(unittest.TestCase):
    def test_a_plain_token_from_an_earlier_build_is_sealed_once(self) -> None:
        import secret_store
        with patch.dict(os.environ, {"LOCALAPPDATA": tempfile.mkdtemp()}):
            remote.token_path().parent.mkdir(parents=True, exist_ok=True)
            remote.token_path().write_text("123456789:AAbbccddeeffgghhiijjkkllmmnnooppqqr", encoding="utf-8")
            self.assertEqual(remote.stored_token(), "123456789:AAbbccddeeffgghhiijjkkllmmnnooppqqr")
            self.assertFalse(remote.token_path().exists())  # no plain copy left behind
            self.assertEqual(secret_store.load(remote.TOKEN_SECRET), "123456789:AAbbccddeeffgghhiijjkkllmmnnooppqqr")
            remote.forget_token()
            self.assertIsNone(remote.stored_token())
