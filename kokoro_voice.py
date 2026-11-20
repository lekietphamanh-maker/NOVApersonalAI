"""Kokoro: Nova's most natural voice (an 82M-parameter neural voice, int8), through sherpa-onnx, on the CPU.

Downloaded only when the user picks it (one 132 MB package holds every Kokoro voice). The engine loads once and
stays in memory, so each sentence costs only its own synthesis.
"""
from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from whisper_engine import _download

PACKAGE = "kokoro-int8-multi-lang-v1_0"
PACKAGE_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/{PACKAGE}.tar.bz2"
DOWNLOAD_MB = 132
# Speaker IDs in this package (from its model metadata).
SPEAKERS = {"heart": 3, "bella": 2, "emma": 21}
_REQUIRED = ("model.int8.onnx", "voices.bin", "tokens.txt", "lexicon-us-en.txt", "lexicon-zh.txt", "espeak-ng-data", "dict")

_engine = None
_engine_lock = threading.Lock()


def folder() -> Path:
    base = os.environ.get("ALFRED_DATA_DIR") or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Alfred" / "DesktopData"
    return Path(base) / "kokoro" / PACKAGE


def installed() -> bool:
    return all((folder() / name).exists() for name in _REQUIRED)


def install(progress: Callable[[str], None]) -> None:
    target = folder()
    with tempfile.TemporaryDirectory() as scratch:
        archive = Path(scratch) / "kokoro.tar.bz2"
        _download(PACKAGE_URL, archive, progress, "Nova's natural voice")
        progress("Unpacking Nova's natural voice…")
        with tarfile.open(archive, "r:bz2") as bundle:
            bundle.extractall(scratch, filter="data")  # no paths outside the folder, no links or devices
        unpacked = Path(scratch) / PACKAGE
        if not all((unpacked / name).exists() for name in _REQUIRED):
            raise RuntimeError("the voice package is incomplete")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(unpacked), str(target))
    progress("Nova's natural voice is installed.")


def _load():
    global _engine
    if _engine is None:
        import sherpa_onnx
        model = folder()
        _engine = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=str(model / "model.int8.onnx"), voices=str(model / "voices.bin"),
                    tokens=str(model / "tokens.txt"), data_dir=str(model / "espeak-ng-data"),
                    dict_dir=str(model / "dict"),
                    lexicon=f"{model / 'lexicon-us-en.txt'},{model / 'lexicon-zh.txt'}"),
                provider="cpu", num_threads=max(1, min(4, (os.cpu_count() or 2) - 1))),
            max_num_sentences=1))
    return _engine


def synthesize(speaker: str, text: str) -> tuple[bytes, int]:
    """16-bit mono PCM and its sample rate. One sentence at a time (the engine is shared)."""
    import numpy
    with _engine_lock:
        audio = _load().generate(" ".join(text.split()), sid=SPEAKERS[speaker], speed=1.0)
    samples = numpy.clip(numpy.asarray(audio.samples, dtype=numpy.float32), -1.0, 1.0)
    return (samples * 32767).astype(numpy.int16).tobytes(), int(audio.sample_rate)


def warm_up() -> None:
    """Load the model ahead of the first reply (about a second or two), in the background."""
    with _engine_lock:
        _load()


def speed_check() -> float:
    """Seconds of work per second of speech on this PC (below 1 keeps up with talking; lower is better)."""
    with _engine_lock:
        _load()  # loading the model once is not part of the per-sentence cost
    started = time.perf_counter()
    pcm, sample_rate = synthesize("heart", "Hi, I'm Nova. This is how I sound.")
    return (time.perf_counter() - started) / max(0.1, len(pcm) / 2 / sample_rate)
