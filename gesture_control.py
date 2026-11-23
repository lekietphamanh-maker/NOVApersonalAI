"""Always-on webcam gestures. Hold 👍/👎 for volume, swipe an open hand for next/previous,
hold ✊ for play/pause, hold ✌ to open creative mode. The owner can add their own: a hand pose Nova records from
the webcam (matched against the 21 hand points MediaPipe finds), or ☝ / 🤟, each doing an action they choose.

Frames stay in memory and are discarded; nothing is recorded or sent anywhere.
"""
from __future__ import annotations

import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

# Seconds a gesture must be held before it acts, and how often a held gesture repeats.
HOLD = {"Thumb_Up": 0.3, "Thumb_Down": 0.3, "Closed_Fist": 0.6, "Victory": 0.8}
REPEAT = {"Thumb_Up": 0.2, "Thumb_Down": 0.2}
ACTION = {"Thumb_Up": "volume_up", "Thumb_Down": "volume_down", "Closed_Fist": "play_pause", "Victory": "creative"}
SWIPE_DISTANCE = 0.2   # fraction of the frame width
SWIPE_WINDOW = 0.6     # seconds
SWIPE_COOLDOWN = 0.8
GESTURE_SCORE = 0.5    # MediaPipe's confidence needed to count a gesture
CUSTOM_HOLD = 0.5      # seconds the owner's own gesture is held before it acts
CUSTOM_MATCH = 0.2     # how close a pose must be to a recorded one (mean distance per hand point, in palm sizes)
BUILT_IN_POSES = ("Pointing_Up", "ILoveYou")  # MediaPipe knows these; Nova uses them only for the owner's gestures


def pose_features(hand) -> list[float]:
    """A hand's shape, wherever it is in the frame and however near: the 21 points (x, y) from the wrist, in palm
    sizes (wrist to the middle finger's knuckle). Turning the hand changes it, so ☝ and 👉 stay different gestures."""
    wrist, knuckle = hand[0], hand[9]
    palm = max(1e-6, ((knuckle.x - wrist.x) ** 2 + (knuckle.y - wrist.y) ** 2) ** 0.5)
    return [round(value, 4) for point in hand for value in ((point.x - wrist.x) / palm, (point.y - wrist.y) / palm)]


def pose_distance(features: list[float], sample: list[float]) -> float:
    """The mean distance between matching hand points of two poses."""
    pairs = range(0, min(len(features), len(sample)) - 1, 2)
    return sum(((features[i] - sample[i]) ** 2 + (features[i + 1] - sample[i + 1]) ** 2) ** 0.5 for i in pairs) / max(1, len(pairs))


def match_custom(features: list[float] | None, gesture: str | None, custom: list[dict]) -> str | None:
    """The owner's gesture this frame shows: "custom:<id>", or None."""
    for item in custom:
        if item.get("pose") and item["pose"] == gesture:
            return f"custom:{item['id']}"
    if features is None:
        return None
    best, best_id = CUSTOM_MATCH, None
    for item in custom:
        for sample in item.get("samples") or []:
            distance = pose_distance(features, sample)
            if distance < best:
                best, best_id = distance, item["id"]
    return f"custom:{best_id}" if best_id else None


def model_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / "creative" / "vendor" / "models" / "gesture_recognizer.task"


class GestureInterpreter:
    """Turns per-frame (time, gesture, wrist x) into at most one action. Pure logic, no camera."""

    def __init__(self) -> None:
        self.current: str | None = None
        self.since = 0.0
        self.last_fired: float | None = None
        self.track: deque[tuple[float, float]] = deque()
        self.swipe_ready_at = 0.0

    def update(self, now: float, gesture: str | None, wrist_x: float | None) -> str | None:
        """gesture: MediaPipe's category ("None" for a hand making no known gesture), or None with no hand.
        wrist_x: 0..1 as the user sees themselves in a mirror (moving right increases it)."""
        if wrist_x is None:
            self.track.clear()
        else:
            self.track.append((now, wrist_x))
            while self.track and now - self.track[0][0] > SWIPE_WINDOW:
                self.track.popleft()
            if gesture in ("Open_Palm", "None") and now >= self.swipe_ready_at and len(self.track) >= 3:
                travel = self.track[-1][1] - self.track[0][1]
                if abs(travel) >= SWIPE_DISTANCE:
                    self.swipe_ready_at = now + SWIPE_COOLDOWN
                    self.track.clear()
                    return "next" if travel > 0 else "previous"

        if gesture != self.current:
            self.current, self.since, self.last_fired = gesture, now, None
            return None
        if gesture is not None and gesture.startswith("custom:"):  # the owner's own gesture: acts once per hold
            if self.last_fired is None and now - self.since >= CUSTOM_HOLD:
                self.last_fired = now
                return gesture
            return None
        if gesture not in HOLD:
            return None
        if self.last_fired is None:
            if now - self.since >= HOLD[gesture]:
                self.last_fired = now
                return ACTION[gesture]
        elif gesture in REPEAT and now - self.last_fired >= REPEAT[gesture]:
            self.last_fired = now
            return ACTION[gesture]
        return None


class GestureControl:
    """Reads the webcam in a background thread. pause() releases the camera (for creative mode)."""

    def __init__(self, on_action: Callable[[str], None], on_error: Callable[[str], None] | None = None,
                 source: int | str = 0) -> None:
        self.on_action = on_action
        self.on_error = on_error or (lambda _message: None)
        self.source = source  # a camera index, or a video file for tests
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._camera_free = threading.Event()
        self._camera_free.set()  # nothing held until the reader opens the webcam
        self._thread: threading.Thread | None = None
        self.custom: list[dict] = []  # the owner's own gestures: {"id", "pose"} or {"id", "samples": [features…]}
        self._recording: dict | None = None  # {"until", "skip_until", "samples", "done"} while one is recorded

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if not self.running:
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="AlfredGestures", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)

    def wait_camera_free(self, timeout: float) -> bool:
        """True once the reader has let go of the webcam (already true when it never started)."""
        return self._camera_free.wait(timeout)

    def pause(self, paused: bool) -> None:
        (self._paused.set if paused else self._paused.clear)()

    def record(self, seconds: float, done: Callable[[list[list[float]]], None]) -> None:
        """Collect the hand pose the owner holds for the next few seconds (the first moment is them getting ready)."""
        now = time.monotonic()
        self._recording = {"until": now + seconds, "skip_until": now + 0.8, "samples": [], "done": done}

    def _keep_sample(self, hand) -> None:
        recording = self._recording
        if recording is None:
            return
        now = time.monotonic()
        if hand is not None and now >= recording["skip_until"]:
            recording["samples"].append(pose_features(hand))
        if now >= recording["until"]:
            self._recording = None
            samples = recording["samples"]
            step = max(1, len(samples) // 20)  # at most 20 kept, spread over the hold
            recording["done"](samples[::step][:20])

    def _run(self) -> None:
        try:
            import cv2
            import mediapipe as mp
            from mediapipe.tasks.python import vision
            from mediapipe.tasks.python.core.base_options import BaseOptions
            recognizer = vision.GestureRecognizer.create_from_options(vision.GestureRecognizerOptions(
                base_options=BaseOptions(model_asset_path=str(model_path())), running_mode=vision.RunningMode.VIDEO,
                num_hands=1, min_hand_detection_confidence=0.5, min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5))
        except Exception as exc:
            self.on_error(f"Gesture control could not start: {exc}")
            return
        interpreter = GestureInterpreter()
        from_file = isinstance(self.source, str)
        camera = None
        last_timestamp = -1
        reported = False
        try:
            while not self._stop.is_set():
                if self._paused.is_set():
                    if camera is not None:
                        camera.release()  # hand the webcam to creative mode
                        camera = None
                        self._camera_free.set()
                    time.sleep(0.3)
                    continue
                if camera is None:
                    backend = cv2.CAP_DSHOW if sys.platform == "win32" and not from_file else cv2.CAP_ANY
                    camera = cv2.VideoCapture(self.source, backend)
                    if not camera.isOpened():
                        camera = None
                        if not reported:
                            self.on_error("The webcam is not available. Check that it is connected and allowed in "
                                          "Windows Settings > Privacy > Camera.")
                            reported = True
                        time.sleep(3)
                        continue
                    self._camera_free.clear()
                    reported = False
                ok, frame = camera.read()
                if not ok:
                    if from_file:
                        break
                    camera.release()
                    camera = None
                    self._camera_free.set()
                    continue
                # Video files carry their own clock; a live camera uses wall time.
                now = camera.get(cv2.CAP_PROP_POS_MSEC) / 1000 if from_file else time.monotonic()
                timestamp = max(last_timestamp + 1, int(now * 1000))
                last_timestamp = timestamp
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                result = recognizer.recognize_for_video(image, timestamp)
                hand = result.hand_landmarks[0] if result.hand_landmarks else None
                gesture = None
                if hand is not None:
                    top = result.gestures[0][0] if result.gestures and result.gestures[0] else None
                    gesture = top.category_name if top is not None and top.score >= GESTURE_SCORE else "None"
                    if self._recording is None and self.custom:
                        gesture = match_custom(pose_features(hand), gesture, self.custom) or gesture
                self._keep_sample(hand)
                action = interpreter.update(now, gesture, 1 - hand[0].x if hand is not None else None)
                if action:
                    self.on_action(action)
                if not from_file:
                    time.sleep(0.03)  # ~20 frames a second: quick enough to feel instant, still light on CPU
        finally:
            if camera is not None:
                camera.release()
                self._camera_free.set()
            recognizer.close()
