"""What's playing on this PC and how its sound moves, for Nova's music look: the album art spinning as a disc
inside a ring of bars, in the HUD and on the corner orb.

The track comes from Windows' media controls (the same ones the volume flyout shows: Spotify, YouTube or SoundCloud
in a browser, Apple Music, VLC, ...). The bars come from what the PC plays (WASAPI loopback), measured only while
music plays; nothing is recorded or kept.
"""
from __future__ import annotations

import asyncio
import io
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

BANDS = 24
RATE = 16_000
BLOCK = 1024


@dataclass
class Track:
    title: str
    artist: str = ""
    album: str = ""
    playing: bool = False
    app: str = ""
    art: bytes | None = field(default=None, repr=False)  # the cover, as the app gave it (JPEG or PNG)

    @property
    def key(self) -> str:
        return f"{self.title}␟{self.artist}"


def app_name(app_id: str) -> str:
    """'Spotify.exe' / 'SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify' / 'MSEdge' -> a readable name."""
    tail = app_id.split("!")[-1].split("\\")[-1]
    tail = tail[:-4] if tail.lower().endswith(".exe") else tail
    known = {"msedge": "Edge", "chrome": "Chrome", "firefox": "Firefox", "spotify": "Spotify", "vlc": "VLC",
             "applemusic": "Apple Music", "zunemusic": "Media Player", "music.ui": "Media Player"}
    return known.get(tail.lower(), tail)


def windows_now_playing() -> Track | None:
    """The current media session, or None when nothing is playing or paused."""
    async def read() -> Track | None:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status
        manager = await Manager.request_async()
        session = manager.get_current_session()
        if session is None:
            return None
        properties = await session.try_get_media_properties_async()
        if not properties.title:
            return None
        playing = session.get_playback_info().playback_status == Status.PLAYING
        art = None
        if properties.thumbnail is not None:
            try:
                from winrt.windows.storage.streams import Buffer, InputStreamOptions
                stream = await properties.thumbnail.open_read_async()
                buffer = Buffer(min(int(stream.size), 4_000_000))
                await stream.read_async(buffer, buffer.capacity, InputStreamOptions.NONE)
                art = bytes(memoryview(buffer))[: buffer.length]
            except Exception:
                art = None  # the disc is drawn without a cover
        return Track(properties.title, properties.artist or "", properties.album_title or "", playing,
                     app_name(session.source_app_user_model_id or ""), art)
    return asyncio.run(read())


_mac_art: dict[str, bytes] = {}


def mac_now_playing() -> Track | None:
    """Spotify or Apple Music on the Mac (asked through AppleScript; only while one of them is open)."""
    import mac
    found = mac.now_playing()
    if not found:
        return None
    key = f"{found['title']}␟{found['artist']}"
    art = _mac_art.get(key)
    if art is None and found["player"] == "Spotify":
        _mac_art.clear()  # one cover kept: the current song's
        try:
            from urllib.request import urlopen
            link = mac.osascript('tell application "Spotify" to artwork url of current track')
            if link.startswith("https://"):
                with urlopen(link, timeout=5) as response:  # Spotify's own picture server
                    art = response.read(2_000_000)
        except OSError:
            art = None
        _mac_art[key] = art or b""
    return Track(found["title"], found["artist"], playing=True, app=found["player"], art=art or None)


def now_playing_here() -> Track | None:
    import sys
    return mac_now_playing() if sys.platform == "darwin" else windows_now_playing()


def bands_from(samples, previous: list[float] | None = None) -> list[float]:
    """BANDS levels 0..1 from a block of float samples, spaced like hearing (60 Hz to 8 kHz), smoothed so the bars
    rise quickly and fall slowly."""
    import numpy
    block = numpy.asarray(samples, dtype=numpy.float64)
    if block.size < 64:
        return previous or [0.0] * BANDS
    spectrum = numpy.abs(numpy.fft.rfft(block * numpy.hanning(block.size)))
    frequencies = numpy.fft.rfftfreq(block.size, 1 / RATE)
    edges = numpy.geomspace(60, 8000, BANDS + 1)
    levels = []
    for low, high in zip(edges, edges[1:]):
        part = spectrum[(frequencies >= low) & (frequencies < high)]
        power = float(part.max()) if part.size else 0.0
        decibels = 20 * math.log10(power / block.size + 1e-9)
        levels.append(min(1.0, max(0.0, (decibels + 70) / 55)))  # -70 dB (quiet) .. -15 dB (loud)
    if previous and len(previous) == BANDS:
        levels = [now if now > before else before * 0.82 + now * 0.18 for now, before in zip(levels, previous)]
    return levels


class Music:
    """Watches what's playing (every second) and, while music plays, how its sound moves (~20 times a second)."""

    def __init__(self, now_playing: Callable[[], Track | None] = now_playing_here,
                 on_change: Callable[[Track | None], None] = lambda _track: None) -> None:
        self.now_playing = now_playing
        self.on_change = on_change
        self.track: Track | None = None
        self.bands: list[float] = [0.0] * BANDS
        self._art_key = ""
        self._art_image = None
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    @property
    def playing(self) -> bool:
        return bool(self.track and self.track.playing)

    def start(self) -> None:
        if any(thread.is_alive() for thread in self._threads):
            return
        self._stop.clear()
        self._threads = [threading.Thread(target=self._watch, name="NovaMusic", daemon=True),
                         threading.Thread(target=self._listen, name="NovaMusicBars", daemon=True)]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()

    def check(self) -> None:
        """One look at Windows' media controls."""
        try:
            track = self.now_playing()
        except Exception:
            track = None
        before = self.track
        self.track = track
        if (before is None) != (track is None) or (track and before and (track.key != before.key or track.playing != before.playing)):
            self.on_change(track)

    def _watch(self) -> None:
        while not self._stop.is_set():
            self.check()
            self._stop.wait(1.0)

    def _listen(self) -> None:
        recorder = None
        while not self._stop.is_set():
            if not self.playing:
                self.bands = [level * 0.8 for level in self.bands]
                recorder = None
                self._stop.wait(0.3)
                continue
            try:
                if recorder is None:
                    import pythoncom
                    import soundcard
                    pythoncom.CoInitializeEx(0)
                    recorder = soundcard.get_microphone(str(soundcard.default_speaker().name), include_loopback=True)
                data = recorder.record(numframes=BLOCK, samplerate=RATE, channels=1)
                self.bands = bands_from(data[:, 0], self.bands)
            except Exception:
                recorder = None  # no loopback here (or the speaker changed): the disc spins without bars
                self.bands = [0.0] * BANDS
                self._stop.wait(5)

    def art_image(self, size: int = 256):
        """The cover as a Pillow image (cached per track), or None."""
        track = self.track
        if not track or not track.art:
            return None
        if track.key != self._art_key:
            self._art_key, self._art_image = track.key, None
            try:
                from PIL import Image
                self._art_image = Image.open(io.BytesIO(track.art)).convert("RGBA").resize((size, size))
            except Exception:
                self._art_image = None
        return self._art_image

    def state(self) -> dict | None:
        """For the HUD (the cover goes separately, once per track)."""
        track = self.track
        if not track:
            return None
        return {"title": track.title, "artist": track.artist, "album": track.album, "playing": track.playing,
                "app": track.app, "key": track.key, "art": bool(track.art), "at": time.time()}
