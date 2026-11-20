"""Real downloads on Windows: Whisper transcribes a sample, Piper speaks. Run with ALFRED_TEST_DOWNLOADS=1."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen

import piper_voice
import whisper_engine

SAMPLE = "https://raw.githubusercontent.com/ggml-org/whisper.cpp/v1.9.2/samples/jfk.wav"


@unittest.skipUnless(sys.platform == "win32" and os.environ.get("ALFRED_TEST_DOWNLOADS") == "1", "downloads ~300 MB")
class DownloadedVoiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = patch.dict(os.environ, {"ALFRED_DATA_DIR": tempfile.mkdtemp()})
        self.data.start()

    def tearDown(self) -> None:
        self.data.stop()

    def test_whisper_transcribes_speech(self) -> None:
        whisper_engine.install(print)
        self.assertTrue(whisper_engine.installed())
        sample = Path(tempfile.mkdtemp()) / "jfk.wav"
        sample.write_bytes(urlopen(SAMPLE, timeout=60).read())
        with wave.open(str(sample)) as file:
            self.assertEqual((file.getframerate(), file.getnchannels()), (16_000, 1))
            pcm = file.readframes(file.getnframes())
        engine = whisper_engine.WhisperEngine()
        try:
            text = engine.transcribe(pcm)
        finally:
            engine.stop()
        print("Whisper heard:", text)
        self.assertIn("country", text.lower())

    def test_natural_voice_speaks(self) -> None:
        voice = "Amy (US, female)"
        piper_voice.install(voice, print)
        self.assertTrue(piper_voice.installed(voice))
        pcm, sample_rate = piper_voice.synthesize(voice, "Hello, I'm Nova. How can I help you today?")
        print(f"Piper made {len(pcm) // 2 / sample_rate:.1f} s of audio at {sample_rate} Hz")
        self.assertGreater(len(pcm) // 2 / sample_rate, 1.0)

    def test_vietnamese_sentences_get_the_vietnamese_voice(self) -> None:
        piper_voice.install(piper_voice.VIETNAMESE, print)
        self.assertTrue(piper_voice.installed(piper_voice.VIETNAMESE))
        pcm, sample_rate = piper_voice.synthesize(piper_voice.VIETNAMESE, "Xin chào, tôi là Nova. Tôi có thể giúp gì cho bạn?")
        print(f"The Vietnamese voice made {len(pcm) // 2 / sample_rate:.1f} s of audio at {sample_rate} Hz")
        self.assertGreater(len(pcm) // 2 / sample_rate, 1.5)

    def test_kokoro_speaks_clearly(self) -> None:
        """Nova's most natural voice: installs, speaks, and the offline recognizer hears the words."""
        import kokoro_voice
        import numpy
        from voice import VoiceController
        voice = "Heart (US, female, most natural)"
        piper_voice.install(voice, print)
        self.assertTrue(piper_voice.installed(voice))
        pcm, rate = piper_voice.synthesize(voice, "Hello, I'm Nova. How can I help you today?")
        samples = numpy.frombuffer(pcm, dtype=numpy.int16).astype(numpy.float32)
        positions = numpy.arange(0, len(samples), rate / 16_000)
        heard = VoiceController().transcribe_pcm(numpy.interp(positions, numpy.arange(len(samples)), samples)
                                                 .astype(numpy.int16).tobytes())
        print(f"Kokoro made {len(samples) / rate:.1f} s of speech; the recognizer heard {heard!r}; "
              f"{kokoro_voice.speed_check():.2f} s of work per second of speech on this runner")
        self.assertIn("help", heard.lower())


if __name__ == "__main__":
    unittest.main()
