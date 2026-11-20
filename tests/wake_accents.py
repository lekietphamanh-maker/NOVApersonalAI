"""The wake-word checks with espeak-ng accents (English read by US, UK, Vietnamese and Chinese voices), on any OS:
python tests/wake_accents.py. Needs espeak-ng and the Vosk model in assets/."""
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent.parent), str(Path(__file__).resolve().parent)]
import numpy  # noqa: E402
from test_wake_word_windows import WakeWordTests  # noqa: E402


def espeak(text: str, voice: str) -> bytes:
    path = tempfile.mktemp(suffix=".wav")
    name, _, speed = voice.partition("@")
    subprocess.run(["espeak-ng", "-v", name, "-s", speed or "150", "-w", path, text], check=True)
    with wave.open(path) as recording:
        rate, frames = recording.getframerate(), recording.readframes(recording.getnframes())
    samples = numpy.frombuffer(frames, dtype=numpy.int16).astype(numpy.float32)
    positions = numpy.arange(0, len(samples), rate / 16_000)
    return numpy.interp(positions, numpy.arange(len(samples)), samples).astype(numpy.int16).tobytes()


class AccentTests(unittest.TestCase):
    def test_accents(self):
        voices = [(voice, voice) for voice in ("en-us@140", "en-gb@170", "vi@130", "vi@170", "zh@150")]
        WakeWordTests.check_voices(self, espeak, voices, nova_voices=["en-us+f3@165"])  # Nova: a woman's voice

    listen = WakeWordTests.listen


if __name__ == "__main__":
    unittest.main()
