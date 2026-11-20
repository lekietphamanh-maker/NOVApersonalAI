"""Screen recording (Cap's idea, Nova's own code): "record my screen" … "stop recording" makes an MP4 of the whole
desktop in Videos/Nova Recordings, with ffmpeg. On Windows ffmpeg is downloaded once into Nova's data folder (the
BtbN build on GitHub); on the Mac it's Homebrew's (brew install ffmpeg)."""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

FFMPEG_ZIP = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
FOLDER = Path.home() / "Videos" / "Nova Recordings"


def ffmpeg_path(data_dir: Path) -> str | None:
    own = Path(data_dir) / "ffmpeg" / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if own.exists():
        return str(own)
    found = shutil.which("ffmpeg")
    if found:
        return found
    if sys.platform == "darwin":
        for folder in ("/opt/homebrew/bin", "/usr/local/bin"):
            if Path(folder, "ffmpeg").exists():
                return f"{folder}/ffmpeg"
    return None


def install_ffmpeg(data_dir: Path, progress: Callable[[str], None] = lambda text: None,
                   opener: Callable[..., Any] = urlopen) -> str:
    """Windows: the ffmpeg build from GitHub, unpacked to <data>/ffmpeg (only ffmpeg.exe is kept)."""
    if sys.platform != "win32":
        raise RuntimeError("install ffmpeg with Homebrew: brew install ffmpeg")
    progress("Downloading ffmpeg for screen recording (about 140 MB)")
    with opener(Request(FFMPEG_ZIP, headers={"User-Agent": "Nova"}), timeout=600) as response:
        data = response.read()
    target = Path(data_dir) / "ffmpeg"
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        member = next(name for name in archive.namelist() if name.endswith("/bin/ffmpeg.exe"))
        (target / "ffmpeg.exe").write_bytes(archive.read(member))
    return str(target / "ffmpeg.exe")


def arguments(ffmpeg: str, out: Path, platform: str = sys.platform, fps: int = 30) -> list[str]:
    if platform == "win32":
        source = ["-f", "gdigrab", "-framerate", str(fps), "-draw_mouse", "1", "-i", "desktop"]
    elif platform == "darwin":
        source = ["-f", "avfoundation", "-framerate", str(fps), "-capture_cursor", "1", "-i", "Capture screen 0"]
    else:
        source = ["-f", "x11grab", "-framerate", str(fps), "-i", os.environ.get("DISPLAY", ":0")]
    return [ffmpeg, "-y", *source, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26", "-pix_fmt", "yuv420p",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", str(out)]


class Recorder:
    def __init__(self, data_dir: Path, folder: Path = FOLDER, popen: Callable[..., Any] = subprocess.Popen,
                 clock: Callable[[], datetime] = datetime.now) -> None:
        self.data_dir, self.folder, self._popen, self._clock = Path(data_dir), Path(folder), popen, clock
        self.process: Any = None
        self.file: Path | None = None
        self.started: datetime | None = None

    def start(self) -> str:
        if self.process is not None and self.process.poll() is None:
            return f"Already recording (since {self.started:%H:%M}). Say stop recording to finish."
        ffmpeg = ffmpeg_path(self.data_dir)
        if ffmpeg is None:
            raise RuntimeError("screen recording needs ffmpeg: SETTINGS → Downloads (or Set up everything)")
        self.folder.mkdir(parents=True, exist_ok=True)
        self.started = self._clock()
        self.file = self.folder / f"Screen {self.started:%Y-%m-%d %H%M%S}.mp4"
        flags = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if sys.platform == "win32" else {}
        self.process = self._popen(arguments(ffmpeg, self.file), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, **flags)
        return "Recording the screen. Say stop recording when you're done."

    def stop(self) -> str:
        if self.process is None or self.process.poll() is not None:
            return "Nothing is being recorded."
        try:
            self.process.stdin.write(b"q")  # ffmpeg finishes the file properly on q
            self.process.stdin.flush()
            self.process.wait(timeout=20)
        except Exception:
            self.process.kill()
        minutes = (self._clock() - self.started).total_seconds() / 60 if self.started else 0
        self.process = None
        return f"Saved {minutes:.1f} minutes of screen recording: {self.file}"

    def status(self) -> str:
        if self.process is not None and self.process.poll() is None:
            return f"Recording since {self.started:%H:%M}: {self.file.name}"
        return "Not recording."
