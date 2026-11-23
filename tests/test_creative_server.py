"""Creative mode's server: the control orb's presses and the objects the camera sees reach Nova; other pages can't."""
import json
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import creative_mode


class CreativeServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = creative_mode.CreativeServer()
        self.pressed: list[str] = []
        self.server.on_control = self.pressed.append
        self.base = self.server.start().rsplit("/", 1)[0]

    def tearDown(self) -> None:
        self.server.stop()

    def post(self, path: str, body: object, content_type: str = "application/json") -> int:
        request = Request(self.base + path, data=json.dumps(body).encode(), headers={"Content-Type": content_type}, method="POST")
        try:
            with urlopen(request, timeout=5) as response:
                return response.status
        except HTTPError as error:
            return error.code

    def test_controls_reach_nova(self) -> None:
        self.assertEqual(self.post("/control", {"action": "volume_up"}), 204)
        self.assertEqual(self.post("/control", {"action": "exit"}), 204)
        self.assertEqual(self.pressed, ["volume_up", "exit"])

    def test_unknown_actions_and_form_posts_are_refused(self) -> None:
        self.assertEqual(self.post("/control", {"action": "shutdown"}), 400)
        # What a page on another site could send without a CORS preflight:
        self.assertEqual(self.post("/control", {"action": "volume_up"}, "text/plain"), 400)
        self.assertEqual(self.pressed, [])

    def test_what_the_camera_sees(self) -> None:
        self.assertIn("closed", self.server.seen())  # no page is open
        with urlopen(self.base + "/commands", timeout=5):
            pass  # the page polls: creative mode is open
        self.assertEqual(self.post("/seen", ["cup (held)", "cell phone"]), 204)
        self.assertIn("cup (held), cell phone", creative_mode.run_tool(self.server, {"action": "look"}))
        self.assertEqual(self.post("/seen", []), 204)
        self.assertIn("nothing it knows", self.server.seen())
        self.assertIn("No vision model", self.server.seen())

    def test_a_vision_model_names_what_you_show(self) -> None:
        import base64
        import threading
        with urlopen(self.base + "/commands", timeout=5):
            pass
        photo = b"\xff\xd8\xff\xe0 a tiny jpeg"
        named = []
        self.server.identify = lambda jpeg, guess: named.append((jpeg, guess)) or "red Rubik's cube"

        def page_answers() -> None:  # the page sees the snapshot command and posts a photo
            for _ in range(50):
                with urlopen(self.base + "/commands", timeout=5) as response:
                    if any(command["action"] == "snapshot" for command in json.loads(response.read())):
                        self.post("/snapshot", {"image": "data:image/jpeg;base64," + base64.b64encode(photo).decode(), "guess": "cup"})
                        return
                threading.Event().wait(0.05)
        threading.Thread(target=page_answers, daemon=True).start()
        self.assertIn("red Rubik's cube", self.server.seen())
        self.assertEqual(named, [(photo, "cup")])
        # The orb's button: the photo goes straight to Nova; not-a-JPEG is refused.
        scans = []
        self.server.on_scan = lambda jpeg, guess: scans.append(guess)
        self.assertEqual(self.post("/snapshot", {"image": base64.b64encode(photo).decode(), "guess": "", "ask": True}), 204)
        self.assertEqual(self.post("/snapshot", {"image": base64.b64encode(b"not a jpeg").decode(), "ask": True}), 400)
        self.assertEqual(scans, [""])



def small_jpeg(color: tuple[int, int, int]) -> bytes:
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (64, 36), color).save(out, "JPEG")
    return out.getvalue()


class PhotoTests(unittest.TestCase):
    """The photo booth: photos are saved whole on this PC, blended into the average, and taken on request."""

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path
        self.server = creative_mode.CreativeServer()
        self.folder = Path(tempfile.mkdtemp()) / "Nova"
        self.server.photo_folder = self.folder
        self.saved: list = []
        self.server.on_photo = self.saved.append
        self.base = self.server.start().rsplit("/", 1)[0]

    def tearDown(self) -> None:
        self.server.stop()

    def post_photo(self, jpeg: bytes) -> tuple[int, dict]:
        import base64
        body = json.dumps({"image": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(), "lens": "pixel"}).encode()
        request = Request(self.base + "/photo", data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, {}

    def test_photos_are_saved_and_piled_into_the_average(self) -> None:
        from PIL import Image
        status, answer = self.post_photo(small_jpeg((255, 0, 0)))
        self.assertEqual(status, 200)
        self.assertTrue((self.folder / answer["saved"]).is_file())
        self.assertEqual(self.post_photo(small_jpeg((0, 0, 255)))[0], 200)
        photos = sorted(path.name for path in self.folder.glob("nova-*.jpg"))
        self.assertEqual(len(photos), 2, photos)  # two in the same second get different names
        self.assertEqual(json.loads((self.folder / "average.json").read_text())["count"], 2)
        red, _green, blue = Image.open(self.folder / "average.jpg").convert("RGB").getpixel((480, 270))
        self.assertTrue(100 < red < 160 and 100 < blue < 160, (red, blue))  # half red, half blue
        self.assertEqual(list(self.folder.glob("*.part")), [])  # nothing half-written left behind
        self.assertEqual(sorted(path.name for path in self.saved), photos)  # Nova heard about both
        self.assertEqual(self.post_photo(b"not a jpeg")[0], 400)

    def test_take_a_photo_lens_and_kiss_cam_on_request(self) -> None:
        import threading
        with urlopen(self.base + "/commands", timeout=5):
            pass  # the page polls: creative mode is open
        seen: list = []

        done = threading.Event()
        self.addCleanup(done.set)

        def page() -> None:  # the open page: does what Nova asks; a photo after its countdown
            while not done.wait(0.05):
                try:
                    with urlopen(self.base + "/commands", timeout=5) as response:
                        commands = json.loads(response.read())
                except OSError:
                    return  # the test is over
                for command in commands:
                    seen.append(command)
                    if command["action"] == "photo":
                        self.post_photo(small_jpeg((20, 200, 20)))
        threading.Thread(target=page, daemon=True).start()
        self.server.describe = lambda jpeg: "two friends laughing in a bright kitchen"
        result = creative_mode.run_tool(self.server, {"action": "photo", "describe": True})
        self.assertIn("saved it as nova-", result)
        self.assertIn("two friends laughing", result)
        self.assertIn("Camera lens: ascii", creative_mode.run_tool(self.server, {"action": "lens", "lens": "ascii"}))
        self.assertIn("Unknown lens", creative_mode.run_tool(self.server, {"action": "lens", "lens": "sepia"}))
        self.assertIn("Kiss cam is on", creative_mode.run_tool(self.server, {"action": "kiss_cam"}))
        self.assertIn("Kiss cam is off", creative_mode.run_tool(self.server, {"action": "kiss_cam", "on": False}))
        threading.Event().wait(0.4)
        self.assertEqual([command for command in seen if command["action"] != "photo"],
                         [{"action": "lens", "lens": "ascii"}, {"action": "kiss_cam", "on": True}, {"action": "kiss_cam", "on": False}])


class MediaPermissionTests(unittest.TestCase):
    """Seeding a profile grants the camera to Nova's own loopback origin — and nothing else."""

    def test_seeding_grants_only_novas_origin(self) -> None:
        import tempfile
        profile = Path(tempfile.mkdtemp()) / "creative-browser"
        creative_mode.seed_media_permission(profile, "http://127.0.0.1:54321")
        prefs = json.loads((profile / "Preferences").read_text(encoding="utf-8"))
        grants = prefs["profile"]["content_settings"]["exceptions"]["media_stream_camera"]
        self.assertEqual(list(grants), ["http://127.0.0.1:54321,*"])
        self.assertEqual(grants["http://127.0.0.1:54321,*"]["setting"], 1)
        self.assertEqual(prefs["profile"]["content_settings"]["exceptions"]["media_stream_mic"]["http://127.0.0.1:54321,*"]["setting"], 1)

    def test_other_origins_keep_their_settings_and_reseeding_is_safe(self) -> None:
        import tempfile
        profile = Path(tempfile.mkdtemp()) / "creative-browser"
        profile.mkdir(parents=True)
        existing = {"profile": {"content_settings": {"exceptions": {
            "media_stream_camera": {"https://example.com,*": {"setting": 2, "last_modified": "1"}},
            "media_stream_mic": {}}}}}
        (profile / "Preferences").write_text(json.dumps(existing), encoding="utf-8")
        creative_mode.seed_media_permission(profile, "http://127.0.0.1:54321")
        creative_mode.seed_media_permission(profile, "http://127.0.0.1:54321")
        prefs = json.loads((profile / "Preferences").read_text(encoding="utf-8"))
        camera = prefs["profile"]["content_settings"]["exceptions"]["media_stream_camera"]
        self.assertEqual(camera["https://example.com,*"]["setting"], 2)  # the other site still blocked
        self.assertEqual(len([key for key in camera if "127.0.0.1" in key]), 1)  # no duplicate grant


class OpenWindowTests(unittest.TestCase):
    """Opening Creative closes an already-open creative window first: a running Edge never
    re-reads the Preferences file the camera grant is seeded into, so without this the
    seed is silently ignored and the camera request pends on a prompt nobody sees."""

    def _open_with_mocks(self, existing):
        from unittest import mock
        server = creative_mode.CreativeServer()
        self.addCleanup(server.stop)
        events: list[tuple] = []
        patches = [
            mock.patch.object(creative_mode, "find_edge", return_value=Path("msedge.exe")),
            mock.patch.object(creative_mode, "find_window", return_value=existing),
            mock.patch.object(creative_mode, "is_window", return_value=False),
            mock.patch.object(creative_mode, "close_window",
                              side_effect=lambda hwnd: events.append(("close", hwnd))),
            mock.patch.object(creative_mode, "seed_media_permission",
                              side_effect=lambda _profile, origin: events.append(("seed", origin))),
            mock.patch.object(creative_mode, "bring_window_titled_to_front",
                              side_effect=lambda *_args: None),
            mock.patch.object(creative_mode.subprocess, "Popen",
                              side_effect=lambda argv, **_k: events.append(("open", argv))),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        server.open_window()
        return events

    def test_existing_window_is_closed_before_the_grant_is_seeded(self) -> None:
        events = self._open_with_mocks(existing=1234)
        self.assertEqual([kind for kind, _ in events], ["close", "seed", "open"])
        self.assertEqual(events[0][1], 1234)
        self.assertTrue(str(events[1][1]).startswith("http://127.0.0.1:"))
        self.assertIn("--user-data-dir=", " ".join(str(part) for part in events[2][1]))
        self.assertIn("creative-browser", " ".join(str(part) for part in events[2][1]))

    def test_no_existing_window_means_no_close_just_seed_and_open(self) -> None:
        events = self._open_with_mocks(existing=None)
        self.assertEqual([kind for kind, _ in events], ["seed", "open"])


if __name__ == "__main__":
    unittest.main()
