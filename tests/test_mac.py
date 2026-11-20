"""Nova on the Mac: hotkeys read through Quartz with the same saved codes, the RAM and chip deciding the model (Apple
silicon's GPU shares the RAM), volume and players through AppleScript, apps opened by their Mac names, the built-in
voice behind the SAPI calls, and secrets sealed with a key in the Keychain. The live tests run on a real Mac in CI."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import hardware_advisor
import hotkeys
import instant_commands
import mac

VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               12000.
Pages active:                            300000.
Pages inactive:                          100000.
Pages speculative:                         8000.
Pages purgeable:                           5000.
"""
SAY_VOICES = """Albert              en_US    # Hello! My name is Albert.
Samantha            en_US    # Hello! My name is Samantha.
Linh                vi_VN    # Xin chào, tên tôi là Linh.
Thomas              fr_FR    # Bonjour, je m’appelle Thomas.
"""


class Runs:
    """A fake for subprocess.run: answers by the command, and remembers what was asked."""

    def __init__(self, answers: dict[str, str] | None = None) -> None:
        self.answers, self.calls = answers or {}, []

    def __call__(self, arguments, **options):
        self.calls.append((arguments, options))
        joined = " ".join(arguments) + " " + str(options.get("input") or "")
        for needle, reply in self.answers.items():
            if needle in joined:
                return subprocess.CompletedProcess(arguments, 0, reply, "")
        return subprocess.CompletedProcess(arguments, 0, "", "")


class KeyTests(unittest.TestCase):
    def test_saved_windows_codes_become_mac_keys(self) -> None:
        self.assertEqual(mac.KEYCODES[0x11], (0x3B, 0x3E))  # Ctrl → Control, either side
        self.assertEqual(mac.KEYCODES[0x12], (0x3A, 0x3D))  # Alt → Option
        self.assertEqual(mac.KEYCODES[0x1B], (0x35,))
        self.assertEqual(mac.KEYCODES[0x77], (0x64,))  # F8
        self.assertEqual(mac.KEYCODES[ord("A")], (0x00,))
        self.assertEqual(mac.KEYCODES[ord("Z")], (0x06,))
        self.assertEqual(mac.KEYCODES[ord("0")], (0x1D,))
        self.assertEqual(hotkeys.label([0x11, 0x12]), hotkeys.label([0x12, 0x11]))
        with patch.object(hotkeys.sys, "platform", "darwin"):
            self.assertEqual("+".join(hotkeys.key_name(code, "darwin") for code in (0x11, 0x12)), "Control+Option")

    def test_held_asks_quartz_for_either_side(self) -> None:
        class Fake:
            def held(self, code: int) -> bool:
                return code == 0x3E  # the right Control key
        with patch.object(mac, "_quartz", Fake()):
            self.assertTrue(hotkeys.held(0x11, "darwin"))
            self.assertFalse(hotkeys.held(0x12, "darwin"))


class HardwareTests(unittest.TestCase):
    def test_memory_from_sysctl_and_vm_stat(self) -> None:
        run = Runs({"hw.memsize": str(16 * 1024 ** 3), "vm_stat": VM_STAT})
        total, available = mac.memory_gib(run)
        self.assertEqual(total, 16.0)
        self.assertEqual(available, round((12000 + 100000 + 8000 + 5000) * 16384 / 1024 ** 3, 1))

    def test_the_model_fits_the_unified_memory(self) -> None:
        def pick(ram: float) -> str:
            gpus = [{"name": "Apple M3 GPU", "reported_vram_gib": mac.gpu_share(ram), "unified": True}]
            return hardware_advisor.recommend_model(hardware_advisor.HardwareProfile("macOS", "arm64", "Apple M3", ram, ram,
                                                                                     gpus, "", []))[0]
        self.assertEqual([pick(ram) for ram in (8, 16, 24)], ["qwen3:4b", "qwen3:8b", "qwen3:14b"])
        self.assertEqual(mac.gpu_share(64), 48.0)  # more of it for the GPU on big Macs


class SystemTests(unittest.TestCase):
    def test_voices_english_and_vietnamese_only(self) -> None:
        self.assertEqual(mac.voices(Runs({"say -v ?": SAY_VOICES})), ["Albert", "Samantha", "Linh"])

    def test_volume_steps_and_limits(self) -> None:
        run = Runs({"output volume of": "97"})
        mac.change_volume("volume_up", 3, run)
        self.assertIn("set volume output volume 100", run.calls[-1][0][-1])
        run = Runs({"output volume of": "10"})
        mac.change_volume("volume_down", 10, run)
        self.assertIn("set volume output volume 0", run.calls[-1][0][-1])

    def test_media_goes_to_the_player_that_is_open(self) -> None:
        run = Runs({'application "Music" is running': "true", 'application "Spotify" is running': "false"})
        self.assertEqual(mac.media("next", run), "Music")
        self.assertEqual(run.calls[-1][0][-1], 'tell application "Music" to next track')
        with self.assertRaises(OSError):
            mac.media("play_pause", Runs({"is running": "false"}))

    def test_apps_open_by_their_mac_names(self) -> None:
        started: list = []
        with patch.object(instant_commands.sys, "platform", "darwin"):
            self.assertEqual(instant_commands.open_app("notepad", run=lambda arguments, **_: started.append(arguments)),
                             "Opening Notepad.")
        self.assertEqual(started, [["open", "-a", "TextEdit"]])

    def test_tools_installed_by_homebrew_and_nvm_are_found(self) -> None:
        home = Path(tempfile.mkdtemp())
        for version in ("v20.18.0", "v22.23.4", "v9.0.0"):
            (home / ".nvm" / "versions" / "node" / version / "bin").mkdir(parents=True)
        (home / ".local" / "bin").mkdir(parents=True)
        folders = [Path(folder) for folder in mac.tool_folders(home) if folder.startswith(str(home))]
        self.assertEqual([folder.parent.name if folder.name == "bin" and folder.parent.name.startswith("v") else folder.name
                          for folder in folders], ["bin", "v22.23.4", "v20.18.0", "v9.0.0"])


class SecretTests(unittest.TestCase):
    def test_sealed_with_the_keychain_key_and_tamper_is_caught(self) -> None:
        key = lambda: b"k" * 32  # noqa: E731
        sealed = mac.protect(b"refresh-token", key)
        self.assertNotIn(b"refresh-token", sealed)
        self.assertEqual(mac.unprotect(sealed, key), b"refresh-token")
        with self.assertRaises(Exception):
            mac.unprotect(sealed[:-1] + bytes([sealed[-1] ^ 1]), key)
        with self.assertRaises(ValueError):
            mac.unprotect(b"something else", key)

    def test_the_key_never_goes_on_a_command_line(self) -> None:
        run = Runs()  # nothing in the Keychain yet: a key is made and added
        key = mac.keychain_key(run=run)
        add = run.calls[-1]
        self.assertEqual(add[0], ["security", "-i"])
        self.assertIn(key.hex(), add[1]["input"])
        self.assertTrue(all(key.hex() not in " ".join(arguments) for arguments, _ in run.calls))
        found = Runs({"find-generic-password": key.hex() + "\n"})
        self.assertEqual(mac.keychain_key(run=found), key)


class VoiceTests(unittest.TestCase):
    def test_say_stands_in_for_sapi(self) -> None:
        import voice
        said: list = []

        class Process:
            def __init__(self) -> None:
                self.waited = 0

            def poll(self):
                return 0

            def wait(self, timeout=None):
                self.waited += 1

        def fake_say(text, voice="", rate=0):
            said.append((text, voice))
            return Process()
        voice._SayVoice._voice = "Samantha"
        with patch.object(mac, "say", fake_say):
            speaker = voice._SayVoice()
            speaker.Speak("Hello there.", voice.SVSF_ASYNC)
            self.assertTrue(speaker.WaitUntilDone(80))
            speaker.Volume = 8
            speaker.Speak("Nova audio output test.", 0)
        self.assertEqual(said, [("Hello there.", "Samantha"), ("[[volm 0.08]] Nova audio output test.", "Samantha")])


@unittest.skipUnless(sys.platform == "darwin" and os.environ.get("NOVA_TEST_MAC") == "1", "a real Mac (CI sets NOVA_TEST_MAC=1)")
class LiveMacTests(unittest.TestCase):
    def test_this_mac(self) -> None:
        total, available = mac.memory_gib()
        print("memory", total, available, "chip", mac.chip(), "voices", mac.voices()[:5])
        self.assertGreater(total, 1)
        self.assertGreater(available, 0)
        profile = hardware_advisor.detect_hardware()
        print("profile", profile.cpu, profile.gpus, hardware_advisor.recommend_model(profile))
        self.assertEqual(profile.total_ram_gib, total)
        busy, all_ticks = mac.cpu_ticks()
        self.assertGreater(all_ticks, busy)
        self.assertIsInstance(mac.quartz().may_listen(ask=False), bool)
        self.assertFalse(mac.key_held(0x7B))  # F12: nobody is pressing it on a CI runner

    def test_say_speaks_and_the_keychain_keeps_a_key(self) -> None:
        process = mac.say("[[volm 0.0]] Nova test.")
        self.assertEqual(process.wait(timeout=30), 0)
        account = "nova-ci-test"
        try:
            key = mac.keychain_key(account)
            self.assertEqual(mac.keychain_key(account), key)  # the same key comes back
            self.assertEqual(mac.unprotect(mac.protect(b"secret", lambda: key), lambda: key), b"secret")
        finally:
            subprocess.run(["security", "delete-generic-password", "-s", mac.KEYCHAIN_SERVICE, "-a", account],
                           capture_output=True)


if __name__ == "__main__":
    unittest.main()
