"""The lite versions of the owner's repos: an SEO check (open-seo), free time from the calendar (cal.diy), screen
recording (Cap), pictures on the API brain (Open-Generative-AI), and dictation (OpenWhispr)."""
from __future__ import annotations

import base64
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

import api_brains
import calendar_tools
import screen_record
import seo_check

PAGE = b"""<html lang="en"><head><title>Klee - portfolio of games and AI projects</title>
<meta name="description" content="Games, AI tools and experiments by Klee: Project W, Nova and more, with code and demos.">
<meta name="viewport" content="width=device-width"><link rel="canonical" href="https://klee.dev/">
<meta property="og:title" content="Klee"><meta property="og:image" content="/og.png"></head>
<body><h1>Klee</h1><h2>Projects</h2><img src="a.png"><img src="b.png" alt="Nova">
<a href="/projects">Projects</a><a href="https://github.com/klee">GitHub</a><p>""" + b"word " * 320 + b"</p></body></html>"


class Answer(io.BytesIO):
    def __init__(self, data: bytes, url: str = "", status: int = 200) -> None:
        super().__init__(data)
        self.status, self._url, self.headers = status, url, {"Content-Type": "text/html"}

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class SeoTests(unittest.TestCase):
    def test_what_to_fix_first_and_what_is_good(self) -> None:
        def opener(request, timeout):
            if request.full_url.endswith("/sitemap.xml"):
                raise HTTPError(request.full_url, 404, "no", {}, None)
            return Answer(PAGE if request.full_url.startswith("https://klee.dev/") and "robots" not in request.full_url
                          else b"User-agent: *", request.full_url)
        times = iter([0.0, 0.4])
        report = seo_check.check("klee.dev/", opener, lambda: next(times))
        fixes, good = report.split("Already good:")
        self.assertIn("Link previews (Open Graph): 2 of 3 set", fixes)
        self.assertIn("1 of 2 images without alt text", fixes)
        self.assertIn("/sitemap.xml missing", fixes)
        self.assertIn("1 main heading(s) (h1): Klee", good)
        self.assertIn("1 internal and 1 external links", good)
        self.assertIn("/robots.txt found", good)


class FreeTimeTests(unittest.TestCase):
    def test_free_slots_skip_busy_times_and_weekends(self) -> None:
        now = datetime(2026, 11, 20, 8, 0)  # a Friday morning
        busy = {"calendars": {"primary": {"busy": [
            {"start": datetime(2026, 11, 20, 9, 0).astimezone().isoformat(), "end": datetime(2026, 11, 20, 12, 0).astimezone().isoformat()}]}}}
        asked: list = []

        def opener(request, timeout):
            asked.append(json.loads(request.data))
            return Answer(json.dumps(busy).encode())
        calendar = calendar_tools.Calendar(token=lambda: "t", opener=opener)
        answer = calendar.free_time(60, 3, now=now)
        lines = [line for line in answer.splitlines() if line.startswith("- ")]
        self.assertEqual(lines[0], "- Fri 20 Nov 12:00–13:00")  # after the busy morning
        self.assertFalse(any("Sat" in line or "Sun" in line for line in lines))
        self.assertTrue(any(line.startswith("- Mon 23 Nov 09:00") for line in lines))
        self.assertIn("A message the owner can send: Would any of these work for you?", answer)
        self.assertEqual(asked[0]["items"], [{"id": "primary"}])


class RecorderTests(unittest.TestCase):
    def test_start_stop_and_the_ffmpeg_line(self) -> None:
        started: list = []

        class Process:
            def __init__(self) -> None:
                self.stdin, self.ended = io.BytesIO(), None

            def poll(self):
                return self.ended

            def wait(self, timeout=None):
                self.ended = 0

        def popen(arguments, **options):
            started.append(arguments)
            return Process()
        folder = Path(tempfile.mkdtemp())
        clock = iter([datetime(2026, 11, 20, 10, 0), datetime(2026, 11, 20, 10, 3)])
        with mock.patch.object(screen_record, "ffmpeg_path", lambda data: "/bin/ffmpeg"):
            recorder = screen_record.Recorder(folder, folder / "videos", popen, lambda: next(clock))
            self.assertIn("Recording the screen", recorder.start())
            self.assertIn("Already recording", recorder.start())
            self.assertIn("Saved 3.0 minutes", recorder.stop())
        self.assertEqual(len(started), 1)
        self.assertEqual(screen_record.arguments("ffmpeg", Path("x.mp4"), "win32")[2:7],
                         ["-f", "gdigrab", "-framerate", "30", "-draw_mouse"])
        with mock.patch.object(screen_record, "ffmpeg_path", lambda data: None):
            with self.assertRaises(RuntimeError):
                screen_record.Recorder(folder).start()


class ImageTests(unittest.TestCase):
    def test_a_picture_is_saved_from_the_images_endpoint(self) -> None:
        sent: list = []

        def opener(request, timeout):
            sent.append((request.full_url, json.loads(request.data)))
            return Answer(json.dumps({"data": [{"b64_json": base64.b64encode(b"\x89PNG fake").decode()}]}).encode())
        path = api_brains.make_image("https://api.openai.com/v1", "sk", "a neon street", Path(tempfile.mkdtemp()), opener=opener)
        self.assertEqual(path.read_bytes(), b"\x89PNG fake")
        self.assertEqual(sent[0][0], "https://api.openai.com/v1/images/generations")
        self.assertEqual((sent[0][1]["model"], sent[0][1]["prompt"]), ("gpt-image-1", "a neon street"))


class DictationTests(unittest.TestCase):
    def test_the_dictate_key_does_not_clash(self) -> None:
        import hotkeys
        others = [keys for which, keys in hotkeys.DEFAULTS.items() if which != "dictate"]
        self.assertEqual(hotkeys.check("dictate", hotkeys.DEFAULTS["dictate"], others)[1], "")


if __name__ == "__main__":
    unittest.main()
