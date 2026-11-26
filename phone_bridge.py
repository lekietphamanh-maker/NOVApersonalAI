"""Nova Lite: a small web app for the user's iPhone that talks to Nova on this PC over the home network.

Off until the user turns it on. Every request needs the pairing token from the QR code; actions that need
approval are approved on the phone. The app runs over HTTPS with a certificate from Nova's own local
authority (local_tls), which the phone trusts after a one-time install from the setup page. HTTPS also lets
the page use the phone's microphone; recordings are transcribed on the PC and not kept.
"""
from __future__ import annotations

import hmac
import io
import json
import os
import ssl
import wave
import secrets
import socket
import sys
import threading
import uuid
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

PORT = 8766       # the app, HTTPS
SETUP_PORT = 8767  # the one-time setup page and the certificate download, plain HTTP
APPROVAL_TIMEOUT = 120  # seconds; no answer means "no"
MAX_VOICE_BYTES = 16_000 * 2 * 60 + 44  # one minute of 16 kHz mono speech


def phone_folder() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "phone"


# The HUD's orb and its fonts, so the phone, the TV and the deck show the same Nova as the PC.
FROM_HUD = {"/core.js": ("core.js", "text/javascript"),
            **{f"/fonts/{name}": (f"fonts/{name}", "font/woff2") for name in (
                "rajdhani-latin-600-normal.woff2", "jetbrains-mono-latin-400-normal.woff2",
                "jetbrains-mono-latin-600-normal.woff2")}}


def _send_from_hud(handler: SimpleHTTPRequestHandler, path: str) -> bool:
    if path not in FROM_HUD:
        return False
    name, kind = FROM_HUD[path]
    body = (Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "ui" / name).read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", kind)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "max-age=3600")
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _screen_for(bridge: "PhoneBridge", raw_path: str) -> dict:
    """What a screen shows, for GET /api/screen?music=<key>&slide=<id>: the cover and picture it already has stay home."""
    known = parse_qs(urlsplit(raw_path).query)
    return bridge.screen_state((known.get("music") or [""])[0], (known.get("slide") or [""])[0])


def _token_path() -> Path:
    base = os.environ.get("ALFRED_DATA_DIR") or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Alfred" / "DesktopData"
    return Path(base) / "phone_token.txt"


def load_token(rotate: bool = False) -> str:
    path = _token_path()
    if not rotate and path.is_file():
        return path.read_text(encoding="utf-8").strip()
    token = secrets.token_urlsafe(24)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")
    return token


def lan_address() -> str:
    """This PC's address on the home network (no packet is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("10.255.255.255", 1))
            return probe.getsockname()[0]
        except OSError:
            return "127.0.0.1"


class _Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".html": "text/html", ".png": "image/png"}

    def __init__(self, *args, bridge: "PhoneBridge", **kwargs) -> None:
        self.bridge = bridge
        super().__init__(*args, **kwargs)

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        return hmac.compare_digest(supplied.encode(), self.bridge.token.encode())

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path.startswith("/api/"):
            if not self._authorized():
                return self._json(401, {"error": "not paired"})
            if path == "/api/hello":
                return self._json(200, {"ok": True})
            if path == "/api/pending":
                return self._json(200, self.bridge.pending_question())
            if path == "/api/screen":  # the phone's home screen shows what the TV shows
                return self._json(200, _screen_for(self.bridge, self.path))
            return self._json(404, {"error": "unknown"})
        if path in ("/", "/index.html", "/icon.png", "/deck", "/deck.html"):
            self.path = {"/": "/index.html", "/deck": "/deck.html"}.get(path, path)
            return super().do_GET()
        if _send_from_hud(self, path):
            return None
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith("/api/") or not self._authorized():
            return self._json(401, {"error": "not paired"})
        if self.path == "/api/voice":
            return self._voice()
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length)) if 0 < length <= 64_000 else {}  # text is cut to 2,000 below
        except (ValueError, json.JSONDecodeError):
            data = {}
        if self.path == "/api/chat":
            text = str(data.get("text", "")).strip()[:2000]
            if not text:
                return self._json(400, {"error": "empty message"})
            return self._json(200, {"reply": self.bridge.chat(text)})
        if self.path == "/api/answer":
            self.bridge.answer(str(data.get("id", "")), data.get("approved") is True)
            return self._json(200, {"ok": True})
        if self.path == "/api/control":
            return self._json(200, {"message": self.bridge.control(str(data.get("action", "")))})
        if self.path == "/api/deck" and ("keys" in data or "text" in data):
            return self._json(200, {"message": self.bridge.keyboard(data)})
        if self.path == "/api/deck":
            return self._json(200, {"message": self.bridge.deck(str(data.get("action", "")))})
        return self._json(404, {"error": "unknown"})

    def _voice(self) -> None:
        """A recording from the phone (16 kHz mono WAV) becomes text on this PC; the audio is not kept."""
        length = int(self.headers.get("Content-Length", "0"))
        if not 44 < length <= MAX_VOICE_BYTES:
            return self._json(400, {"error": "recording too long or empty"})
        try:
            with wave.open(io.BytesIO(self.rfile.read(length))) as recording:
                if (recording.getnchannels(), recording.getsampwidth(), recording.getframerate()) != (1, 2, 16_000):
                    raise ValueError("expected 16 kHz mono 16-bit audio")
                pcm = recording.readframes(recording.getnframes())
        except (wave.Error, EOFError, ValueError) as exc:
            return self._json(400, {"error": f"bad recording: {exc}"})
        try:
            return self._json(200, {"text": self.bridge.transcribe(pcm)})
        except Exception as exc:
            return self._json(500, {"error": f"speech recognition failed: {exc}"})

    def log_message(self, *_args) -> None:
        pass  # the windowed app has no console


class _SetupHandler(SimpleHTTPRequestHandler):
    """Plain HTTP: the setup page, Nova's certificate and the TV page (TVs can't install the certificate). Only what
    Nova shows on screen is served here, and only to a TV the owner allowed (screens.py)."""

    _json = _Handler._json

    def __init__(self, *args, bridge: "PhoneBridge", **kwargs) -> None:
        self.bridge = bridge
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/alfred-ca.crt":
            from local_tls import ca_certificate_der
            body = ca_certificate_der()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-x509-ca-cert")
            self.send_header("Content-Disposition", 'attachment; filename="Nova.crt"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("/", "/setup"):
            self.path = "/setup.html"
            return super().do_GET()
        if path == "/icon.png":
            return super().do_GET()
        if path in ("/tv", "/tv.html"):
            self.path = "/tv.html"
            return super().do_GET()
        screens = self.bridge.screens
        if path == "/api/tv/status" and screens is not None:
            session = (parse_qs(urlsplit(self.path).query).get("session") or [""])[0]
            return self._json(200, screens.status(session))
        if path == "/api/screen" and screens is not None:
            if not screens.allowed(self.headers.get("Authorization", "").removeprefix("Bearer ").strip()):
                return self._json(401, {"error": "not allowed"})
            return self._json(200, _screen_for(self.bridge, self.path))
        if _send_from_hud(self, path):
            return None
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/tv/hello" and self.bridge.screens is not None:
            return self._json(200, self.bridge.screens.hello())
        self.send_error(404)

    def log_message(self, *_args) -> None:
        pass


class PhoneBridge:
    def __init__(self, ask: Callable[[str, Callable[[str, dict], bool]], str], control: Callable[[str], str],
                 transcribe: Callable[[bytes], str] | None = None, screens: Any = None,
                 screen_state: Callable[[str, str], dict] | None = None, deck: Callable[[str], str] | None = None,
                 keyboard: Callable[[dict], str] | None = None) -> None:
        """ask(text, approve) runs one Nova turn; control(action) handles a button; transcribe(pcm) hears the phone.
        screens (screens.ScreenPairing) lets allowed TVs read screen_state(known cover, known slide); deck(action)
        runs one of screens.DECK_ACTIONS; keyboard({'keys': [...]} or {'text': ...}) types on the PC (deck_keyboard)."""
        self.screens = screens
        self._screen_state = screen_state or (lambda _music, _slide: {})
        self._deck = deck or (lambda _action: "The deck isn't available.")
        self._keyboard = keyboard or (lambda _request: "The keyboard isn't available here.")
        self._ask = ask
        self._control = control
        self._transcribe = transcribe
        self.token = load_token()
        self._pending: dict[str, Any] | None = None
        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None
        self._setup: ThreadingHTTPServer | None = None
        self.address = "127.0.0.1"

    @property
    def running(self) -> bool:
        return self._httpd is not None

    def app_url(self) -> str:
        # The token rides in the #fragment: browsers never send it in requests, and "Add to Home Screen" keeps it.
        return f"https://{self.address}:{self._httpd.server_address[1]}/#token={self.token}"

    def pairing_url(self) -> str:
        """What the QR code opens: the setup page, which installs the certificate and then opens the app."""
        return f"http://{self.address}:{self._setup.server_address[1]}/setup#token={self.token}&app={self._httpd.server_address[1]}"

    def start(self, host: str = "0.0.0.0", port: int = PORT, setup_port: int = SETUP_PORT) -> str:
        if self._httpd is None:
            from local_tls import ensure_server_certificate
            self.address = lan_address() if host == "0.0.0.0" else host
            certificate, key = ensure_server_certificate(self.address)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(certificate, key)
            self._httpd = ThreadingHTTPServer((host, port), partial(_Handler, directory=str(phone_folder()), bridge=self))
            # The handshake happens on the request's own thread, so a slow phone never blocks the others.
            self._httpd.socket = context.wrap_socket(self._httpd.socket, server_side=True, do_handshake_on_connect=False)
            self._setup = ThreadingHTTPServer((host, setup_port), partial(_SetupHandler, directory=str(phone_folder()), bridge=self))
            for server, name in ((self._httpd, "AlfredPhone"), (self._setup, "AlfredPhoneSetup")):
                server.daemon_threads = True
                server.handle_error = lambda _request, _address: None  # e.g. a phone that doesn't trust the certificate yet
                threading.Thread(target=server.serve_forever, name=name, daemon=True).start()
        return self.pairing_url()

    def stop(self) -> None:
        for server in (self._httpd, self._setup):
            if server is not None:
                server.shutdown()
                server.server_close()
        self._httpd = self._setup = None

    def transcribe(self, pcm: bytes) -> str:
        if self._transcribe is None:
            raise RuntimeError("voice is not available on this PC")
        return self._transcribe(pcm)

    def new_pairing(self) -> str:
        """A new token: phones paired before must scan the new code."""
        self.token = load_token(rotate=True)
        return self.pairing_url()

    def chat(self, text: str) -> str:
        try:
            return self._ask(text, self._approve_on_phone)
        except Exception as exc:  # a failed turn must still answer the phone
            return f"Sorry, that didn't work: {exc}"

    def control(self, action: str) -> str:
        return self._control(action)

    def screen_state(self, known_music: str = "", known_slide: str = "") -> dict:
        return self._screen_state(known_music, known_slide)

    def deck(self, action: str) -> str:
        return self._deck(action)

    def keyboard(self, request: dict) -> str:
        try:
            return self._keyboard(request)
        except (ValueError, OSError) as exc:  # a key the deck doesn't have; Windows refusing the input
            return str(exc)

    def tv_url(self) -> str:
        return f"http://{self.address}:{self._setup.server_address[1]}/tv" if self._setup else ""

    def deck_url(self) -> str:
        return f"https://{self.address}:{self._httpd.server_address[1]}/deck#token={self.token}" if self._httpd else ""

    def _approve_on_phone(self, name: str, arguments: dict) -> bool:
        summary = arguments.get("summary") or (f"Save this task?\n\n{arguments['task']}" if "task" in arguments else name)
        question = {"id": uuid.uuid4().hex, "summary": summary, "answer": threading.Event(), "approved": False}
        with self._lock:
            self._pending = question
        question["answer"].wait(APPROVAL_TIMEOUT)
        with self._lock:
            self._pending = None
        return question["approved"]

    def pending_question(self) -> dict[str, str]:
        with self._lock:
            return {"id": self._pending["id"], "summary": self._pending["summary"]} if self._pending else {}

    def answer(self, question_id: str, approved: bool) -> None:
        with self._lock:
            if self._pending and hmac.compare_digest(self._pending["id"], question_id):
                self._pending["approved"] = approved
                self._pending["answer"].set()
