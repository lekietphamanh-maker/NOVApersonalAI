from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from memory import Memory
from tools import TOOLS, execute_tool


class ToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.memory = Memory(Path(self.temp_dir.name) / "test.sqlite3")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_only_the_task_tool_is_advertised(self) -> None:
        self.assertEqual([item["function"]["name"] for item in TOOLS], ["add_task"])

    def test_approved_action_writes_task(self) -> None:
        result = execute_tool("add_task", {"task": "Pay rent"}, self.memory, lambda *_: True)
        self.assertIn("Saved task", result)
        self.assertEqual(self.memory.list_tasks()[0]["task"], "Pay rent")

    def test_declined_action_does_not_write(self) -> None:
        result = execute_tool("add_task", {"task": "Pay rent"}, self.memory, lambda *_: False)
        self.assertIn("declined", result)
        self.assertEqual(self.memory.list_tasks(), [])

    def test_unknown_or_extra_arguments_do_not_write(self) -> None:
        approve: Any = lambda *_: self.fail("Approval must not be requested for invalid tools")
        self.assertIn("not available", execute_tool("run_shell", {}, self.memory, approve))
        self.assertIn("invalid", execute_tool("add_task", {"task": "Pay rent", "path": "x"}, self.memory, approve))
        self.assertEqual(self.memory.list_tasks(), [])


if __name__ == "__main__":
    unittest.main()
