"""Telegram with the PC off: deploying the relay to Cloudflare (a stand-in Cloudflare here), the PC's check-ins, and
the relay itself (cloud/worker.js, through Node's test runner when Node is installed)."""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import cloud_relay
import telegram_remote as remote

ROOT = Path(__file__).resolve().parent.parent
CLOUDFLARE_TOKEN = "cf_" + "a" * 37
BOT_TOKEN = "123456789:AAH" + "x" * 32


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeCloudflare:
    def __init__(self, subdomain: str | None = "sam", spaces: list | None = None) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self.subdomain, self.spaces = subdomain, spaces or []

    def __call__(self, request, timeout):
        path = request.full_url.removeprefix(cloud_relay.CLOUDFLARE)
        body = request.data
        if body and "json" in request.get_header("Content-type", ""):
            body = json.loads(body)
        self.calls.append((request.get_method(), path, body))
        assert request.get_header("Authorization") == f"Bearer {CLOUDFLARE_TOKEN}"
        if path == "/accounts":
            result = [{"id": "acc1"}]
        elif path.endswith("/workers/subdomain") and request.get_method() == "GET":
            if self.subdomain is None:
                raise HTTPError(request.full_url, 404, "Not Found", {},
                                io.BytesIO(b'{"success":false,"errors":[{"code":10007,"message":"not found"}]}'))
            result = {"subdomain": self.subdomain}
        elif path.endswith("/workers/subdomain"):
            result = {"subdomain": body["subdomain"]}
        elif "/storage/kv/namespaces" in path and request.get_method() == "GET":
            result = self.spaces
        elif path.endswith("/storage/kv/namespaces"):
            result = {"id": "kv1", "title": body["title"]}
        else:
            result = {}
        return Answer(json.dumps({"success": True, "result": result}).encode())


class DeployTests(unittest.TestCase):
    def test_puts_the_relay_with_its_secrets_on_the_owners_account(self) -> None:
        cloudflare = FakeCloudflare()
        relay = cloud_relay.deploy(CLOUDFLARE_TOKEN, BOT_TOKEN, "claude", "sk-ant-" + "k" * 40, opener=cloudflare,
                                   script="export default {}")
        self.assertEqual(relay.url, "https://nova-telegram.sam.workers.dev")
        self.assertEqual(relay.brain, "claude")
        steps = [(method, path) for method, path, _ in cloudflare.calls]
        self.assertEqual(steps, [
            ("GET", "/accounts"), ("GET", "/accounts/acc1/workers/subdomain"),
            ("GET", "/accounts/acc1/storage/kv/namespaces?per_page=100"), ("POST", "/accounts/acc1/storage/kv/namespaces"),
            ("PUT", "/accounts/acc1/workers/scripts/nova-telegram"),
            ("POST", "/accounts/acc1/workers/scripts/nova-telegram/subdomain"),
            ("PUT", "/accounts/acc1/workers/scripts/nova-telegram/schedules")])
        upload = cloudflare.calls[4][2].decode()
        metadata = json.loads(upload.split("\r\n\r\n", 1)[1].split("\r\n--", 1)[0])
        bindings = {binding["name"]: binding for binding in metadata["bindings"]}
        self.assertEqual(metadata["main_module"], "worker.js")
        self.assertEqual(bindings["NOVA"], {"type": "kv_namespace", "name": "NOVA", "namespace_id": "kv1"})
        self.assertEqual(bindings["BOT_TOKEN"]["type"], "secret_text")  # secrets, not readable in the dashboard
        self.assertEqual(bindings["PC_SECRET"]["text"], relay.secret)
        self.assertEqual(bindings["SELF_URL"]["text"], relay.url)
        self.assertEqual(bindings["BRAIN_MODEL"]["text"], "claude-haiku-5-5")
        self.assertIn("application/javascript+module", upload)
        self.assertEqual(cloudflare.calls[6][2], [{"cron": "* * * * *"}])

    def test_a_new_account_gets_a_workers_dev_name_and_the_old_store_is_reused(self) -> None:
        cloudflare = FakeCloudflare(subdomain=None, spaces=[{"id": "old", "title": "nova-telegram"}])
        relay = cloud_relay.deploy(CLOUDFLARE_TOKEN, BOT_TOKEN, opener=cloudflare, script="")
        self.assertRegex(relay.url, r"^https://nova-telegram\.nova-[0-9a-f]{8}\.workers\.dev$")
        self.assertNotIn(("POST", "/accounts/acc1/storage/kv/namespaces"), [(m, p) for m, p, _ in cloudflare.calls])

    def test_mistakes_are_said_plainly_and_never_carry_a_token(self) -> None:
        with self.assertRaises(cloud_relay.RelayError):
            cloud_relay.deploy("short", BOT_TOKEN, opener=FakeCloudflare())
        with self.assertRaises(cloud_relay.RelayError) as caught:
            cloud_relay.deploy(CLOUDFLARE_TOKEN, BOT_TOKEN, "ollama", "", opener=FakeCloudflare())
        self.assertIn("needs its key", str(caught.exception))

        def refused(request, timeout):
            raise HTTPError(request.full_url, 403, "Forbidden", {},
                            io.BytesIO(b'{"success":false,"errors":[{"code":10000,"message":"Authentication error"}]}'))
        with self.assertRaises(cloud_relay.RelayError) as caught:
            cloud_relay.deploy(CLOUDFLARE_TOKEN, BOT_TOKEN, opener=refused)
        self.assertIn("Authentication error", str(caught.exception))
        self.assertNotIn(CLOUDFLARE_TOKEN, str(caught.exception))

    def test_the_relay_is_kept_in_the_users_folder(self) -> None:
        with patch.dict(os.environ, {"LOCALAPPDATA": tempfile.mkdtemp()}):
            self.assertIsNone(cloud_relay.load())
            cloud_relay.save(cloud_relay.Relay("https://x.workers.dev", "s3cret", "ollama"))
            self.assertEqual(cloud_relay.load(), cloud_relay.Relay("https://x.workers.dev", "s3cret", "ollama"))
            cloud_relay.forget()
            self.assertIsNone(cloud_relay.load())

    def test_the_relay_script_ships_with_nova(self) -> None:
        self.assertTrue(cloud_relay.WORKER_FILE.exists())
        self.assertIn("('cloud/worker.js', 'cloud')", (ROOT / "Alfred.spec").read_text())


class CheckInTests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = {"owner": {"user_id": 1001, "chat_id": 1001, "name": "Sam"}}
        self.reports: list[dict] = []
        self.sent: list[dict] = []
        self.answer = {"away": [], "delivered": []}

        class Relay:
            def sync(relay, body, timeout=20):
                self.sent.append(body)
                return self.answer
        self.remote = remote.TelegramRemote(ask=lambda *_: "", transcribe=lambda _p: "", load=lambda: dict(self.saved),
                                            save=self.saved.update, relay=lambda: Relay(),
                                            check_in=lambda: {"name": "Sam", "facts": ["likes tea"]},
                                            on_away=self.reports.append)

    def test_checks_in_with_the_owner_and_hears_what_happened_while_off(self) -> None:
        self.remote._check_in()
        self.assertEqual(self.sent[-1], {"name": "Sam", "facts": ["likes tea"], "owner": 1001, "going": False})
        self.assertEqual(self.reports, [])  # nothing happened
        self.answer = {"away": [{"text": "hi", "reply": "Hello!"}], "delivered": ["1@2026-11-20 08:00"]}
        self.remote._check_in(going=True)
        self.assertTrue(self.sent[-1]["going"])
        self.assertEqual(self.reports, [self.answer])

    def test_no_check_in_before_pairing(self) -> None:
        self.saved["owner"] = None
        self.remote._check_in()
        self.assertEqual(self.sent, [])

    def test_starting_takes_telegram_back_from_the_relay(self) -> None:
        calls: list[str] = []

        class Bot:
            def call(self, method, params=None, timeout=30, upload=None):
                calls.append(method)
                if method == "getUpdates":
                    time.sleep(0.05)
                    return []
                return {"username": "nova_bot"} if method == "getMe" else True
        self.remote.make_bot = lambda token: Bot()
        self.remote.start(BOT_TOKEN)
        deadline = time.monotonic() + 3
        while "getUpdates" not in calls and time.monotonic() < deadline:
            time.sleep(0.02)
        self.remote.stop(going=True)
        self.assertEqual(calls[:3], ["getMe", "deleteWebhook", "getUpdates"])
        self.assertEqual([body["going"] for body in self.sent], [False, True])  # checked in at start and on the way out


class TakeBackTests(unittest.TestCase):
    def test_a_webhook_set_by_the_relay_while_the_pc_runs_is_removed_again(self) -> None:
        calls: list[str] = []

        class Bot:
            conflicts = 1

            def call(self, method, params=None, timeout=30, upload=None):
                calls.append(method)
                if method == "getUpdates":
                    if Bot.conflicts:
                        Bot.conflicts -= 1
                        raise remote.TelegramError("Telegram said 409: webhook is active", code=409)
                    time.sleep(0.05)
                    return []
                return {"username": "nova_bot"} if method == "getMe" else True
        telegram = remote.TelegramRemote(ask=lambda *_: "", transcribe=lambda _p: "", load=dict, save=lambda _d: None,
                                         bot=lambda token: Bot())
        with patch.object(remote, "RETRY_SECONDS", (0.01,)):
            telegram.start(BOT_TOKEN)
            deadline = time.monotonic() + 3
            while calls.count("getUpdates") < 2 and time.monotonic() < deadline:
                time.sleep(0.02)
            telegram.stop()
        self.assertEqual(calls[:5], ["getMe", "deleteWebhook", "getUpdates", "deleteWebhook", "getUpdates"])


class ReminderTimesTests(unittest.TestCase):
    def test_the_next_three_days_of_reminders_for_the_relay(self) -> None:
        from datetime import datetime
        from reminders import Reminders
        now = datetime(2026, 11, 20, 9, 0)
        reminders = Reminders(Path(tempfile.mkdtemp()) / "r.json", clock=lambda: now)
        reminders.add("stretch", "2026-11-20 10:00", "daily")
        reminders.add("call mom", "2026-11-21 17:00")
        times = reminders.upcoming(hours=72)
        self.assertEqual([entry["key"] for entry in times], [
            "1@2026-11-20 10:00", "1@2026-11-21 10:00", "2@2026-11-21 17:00", "1@2026-11-22 10:00"])  # 72 h ends 09:00 on the 23rd
        self.assertEqual(times[0]["due"], int(datetime(2026, 11, 20, 10, 0).timestamp()))


@unittest.skipUnless(shutil.which("node"), "the relay's own tests need Node.js")
class WorkerTests(unittest.TestCase):
    def test_the_relay_passes_its_tests(self) -> None:
        result = subprocess.run(["node", "--test", "cloud/worker.test.mjs"], cwd=ROOT, capture_output=True, text=True,
                                timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
