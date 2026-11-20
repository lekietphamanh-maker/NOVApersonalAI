"""With a real Ollama (CI starts one): Nova's approved download, then a real streamed answer and a tool call.

Runs only when ALFRED_TEST_OLLAMA=1, against ALFRED_API_URL or the default local Ollama.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from agent import Agent, local_base_url
from hardware_advisor import pull_model
from memory import Memory

MODEL = os.environ.get("ALFRED_TEST_MODEL", "qwen3:0.6b")


@unittest.skipUnless(os.environ.get("ALFRED_TEST_OLLAMA") == "1", "needs a running Ollama (ALFRED_TEST_OLLAMA=1)")
class RealModelTests(unittest.TestCase):
    def test_download_then_stream_a_real_answer(self):
        progress: list[str] = []
        pull_model(local_base_url(), MODEL, progress.append)
        print("download progress, last lines:", progress[-3:])
        self.assertTrue(any("%" in line for line in progress), progress[-5:])

        with tempfile.TemporaryDirectory() as folder:
            agent = Agent(model=MODEL, memory=Memory(Path(folder) / "m.sqlite3"))
            agent.check_ready()
            pieces: list[str] = []
            reply = agent.ask("Say hello to Sam in one short sentence.", lambda *_: False, on_text=pieces.append)
            print("streamed reply:", reply, "| pieces:", len(pieces))
            self.assertTrue(reply.strip())
            self.assertGreater(len(pieces), 1, "the reply did not stream")

            asked: list[str] = []
            reply = agent.ask("Remind me to buy milk: add it as a task.", lambda name, _arguments: asked.append(name) or False)
            print("tool reply:", reply, "| approvals asked:", asked)
            # A 0.6b model does not always call tools; when it does, Nova must ask before saving.
            self.assertEqual(Memory(Path(folder) / "m.sqlite3").list_tasks(), [])

            # ✦ Ask Nova on the brainstorm map: structured ideas from the real model, merged under the idea.
            import visual_notes
            outline = "Gameplay\n  Combat\nStory"
            ideas = visual_notes.suggest_ideas(agent, "My video game", outline, ["Gameplay"])
            print("Ask Nova ideas:", ideas)
            self.assertTrue(ideas and all(isinstance(idea, str) and idea for idea in ideas), ideas)
            merged, added, place = visual_notes.add_ideas(outline, ["Gameplay"], ideas)
            print(merged)
            self.assertEqual(place, "Gameplay")
            self.assertGreater(added, 0)


if __name__ == "__main__":
    unittest.main()
