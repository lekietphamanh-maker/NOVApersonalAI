"""Updating from GitHub Releases: only newer versions, a checked download (a damaged or cut-off one is never kept),
GitHub's limits, going back to the previous version, and installing only a copy Nova-Setup.exe installed."""
from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError

import updater

SETUP = b"MZ" + b"nova installer " * 1000
GOOD_HASH = hashlib.sha256(SETUP).hexdigest()


class Answer(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def release(tag: str, with_setup: bool = True) -> dict:
    assets = [{"name": "Nova-Desktop.zip", "browser_download_url": f"https://dl/{tag}/zip"}]
    if with_setup:
        assets += [{"name": "Nova-Setup.exe", "browser_download_url": f"https://dl/{tag}/setup"},
                   {"name": "Nova-Setup.exe.sha256", "browser_download_url": f"https://dl/{tag}/sha"}]
    return {"tag_name": tag, "html_url": f"https://github.com/x/releases/tag/{tag}", "assets": assets, "body": "notes"}


class FakeGitHub:
    def __init__(self, latest: str = "v2.2.0", setup: bytes = SETUP, checksum: str = GOOD_HASH) -> None:
        self.latest, self.setup, self.checksum = latest, setup, checksum
        self.calls: list[str] = []
        self.fail: Exception | None = None

    def __call__(self, request, timeout):
        url = request.full_url
        self.calls.append(url)
        if self.fail is not None:
            raise self.fail
        if url.endswith("/releases/latest"):
            return Answer(json.dumps(release(self.latest)).encode())
        if "/releases?" in url:
            return Answer(json.dumps([release("v2.2.0"), release("v2.1.0"), release("v2.0.0", with_setup=False),
                                      release("v1.9.0")]).encode())
        if url.endswith("/setup"):
            return Answer(self.setup)
        if url.endswith("/sha"):
            return Answer(f"{self.checksum}  Nova-Setup.exe".encode())
        raise AssertionError(url)


class VersionTests(unittest.TestCase):
    def test_only_a_real_newer_version_counts(self) -> None:
        self.assertTrue(updater.is_newer("v2.10.0", "v2.9.3"))
        self.assertFalse(updater.is_newer("v2.1.0", "v2.1.0"))
        self.assertFalse(updater.is_newer("v2.0.9", "v2.1.0"))
        self.assertFalse(updater.is_newer("v3.0.0", "dev"))  # from source: never
        self.assertFalse(updater.is_newer("nightly", "v1.0.0"))


class UpdaterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.github = FakeGitHub()
        self.ran: list[list[str]] = []
        self.updates = updater.Updater("v2.1.0", self.folder, opener=self.github, can_install=lambda: True,
                                       run=self.ran.append)

    def test_a_newer_release_is_downloaded_checked_and_installed_silently(self) -> None:
        found = self.updates.newest()
        self.assertEqual(found.version, "v2.2.0")
        progress: list[int] = []
        installer = self.updates.download(found, progress.append)
        self.assertEqual(installer.read_bytes(), SETUP)
        self.assertEqual(progress[-1], 100)
        self.updates.install(installer)
        self.assertEqual(self.ran, [[str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]])
        calls = len(self.github.calls)
        self.assertEqual(self.updates.download(found), installer)  # already here and still good: not downloaded again
        self.assertEqual(len(self.github.calls), calls + 1)  # only the checksum was asked for

    def test_the_same_or_older_version_is_not_an_update(self) -> None:
        self.github.latest = "v2.1.0"
        self.assertIsNone(self.updates.newest())
        self.assertIsNone(updater.Updater("dev", self.folder, opener=self.github).newest())

    def test_a_damaged_download_is_thrown_away_never_run(self) -> None:
        self.github.setup = SETUP[:-10] + b"tampered!!"
        with self.assertRaises(updater.UpdateError) as caught:
            self.updates.download(self.updates.newest())
        self.assertIn("damaged", str(caught.exception))
        self.assertEqual(list(self.folder.iterdir()), [])
        self.assertEqual(self.ran, [])

    def test_no_network_or_github_limits_are_said_plainly(self) -> None:
        self.github.fail = URLError(OSError("offline"))
        with self.assertRaises(updater.UpdateError) as caught:
            self.updates.newest()
        self.assertIn("couldn't reach GitHub", str(caught.exception))
        self.github.fail = HTTPError("u", 403, "rate limited", {}, io.BytesIO())
        with self.assertRaises(updater.UpdateError) as caught:
            self.updates.newest()
        self.assertIn("limiting", str(caught.exception))

    def test_a_cut_off_download_leaves_nothing_behind(self) -> None:
        github = self.github

        class CutOff(Answer):
            def read(self, size=-1):
                raise TimeoutError("read timed out")

        def opener(request, timeout):
            if request.full_url.endswith("/setup"):
                return CutOff(b"")
            return github(request, timeout)
        self.updates._open = opener
        with self.assertRaises(updater.UpdateError):
            self.updates.download(updater.parse_release(release("v2.2.0")))
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_going_back_finds_the_newest_older_release_with_an_installer(self) -> None:
        updates = updater.Updater("v2.2.0", self.folder, opener=self.github)
        self.assertEqual(updates.previous().version, "v2.1.0")
        older = updater.Updater("v2.1.0", self.folder, opener=self.github)
        self.assertEqual(older.previous().version, "v1.9.0")  # v2.0.0 has no installer

    def test_only_the_newest_two_installers_are_kept(self) -> None:
        for tag in ("v1.9.0", "v2.0.0", "v2.1.0"):
            (self.folder / f"Nova-Setup-{tag}.exe").write_bytes(b"old")
        self.updates.download(self.updates.newest())
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()),
                         ["Nova-Setup-v2.1.0.exe", "Nova-Setup-v2.2.0.exe"])

    def test_a_zip_copy_doesnt_replace_itself(self) -> None:
        zipped = updater.Updater("v2.1.0", self.folder, opener=self.github, can_install=lambda: False, run=self.ran.append)
        installer = zipped.download(zipped.newest())
        with self.assertRaises(updater.UpdateError):
            zipped.install(installer)
        self.assertEqual(self.ran, [])
        folder = Path(tempfile.mkdtemp())
        (folder / "Nova.exe").write_bytes(b"")
        self.assertFalse(updater.installed_by_setup(str(folder / "Nova.exe")))
        (folder / "install.ini").write_text("[Nova]\nversion=2.1.0\n")
        self.assertTrue(updater.installed_by_setup(str(folder / "Nova.exe")))

    def test_a_release_without_an_installer_points_to_its_page(self) -> None:
        bare = updater.parse_release(release("v2.3.0", with_setup=False))
        with self.assertRaises(updater.UpdateError) as caught:
            self.updates.download(bare)
        self.assertIn("releases/tag/v2.3.0", str(caught.exception))


class PackagingTests(unittest.TestCase):
    def test_the_installer_and_icon_are_wired_in(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = (root / "packaging" / "nova.iss").read_text()
        for line in ("PrivilegesRequired=lowest", "SetupIconFile=nova.ico", 'Filename: "{app}\\install.ini"',
                     "CloseApplications=force", 'Filename: "{app}\\Nova.exe"; Description: "Start Nova"; Flags: nowait postinstall'):
            self.assertIn(line, script)
        run_line = next(line for line in script.splitlines() if line.startswith('Filename: "{app}\\Nova.exe"'))
        self.assertNotIn("skipifsilent", run_line)  # a silent update starts Nova again
        self.assertIn("icon='packaging/nova.ico'", (root / "Alfred.spec").read_text())
        from PIL import Image
        self.assertIn((256, 256), Image.open(root / "packaging" / "nova.ico").info["sizes"])
        workflow = (root / ".github" / "workflows" / "build.yml").read_text()
        self.assertIn("Nova-Setup.exe Nova-Setup.exe.sha256", workflow)


if __name__ == "__main__":
    unittest.main()
