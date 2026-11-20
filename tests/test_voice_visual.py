import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import visual_notes
import voice


class SpokenVisualCommandTests(unittest.TestCase):
    def test_create_multibranch_map_from_spoken_idea(self):
        result = visual_notes.parse_spoken_visual_command(
            "Nova, visualize my idea: AI assistant, task memory, voice and diagrams"
        )
        self.assertEqual(result["action"], "replace")
        self.assertEqual(result["title"], "AI assistant")
        self.assertEqual(result["items"], ["task memory", "voice", "diagrams"])

    def test_create_single_topic_map(self):
        result = visual_notes.parse_spoken_visual_command("make a visual note about offline voice assistant")
        self.assertEqual(result["action"], "replace")
        self.assertEqual(result["title"], "offline voice assistant")

    def test_add_branch(self):
        self.assertEqual(
            visual_notes.parse_spoken_visual_command("add microphone selection to the map"),
            {"action": "add", "value": "microphone selection"},
        )

    def test_remove_branch(self):
        self.assertEqual(
            visual_notes.parse_spoken_visual_command("remove email from the idea map"),
            {"action": "remove", "value": "email"},
        )

    def test_rename_map(self):
        self.assertEqual(
            visual_notes.parse_spoken_visual_command("rename the map to Nova"),
            {"action": "title", "value": "Nova"},
        )

    def test_unrelated_chat_is_not_map_edit(self):
        self.assertIsNone(visual_notes.parse_spoken_visual_command("What is the weather today?"))


class AudioPreferenceTests(unittest.TestCase):
    def test_frozen_model_path_uses_meipass_without_resolving_archive_module(self):
        with patch.object(sys, "_MEIPASS", r"C:\\Nova\\_internal", create=True):
            with patch.object(Path, "resolve", side_effect=OSError("synthetic archive path")):
                self.assertEqual(
                    voice.default_model_path(),
                    Path(r"C:\\Nova\\_internal") / "assets" / "vosk-model-small-en-us-0.15",
                )

    def test_normalized_audio_level_tracks_int16_amplitude(self):
        import array
        quiet = array.array("h", [100] * 200).tobytes()
        loud = array.array("h", [8000] * 200).tobytes()
        self.assertLess(voice._normalized_audio_level(quiet), voice._normalized_audio_level(loud))
        self.assertEqual(voice._normalized_audio_level(b""), 0.0)

    def test_audio_selection_stays_in_edition_data_path(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"ALFRED_DATA_DIR": folder}):
                voice.save_audio_preferences("WASAPI::Microphone A", "Speakers B")
                self.assertEqual(
                    voice.load_audio_preferences(),
                    {"input_key": "WASAPI::Microphone A", "output_key": "Speakers B"},
                )
                path = Path(folder) / "audio_settings.json"
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["input_key"], "WASAPI::Microphone A")
                voice.save_audio_preferences(None, None)
                self.assertEqual(voice.load_audio_preferences(), {"input_key": None, "output_key": None})



class NovaNeverHearsHerselfTests(unittest.TestCase):
    def test_the_mic_ignores_sound_while_nova_talks_and_just_after(self) -> None:
        from unittest.mock import patch
        import voice
        controller = voice.VoiceController(model_path="missing-model")
        self.assertFalse(controller._nova_talking())
        controller._sentence_busy(True)   # a reply is being spoken sentence by sentence
        self.assertTrue(controller._nova_talking())
        controller._sentence_busy(False)  # the last sentence just ended: the room still echoes
        self.assertTrue(controller._nova_talking())
        later = voice.time.monotonic() + voice.ECHO_TAIL_SECONDS + 0.1
        with patch.object(voice.time, "monotonic", lambda: later):
            self.assertFalse(controller._nova_talking())


if __name__ == "__main__":
    unittest.main()
