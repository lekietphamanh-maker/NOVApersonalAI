"""Two PCs sharing Nova's memory and second brain through one folder that the owner syncs (Syncthing).

The folder sync itself is Syncthing's job; here both PCs use the same folder, which is what a finished sync gives.
What Nova must guarantee: each PC writes only its own files, and the PCs agree whatever order changes arrive in.
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path

import pc_sync
from memory import Memory
from pc_sync import SharedMemory
from second_brain import SecondBrain, Vault


def facts(memory: Memory) -> list[str]:
    return sorted(item["fact"] for item in memory.list_facts())


class TwoPcs(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.desktop, self.laptop = self.pc("DESKTOP"), self.pc("LAPTOP")

    def pc(self, name: str) -> Memory:
        memory = Memory(Path(tempfile.mkdtemp()) / "memory.sqlite3")
        memory.shared = SharedMemory(self.folder, name)
        return memory

    def test_a_fact_remembered_on_one_pc_reaches_the_other_and_a_forget_too(self) -> None:
        self.desktop.add_fact("I prefer aisle seats")
        self.desktop.add_task("Book the Hoi An trip")
        self.assertEqual(self.laptop.merge_shared(), 2)
        self.assertEqual(facts(self.laptop), ["I prefer aisle seats"])
        self.assertEqual([task["task"] for task in self.laptop.list_tasks()], ["Book the Hoi An trip"])
        self.assertEqual(self.laptop.forget_facts("aisle seats"), ["I prefer aisle seats"])
        self.desktop.merge_shared()
        self.assertEqual(facts(self.desktop), [])
        self.assertEqual(self.desktop.merge_shared(), 0)  # nothing new: nothing changes, nothing more is logged
        size = sum(path.stat().st_size for path in (self.folder / ".nova" / "memory").glob("*.jsonl"))
        self.laptop.merge_shared()
        self.assertEqual(sum(path.stat().st_size for path in (self.folder / ".nova" / "memory").glob("*.jsonl")), size)

    def test_each_pc_writes_only_its_own_log(self) -> None:
        self.desktop.add_fact("My dog is called Mochi")
        self.laptop.merge_shared()
        self.laptop.delete_fact(self.laptop.list_facts()[0]["id"])
        logs = sorted(path.name for path in (self.folder / ".nova" / "memory").iterdir())
        self.assertEqual(logs, ["DESKTOP.jsonl", "LAPTOP.jsonl"])
        for name in ("DESKTOP", "LAPTOP"):
            lines = (self.folder / ".nova" / "memory" / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual({json.loads(line)["pc"] for line in lines}, {name})

    def test_the_newest_change_wins_whichever_pc_merges_first(self) -> None:
        both = self.pc("LAPTOP")  # a second database for the laptop: merge in the other order
        # the later change is in the log read first (DESKTOP < LAPTOP): reading order must not decide
        self.desktop.shared.record("fact", "forget", "gym on mondays", at=200)
        self.laptop.shared.record("fact", "remember", "Gym on Mondays", at=100)
        self.desktop.merge_shared()
        self.laptop.merge_shared()
        both.merge_shared()
        self.assertEqual((facts(self.desktop), facts(self.laptop), facts(both)), ([], [], []))
        self.desktop.add_fact("Gym on Mondays")  # remembered again, later still: it is back on both
        self.laptop.merge_shared()
        self.assertEqual(facts(self.laptop), ["Gym on Mondays"])

    def test_facts_from_before_sharing_go_to_the_other_pc(self) -> None:
        alone = Memory(Path(tempfile.mkdtemp()) / "memory.sqlite3")
        alone.add_fact("I live in Da Nang")
        alone.add_task("Renew passport")
        alone.shared = SharedMemory(self.folder, "OLDPC")
        alone.merge_shared()
        self.laptop.merge_shared()
        self.assertEqual(facts(self.laptop), ["I live in Da Nang"])
        self.assertEqual([task["task"] for task in self.laptop.list_tasks()], ["Renew passport"])

    def test_a_line_still_arriving_is_skipped(self) -> None:
        self.desktop.add_fact("Coffee, no sugar")
        with (self.folder / ".nova" / "memory" / "DESKTOP.jsonl").open("a", encoding="utf-8") as log:
            log.write('{"kind": "fact", "op": "forg')
        self.laptop.merge_shared()
        self.assertEqual(facts(self.laptop), ["Coffee, no sugar"])

    def test_not_shared_changes_nothing_outside_this_pc(self) -> None:
        alone = Memory(Path(tempfile.mkdtemp()) / "memory.sqlite3")
        alone.add_fact("Private")
        self.assertEqual(alone.merge_shared(), 0)
        self.assertFalse((self.folder / ".nova").exists())

    def test_a_merge_running_while_nova_remembers_loses_nothing(self) -> None:
        def remember() -> None:
            for number in range(30):
                self.desktop.add_fact(f"Fact number {number}")
        writer = threading.Thread(target=remember)
        writer.start()
        while writer.is_alive():
            self.desktop.merge_shared()
        writer.join()
        self.desktop.merge_shared()
        self.laptop.merge_shared()
        self.assertEqual(len(self.laptop.list_facts(limit=100)), 30)
        self.assertEqual(len(self.desktop.list_facts(limit=100)), 30)

    def test_the_other_pc_says_when_it_was_here(self) -> None:
        self.laptop.shared.beat()
        others = self.desktop.shared.others()
        self.assertEqual([other["pc"] for other in others], ["LAPTOP"])
        self.assertLess(time.time() - others[0]["seen"], 5)
        self.assertEqual(pc_sync.ago(30), "just now")
        self.assertEqual(pc_sync.ago(600), "10 min ago")
        self.assertEqual(pc_sync.ago(3 * 86_400), "3 days ago")
        self.assertRegex(pc_sync.this_pc(), r"^[\w.-]+$")


class SharedVaultTests(unittest.TestCase):
    def test_each_pc_writes_its_own_daily_files_and_reads_both(self) -> None:
        folder = Path(tempfile.mkdtemp())
        desktop, laptop = Vault(folder, "DESKTOP", shared=True), Vault(folder, "LAPTOP", shared=True)
        today = datetime.now()
        desktop.append(today, "09:00-09:20", "Read about Rust lifetimes.")
        laptop.append(today, "13:00-13:20", "Watched a video on sourdough.")
        laptop.note("Buy rye flour")
        names = sorted(path.name for path in (folder / "raw" / "activity").iterdir())
        self.assertEqual(names, [f"{today:%Y-%m-%d} DESKTOP.md", f"{today:%Y-%m-%d} LAPTOP.md"])
        self.assertTrue((folder / "raw" / "notes" / f"{today:%Y-%m-%d} LAPTOP.md").exists())
        self.assertEqual(desktop.notes_today(), 2)
        recent = desktop.recent()
        for text in ("Rust lifetimes", "sourdough", "Buy rye flour"):
            self.assertIn(text, recent)

    def test_one_pc_writes_the_wiki_until_it_is_away_for_a_week(self) -> None:
        folder = Path(tempfile.mkdtemp())
        desktop, laptop = Vault(folder, "DESKTOP", shared=True), Vault(folder, "LAPTOP", shared=True)
        SharedMemory(folder, "DESKTOP").beat()
        self.assertTrue(desktop.writes_wiki())  # the first to ingest claims it
        self.assertFalse(laptop.writes_wiki())
        stale = folder / ".nova" / "pcs" / "DESKTOP.json"
        stale.write_text(json.dumps({"pc": "DESKTOP", "seen": time.time() - 8 * 86_400}), encoding="utf-8")
        self.assertTrue(laptop.writes_wiki())  # the desktop is gone: the laptop takes over
        self.assertEqual(laptop.wiki_writer(), "LAPTOP")
        self.assertTrue(Vault(folder, "LAPTOP", shared=False).writes_wiki() and Vault(folder, "DESKTOP").writes_wiki())

    def test_the_other_pcs_ingest_leaves_the_wiki_alone(self) -> None:
        folder = Path(tempfile.mkdtemp())
        SharedMemory(folder, "DESKTOP").beat()
        Vault(folder, "DESKTOP", shared=True).claim_wiki()
        brain = SecondBrain(Vault(folder, "LAPTOP", shared=True), foreground=lambda: ("", "", 0), read_text=str,
                            summarize=str, extract=lambda prompt, schema: self.fail("the laptop must not ingest"))
        (folder / "raw").mkdir(parents=True, exist_ok=True)
        (folder / "raw" / "Article.md").write_text("Something to learn.", encoding="utf-8")
        self.assertIn("DESKTOP writes the wiki", brain.ingest())
        self.assertEqual(list((folder / "wiki").glob("*.md")), [folder / "wiki" / "index.md"])

    def test_syncthing_is_told_to_skip_obsidians_window_layout(self) -> None:
        folder = Path(tempfile.mkdtemp())
        Vault(folder, "DESKTOP").ensure_layout()
        self.assertIn(".obsidian/workspace.json", (folder / ".stignore").read_text(encoding="utf-8"))

    def test_no_whisper_on_videos_while_a_laptop_is_on_battery(self) -> None:
        heard: list[int] = []
        brain = SecondBrain(Vault(Path(tempfile.mkdtemp())), foreground=lambda: ("Lofi beats - YouTube", "chrome", 1),
                            read_text=str, summarize=str, on_battery=lambda: True)
        stop = threading.Event()
        loop = threading.Thread(target=brain._video_loop, args=(stop, lambda: heard.append(1) or "words words words words"))
        loop.start()
        time.sleep(0.3)
        stop.set()
        loop.join(timeout=5)
        self.assertEqual(heard, [])


if __name__ == "__main__":
    unittest.main()
