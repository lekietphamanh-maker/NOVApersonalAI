"""Voice adaptation: Whisper model choice, pause tolerance, personal vocabulary, Vietnamese,
the default speaking voice, spoken style, Nova's soul, and the persona reaching the model."""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import voice
import whisper_engine
from agent import CLAUDE_SYSTEM, DEFAULT_SOUL, FREE_CLOUD_SYSTEM, SYSTEM_PROMPT, Agent
from memory import Memory


class ModelRegistryTests(unittest.TestCase):
    def test_three_models_with_hugging_face_urls(self) -> None:
        self.assertEqual(set(whisper_engine.MODELS), {"small.en", "medium.en", "small"})
        for key, (name, url, mb, multilingual) in whisper_engine.MODELS.items():
            self.assertTrue(name.endswith(".bin"), key)
            self.assertTrue(url.startswith("https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"), key)
            self.assertTrue(url.endswith(name), key)
            self.assertGreater(mb, 0, key)
            self.assertIsInstance(multilingual, bool)
        self.assertTrue(whisper_engine.MODELS["small"][3])  # only the multilingual one hears other languages
        self.assertFalse(whisper_engine.MODELS["small.en"][3])
        self.assertFalse(whisper_engine.MODELS["medium.en"][3])
        self.assertGreater(whisper_engine.MODELS["medium.en"][2], whisper_engine.MODELS["small.en"][2])

    def test_default_model_is_unchanged(self) -> None:
        self.assertEqual(whisper_engine.DEFAULT_MODEL, "small.en")
        self.assertEqual(whisper_engine.MODEL_NAME, "ggml-small.en-q5_1.bin")
        self.assertEqual(whisper_engine.MODEL_URL, whisper_engine.MODELS["small.en"][1])
        self.assertEqual(whisper_engine.DOWNLOAD_MB, 190)


class InstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.env = patch.dict(os.environ, {"ALFRED_DATA_DIR": str(self.folder)})
        self.env.start()
        (whisper_engine.folder()).mkdir(parents=True)
        (whisper_engine.folder() / "whisper-server.exe").write_bytes(b"server")  # server already there

    def tearDown(self) -> None:
        self.env.stop()

    def _fake_download(self, calls: list) -> object:
        def download(url: str, destination: Path, progress, label: str) -> None:
            calls.append(url)
            destination.write_bytes(b"model")
        return download

    def test_install_downloads_the_selected_model(self) -> None:
        calls: list[str] = []
        with patch.object(whisper_engine, "_download", self._fake_download(calls)):
            whisper_engine.install(print, "medium.en")
        self.assertEqual(calls, [whisper_engine.MODELS["medium.en"][1]])
        self.assertTrue(whisper_engine.installed("medium.en"))
        self.assertFalse(whisper_engine.installed())  # small.en was not downloaded
        self.assertTrue(whisper_engine.installed_any())

    def test_install_defaults_to_small_en_and_unknown_model_falls_back(self) -> None:
        calls: list[str] = []
        with patch.object(whisper_engine, "_download", self._fake_download(calls)):
            whisper_engine.install(print)
            whisper_engine.install(print, "not-a-model")
        self.assertEqual(calls, [whisper_engine.MODELS["small.en"][1]])  # second call: already there

    def test_engine_falls_back_to_a_downloaded_model(self) -> None:
        (whisper_engine.folder() / "ggml-small.en-q5_1.bin").write_bytes(b"model")
        engine = whisper_engine.WhisperEngine(model="medium.en")
        self.assertEqual(engine.model_key, "medium.en")
        self.assertEqual(engine.model_file, "ggml-small.en-q5_1.bin")  # medium isn't there: use what is

    def test_prompt_carries_the_owners_words(self) -> None:
        prompt = whisper_engine.build_prompt(["Kiet", "ECO 251", "microeconomics"])
        for word in ("Kiet", "ECO 251", "microeconomics", "Hey Nova", "homework"):
            self.assertIn(word, prompt)
        self.assertEqual(prompt.count("Kiet"), 1)  # no duplicates with the built-in list
        self.assertLessEqual(len(prompt), 900)


class TranscribeLanguageTests(unittest.TestCase):
    def _engine(self, **kwargs) -> whisper_engine.WhisperEngine:
        engine = whisper_engine.WhisperEngine(**kwargs)
        engine._ensure_started = lambda: None  # noqa: SLF001 - no server in this test
        return engine

    def _capture_body(self) -> tuple[list, object]:
        bodies: list[bytes] = []

        class Reply(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout=60):
            bodies.append(request.data)
            return Reply(json.dumps({"text": "hello"}).encode())
        return bodies, fake_urlopen

    def test_auto_detect_sends_no_language(self) -> None:
        bodies, fake = self._capture_body()
        engine = self._engine(model="small", language="auto")
        self.assertEqual(engine.language, "auto")
        with patch.object(whisper_engine, "urlopen", fake):
            self.assertEqual(engine.transcribe(b"\x00\x00" * 8000), "hello")
        self.assertNotIn(b'name="language"', bodies[0])
        self.assertIn(b"Kiet", bodies[0])  # the owner's words travel in the prompt

    def test_english_model_forces_english_even_when_auto_is_asked(self) -> None:
        bodies, fake = self._capture_body()
        engine = self._engine(model="small.en", language="auto")
        self.assertEqual(engine.language, "en")  # English-only models cannot auto-detect
        with patch.object(whisper_engine, "urlopen", fake):
            engine.transcribe(b"\x00\x00" * 8000)
        self.assertIn(b'name="language"\r\n\r\nen\r\n', bodies[0])


class WhisperSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.mkdtemp()
        self.env = patch.dict(os.environ, {"ALFRED_DATA_DIR": self.folder})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def test_defaults(self) -> None:
        settings = voice.load_whisper_settings()
        self.assertEqual(settings["model"], "small.en")
        self.assertEqual(settings["language"], "en")
        self.assertEqual(settings["pause_seconds"], 2.0)
        for word in ("Kiet", "Keith", "ECO 251", "CHM 151", "microeconomics", "thermochemistry",
                     "Hey Nova", "screen assist", "building mode", "trading", "workplace", "homework"):
            self.assertIn(word, settings["vocabulary"])

    def test_round_trip_and_validation(self) -> None:
        saved = voice.save_whisper_settings(model="medium.en", language="auto", pause_seconds=3,
                                            vocabulary=["Nova", "nova", "  ", "Kiet"])
        self.assertEqual(saved["language"], "en")  # auto needs the multilingual model
        self.assertEqual(saved["vocabulary"], ["Nova", "Kiet"])
        self.assertEqual(voice.load_whisper_settings()["model"], "medium.en")
        saved = voice.save_whisper_settings(model="small", language="auto", pause_seconds=0.5)
        self.assertEqual(saved["language"], "auto")
        self.assertEqual(saved["pause_seconds"], 1.35)  # below the old 1.35 s: clamped to it
        self.assertEqual(voice.save_whisper_settings(model="nope")["model"], "small.en")
        self.assertEqual(voice.save_whisper_settings(pause_seconds=9)["pause_seconds"], 5.0)
        self.assertEqual(voice.save_whisper_settings(pause_seconds="abc")["pause_seconds"], 2.0)

    def test_saving_a_voice_keeps_the_speech_settings(self) -> None:
        voice.save_whisper_settings(model="medium.en", pause_seconds=3)
        voice.save_voice_name("Emma (British, female, most natural)")
        settings = voice.load_whisper_settings()
        self.assertEqual((settings["model"], settings["pause_seconds"]), ("medium.en", 3.0))
        self.assertEqual(voice.load_voice_name(), "Emma (British, female, most natural)")


class DefaultVoiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"ALFRED_DATA_DIR": tempfile.mkdtemp()})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def test_fresh_nova_defaults_to_emma(self) -> None:
        self.assertEqual(voice.load_voice_name(), "Emma (British, female, most natural)")
        self.assertIsNone(voice.saved_voice_name())  # nothing picked yet

    def test_an_explicit_built_in_choice_stays_built_in(self) -> None:
        voice.save_voice_name(None)
        self.assertIsNone(voice.load_voice_name())

    def test_a_saved_voice_wins_over_the_default(self) -> None:
        voice.save_voice_name("Heart (US, female, most natural)")
        self.assertEqual(voice.load_voice_name(), "Heart (US, female, most natural)")
        self.assertEqual(voice.saved_voice_name(), "Heart (US, female, most natural)")


class PersonaTests(unittest.TestCase):
    def test_spoken_style_rules_are_in_the_prompt(self) -> None:
        for rule in ("answer first and explain after", "No stiff templates",
                     'no filler ("Of course!", "Certainly", "I\'d be happy to help")',
                     "no lists, headings or tables unless he asked for one",
                     "Talk like a person in conversation"):
            self.assertIn(rule, SYSTEM_PROMPT)

    def test_persona_is_concrete_not_just_adjectives(self) -> None:
        for line in ("Okay, that one got me", "Yes! The hard part's done",
                     "Honestly? I'd pick the other one"):
            self.assertIn(line, SYSTEM_PROMPT)

    def test_the_cloud_brain_keeps_novas_persona(self) -> None:
        self.assertNotIn("Be yourself underneath", CLAUDE_SYSTEM)
        self.assertNotIn("Be yourself underneath", FREE_CLOUD_SYSTEM)
        for prompt in (CLAUDE_SYSTEM, FREE_CLOUD_SYSTEM):
            self.assertIn("Stay Nova underneath", prompt)
            self.assertIn("Okay, that one got me", prompt)
            self.assertIn("answer first and explain after", prompt)

    def test_soul_reaches_both_paths(self) -> None:
        self.assertTrue(DEFAULT_SOUL)
        agent = Agent(memory=Memory(Path(tempfile.mkdtemp()) / "memory.sqlite3"))
        self.assertEqual(agent.soul, DEFAULT_SOUL)
        self.assertIn("Loves space", agent._soul_prompt())
        self.assertIn("Loves space", agent._online_system(CLAUDE_SYSTEM))  # online, default privacy rule
        agent.private_topics = "personal"  # strict: nothing the owner wrote goes online
        self.assertNotIn("Loves space", agent._online_system(CLAUDE_SYSTEM))
        agent.soul = ""
        self.assertEqual(agent._soul_prompt(), "")  # cleared means no soul note at all

    def test_local_ask_sends_persona_and_soul_to_the_model(self) -> None:
        agent = Agent(memory=Memory(Path(tempfile.mkdtemp()) / "memory.sqlite3"))
        sent: list[list[dict]] = []
        agent._chat = lambda messages, tools: sent.append(messages) or {
            "message": {"role": "assistant", "content": "Paris."}}
        self.assertEqual(agent.ask("what is the capital of France?", lambda *_: True), "Paris.")
        system = sent[0][0]["content"]
        self.assertEqual(sent[0][0]["role"], "system")
        for line in ("Okay, that one got me", "answer first and explain after", "Loves space"):
            self.assertIn(line, system)


if __name__ == "__main__":
    unittest.main()
