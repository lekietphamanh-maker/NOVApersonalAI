"""Serves creative mode (creative/index.html) on loopback and relays Nova's commands to the page."""
from __future__ import annotations

import base64
import binascii
import io
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from typing import Callable
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app_window import find_edge

# A fixed port keeps the page's origin stable, so the browser remembers the camera permission.
PREFERRED_PORT = 8765
SHAPES = ("reactor", "cube", "sphere", "torus", "cone", "cylinder")
ACTIONS = ("open", "add", "explode", "assemble", "clear", "look", "photo", "lens", "kiss_cam", "style")
STYLES = {"wire": "glowing wireframe", "solid": "solid glass"}
CONTROLS = ("volume_up", "volume_down", "play_pause", "next", "previous", "exit")
SNAPSHOT_BYTES = 1_500_000  # one cropped JPEG of the object (the page sends at most 384 x 384)
PHOTO_BYTES = 12_000_000    # one photo as a data URL (the page sends at most 1600 px wide)
# Live camera effects (creative/lenses.js), after the camera ideas in github.com/tigrisli/curious-machines.
LENSES = {
    "normal": "the plain mirror",
    "pixel": "chunky pixels that sharpen as you come closer",
    "ascii": "the picture drawn in text, with the letters of the owner's name",
    "glitch": "a glitch that calms down when you hold still",
    "slitscan": "a slit-scan: whatever crosses the middle is stretched over time",
    "echo": "the picture from 3 seconds ago",
}
AVERAGE_SIZE = (960, 540)


def photo_folder() -> Path:
    return Path.home() / "Pictures" / "Nova"


def save_photo(folder: Path, jpeg: bytes) -> Path:
    """nova-YYYYMMDD-HHMMSS.jpg in `folder`, written to a temporary name first and renamed when complete, so an
    interrupted save never leaves a broken photo behind."""
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = folder / f"nova-{stamp}.jpg"
    number = 2
    while path.exists():
        path = folder / f"nova-{stamp}-{number}.jpg"
        number += 1
    partial_path = path.with_suffix(".part")
    partial_path.write_bytes(jpeg)
    os.replace(partial_path, path)
    return path


def update_average(folder: Path, jpeg: bytes) -> int:
    """Blend this photo into average.jpg: every photo so far, piled into one picture. Returns how many it holds."""
    from PIL import Image, ImageOps
    picture = ImageOps.fit(Image.open(io.BytesIO(jpeg)).convert("RGB"), AVERAGE_SIZE)
    average_path, count_path = folder / "average.jpg", folder / "average.json"
    try:
        count = int(json.loads(count_path.read_text(encoding="utf-8")).get("count", 0))
        average = Image.open(average_path).convert("RGB").resize(AVERAGE_SIZE) if count else None
    except (OSError, ValueError, AttributeError):
        count, average = 0, None  # missing or broken: start again from this photo
    if average is not None:
        picture = Image.blend(average, picture, 1 / (count + 1))
    partial_path = average_path.with_suffix(".part")
    picture.save(partial_path, "JPEG", quality=95)
    os.replace(partial_path, average_path)
    count_path.write_text(json.dumps({"count": count + 1}), encoding="utf-8")
    return count + 1


def creative_folder() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / "creative"


class _Handler(SimpleHTTPRequestHandler):
    # Windows registries often map .js to text/plain, which browsers refuse for modules.
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript", ".mjs": "text/javascript",
                      ".wasm": "application/wasm", ".task": "application/octet-stream", ".tflite": "application/octet-stream", ".html": "text/html"}

    def __init__(self, *args, server_state: "CreativeServer", **kwargs) -> None:
        self.server_state = server_state
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        if self.path.split("?")[0] == "/commands":
            body = json.dumps(self.server_state.take_commands()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - http.server naming
        """The page's control orb (/control), the objects it sees (/seen) and a photo of the one you show
        (/snapshot). JSON only: a web page from elsewhere can't send that without a CORS preflight, which this
        server never answers."""
        route = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        limit = {"/snapshot": SNAPSHOT_BYTES, "/photo": PHOTO_BYTES}.get(route, 4096)
        if (route not in ("/control", "/seen", "/snapshot", "/photo") or self.headers.get("Content-Type") != "application/json"
                or not 0 < length <= limit):
            self.send_error(400)
            return
        try:
            data = json.loads(self.rfile.read(length))
        except ValueError:
            self.send_error(400)
            return
        if route == "/control" and isinstance(data, dict) and data.get("action") in CONTROLS:
            self.server_state.on_control(data["action"])
        elif route == "/seen" and isinstance(data, list):
            self.server_state.set_seen(data)
        elif route == "/snapshot" and isinstance(data, dict) and isinstance(data.get("image"), str):
            try:
                jpeg = base64.b64decode(data["image"].split(",", 1)[-1], validate=True)
            except (binascii.Error, ValueError):
                self.send_error(400)
                return
            if not jpeg.startswith(b"\xff\xd8"):
                self.send_error(400)
                return
            self.server_state.set_snapshot(jpeg, str(data.get("guess") or "")[:60], bool(data.get("ask")))
        elif route == "/photo" and isinstance(data, dict) and isinstance(data.get("image"), str):
            try:
                jpeg = base64.b64decode(data["image"].split(",", 1)[-1], validate=True)
            except (binascii.Error, ValueError):
                self.send_error(400)
                return
            if not jpeg.startswith(b"\xff\xd8"):
                self.send_error(400)
                return
            try:
                path = self.server_state.keep_photo(jpeg)
            except OSError:
                self.send_error(500)
                return
            body = json.dumps({"saved": path.name}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        else:
            self.send_error(400)
            return
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_args) -> None:
        pass  # the windowed app has no console; stderr may be None


class CreativeServer:
    def __init__(self) -> None:
        self._commands: list[dict] = []
        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None
        self._last_poll = 0.0
        self.before_open: Callable[[], None] = lambda: None  # e.g. let go of the webcam first
        self.open_in_app: Callable[[str], bool] = lambda _url: False  # True when Nova's window showed it
        self.on_control: Callable[[str], None] = lambda _action: None  # the page's control orb was pressed
        self._seen: list[str] = []
        self._seen_at = 0.0
        # A local vision model that names anything in a photo (None until one is installed), and the orb's
        # "what is this" button: (jpeg, detector's guess) -> handled by Nova.
        self.identify: Callable[[bytes, str], str] | None = None
        self.on_scan: Callable[[bytes, str], None] = lambda _jpeg, _guess: None
        self._snapshot: tuple[bytes, str] | None = None
        self._snapshot_ready = threading.Event()
        # Photos: where they go, what Nova does with a new one (a toast), and a local vision model's one-line
        # description of a whole photo (None until one is installed).
        self.photo_folder: Path = photo_folder()
        self.on_photo: Callable[[Path], None] = lambda _path: None
        self.describe: Callable[[bytes], str] | None = None
        self._photo: tuple[Path, bytes] | None = None
        self._photo_ready = threading.Event()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._httpd.server_address[1]}/index.html"

    def start(self) -> str:
        if self._httpd is None:
            handler = partial(_Handler, directory=str(creative_folder()), server_state=self)
            try:
                self._httpd = ThreadingHTTPServer(("127.0.0.1", PREFERRED_PORT), handler)
            except OSError:
                self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=self._httpd.serve_forever, name="AlfredCreative", daemon=True).start()
        return self.url

    def send(self, command: dict) -> None:
        with self._lock:
            self._commands.append(command)

    @property
    def active(self) -> bool:
        """True while a creative window is open (it asks for commands every 0.6 s)."""
        return time.monotonic() - self._last_poll < 3

    def set_seen(self, objects: list) -> None:
        """What the camera sees right now, e.g. ["cup (held)", "cell phone"]."""
        with self._lock:
            self._seen = [str(item)[:60] for item in objects[:10]]
            self._seen_at = time.monotonic()

    def set_snapshot(self, jpeg: bytes, guess: str, ask: bool) -> None:
        if ask:
            self.on_scan(jpeg, guess)
            return
        self._snapshot = (jpeg, guess)
        self._snapshot_ready.set()

    def request_snapshot(self, timeout: float = 4.0) -> tuple[bytes, str] | None:
        """Ask the open page for a photo of what you are showing; None if it doesn't answer in time."""
        self._snapshot_ready.clear()
        self._snapshot = None
        self.send({"action": "snapshot"})
        return self._snapshot if self._snapshot_ready.wait(timeout) else None

    def keep_photo(self, jpeg: bytes) -> Path:
        """A photo from the page: saved, blended into the average, then announced."""
        path = save_photo(self.photo_folder, jpeg)
        try:
            update_average(self.photo_folder, jpeg)
        except Exception:
            pass  # the photo itself is saved; the average is just for fun
        self._photo = (path, jpeg)
        self._photo_ready.set()
        self.on_photo(path)
        return path

    def take_photo(self, timeout: float = 16.0) -> tuple[Path, bytes] | None:
        """Ask the page for a photo (3-2-1, then the shot; the camera may still be starting)."""
        self._photo_ready.clear()
        self._photo = None
        self.send({"action": "photo"})
        return self._photo if self._photo_ready.wait(timeout) else None

    def show_label(self, text: str) -> None:
        """Write what the vision model said next to the object on the page."""
        self.send({"action": "label", "text": text[:120]})

    def seen(self) -> str:
        with self._lock:
            fresh = self._seen if time.monotonic() - self._seen_at < 5 else []
        if not self.active:
            return "Creative mode is closed, so the camera is off. Open it first, then ask again."
        detector = ("The quick detector sees: " + ", ".join(fresh) + "." if fresh
                    else "The quick detector sees nothing it knows (it knows about 80 everyday kinds).")
        if self.identify is not None:
            snapshot = self.request_snapshot()
            if snapshot is not None:
                name = self.identify(*snapshot)
                self.show_label(name)
                return f"The vision model looked at what the user is showing: {name}. {detector}"
            return f"The camera page didn't send a photo in time. {detector}"
        return (f"{detector} No vision model is installed, so only those 80 kinds can be named. Tell the user they "
                "can download one (about 3 GB, runs on this PC) with the WHAT IS THIS button on the orb or in SETTINGS.")

    def take_commands(self) -> list[dict]:
        self._last_poll = time.monotonic()
        with self._lock:
            commands, self._commands = self._commands, []
        return commands

    def open_window(self) -> str:
        """Show the page inside Nova's window when it is open, else as an Edge app window or in the browser."""
        url = self.start()
        self.before_open()
        if self.open_in_app(url):
            return url
        edge = find_edge()
        if edge is not None:
            subprocess.Popen([str(edge), f"--app={url}", "--start-maximized"])
        else:
            webbrowser.open(url)
        return url

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd = None


def run_tool(server: CreativeServer, arguments: object) -> str:
    """The creative_mode tool: validated, then relayed to the page."""
    if not isinstance(arguments, dict) or arguments.get("action") not in ACTIONS:
        return f"Tool arguments were invalid; action must be one of {', '.join(ACTIONS)}."
    action = arguments["action"]
    if action == "open":
        server.open_window()
        return "Opened creative mode. The user may need to allow the camera."
    if action == "add":
        shape = arguments.get("shape")
        if shape not in SHAPES:
            return f"Unknown shape; choose one of {', '.join(SHAPES)}."
        server.send({"action": "add", "shape": shape})
        return f"Added a {shape} in creative mode."
    if action == "look":
        return server.seen()
    if action == "lens":
        lens = arguments.get("lens")
        if lens not in LENSES:
            return f"Unknown lens; choose one of {', '.join(LENSES)}."
        if not server.active:
            server.open_window()
        server.send({"action": "lens", "lens": lens})
        return f"Camera lens: {lens}, {LENSES[lens]}."
    if action == "kiss_cam":
        on = arguments.get("on") is not False
        if on and not server.active:
            server.open_window()
        server.send({"action": "kiss_cam", "on": on})
        return ("Kiss cam is on: when two faces stay in the picture for 3 seconds, it counts down and takes a photo."
                if on else "Kiss cam is off.")
    if action == "photo":
        return _take_photo(server, describe=bool(arguments.get("describe")))
    if action == "style":
        look = arguments.get("style")
        if look not in STYLES:
            return f"Unknown look; choose one of {', '.join(STYLES)}."
        if not server.active:
            server.open_window()
        server.send({"action": "style", "style": look})
        return f"Holograms now look like {STYLES[look]}."
    server.send({"action": action})
    return {"explode": "Exploded the selected object into its parts.", "assemble": "Put the selected object back together.",
            "clear": "Cleared all objects."}[action]


def _take_photo(server: CreativeServer, describe: bool) -> str:
    if not server.active:
        server.open_window()
        deadline = time.monotonic() + 10
        while not server.active and time.monotonic() < deadline:
            time.sleep(0.2)
    taken = server.take_photo()
    if taken is None:
        return ("The camera didn't take the photo in time. Creative mode may still be starting, or the camera isn't "
                "allowed; ask the user to try again.")
    path, jpeg = taken
    text = (f"Took the photo after a 3-2-1 countdown and saved it as {path.name} in {path.parent} (only on this PC). "
            "Every photo is also blended into average.jpg there.")
    if describe:
        if server.describe is None:
            text += " No vision model is installed, so you can't see what is in it; say so."
        else:
            text += f" A local vision model looked at it: {server.describe(jpeg)}"
    return text
