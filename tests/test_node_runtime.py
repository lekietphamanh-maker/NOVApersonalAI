"""Finding Node.js: PATH gained after Nova started, the usual install places, the owner's own node.exe, Node first on
PATH for npx, and REA saying whether Node is missing or too old."""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import node_runtime
import reverse_engineering as rea


class NodeRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        patcher = patch.dict(os.environ, {"PATH": str(self.root / "empty"), "ProgramFiles": str(self.root / "pf"),
                                          "LOCALAPPDATA": str(self.root / "local"), "APPDATA": str(self.root / "roaming"),
                                          "USERPROFILE": str(self.root / "home"), "NVM_HOME": "", "NVM_SYMLINK": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_node(self, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        node = folder / node_runtime.NODE
        node.write_text("#!/bin/sh\necho v24.22.1\n")
        node.chmod(0o755)
        return node

    def test_path_added_after_nova_started_is_picked_up(self) -> None:
        node = self.make_node(self.root / "fresh")
        self.assertEqual(node_runtime.find(fresh=lambda: [str(node.parent)]), node)
        self.assertIn(str(node.parent), os.environ["PATH"].split(os.pathsep))

    def test_the_usual_install_places_and_the_owners_choice(self) -> None:
        installed = self.make_node(self.root / "pf" / "nodejs")
        self.assertEqual(node_runtime.find(fresh=lambda: []), installed)
        portable = self.make_node(self.root / "Tools" / "node-v24")
        self.assertEqual(node_runtime.find(str(portable.parent), fresh=lambda: []), portable)  # its folder works too
        self.assertIsNone(node_runtime.chosen(str(self.root / "nowhere")))

    def test_found_node_goes_first_on_path(self) -> None:
        node = self.make_node(self.root / "fresh")
        node_runtime.use(node)
        self.assertEqual(os.environ["PATH"].split(os.pathsep)[0], str(node.parent))

    def test_version_and_rea_messages(self) -> None:
        node = self.make_node(self.root / "pf" / "nodejs")
        answer = lambda *a, **k: subprocess.CompletedProcess(a, 0, "v20.11.0\n", "")  # noqa: E731
        self.assertEqual(node_runtime.version(node, answer), (20, 11, 0))
        job = rea.ReverseEngineering(save=None, library=None, done=None, workspace=Path("."), command=lambda: "claude",
                                     node=lambda: (20, 11, 0))
        self.assertIn("Node.js 20.11.0 is too old", job.problem())
        job.node = lambda: None
        self.assertIn("can't find Node.js", job.problem())


if __name__ == "__main__":
    unittest.main()
