"""Set up everything: steps run in order, done ones are skipped, a failure doesn't stop the rest, disk space is kept."""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import setup_everything
from setup_everything import Setup, Step


class RunnerTests(unittest.TestCase):
    def run_steps(self, steps: list[Step], disk_mb: float = 500_000) -> Setup:
        reports: list = []
        setup = Setup(reports.append, lambda: disk_mb)
        self.assertTrue(setup.start(steps))
        setup.wait(10)
        self.reports = reports
        return setup

    def test_each_step_in_turn_and_features_turned_on(self) -> None:
        ran, turned_on = [], []
        steps = [
            Step("here", "Already here", "", 10, lambda: True, lambda progress: ran.append("here"), lambda: turned_on.append("here")),
            Step("broken", "Broken", "", 10, lambda: False, lambda progress: (_ for _ in ()).throw(OSError("no network"))),
            Step("model", "Model", "", 10, lambda: False, lambda progress: (progress("50%"), ran.append("model")),
                 lambda: turned_on.append("model")),
        ]
        setup = self.run_steps(steps)
        self.assertEqual(ran, ["model"])  # the step already done isn't downloaded again
        self.assertEqual(turned_on, ["here", "model"])  # but it is turned on
        self.assertEqual([step["status"] for step in setup.steps], ["done", "failed", "done"])
        self.assertEqual(setup.steps[1]["note"], "no network")
        self.assertIn("50%", [step["note"] for report in self.reports for step in report["steps"]])
        self.assertFalse(self.reports[-1]["running"])
        self.assertEqual(setup.summary(), "Set up everything: 2 ready, 1 didn't work (SETTINGS → Downloads says why).")

    def test_a_step_that_would_fill_the_disk_is_skipped(self) -> None:
        setup = self.run_steps([Step("vision", "Vision", "", 3000, lambda: False, lambda progress: self.fail("ran"))], disk_mb=4000)
        self.assertEqual((setup.steps[0]["status"], setup.steps[0]["note"]), ("skipped", "needs 2.9 GB free on the disk"))

    def test_stop_ends_it_between_steps(self) -> None:
        holder: list[Setup] = []
        steps = [Step("a", "A", "", 0, lambda: False, lambda progress: holder[0].stop()),
                 Step("b", "B", "", 0, lambda: False, lambda progress: self.fail("ran after stop"))]
        setup = Setup(lambda state: None, lambda: 10 ** 6)
        holder.append(setup)
        setup.start(steps)
        setup.wait(10)
        self.assertEqual([step["status"] for step in setup.steps], ["done", "stopped"])
        self.assertFalse(setup.start([]) is False and setup.running)


class InstallerTests(unittest.TestCase):
    def test_ollama_installs_for_this_user_silently(self) -> None:
        calls: list = []

        def run(arguments, **_options):
            calls.append(arguments)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch.object(setup_everything, "winget", lambda: "winget"):
            setup_everything.install_ollama(lambda text: None, run, platform="win32")
        self.assertEqual(calls[0][:5], ["winget", "install", "-e", "--id", "Ollama.Ollama"])
        self.assertIn("--silent", calls[0])
        calls.clear()

        class Download:
            def __init__(self):
                self.data = [b"MZ", b""]

            def read(self, *_):
                return self.data.pop(0)

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False
        with mock.patch.object(setup_everything, "winget", lambda: None):
            setup_everything.install_ollama(lambda text: None, run, opener=lambda request, timeout: Download(), platform="win32")
        self.assertEqual(Path(calls[0][0]).name, "OllamaSetup.exe")
        self.assertEqual(calls[0][1:], ["/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"])

    def test_a_failed_command_says_its_last_line(self) -> None:
        def run(arguments, **_options):
            return SimpleNamespace(returncode=1, stdout="", stderr="downloading\nNo package found matching input criteria.")
        with self.assertRaisesRegex(RuntimeError, "No package found"):
            setup_everything._command(["winget", "install"], lambda text: None, "Installing", run=run)

    def test_no_homebrew_on_the_mac_is_said(self) -> None:
        with mock.patch.object(setup_everything, "brew", lambda: None):
            with self.assertRaisesRegex(RuntimeError, "Homebrew"):
                setup_everything.install_ollama(lambda text: None, platform="darwin")


if __name__ == "__main__":
    unittest.main()


class NaturalVoiceTests(unittest.TestCase):
    """Set up everything installs the natural voice only for a Nova still on it: a voice the owner picked stays."""

    def test_a_picked_voice_stays_and_the_default_is_installed(self) -> None:
        from types import SimpleNamespace
        import setup_actions
        for current, expected in (("Amy (US, female)", []), (None, []),
                                  (setup_actions.NATURAL_VOICE, [setup_actions.NATURAL_VOICE])):
            installed: list[str] = []
            app = SimpleNamespace(voice=SimpleNamespace(voice_name=current), _voice_installed=installed.append)
            setup_actions.SetupActions._natural_voice(app)
            self.assertEqual(installed, expected, current)
