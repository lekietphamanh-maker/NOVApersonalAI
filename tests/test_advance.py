"""Advance mode: the voice command, the Docker apps it starts, and the owner's own apps."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import advance_mode
import instant_commands
import separate_apps


class VoiceTests(unittest.TestCase):
    def test_on_and_off_by_voice_without_any_ai(self) -> None:
        for said, on in [("advance mode", True), ("turn on advanced mode", True), ("Hey Nova, open advance mode please", True),
                         ("exit advance mode", False), ("advance mode off", False), ("turn off the advance mode", False)]:
            quick = instant_commands.match(said)
            self.assertEqual((quick.tool, quick.arguments), ("advance", {"on": on}), said)
        self.assertIsNone(instant_commands.match("what is advance mode and how do I use it"))


class DockerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[list[str]] = []
        self.answers: dict[str, SimpleNamespace] = {}

    def fake_run(self, arguments, **_options):
        self.calls.append(arguments)
        return self.answers.get(arguments[1], SimpleNamespace(returncode=0, stdout="", stderr=""))

    def docker(self) -> separate_apps.Docker:
        return separate_apps.Docker(self.fake_run, lambda: "docker")

    def test_first_start_runs_openproject_on_this_pc_only_with_a_sealed_secret(self) -> None:
        app = separate_apps.find("openproject")
        said = self.docker().start(app, lambda: "s3cret")
        run = self.calls[-1]
        self.assertEqual(run[:5], ["docker", "run", "-d", "--name", "nova-openproject"])
        self.assertIn("127.0.0.1:8080:80", run)  # not reachable from the network
        self.assertIn("OPENPROJECT_SECRET_KEY_BASE=s3cret", run)
        self.assertIn("nova-openproject-pgdata:/var/openproject/pgdata", run)
        self.assertEqual(run[-1], "openproject/openproject:15")
        self.assertIn("http://localhost:8080", said)

    def test_a_stopped_app_is_started_again_and_its_data_kept(self) -> None:
        self.answers["ps"] = SimpleNamespace(returncode=0, stdout="exited\n", stderr="")
        self.docker().start(separate_apps.find("openproject"), lambda: "unused")
        self.assertEqual(self.calls[-1], ["docker", "start", "nova-openproject"])
        self.assertEqual(self.docker().status(separate_apps.find("openproject")), "stopped")

    def test_docker_missing_or_not_running_is_said_plainly(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "isn't installed"):
            separate_apps.Docker(self.fake_run, lambda: None).start(separate_apps.find("openproject"), lambda: "")
        self.answers["info"] = SimpleNamespace(returncode=1, stdout="", stderr="daemon")
        with self.assertRaisesRegex(RuntimeError, "isn't running"):
            self.docker().start(separate_apps.find("openproject"), lambda: "")
        self.assertEqual(separate_apps.Docker(self.fake_run, lambda: None).status(separate_apps.find("openproject")), "")


class OwnAppTests(unittest.TestCase):
    def test_a_web_address_or_a_real_file(self) -> None:
        self.assertEqual(separate_apps.OwnApp.new(" My  site ", "https://klee.dev").name, "My site")
        program = Path(tempfile.mkdtemp()) / "tool.exe"
        program.write_bytes(b"")
        self.assertEqual(separate_apps.OwnApp.new("Tool", f'"{program}"').target, str(program))
        for name, target in [("", "https://a.b"), ("X", ""), ("X", "rm -rf /")]:
            with self.assertRaises(ValueError):
                separate_apps.OwnApp.new(name, target)

    def test_saved_apps_skip_broken_entries(self) -> None:
        saved = [{"id": "1", "name": "A", "target": "https://a.b"}, {"id": "2"}, "junk"]
        self.assertEqual([app.name for app in separate_apps.own_apps(saved)], ["A"])
        self.assertEqual(separate_apps.own_apps(None), [])

    def test_installed_desktop_apps_are_found_where_their_installer_puts_them(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "AppFlowy").mkdir()
        (root / "AppFlowy" / "AppFlowy.exe").write_bytes(b"")
        app = separate_apps.find("appflowy")
        self.assertEqual(separate_apps.installed_path(app, "win32", {"LOCALAPPDATA": str(root)}), str(root / "AppFlowy" / "AppFlowy.exe"))
        self.assertIsNone(separate_apps.installed_path(app, "win32", {}))


class WidgetTests(unittest.TestCase):
    def test_only_known_widgets_once_each(self) -> None:
        self.assertEqual(advance_mode.clean_widgets(["pc", "x", "pc", "clock"]), ["pc", "clock"])
        self.assertEqual(advance_mode.clean_widgets("nope"), advance_mode.DEFAULT_WIDGETS)
        self.assertEqual(advance_mode.clean_widgets([]), [])


if __name__ == "__main__":
    unittest.main()
