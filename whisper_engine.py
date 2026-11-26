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
# key -> (model file, download URL, size in MB, can it hear languages other than English?)
MODELS = {
    # Small English: the default. Quick on a CPU, good with accents; English only.
    "small.en": ("ggml-small.en-q5_1.bin",
                 "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en-q5_1.bin", 190, False),
    # Medium English: hears noticeably better (accents, mumbled words, names), about three times slower and bigger.
    "medium.en": ("ggml-medium.en-q5_0.bin",
                  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.en-q5_0.bin", 515, False),
    # Small multilingual: same size class as small.en, hears other languages too (Vietnamese included) when the
    # language is left to auto-detect; a little less accurate in English than small.en.
    "small": ("ggml-small-q5_1.bin",
              "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small-q5_1.bin", 190, True),
}
DEFAULT_MODEL = "small.en"
DOWNLOAD_MB = MODELS[DEFAULT_MODEL][2]
PORT = 8179
# Words Whisper should expect; it biases recognition toward these spellings.
VOCABULARY = "Hey Nova, Ollama, screen assist, creative mode, homework, Claude, Gmail."
# The owner's own words, added to the prompt above; the user can edit this list in Settings.
DEFAULT_VOCABULARY = ["Kiet", "Keith", "Hey Nova", "screen assist", "building mode", "trading",
                      "workplace", "homework", "ECO 251", "CHM 151", "microeconomics", "thermochemistry"]


def build_prompt(extra_words: list[str] | None = None) -> str:
    """The hint Whisper is given: the built-in words plus the owner's own, de-duplicated and kept short
    (a very long prompt drowns the hint)."""
    words: list[str] = []
    for word in [VOCABULARY, ", ".join(extra_words or [])]:
        for part in word.split(","):
            part = part.strip()
            if part and part.casefold() not in {item.casefold() for item in words}:
                words.append(part)
    prompt = ", ".join(words) + "."
    return prompt if len(prompt) <= 900 else prompt[:900].rsplit(",", 1)[0] + "."


def model_options() -> list[dict[str, object]]:
    """Every installable model, for Settings: key, file, size and whether it hears other languages."""
    return [{"key": key, "file": value[0], "mb": value[2], "multilingual": value[3],
             "installed": (folder() / value[0]).is_file()} for key, value in MODELS.items()]


def installed_any() -> bool:
    return (folder() / "whisper-server.exe").is_file() and any(
        (folder() / value[0]).is_file() for value in MODELS.values())


def selected_model_file(preferred: str | None = None) -> str | None:
    """The model file to run: the preferred one when it is downloaded, else any downloaded model
    (small.en first), else None."""
    order = [preferred] if preferred in MODELS else []
    order += [key for key in MODELS if key not in order]
    for key in order:
        if (folder() / MODELS[key][0]).is_file():
            return MODELS[key][0]
    return None


def folder() -> Path:
    base = os.environ.get("ALFRED_DATA_DIR") or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Alfred" / "DesktopData"
    return Path(base) / "whisper"


def installed(model: str = DEFAULT_MODEL) -> bool:
    return (folder() / "whisper-server.exe").is_file() and (folder() / MODELS.get(model, MODELS[DEFAULT_MODEL])[0]).is_file()


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


def install(progress: Callable[[str], None], model: str = DEFAULT_MODEL) -> None:
    """Download whisper-server and the chosen speech model. Existing files are kept; a failed download leaves no partial files."""
    key = model if model in MODELS else DEFAULT_MODEL
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
    name, url, _mb, _multilingual = MODELS[key]
    if not (target / name).is_file():
        _download(url, target / name, progress, "English speech model" if key == DEFAULT_MODEL else "speech model")
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
    """Starts whisper-server on first use and keeps it running until stop().

    `model` is the preferred model key from MODELS; when it isn't downloaded yet the engine runs the
    best model that is, so picking a new model in Settings never silences Whisper. `language` is "en",
    or "auto" to let the server detect the language — only with a multilingual model; English-only
    models are always run in English.
    """

    def __init__(self, model: str | None = None, vocabulary: list[str] | None = None,
                 language: str = "en") -> None:
        self._process: subprocess.Popen | None = None
        self.base_url = f"http://127.0.0.1:{PORT}"
        self.model_key = model if model in MODELS else DEFAULT_MODEL
        self.model_file = selected_model_file(self.model_key) or MODELS[self.model_key][0]
        self.language = language if language == "auto" and MODELS[self.model_key][3] else "en"
        self.prompt = build_prompt(vocabulary if vocabulary is not None else DEFAULT_VOCABULARY)

    def _responding(self) -> bool:
        try:
            with urlopen(self.base_url, timeout=0.5):
                return True
        except OSError:
            return False

    def _ensure_started(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        if self._responding():  # left running by a Nova that crashed: a second server couldn't take the port
            return
        threads = str(max(2, min(8, (os.cpu_count() or 4) - 2)))
        self._process = subprocess.Popen(
            [str(folder() / "whisper-server.exe"), "-m", str(folder() / self.model_file), "--host", "127.0.0.1",
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
        # whisper-server starts every request from its own default ("en"), so "auto" has to be asked for by name.
        fields = {"response_format": "json", "temperature": "0", "prompt": self.prompt, "language": self.language}
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
