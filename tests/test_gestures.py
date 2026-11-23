"""Gesture timing rules, then the real recognizer on a short video made from photos of hands."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gesture_control import GestureControl, GestureInterpreter

FIXTURES = Path(__file__).with_name("fixtures")


def feed(frames: list[tuple[float, str | None, float | None]]) -> list[str]:
    interpreter = GestureInterpreter()
    return [action for now, gesture, x in frames if (action := interpreter.update(now, gesture, x))]


class GestureRuleTests(unittest.TestCase):
    def test_thumbs_up_must_be_held_then_repeats(self) -> None:
        frames = [(t / 10, "Thumb_Up", 0.5) for t in range(0, 16)]  # 1.5 s
        self.assertEqual(len(feed(frames)), 5)  # first at 0.3 s, then every 0.2 s (a frame later at 10 fps)

    def test_a_flash_of_a_gesture_does_nothing(self) -> None:
        frames = [(0.0, "Thumb_Up", 0.5), (0.2, "Thumb_Up", 0.5), (0.25, "Open_Palm", 0.5), (0.5, "Thumb_Up", 0.5)]
        self.assertEqual(feed(frames), [])

    def test_fist_and_victory_fire_once_per_hold(self) -> None:
        self.assertEqual(feed([(t / 10, "Closed_Fist", 0.5) for t in range(30)]), ["play_pause"])
        self.assertEqual(feed([(t / 10, "Victory", 0.5) for t in range(30)]), ["creative"])

    def test_swipes(self) -> None:
        right = [(0.0, "Open_Palm", 0.3), (0.1, "Open_Palm", 0.45), (0.2, "Open_Palm", 0.65)]
        left = [(2.0, "Open_Palm", 0.7), (2.1, "Open_Palm", 0.5), (2.2, "Open_Palm", 0.35)]
        self.assertEqual(feed(right + left), ["next", "previous"])

    def test_slow_drift_is_not_a_swipe_and_swipes_cool_down(self) -> None:
        drift = [(t / 10, "Open_Palm", 0.3 + t * 0.005) for t in range(30)]
        self.assertEqual(feed(drift), [])
        double = [(0.0, "Open_Palm", 0.2), (0.1, "Open_Palm", 0.4), (0.2, "Open_Palm", 0.6),
                  (0.3, "Open_Palm", 0.2), (0.4, "Open_Palm", 0.4), (0.5, "Open_Palm", 0.6)]
        self.assertEqual(feed(double), ["next"])

    def test_losing_the_hand_resets(self) -> None:
        frames = [(0.0, "Thumb_Up", 0.5), (0.2, None, None), (0.4, "Thumb_Up", 0.5), (0.6, "Thumb_Up", 0.5)]
        self.assertEqual(feed(frames), [])


def make_video(path: str) -> None:
    """1.2 s of a held thumbs-up, then 1.5 s of a peace sign, as the webcam would see them."""
    import cv2
    width, height = 640, 480
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 10, (width, height))
    for name, seconds in (("thumbs_up.jpg", 1.2), ("victory.jpg", 1.5)):
        frame = cv2.resize(cv2.imread(str(FIXTURES / name)), (width, height))
        for _ in range(int(seconds * 10)):
            writer.write(frame)
    writer.release()


class OwnGesturesTest(unittest.TestCase):
    """The owner's own gestures: a recorded hand pose (or ☝ / 🤟) matched frame by frame, held, then acted on once."""

    @staticmethod
    def hand(points, at=(0.5, 0.5), size=1.0):
        from types import SimpleNamespace
        return [SimpleNamespace(x=at[0] + x * size, y=at[1] + y * size) for x, y in points]

    # 21 hand points: an open hand and a "rock on" (index and little finger up), wrist at (0, 0), knuckle 9 at (0, -0.1)
    OPEN = [(0, 0), (-.04, -.02), (-.07, -.05), (-.09, -.08), (-.11, -.1), (-.03, -.1), (-.035, -.15), (-.04, -.19),
            (-.045, -.22), (0, -.1), (0, -.16), (0, -.21), (0, -.25), (.03, -.095), (.035, -.15), (.04, -.19), (.045, -.22),
            (.055, -.085), (.065, -.12), (.07, -.15), (.075, -.18)]
    ROCK = [(0, 0), (-.04, -.02), (-.05, -.05), (-.03, -.07), (-.01, -.08), (-.03, -.1), (-.035, -.15), (-.04, -.19),
            (-.045, -.22), (0, -.1), (0, -.12), (.005, -.09), (.01, -.08), (.03, -.095), (.03, -.11), (.03, -.09),
            (.03, -.08), (.055, -.085), (.065, -.12), (.07, -.15), (.075, -.18)]

    def test_a_pose_is_the_same_anywhere_in_the_frame_and_at_any_distance(self) -> None:
        from gesture_control import pose_distance, pose_features
        near = pose_features(self.hand(self.ROCK, at=(0.3, 0.7), size=1.6))
        far = pose_features(self.hand(self.ROCK, at=(0.6, 0.4), size=0.7))
        self.assertLess(pose_distance(near, far), 0.01)
        self.assertGreater(pose_distance(near, pose_features(self.hand(self.OPEN))), 0.2)

    def test_the_closest_recorded_pose_wins_and_others_are_ignored(self) -> None:
        from gesture_control import match_custom, pose_features
        custom = [{"id": "rock", "samples": [pose_features(self.hand(self.ROCK))]},
                  {"id": "point", "pose": "Pointing_Up"}]
        jittered = [(x + (0.004 if index % 2 else -0.004), y) for index, (x, y) in enumerate(self.ROCK)]
        self.assertEqual(match_custom(pose_features(self.hand(jittered, at=(0.2, 0.6))), "None", custom), "custom:rock")
        self.assertIsNone(match_custom(pose_features(self.hand(self.OPEN)), "Open_Palm", custom))
        self.assertEqual(match_custom(None, "Pointing_Up", custom), "custom:point")

    def test_held_it_acts_once(self) -> None:
        interpreter = GestureInterpreter()
        frames = [(t / 10, "custom:rock", 0.5) for t in range(0, 30)]
        self.assertEqual([action for now, gesture, x in frames if (action := interpreter.update(now, gesture, x))], ["custom:rock"])
        later = [(3.1, "custom:rock", 0.5), (3.2, None, None), (3.3, "custom:rock", 0.5), (3.9, "custom:rock", 0.5)]
        self.assertEqual([action for now, gesture, x in later if (action := interpreter.update(now, gesture, x))], ["custom:rock"])

    def test_recording_keeps_the_held_pose(self) -> None:
        import time as clock
        from gesture_control import pose_features
        control = GestureControl(on_action=lambda _action: None)
        got: list = []
        control.record(0.0, got.append)
        control._recording["skip_until"] = 0
        control._recording["until"] = clock.monotonic() + 60
        for _ in range(45):
            control._keep_sample(self.hand(self.ROCK))
        control._recording["until"] = 0
        control._keep_sample(None)
        self.assertEqual(len(got[0]), 20)  # spread over the hold, at most 20
        self.assertEqual(got[0][0], pose_features(self.hand(self.ROCK)))
        self.assertIsNone(control._recording)


class CameraHandoffTest(unittest.TestCase):
    """Pausing the gesture reader really lets go of the webcam, so Creative mode can open it."""

    @staticmethod
    def _long_video(path: str, seconds: float = 10) -> None:
        """A long still video, so the reader is still holding it when the test pauses it."""
        import cv2
        frame = cv2.imread(str(FIXTURES / "thumbs_up.jpg"))
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 10, (640, 480))
        for _ in range(int(seconds * 10)):
            writer.write(cv2.resize(frame, (640, 480)))
        writer.release()

    def test_pause_releases_the_camera(self) -> None:
        import time
        try:
            import cv2  # noqa: F401
            import mediapipe  # noqa: F401
        except ImportError as exc:
            self.skipTest(f"needs OpenCV and MediaPipe: {exc}")
        video = Path(tempfile.mkdtemp()) / "hands.avi"
        self._long_video(str(video))
        control = GestureControl(lambda _action: None, lambda _message: None, source=str(video))
        try:
            self.assertTrue(control.wait_camera_free(1), "nothing is held before it starts")
            control.start()
            deadline = time.monotonic() + 15
            while control.wait_camera_free(0) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(control.wait_camera_free(0), "the reader should be holding the video")
            control.pause(True)
            self.assertTrue(control.wait_camera_free(5), "pausing should release the camera")
        finally:
            control.stop()


class RecognizerVideoTest(unittest.TestCase):
    """The real MediaPipe model reading a video file, exactly as it reads the webcam."""

    def test_held_thumbs_up_and_victory_in_a_video(self) -> None:
        try:
            import cv2  # noqa: F401
            import mediapipe  # noqa: F401
        except ImportError as exc:
            self.skipTest(f"needs OpenCV and MediaPipe: {exc}")
        video = Path(tempfile.mkdtemp()) / "hands.avi"
        make_video(str(video))
        actions: list[str] = []
        errors: list[str] = []
        control = GestureControl(actions.append, errors.append, source=str(video))
        control.start()
        control._thread.join(timeout=60)
        print("actions:", actions, "errors:", errors)
        self.assertEqual(errors, [])
        self.assertIn("volume_up", actions)
        self.assertEqual(actions.count("creative"), 1)


if __name__ == "__main__":
    unittest.main()
