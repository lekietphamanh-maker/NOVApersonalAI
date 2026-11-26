"""Every edition keeps memory and idea maps in the same folder, and the newest copy wins once, nothing deleted."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

import data_folder


class DataFolderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.local, self.home = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        patcher = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.local), "HOME": str(self.home),
                                               "USERPROFILE": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("ALFRED_DATA_DIR", None)
        self.old = data_folder.earlier_places(self.local, self.home)

    def memory_at(self, path: Path, fact: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db, db:  # closed: Windows can't move a file that is still open
            db.execute("CREATE TABLE facts (fact TEXT)")
            db.execute("INSERT INTO facts VALUES (?)", (fact,))

    def test_a_launcher_folder_is_left_alone(self) -> None:
        with mock.patch.dict(os.environ, {"ALFRED_DATA_DIR": str(self.home / "USB")}):
            self.assertEqual(data_folder.unify(), self.home / "USB")

    def test_the_installed_editions_memory_and_maps_come_along(self) -> None:
        self.memory_at(self.old["memory.sqlite3"], "likes tea")
        self.old["visual_notes.json"].parent.mkdir(parents=True)
        self.old["visual_notes.json"].write_text(json.dumps({"maps": ["trip"]}), encoding="utf-8")
        folder = data_folder.unify()
        self.assertEqual(os.environ["ALFRED_DATA_DIR"], str(folder))
        with closing(sqlite3.connect(folder / "memory.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT fact FROM facts").fetchall(), [("likes tea",)])
        self.assertIn("trip", (folder / "visual_notes.json").read_text(encoding="utf-8"))
        self.assertTrue(self.old["memory.sqlite3"].is_file())  # the old copy stays where it was

    def test_the_newer_copy_wins_and_the_older_is_kept_as_bak(self) -> None:
        folder = self.local / "Alfred" / "DesktopData"
        self.memory_at(folder / "memory.sqlite3", "from the zip edition")
        os.utime(folder / "memory.sqlite3", (1_000, 1_000))
        self.memory_at(self.old["memory.sqlite3"], "from the installed edition")
        data_folder.unify()
        with closing(sqlite3.connect(folder / "memory.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT fact FROM facts").fetchall(), [("from the installed edition",)])
        self.assertTrue((folder / "memory.sqlite3.bak").is_file())
        os.environ.pop("ALFRED_DATA_DIR")
        data_folder.unify()  # the next start: the data folder's copy is newest now, nothing moves again
        self.assertFalse((folder / "memory.sqlite3.bak.bak").exists())
        with closing(sqlite3.connect(folder / "memory.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT fact FROM facts").fetchall(), [("from the installed edition",)])


if __name__ == "__main__":
    unittest.main()
