"""Optional natural-sounding voices, downloaded only when the user picks one: Kokoro (the most natural) and
Piper (lighter). Both run locally on the CPU. Windows' built-in voice stays the fallback.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Callable

import kokoro_voice
from whisper_engine import _download

PIPER_ZIP = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"
# Pinned: newer voice files use a phoneme format this Piper program cannot read.
_VOICE_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
# name -> (path inside the Piper voices repository, or "kokoro:<speaker>"; approximate download in MB)
VOICES = {  # Nova is a woman: female voices first, the most natural on top
    "Heart (US, female, most natural)": ("kokoro:heart", kokoro_voice.DOWNLOAD_MB),
    "Bella (US, female, most natural)": ("kokoro:bella", kokoro_voice.DOWNLOAD_MB),
    "Emma (British, female, most natural)": ("kokoro:emma", kokoro_voice.DOWNLOAD_MB),
    "Amy (US, female)": ("en/en_US/amy/medium/en_US-amy-medium", 85),
    "Lessac (US, female)": ("en/en_US/lessac/medium/en_US-lessac-medium", 85),
    "Jenny (British, female)": ("en/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium", 85),
    "Ryan (US, male)": ("en/en_US/ryan/high/en_US-ryan-high", 140),
    "Alan (British, male)": ("en/en_GB/alan/medium/en_GB-alan-medium", 85),
}


# Not a choice in the list: used by itself for sentences in Vietnamese, which English voices can't say.
VIETNAMESE = "Vietnamese (VAIS1000)"
_EXTRA = {VIETNAMESE: ("vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium", 65)}
_VIETNAMESE_LETTERS = set("ăâđêôơưạảãàáằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ")


def is_vietnamese(text: str) -> bool:
    """A sentence in Vietnamese (letters English never uses), not one Vietnamese word in English."""
    return sum(character in _VIETNAMESE_LETTERS for character in text.lower()) >= 3


def _entry(voice: str) -> tuple[str, int]:
    return VOICES.get(voice) or _EXTRA[voice]


def folder() -> Path:
    base = os.environ.get("ALFRED_DATA_DIR") or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Alfred" / "DesktopData"
    return Path(base) / "piper"


def _kokoro_speaker(voice: str) -> str | None:
    path = _entry(voice)[0]
    return path.split(":", 1)[1] if path.startswith("kokoro:") else None


def _model(voice: str) -> Path:
    return folder() / (Path(_entry(voice)[0]).name + ".onnx")


def installed(voice: str) -> bool:
    if voice not in VOICES and voice not in _EXTRA:
        return False
    if _kokoro_speaker(voice):
        return kokoro_voice.installed()
    return (folder() / "piper" / "piper.exe").is_file() and _model(voice).is_file()


def install(voice: str, progress: Callable[[str], None]) -> None:
    if _kokoro_speaker(voice):
        kokoro_voice.install(progress)
        return
    target = folder()
    target.mkdir(parents=True, exist_ok=True)
    if not (target / "piper" / "piper.exe").is_file():
        with tempfile.TemporaryDirectory() as scratch:
            archive = Path(scratch) / "piper.zip"
            _download(PIPER_ZIP, archive, progress, "voice program")
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(Path(scratch) / "unpacked")
            program = next((Path(scratch) / "unpacked").rglob("piper.exe")).parent
            shutil.copytree(program, target / "piper", dirs_exist_ok=True)
    model = _model(voice)
    for suffix in (".onnx.json", ".onnx"):  # config first, so a present .onnx always has its config
        destination = model.with_suffix(suffix)
        if not destination.is_file():
            _download(_VOICE_BASE + _entry(voice)[0] + suffix, destination, progress, f"voice {voice}")
    progress(f"Voice {voice} is installed.")


def synthesize(voice: str, text: str) -> tuple[bytes, int]:
    """Returns 16-bit mono PCM and its sample rate."""
    speaker = _kokoro_speaker(voice)
    if speaker:
        return kokoro_voice.synthesize(speaker, text)
    model = _model(voice)
    sample_rate = int(json.loads(model.with_suffix(".onnx.json").read_text(encoding="utf-8"))["audio"]["sample_rate"])
    result = subprocess.run(
        [str(folder() / "piper" / "piper.exe"), "--model", str(model), "--output_raw"],
        input=" ".join(text.split()).encode("utf-8"), capture_output=True, timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
    )
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(f"Piper failed: {result.stderr.decode('utf-8', 'replace')[-300:]}")
    return result.stdout, sample_rate


_SPOKEN_UNITS = [(re.compile(r"\s?°\s?C\b"), " degrees Celsius"), (re.compile(r"\s?°\s?F\b"), " degrees Fahrenheit"),
                 (re.compile(r"\s?°"), " degrees"), (re.compile(r"\bkm/h\b"), " kilometers per hour"),
                 (re.compile(r"\bmph\b"), " miles per hour"), (re.compile(r"(?<=\d)\s?%"), " percent")]


def speakable(text: str) -> str:
    """What to say aloud for a chat reply: same meaning, without markdown symbols, raw links or emoji, units as words."""
    from plain_text import without_emoji
    text = without_emoji(text)
    for pattern, words in _SPOKEN_UNITS:
        text = pattern.sub(words, text)
    text = re.sub(r"```.*?```", " (code shown on screen) ", text, flags=re.S)
    text = re.sub(r"https?://\S+", "a link", text)
    text = re.sub(r"[*_#`>|]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    return " ".join(text.split())
