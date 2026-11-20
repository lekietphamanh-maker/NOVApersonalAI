"""Optional Whisper speech recognition (whisper.cpp): much better than Vosk with accents and broken English.

Downloaded only when the user asks (about 190 MB) into this edition's data folder, then run locally on
loopback. Audio never leaves the PC.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
import wave
import zipfile
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

SERVER_ZIP = "https://github.com/ggml-org/whisper.cpp/releases/download/v1.9.2/whisper-bin-x64.zip"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en-q5_1.bin"
MODEL_NAME = "ggml-small.en-q5_1.bin"
DOWNLOAD_MB = 190
PORT = 8179
# Words Whisper should expect; it biases recognition toward these spellings.
VOCABULARY = "Hey Nova, Ollama, screen assist, creative mode, homework, Claude, Gmail."


def folder() -> Path:
    base = os.environ.get("ALFRED_DATA_DIR") or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Alfred" / "DesktopData"
    return Path(base) / "whisper"


def installed() -> bool:
    return (folder() / "whisper-server.exe").is_file() and (folder() / MODEL_NAME).is_file()


def _download(url: str, destination: Path, progress: Callable[[str], None], label: str) -> None:
    partial = destination.with_suffix(destination.suffix + ".part")
    with urlopen(Request(url, headers={"User-Agent": "Nova"}), timeout=60) as response, partial.open("wb") as output:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while chunk := response.read(1 << 20):
            output.write(chunk)
            done += len(chunk)
            if total:
                progress(f"Downloading {label}: {done * 100 // total}%")
    os.replace(partial, destination)


def install(progress: Callable[[str], None]) -> None:
    """Download whisper-server and the English model. Existing files are kept; a failed download leaves no partial files."""
    target = folder()
    target.mkdir(parents=True, exist_ok=True)
    if not (target / "whisper-server.exe").is_file():
        with tempfile.TemporaryDirectory() as scratch:
            archive = Path(scratch) / "whisper.zip"
            _download(SERVER_ZIP, archive, progress, "Whisper program")
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(Path(scratch) / "unpacked")
            server = next((Path(scratch) / "unpacked").rglob("whisper-server.exe"))
            for item in server.parent.iterdir():  # the server needs the DLLs beside it
                shutil.copy2(item, target / item.name)
    if not (target / MODEL_NAME).is_file():
        _download(MODEL_URL, target / MODEL_NAME, progress, "English speech model")
    progress("Whisper is installed.")


def wav_bytes(pcm16: bytes, sample_rate: int = 16_000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(sample_rate)
        file.writeframes(pcm16)
    return buffer.getvalue()


class WhisperEngine:
    """Starts whisper-server on first use and keeps it running until stop()."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self.base_url = f"http://127.0.0.1:{PORT}"

    def _responding(self) -> bool:
        try:
            with urlopen(self.base_url, timeout=0.5):
                return True
        except OSError:
            return False

    def _ensure_started(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        threads = str(max(2, min(8, (os.cpu_count() or 4) - 2)))
        self._process = subprocess.Popen(
            [str(folder() / "whisper-server.exe"), "-m", str(folder() / MODEL_NAME), "--host", "127.0.0.1",
             "--port", str(PORT), "-t", threads, "-ac", "768"],  # audio up to ~15 s: about twice as fast
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise RuntimeError("Whisper stopped while starting.")
            if self._responding():
                return
            time.sleep(0.25)
        raise RuntimeError("Whisper did not start in time.")

    def transcribe(self, pcm16: bytes, sample_rate: int = 16_000) -> str:
        self._ensure_started()
        boundary = uuid.uuid4().hex
        fields = {"response_format": "json", "temperature": "0", "language": "en", "prompt": VOCABULARY}
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
                 for name, value in fields.items()]
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\n'
                     "Content-Type: audio/wav\r\n\r\n".encode() + wav_bytes(pcm16, sample_rate) + b"\r\n")
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        request = Request(f"{self.base_url}/inference", data=body, method="POST",
                          headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urlopen(request, timeout=60) as response:
            text = str(json.loads(response.read()).get("text", ""))
        # Whisper writes these for silence and noise.
        for marker in ("[BLANK_AUDIO]", "[MUSIC]", "[NOISE]", "(silence)"):
            text = text.replace(marker, "")
        return " ".join(text.split())

    def stop(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.kill()
        self._process = None
