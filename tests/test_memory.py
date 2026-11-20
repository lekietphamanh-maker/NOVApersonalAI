from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory import Memory


class MemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.memory = Memory(Path(self.temp_dir.name) / "test.sqlite3")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_messages_round_trip_with_tool_metadata(self) -> None:
        self.memory.save_message({"role": "user", "content": "Add a task."})
        self.memory.save_message({
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "add_task", "arguments": {"task": "Call home"}}}],
        })
        messages = self.memory.recent_messages()
        self.assertEqual(messages[0]["content"], "Add a task.")
        self.assertEqual(messages[1]["tool_calls"][0]["function"]["name"], "add_task")

    def test_task_is_saved_and_normalized(self) -> None:
        task_id = self.memory.add_task("  Call   home\n today  ")
        self.assertGreater(task_id, 0)
        self.assertEqual(self.memory.list_tasks()[0]["task"], "Call home today")

    def test_task_rejects_empty_and_overlong_values(self) -> None:
        for value in ("  \n ", "x" * 241):
            with self.subTest(value_length=len(value)), self.assertRaises(ValueError):
                self.memory.add_task(value)

    def test_empty_history_is_safe(self) -> None:
        self.assertEqual(self.memory.recent_messages(), [])
        self.assertEqual(self.memory.list_tasks(), [])


if __name__ == "__main__":
    unittest.main()
