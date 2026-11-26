"""One folder for everything Nova keeps. The zip and USB launchers set ALFRED_DATA_DIR; the installed Nova.exe and the
Mac start Nova directly, which once put memory (JarvisLocalAssistant) and idea maps (~/.local/share/alfred) apart from
the rest, so moving between editions seemed to lose them. Nova now always sets the folder, and carries the newer copy
of each over once; an older copy already there is kept beside it as .bak, and the old file itself stays where it was."""
from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path


def earlier_places(local: Path, home: Path) -> dict[str, Path]:
    return {"memory.sqlite3": local / "JarvisLocalAssistant" / "memory.sqlite3",
            "visual_notes.json": home / ".local" / "share" / "alfred" / "visual_notes.json"}


def unify() -> Path:
    """Sets ALFRED_DATA_DIR when no launcher did, and brings memory and idea maps into it. Returns the folder."""
    if os.environ.get("ALFRED_DATA_DIR"):
        return Path(os.environ["ALFRED_DATA_DIR"])
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    folder = local / "Alfred" / "DesktopData"
    os.environ["ALFRED_DATA_DIR"] = str(folder)
    for name, old in earlier_places(local, Path.home()).items():
        new = folder / name
        try:
            if not old.is_file() or (new.is_file() and new.stat().st_mtime >= old.stat().st_mtime):
                continue
            folder.mkdir(parents=True, exist_ok=True)
            if new.is_file():
                os.replace(new, new.with_name(name + ".bak"))
            if name.endswith(".sqlite3"):  # SQLite's own copy: safe even with a write-ahead log beside it
                with sqlite3.connect(old) as source, sqlite3.connect(new) as target:
                    source.backup(target)
            else:
                shutil.copy2(old, new)
        except (OSError, sqlite3.Error):
            continue  # Nova still starts; that one stays where it was
    return folder
