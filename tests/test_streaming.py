"""Streaming replies: Ollama's streamed chat, cutting text into sentences, speaking them in order and stopping."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

from agent import Agent
from memory import Memory
from voice import SentenceSpeaker, SentenceSplitter


class SplitterTests(unittest.TestCase):
    def test_sentences_come_out_as_soon_as_they_end(self):
        out: list[str] = []
        splitter = SentenceSplitter(out.append)
        for piece in ["The capital", " of Vietnam is Hà Nội. It has", " about 8.5 million people!", " Bún chả is"]:
            splitter.feed(piece)
        self.assertEqual(out, ["The capital of Vietnam is Hà Nội.", "It has about 8.5 million people!"])
        splitter.flush()
        self.assertEqual(out[-1], "Bún chả is")

    def test_the_first_piece_can_end_at_a_comma_so_she_starts_sooner(self):
        out: list[str] = []
        splitter = SentenceSplitter(out.append)
        splitter.feed("Sure, the weather in Da Nang is warm today, around 28 degrees, with some rain later. Then, it")
        self.assertEqual(out, ["Sure, the weather in Da Nang is warm today,", "around 28 degrees, with some rain later."])
        splitter.flush()
        splitter.feed("Okay, the next reply starts over, like the first.")
        self.assertEqual(out[-2:], ["Then, it", "Okay, the next reply starts over,"])

    def test_short_pieces_join_the_next_sentence(self):
        out: list[str] = []
        splitter = SentenceSplitter(out.append)
        splitter.feed("Ok. 1. Click File, then Export.\n- Choose PDF\n")
        self.assertEqual(out, ["Ok. 1. Click File, then Export.", "- Choose PDF"])


class SpeakerTests(unittest.TestCase):
    def test_plays_in_order_reports_busy_and_stop_drops_the_rest(self):
        played: list[str] = []
        busy: list[bool] = []
        release = threading.Event()

        def play(prepared, stop):
            played.append(prepared)
            if prepared == "FIRST.":
                release.wait(2)

        speaker = SentenceSpeaker(lambda text: text.upper(), play, on_busy=busy.append)
        for sentence in ("first.", "second.", "third."):
            speaker.say(sentence)
        time.sleep(0.2)
        speaker.stop()  # while "first." plays: the rest must never play
        release.set()
        time.sleep(0.2)
        self.assertEqual(played, ["FIRST."])
        self.assertEqual(busy, [True, False])
        speaker.say("again.")
        time.sleep(0.3)
        self.assertEqual(played, ["FIRST.", "AGAIN."])
        self.assertEqual(busy, [True, False, True, False])
        self.assertFalse(speaker.busy)


class _StreamingOllama(BaseHTTPRequestHandler):
    replies: list[list[dict]] = []

    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert body["stream"] is True
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for chunk in _StreamingOllama.replies.pop(0):
            self.wfile.write((json.dumps(chunk) + "\n").encode())
            self.wfile.flush()

    def log_message(self, *_args) -> None:
        pass


class AgentStreamingTests(unittest.TestCase):
    def test_text_streams_and_tool_calls_still_run(self):
        _StreamingOllama.replies = [
            [{"message": {"content": "Sure, "}}, {"message": {"content": "saving it."}},
             {"message": {"content": "", "tool_calls": [{"function": {"name": "add_task", "arguments": {"task": "Buy milk"}}}]}},
             {"done": True}],
            [{"message": {"content": "Saved. "}}, {"message": {"content": "Anything else?"}}, {"done": True}],
        ]
        server = HTTPServer(("127.0.0.1", 0), _StreamingOllama)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        pieces: list[str] = []
        try:
            with tempfile.TemporaryDirectory() as folder, \
                    patch.dict(os.environ, {"ALFRED_API_URL": f"http://127.0.0.1:{server.server_address[1]}"}):
                memory = Memory(Path(folder) / "m.sqlite3")
                agent = Agent(model="test", memory=memory)
                reply = agent.ask("remind me to buy milk", lambda *_: True, on_text=pieces.append)
                tasks = [item["task"] for item in memory.list_tasks()]
        finally:
            server.shutdown()
        self.assertEqual(reply, "Saved. Anything else?")
        self.assertEqual(pieces, ["Sure, ", "saving it.", "Saved. ", "Anything else?"])
        self.assertEqual(tasks, ["Buy milk"])
        self.assertIsNone(agent.on_text)


if __name__ == "__main__":
    unittest.main()
