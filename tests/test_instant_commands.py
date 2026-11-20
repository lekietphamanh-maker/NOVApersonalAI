"""Instant commands: the everyday requests done without any AI, and everything else still going to the model."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import instant_commands as quick
from agent import Agent
from memory import Memory


class MatchTests(unittest.TestCase):
    def test_timers(self) -> None:
        cases = {"Set a timer for 5 minutes": {"minutes": 5, "seconds": 0},
                 "nova, 10 minute timer for tea": {"minutes": 10, "seconds": 0, "label": "tea"},
                 "timer for 3 min": {"minutes": 3, "seconds": 0}, "start a 90 second timer": {"minutes": 1, "seconds": 30},
                 "set a timer for two hours": {"minutes": 120, "seconds": 0},
                 "set timer for half an hour": {"minutes": 30, "seconds": 0}}
        for said, arguments in cases.items():
            self.assertEqual(quick.match(said), quick.Instant("set_timer", arguments), said)
        self.assertEqual(quick.match("cancel the timer").tool, "cancel_timer")
        self.assertIsNone(quick.match("set a timer for 900 hours"))

    def test_sound_music_time_and_apps(self) -> None:
        self.assertEqual(quick.match("turn it down a lot").arguments, {"action": "volume_down", "times": 10})
        self.assertEqual(quick.match("louder please").arguments["action"], "volume_up")
        self.assertEqual(quick.match("next song").arguments["action"], "next")
        self.assertEqual(quick.match("pause").arguments["action"], "play_pause")
        self.assertEqual(quick.match("What time is it?").tool, "time")
        self.assertEqual(quick.match("open Spotify"), quick.Instant("open", {"app": "spotify"}))
        self.assertEqual(quick.spoken_time(datetime(2026, 11, 20, 9, 5)), "It's 09:05.")

    def test_anything_more_goes_to_the_ai(self) -> None:
        for said in ("set a timer for 5 minutes and remind me to call mom", "what's the weather", "play some jazz",
                     "open the pod bay doors", "why is the sky blue", "pause the video when the ad starts"):
            self.assertIsNone(quick.match(said), said)


class AgentTests(unittest.TestCase):
    def test_done_without_any_model(self) -> None:
        agent = Agent(model="test", memory=Memory(Path(tempfile.mkdtemp()) / "m.sqlite3"))
        started: list = []
        agent.timers = type("Timers", (), {"start": lambda self, seconds, label: started.append((seconds, label)) or
                                           "Timer set: 5 minutes."})()
        agent._chat = lambda *_a, **_k: self.fail("no model should be asked")
        self.assertEqual(agent.ask("set a timer for 5 minutes", lambda *_: True), "Timer set: 5 minutes.")
        self.assertEqual(started, [(300, "")])
        self.assertEqual(agent.memory.recent_messages(limit=2)[-1]["brain"], "instant")
        self.assertIn("without AI", __import__("agent").describe_timing(agent.turn_stats))
        with patch("media_keys.press") as press:
            self.assertEqual(agent.ask("next song", lambda *_: True), "Next one.")
        press.assert_called_once_with("next", 1)


if __name__ == "__main__":
    unittest.main()
