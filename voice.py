"""Offline, bounded voice input and selectable SAPI output for Nova.

Microphone buffers are kept in RAM only. Audio preferences live in the current
edition's ALFRED_DATA_DIR (never copied from Desktop to USB).
"""
from __future__ import annotations

import json
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time
from array import array
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

import echo_filter
import piper_voice
import whisper_engine

SAMPLE_RATE = 16_000
COMMAND_SECONDS = 8.0
HOLD_MAX_SECONDS = 60.0
SYSTEM_DEFAULT = "System default"
SVSF_ASYNC, SVSF_PURGE_BEFORE_SPEAK = 1, 2


def _audio_settings_path() -> Path:
    base = Path(os.environ.get("ALFRED_DATA_DIR") or Path.home() / "AppData" / "Local" / "Alfred" / "DesktopData")
    return base / "audio_settings.json"


def _voice_settings_path() -> Path:
    return _audio_settings_path().with_name("voice_settings.json")


def load_voice_name() -> str | None:
    """The chosen natural voice, or None for Windows' built-in voice."""
    try:
        name = json.loads(_voice_settings_path().read_text(encoding="utf-8")).get("voice")
        return name if name in piper_voice.VOICES else None
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def save_voice_name(name: str | None) -> None:
    path = _voice_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"voice": name}), encoding="utf-8")


def load_audio_preferences() -> dict[str, str | None]:
    try:
        data = json.loads(_audio_settings_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {
                "input_key": data.get("input_key") if isinstance(data.get("input_key"), str) else None,
                "output_key": data.get("output_key") if isinstance(data.get("output_key"), str) else None,
            }
    except (OSError, json.JSONDecodeError):
        pass
    return {"input_key": None, "output_key": None}


def save_audio_preferences(input_key: str | None, output_key: str | None) -> None:
    path = _audio_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"input_key": input_key, "output_key": output_key}, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _sounddevice():
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("Audio support is unavailable in this Nova edition.") from exc
    return sd


def enumerate_input_devices() -> list[dict[str, object]]:
    """List live PortAudio input endpoints, keyed by stable API/name, not index."""
    sd = _sounddevice()
    hostapis = sd.query_hostapis()
    result: list[dict[str, object]] = []
    for index, device in enumerate(sd.query_devices()):
        if int(device.get("max_input_channels", 0)) < 1:
            continue
        hostapi = hostapis[int(device["hostapi"])]["name"]
        name = str(device["name"])
        key = f"{hostapi}::{name}"
        result.append({"key": key, "label": f"{hostapi} · {name} · #{index}", "index": index})
    return result


def enumerate_speech_outputs() -> list[dict[str, str]]:
    """Enumerate Windows SAPI output devices without launching PowerShell."""
    if sys.platform == "darwin":  # `say` plays on the output chosen in System Settings → Sound
        return [{"key": "", "label": "The Mac's sound output (System Settings → Sound)"}]
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise RuntimeError("Windows offline speech output is unavailable in this Nova edition.") from exc
    pythoncom.CoInitialize()
    try:
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        outputs = voice.GetAudioOutputs("", "")
        result = []
        for index in range(outputs.Count):
            token = outputs.Item(index)
            name = str(token.GetDescription())
            result.append({"key": name, "label": name})
        return result
    except Exception as exc:
        raise RuntimeError(f"Could not enumerate Windows speech output devices: {exc}") from exc
    finally:
        pythoncom.CoUninitialize()


def _use_female_voice(voice) -> None:
    """Nova is a woman: pick a female Windows voice (Zira, Aria, Jenny, Hazel…) when one is installed."""
    try:
        tokens = voice.GetVoices("Gender=Female", "")
        english = [tokens.Item(i) for i in range(tokens.Count)
                   if tokens.Item(i).GetAttribute("Language").lower() in ("409", "809", "c09", "1009")]
        if english or tokens.Count:
            voice.Voice = (english or [tokens.Item(0)])[0]
    except Exception:
        pass  # keep Windows' default voice


def default_model_path() -> Path:
    """Locate bundled Vosk assets without resolving PyInstaller's synthetic module path.

    In an onedir build, ``voice.__file__`` can be a path inside the embedded
    archive (for example ``_internal\\voice``) rather than a real file. Do not
    evaluate/resolve that fallback when PyInstaller provides ``_MEIPASS``.
    """
    import sys
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        base = Path(bundle_root)
    else:
        base = Path(__file__).parent
    return base / "assets" / "vosk-model-small-en-us-0.15"


def _dependencies():
    try:
        from vosk import KaldiRecognizer, Model, SetLogLevel
    except ImportError as exc:
        raise RuntimeError("Offline voice packages are missing; see the included setup guide.") from exc
    SetLogLevel(-1)
    return KaldiRecognizer, Model


def _resolve_input_index(sd, key: str | None) -> int | None:
    if not key:
        return None
    try:
        hostapis = sd.query_hostapis()
        for index, device in enumerate(sd.query_devices()):
            if int(device.get("max_input_channels", 0)) < 1:
                continue
            if f"{hostapis[int(device['hostapi'])]['name']}::{device['name']}" == key:
                return index
    except Exception:
        return None
    return None


def _normalized_audio_level(raw_audio: bytes | bytearray | memoryview) -> float:
    """Return a quick 0..1 RMS level from a raw int16 microphone chunk."""
    raw = bytes(raw_audio)
    raw = raw[:len(raw) - (len(raw) % 2)]
    if not raw:
        return 0.0
    samples = array("h")
    samples.frombytes(raw)
    if not samples:
        return 0.0
    rms = math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768.0
    return min(1.0, rms * 12.0)


@contextmanager
def _open_input(sd, input_key: str | None, callback, *, blocksize: int = 4000) -> Iterator[object]:
    """Open chosen mic; if it vanished or won't open, retry the current system default."""
    selected = _resolve_input_index(sd, input_key)
    missing = bool(input_key and selected is None)
    candidates: list[int | None] = []
    if selected is not None:
        candidates.append(selected)
    candidates.append(None)
    errors: list[str] = []
    for device in dict.fromkeys(candidates):
        stream = None
        try:
            stream = sd.RawInputStream(
                device=device, samplerate=SAMPLE_RATE, blocksize=blocksize,
                channels=1, dtype="int16", callback=callback,
            )
            stream.start()
            if input_key and (missing or device != selected):
                note = "The saved microphone is unavailable; using the current system default instead."
                if _active_controller and _active_controller._notice_callback:
                    _active_controller._notify(note)
            try:
                yield stream
            finally:
                try:
                    stream.stop()
                finally:
                    stream.close()
            return
        except Exception as exc:
            errors.append(str(exc))
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
    detail = errors[-1] if errors else "No input endpoint is available."
    raise RuntimeError(
        "Could not open the selected microphone or the Windows default input. "
        "Check that a microphone is connected and Windows microphone privacy is enabled. " + detail
    )


_active_controller: "VoiceController | None" = None

# Free recognition almost never writes "Nova" (it hears "no matter", "your", "norma"), so a second recognizer
# limited to a few words listens for the name: with only these to choose from, "hey nova" comes through in
# accented English too. The decoys give similar sounds ("no way", "hey now") somewhere else to land.
WAKE_GRAMMAR = json.dumps(["hey nova", "hey", "hi", "hello", "okay", "nova", "no", "know", "over", "now", "[unk]"])
WAKE_CONFIDENCE = 0.5
BARGE_IN_CONFIDENCE = 0.8  # cutting Nova off by voice: her own echo must not pass for the name
FOLLOW_UP_SECONDS = 60.0  # after "Hey Nova" or an answer, keep listening without the name this long
# Right after Nova stops talking, her last words (speaker latency, room echo) still reach the mic.
ECHO_TAIL_SECONDS = 0.8
_SPOKEN_WAKE = re.compile(r"^\W*(?:(?:hey|hi|hay|ok|okay)[\s,]+)?(?:nova|no va|nover|novah|norma|nora|noah)\b[\s,.!?]*", re.IGNORECASE)
_HEY = re.compile(r"^\W*(?:hey|hi|hay|a)\W+\w+\W*", re.IGNORECASE)
_GOODBYE = re.compile(r"^\W*(?:(?:ok(?:ay)?|thanks|thank you|bye|goodbye|that's all|that is all|stop listening|go to sleep|"
                      r"nothing|never ?mind)\W*)+(?:nova\W*)?$", re.IGNORECASE)


def wake_end(words: list[dict], confidence: float = WAKE_CONFIDENCE) -> float | None:
    """When "hey nova" ended (seconds into the stream), from the wake recognizer's words; None if it wasn't said."""
    for first, second in zip(words, words[1:]):
        if (first.get("word") == "hey" and second.get("word") == "nova"
                and min(first.get("conf", 0), second.get("conf", 0)) >= confidence):
            return float(second.get("end", 0))
    return None


def name_end_in(model, chunks: list[bytes]) -> float | None:
    """Where "hey nova" ends (seconds into these chunks) in a fresh, finished decode of just the last ~1.5 s heard
    while Nova talks, both words at least 80% sure; None if it isn't there. The running decode can lose the name
    once you go on talking ("Hey Nova, what about Friday?"): over the whole stretch it may settle on "[unk]".
    Simulated rooms: 18 of 20 such cut-offs caught instead of 13, none of 68 of her own sentences mistaken."""
    KaldiRecognizer, _Model = _dependencies()
    recognizer = KaldiRecognizer(model, SAMPLE_RATE, WAKE_GRAMMAR)
    recognizer.SetWords(True)
    words: list[dict] = []
    for chunk in chunks:
        if recognizer.AcceptWaveform(chunk):
            words += json.loads(recognizer.Result()).get("result", [])
    words += json.loads(recognizer.FinalResult()).get("result", [])
    return wake_end(words, BARGE_IN_CONFIDENCE)


def _audio_after(chunks: list[bytes], seconds: float) -> list[bytes]:
    audio = b"".join(chunks)[int(seconds * SAMPLE_RATE) * 2:]
    return [audio[start:start + 8000] for start in range(0, len(audio), 8000)]


def sounds_like_wake(model, pcm16: bytes, sample_rate: int) -> bool:
    """Could this sentence of Nova's own voice pass for "Hey Nova" to her ears, as is or after a room and the echo
    filter? Looser than the real test ("hey nova" even once in a half-way guess, or the name in two guesses in a row),
    so "Hey, nice work" and "No way... Now let's" count. While such a sentence plays only Esc cuts her off: her echo
    could otherwise do it."""
    clean = echo_filter.to_16k(pcm16, sample_rate)
    if _name_heard_in(model, clean):
        return True
    echo = echo_filter.EchoSuppressor()
    echo.play(clean.clip(-32768, 32767).astype("int16").tobytes(), echo_filter.RATE, started_at=0.0)
    mic = echo_filter.through_a_room(clean).clip(-32768, 32767).astype("int16")
    filtered = b"".join(echo.clean(mic[start:start + 4000].tobytes(), (start + 4000) / echo_filter.RATE)
                        for start in range(0, len(mic), 4000))
    return _name_heard_in(model, _int16_samples(filtered))


def _name_heard_in(model, samples) -> bool:
    KaldiRecognizer, _Model = _dependencies()
    recognizer = KaldiRecognizer(model, SAMPLE_RATE, WAKE_GRAMMAR)
    audio = samples.clip(-32768, 32767).astype("int16").tobytes()
    held = 0
    for start in range(0, len(audio), 8000):
        if recognizer.AcceptWaveform(audio[start:start + 8000]):
            heard, held = json.loads(recognizer.Result()).get("text", ""), 0
            if "nova" in heard.split():
                return True
        else:
            heard = json.loads(recognizer.PartialResult()).get("partial", "")
            held = held + 1 if "nova" in heard.split() else 0
            if "hey nova" in heard or held >= 2:
                return True
    return "nova" in json.loads(recognizer.FinalResult()).get("text", "").split()


def _int16_samples(pcm16: bytes):
    import numpy
    return numpy.frombuffer(pcm16, dtype=numpy.int16)


def strip_wake(text: str) -> str:
    """'Hey Nova, open notepad' -> 'open notepad', also when the name came out misspelled after "hey"."""
    match = _SPOKEN_WAKE.search(text) or _HEY.search(text)
    return (text[match.end():] if match else text).strip(" ,.!?")


def wants_to_end(text: str) -> bool:
    """'thanks', 'bye Nova', 'that's all': close the listening window."""
    return bool(_GOODBYE.match(text.strip()))


def follow_up_heard(words: list[dict]) -> bool:
    """Is this real speech to Nova, not noise? Vosk turns noise into short low-confidence words ("the", "huh")."""
    if not words:
        return False
    confidence = sum(word.get("conf", 0) for word in words) / len(words)
    return confidence >= (0.8 if len(words) == 1 else 0.45)


def _beep(going_to_sleep: bool = False) -> None:
    """A short system sound: Nova is listening, or (a lower sound) stopped listening. Windows only; silent elsewhere."""
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONASTERISK if going_to_sleep else winsound.MB_OK)
    except (ImportError, RuntimeError):
        pass


def _transcribe_window(model, sd, KaldiRecognizer, stop_event: threading.Event, seconds: float,
                       input_key: str | None = None,
                       level_callback: Callable[[float], None] | None = None,
                       end_on_silence: bool = True, keep_audio: list[bytes] | None = None) -> str:
    """Capture a bounded mic interval to RAM, transcribe locally, discard buffers.

    Only final recognizer results are returned; partial guesses are provisional and never used.
    """
    audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=32)
    overflow = threading.Event()

    def callback(indata, frames, time_info, status):
        if status:
            overflow.set()
        if level_callback:
            try:
                level_callback(_normalized_audio_level(indata))
            except Exception:
                pass
        try:
            audio_queue.put_nowait(bytes(indata))
        except queue.Full:
            overflow.set()

    recognizer = KaldiRecognizer(model, SAMPLE_RATE)
    recognizer.SetWords(False)
    finals: list[str] = []
    last_speech_at: float | None = None
    start = time.monotonic()
    try:
        with _open_input(sd, input_key, callback) as _stream:
            while not stop_event.is_set() and time.monotonic() - start < seconds:
                try:
                    chunk = audio_queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                if keep_audio is not None:
                    keep_audio.append(chunk)  # RAM only, for Whisper; discarded after the turn
                if recognizer.AcceptWaveform(chunk):
                    text = str(json.loads(recognizer.Result()).get("text", "")).strip()
                    if text:
                        finals.append(text)
                        last_speech_at = time.monotonic()
                elif json.loads(recognizer.PartialResult()).get("partial", "").strip():
                    last_speech_at = time.monotonic()
                if end_on_silence and last_speech_at is not None and time.monotonic() - last_speech_at > 1.35:
                    break
        finals.append(str(json.loads(recognizer.FinalResult()).get("text", "")).strip())
        collected = " ".join(finals)
    except Exception as exc:
        raise RuntimeError(f"Microphone capture/transcription failed: {exc}") from exc
    finally:
        if level_callback:
            try:
                level_callback(0.0)
            except Exception:
                pass
    if overflow.is_set():
        pass  # Drop overflowed buffers; never persist audio.
    return re.sub(r"\s+", " ", collected).strip()


def _measure_input(input_key: str | None, seconds: float = 0.9) -> tuple[float, float, str]:
    sd = _sounddevice()
    chunks: list[bytes] = []
    def callback(indata, frames, time_info, status):
        chunks.append(bytes(indata))
    with _open_input(sd, input_key, callback, blocksize=1600):
        time.sleep(seconds)
    raw = b"".join(chunks)
    if len(raw) < 2:
        raise RuntimeError("The microphone opened but returned no audio samples.")
    samples = array("h")
    samples.frombytes(raw[:len(raw) - len(raw) % 2])
    if not samples:
        raise RuntimeError("The microphone returned no audio samples.")
    peak = max(abs(value) for value in samples) / 32768.0
    rms = math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768.0
    dbfs = 20 * math.log10(max(rms, 1e-6))
    return dbfs, peak, f"Captured {len(samples)} samples in RAM; recording discarded."


class SentenceSplitter:
    """Cuts streamed reply text into sentences the moment each one ends."""

    END = re.compile(r"(?<=[.!?…])[\"')\]]*\s+")
    LINE = re.compile(r"\n+")
    CLAUSE = re.compile(r"(?<=[,;:])\s+")
    FIRST_CLAUSE = 24  # the first piece may end at a comma once it is this long: she starts talking sooner

    def __init__(self, on_sentence: Callable[[str], None], minimum: int = 14) -> None:
        self.on_sentence = on_sentence
        self.minimum = minimum  # "1." or "Ok." alone sound odd; join them with what follows
        self.buffer = ""
        self.started = False

    def _boundary(self) -> re.Match | None:
        # A line break always ends a piece (list items); a full stop only after `minimum` characters. Before the
        # first piece, a long enough clause also ends one: the later pieces are made while she speaks anyway.
        candidates = [self.LINE.search(self.buffer), self.END.search(self.buffer, self.minimum)]
        if not self.started:
            candidates.append(self.CLAUSE.search(self.buffer, self.FIRST_CLAUSE))
        found = [match for match in candidates if match]
        return min(found, key=lambda match: match.start()) if found else None

    def feed(self, text: str) -> None:
        self.buffer += text
        while (match := self._boundary()) is not None:
            sentence, self.buffer = self.buffer[:match.start()], self.buffer[match.end():]
            if sentence.strip():
                self.started = True
                self.on_sentence(sentence.strip())

    def flush(self) -> None:
        if self.buffer.strip():
            self.on_sentence(self.buffer.strip())
        self.buffer = ""
        self.started = False


class SentenceSpeaker:
    """Speaks sentences in order while the next ones are already being synthesized.

    After plip's QueueSpeaker (github.com/hussainn7/plip-oss, MIT): a prepare thread and a play thread,
    and a generation number so stop() drops everything queued before it.
    """

    def __init__(self, prepare: Callable[[str], object], play: Callable[[object, threading.Event], None],
                 on_busy: Callable[[bool], None] | None = None, on_error: Callable[[str], None] | None = None,
                 lookahead: int = 2) -> None:
        self.prepare, self.play = prepare, play
        self.on_busy = on_busy or (lambda _busy: None)
        self.on_error = on_error or (lambda _message: None)
        self._texts: queue.Queue = queue.Queue()
        self._ready: queue.Queue = queue.Queue(maxsize=max(1, lookahead))
        self._generation = 0
        self._pending = 0
        self._stop = threading.Event()
        self._lock = threading.Lock()
        threading.Thread(target=self._prepare_loop, name="AlfredSpeechPrepare", daemon=True).start()
        threading.Thread(target=self._play_loop, name="AlfredSpeechPlay", daemon=True).start()

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._pending > 0

    def say(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        with self._lock:
            self._pending += 1
            started = self._pending == 1
            generation = self._generation
        if started:
            self.on_busy(True)
        self._texts.put((generation, text))

    def stop(self) -> None:
        with self._lock:
            was_busy = self._pending > 0
            self._generation += 1
            self._pending = 0
            self._stop.set()
        for pending in (self._texts, self._ready):
            try:
                while True:
                    pending.get_nowait()
            except queue.Empty:
                pass
        if was_busy:
            self.on_busy(False)

    def _done(self, generation: int) -> None:
        with self._lock:
            if generation != self._generation or self._pending == 0:
                return
            self._pending -= 1
            finished = self._pending == 0
        if finished:
            self.on_busy(False)

    def _prepare_loop(self) -> None:
        while True:
            generation, text = self._texts.get()
            if generation != self._generation:
                continue
            try:
                prepared = self.prepare(text)
            except Exception as exc:
                self.on_error(f"Speech failed: {exc}")
                prepared = None
            if prepared is None:
                self._done(generation)
            elif generation == self._generation:
                self._ready.put((generation, prepared))

    def _play_loop(self) -> None:
        while True:
            generation, prepared = self._ready.get()
            with self._lock:  # re-arm atomically with stop(), or a stale sentence could play
                if generation != self._generation:
                    continue
                self._stop.clear()
            try:
                self.play(prepared, self._stop)
            except Exception as exc:
                self.on_error(f"Speech failed: {exc}")
            finally:
                self._done(generation)


class VoiceController:
    """Opt-in local wake word and push-to-talk, with selectable endpoints."""

    def __init__(self, model_path: str | Path | None = None) -> None:
        global _active_controller
        self.model_path = Path(model_path) if model_path else default_model_path()
        self._stop = threading.Event()
        self._speaking = threading.Event()  # a whole reply spoken at once (speak())
        self._sentences_busy = False  # a reply spoken sentence by sentence as it is written (say())
        self._quiet_until = 0.0  # the echo tail after Nova stops talking
        self._now_saying = ""  # the sentence Nova is saying right now (her own "Nova" must not cut her off)
        self._interrupted = False  # the owner cut Nova off: listen at once, no echo tail
        self._muted = False  # after a cut-off, the rest of that answer stays unsaid
        self._barge_in_callback: Callable[[], None] | None = None
        self.echo = echo_filter.EchoSuppressor()  # her natural voice, taken out of what the "Hey Nova" listener hears
        self._sounds_like_wake: bool | None = False  # the sentence playing now could pass for "Hey Nova" (None: checking)
        self._own_voice_check: object | None = None
        self._carry_over: list[bytes] = []  # what you said over Nova when you cut her off, for the request
        self._stop_speaking = threading.Event()
        self._thread: threading.Thread | None = None
        self._model = None
        self._audio_lock = threading.Lock()
        self._wake_callback: Callable[[], None] | None = None
        self._command_callback: Callable[[str], None] | None = None
        self._error_callback: Callable[[str], None] | None = None
        self._notice_callback: Callable[[str], None] | None = None
        self._sleep_callback: Callable[[], None] | None = None
        self._level_callback: Callable[[float], None] | None = None
        preferences = load_audio_preferences()
        self.input_key = preferences.get("input_key")
        self.output_key = preferences.get("output_key")
        self._last_notice = ""
        self.whisper = whisper_engine.WhisperEngine() if whisper_engine.installed() else None
        self.voice_name = load_voice_name()
        self.on_speaking: Callable[[bool], None] | None = None  # sentence-by-sentence replies started/finished
        self._sentences: SentenceSpeaker | None = None
        _active_controller = self

    def _nova_talking(self) -> bool:
        """While Nova talks, and a moment after, the mic ignores what it hears: it would be her own voice."""
        return self._speaking.is_set() or self._sentences_busy or time.monotonic() < self._quiet_until

    def _sentence_busy(self, busy: bool) -> None:
        self._sentences_busy = busy
        if busy:
            self._interrupted = False
        else:
            self._quiet_until = 0.0 if self._interrupted else time.monotonic() + ECHO_TAIL_SECONDS
        if self.on_speaking:
            self.on_speaking(busy)

    @property
    def available(self) -> bool:
        return self.model_path.is_dir()

    def set_audio_devices(self, input_key: str | None, output_key: str | None) -> None:
        self.input_key = input_key or None
        self.output_key = output_key or None
        save_audio_preferences(self.input_key, self.output_key)
        self._last_notice = ""

    def _load(self):
        if self._model is not None:
            return self._model
        if not self.model_path.is_dir():
            raise RuntimeError(f"Offline speech model not found: {self.model_path}")
        KaldiRecognizer, Model = _dependencies()
        self._model = Model(str(self.model_path))
        return self._model

    def set_level_callback(self, callback: Callable[[float], None] | None) -> None:
        """Subscribe to live microphone RMS levels; no audio samples are retained."""
        self._level_callback = callback

    def _emit_level(self, level: float) -> None:
        callback = self._level_callback
        if callback:
            try:
                callback(max(0.0, min(1.0, float(level))))
            except Exception:
                pass

    def _better_transcript(self, vosk_text: str, audio: list[bytes]) -> str:
        """Whisper hears accented, broken English far better than Vosk; Vosk stays the fallback.

        Whisper runs only when Vosk heard speech: on silence Whisper tends to invent words like "Thank you."
        """
        if self.whisper is None or not audio or not vosk_text:
            return vosk_text
        try:
            return self.whisper.transcribe(b"".join(audio)) or vosk_text
        except Exception as exc:
            self._notify(f"Whisper failed, so the basic recognizer was used: {exc}")
            return vosk_text

    def transcribe_pcm(self, pcm16: bytes) -> str:
        """Text from a finished 16 kHz mono recording (from Nova Lite): Vosk, then Whisper when installed."""
        KaldiRecognizer, _Model = _dependencies()
        # Its own recognizer on the shared model (Vosk allows that), so it works while the mic listens too.
        recognizer = KaldiRecognizer(self._load(), 16_000)
        for start in range(0, len(pcm16), 8000):
            recognizer.AcceptWaveform(pcm16[start:start + 8000])
        text = json.loads(recognizer.FinalResult()).get("text", "")
        return self._better_transcript(text, [pcm16])

    def verify_offline_recognizer(self) -> None:
        """Load the actual local model and construct its recognizer without recording."""
        KaldiRecognizer, _Model = _dependencies()
        recognizer = KaldiRecognizer(self._load(), SAMPLE_RATE)
        recognizer.SetWords(False)

    def _notify(self, text: str) -> None:
        if text and text != self._last_notice:
            self._last_notice = text
            if self._notice_callback:
                self._notice_callback(text)

    def start_wake(self, on_wake: Callable[[], None], on_command: Callable[[str], None],
                   on_error: Callable[[str], None], on_notice: Callable[[str], None] | None = None,
                   on_sleep: Callable[[], None] | None = None, on_barge_in: Callable[[], None] | None = None) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._barge_in_callback = on_barge_in
        self._stop.clear()
        self._wake_callback, self._command_callback, self._error_callback = on_wake, on_command, on_error
        self._notice_callback, self._sleep_callback = on_notice, on_sleep
        self._thread = threading.Thread(target=self._wake_loop, name="AlfredWakeWord", daemon=True)
        self._thread.start()

    def stop_wake(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def _woke(self) -> None:
        if self._wake_callback:
            self._wake_callback()
        _beep()

    def _wake_loop(self) -> None:
        """Listen for "Hey Nova". Then every sentence is a request, with no name needed, until FOLLOW_UP_SECONDS
        pass without one (counted from when Nova finished answering). "Hey Nova, open notepad" in one breath
        works, and so does "Hey Nova" ... pause ... "open notepad"."""
        try:
            sd = _sounddevice()
            KaldiRecognizer, _Model = _dependencies()
            model = self._load()
            listening_until = 0.0  # monotonic time the follow-up window closes; 0 = asleep, waiting for the name
            with self._audio_lock:
                while not self._stop.is_set():
                    if self._nova_talking():  # Nova talks: only "Hey Nova" (to cut her off) is listened for
                        if self._watch_for_barge_in(sd, KaldiRecognizer, model) or listening_until:
                            listening_until = time.monotonic() + FOLLOW_UP_SECONDS  # what you say next needs no name
                        continue
                    audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=48)
                    def callback(indata, frames, time_info, status):
                        if not self._nova_talking():
                            self._emit_level(_normalized_audio_level(indata))
                            try:
                                audio_queue.put_nowait(bytes(indata))
                            except queue.Full:
                                pass
                        else:
                            self._emit_level(0.0)
                    # Both hear the same audio from the same moment, so their word times line up.
                    words_recognizer = KaldiRecognizer(model, SAMPLE_RATE)
                    words_recognizer.SetWords(True)
                    name_recognizer = KaldiRecognizer(model, SAMPLE_RATE, WAKE_GRAMMAR)
                    name_recognizer.SetWords(True)
                    utterance: list[bytes] = []  # RAM only; lets Whisper re-hear the whole sentence
                    name_words: list[dict] = []
                    woke = False
                    command: str | None = None
                    # Just cut her off: start with the last moments heard over her ("Hey Nova, what about…"), so a
                    # request said in the same breath is heard whole. The cut-off already beeped for that name.
                    carried, self._carry_over = self._carry_over, []
                    for piece in carried:
                        audio_queue.put_nowait(piece)
                    quiet_wake_until = time.monotonic() + 3.0 if carried else 0.0
                    with _open_input(sd, self.input_key, callback) as _stream:
                        while not self._stop.is_set() and not self._nova_talking():
                            if listening_until and time.monotonic() > listening_until:
                                listening_until = 0.0
                                self._went_to_sleep()
                            try:
                                chunk = audio_queue.get(timeout=0.25)
                            except queue.Empty:
                                continue
                            utterance = (utterance + [chunk])[-48:]  # about 12 seconds
                            # Always fed (its clock must match), also in the follow-up window: "Hey Nova" there
                            # just marks where the request starts. Only a finished result counts: half-way guesses
                            # mistook "hey, no problem" for the name.
                            if name_recognizer.AcceptWaveform(chunk):
                                name_words += json.loads(name_recognizer.Result()).get("result", [])
                                if not woke and wake_end(name_words) is not None:
                                    woke = True
                                    if time.monotonic() > quiet_wake_until:
                                        self._woke()
                            if not words_recognizer.AcceptWaveform(chunk):
                                continue
                            words = json.loads(words_recognizer.Result()).get("result", [])
                            if not woke and "hey" in json.loads(name_recognizer.PartialResult()).get("partial", ""):
                                # The sentence ended before the name recognizer decided: make it decide now.
                                name_words += json.loads(name_recognizer.FinalResult()).get("result", [])
                                if wake_end(name_words) is not None:
                                    woke = True
                                    if time.monotonic() > quiet_wake_until:
                                        self._woke()
                            if woke:
                                ended = wake_end(name_words)
                                command = " ".join(word["word"] for word in words if word.get("start", 0) >= ended - 0.05)
                                if command:
                                    break
                                # Only "Hey Nova": the request comes next, no name needed (same stream, nothing lost).
                                listening_until = time.monotonic() + FOLLOW_UP_SECONDS
                                woke, command, name_words, utterance = False, None, [], []
                                continue
                            if listening_until and follow_up_heard(words):
                                command = " ".join(word["word"] for word in words)
                                break
                            utterance, name_words = [], []
                    if command is None or self._stop.is_set():
                        continue
                    if command:
                        better = self._better_transcript(command, utterance)
                        command = strip_wake(better) if woke and better != command else better
                    if not command:  # Whisper heard only the name
                        listening_until = time.monotonic() + FOLLOW_UP_SECONDS
                        continue
                    if listening_until and not woke and wants_to_end(command):
                        listening_until = 0.0
                        self._went_to_sleep()
                        continue
                    listening_until = time.monotonic() + FOLLOW_UP_SECONDS
                    if self._command_callback:
                        self._command_callback(command)
                    time.sleep(0.12)
        except Exception as exc:
            if not self._stop.is_set() and self._error_callback:
                self._error_callback(str(exc))

    def _watch_for_barge_in(self, sd, KaldiRecognizer, model) -> bool:
        """While Nova talks, the mic listens only for "Hey Nova", so you can cut her off. Her natural voice is taken
        out of what it hears first (echo_filter). Her own voice can't do it: it takes both words, held for half a
        second or re-checked on the last 1.5 s and 80% sure (name_end_in), and never while her sentence says
        "Nova" or sounds like it (sounds_like_wake). Returns True when you cut her off (she has stopped, the rest of
        that answer is dropped, and what you said over her goes on to the request listener)."""
        audio_queue: queue.Queue[tuple[bytes, float]] = queue.Queue(maxsize=48)

        def callback(indata, frames, time_info, status):
            try:
                audio_queue.put_nowait((bytes(indata), time.monotonic()))
            except queue.Full:
                pass
        self._emit_level(0.0)  # the orb follows your voice, not hers
        recognizer = KaldiRecognizer(model, SAMPLE_RATE, WAKE_GRAMMAR)
        recognizer.SetWords(True)
        held = 0
        recent: list[bytes] = []  # the last ~1.5 s heard, handed to the request listener on a cut-off
        self.echo.new_stream()
        with _open_input(sd, self.input_key, callback) as _stream:
            while not self._stop.is_set() and self._nova_talking():
                try:
                    chunk, captured_at = audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                chunk = self.echo.clean(chunk, captured_at)  # her natural voice taken out (the built-in one has no copy)
                if not chunk:
                    continue
                recent = (recent + [chunk])[-6:]
                if recognizer.AcceptWaveform(chunk):
                    finished = wake_end(json.loads(recognizer.Result()).get("result", [])) is not None
                    held = 0
                else:
                    finished = False
                    held = held + 1 if "hey nova" in json.loads(recognizer.PartialResult()).get("partial", "") else 0
                if "nova" in self._now_saying.lower() or self._sounds_like_wake is not False:
                    continue  # her sentence says the name or sounds like it: only Esc cuts this one off
                name_end = name_end_in(model, recent) if len(recent) >= 3 else None
                if finished or held >= 2 or name_end is not None:
                    # What you said after the name goes on to the request listener (from the name on if unsure).
                    self._carry_over = recent if name_end is None else _audio_after(recent, name_end)
                    self._interrupted = self._muted = True
                    self.stop_speaking()
                    self._quiet_until = 0.0
                    if self._barge_in_callback:
                        self._barge_in_callback()
                    self._woke()
                    return True
        return False

    def _her_audio_starts(self, pcm: bytes, sample_rate: int, started_at: float | None = None) -> None:
        """Nova's natural voice starts playing this: the echo filter gets a copy, and it is checked (in the
        background, so playback isn't delayed) for sounding like "Hey Nova" to her own ears."""
        self.echo.play(pcm, sample_rate, started_at)
        model = self._model
        if model is None:  # the wake word isn't listening: nothing can cut her off anyway
            self._sounds_like_wake = False
            return
        self._sounds_like_wake = None
        check = self._own_voice_check = object()

        def run() -> None:
            try:
                result = sounds_like_wake(model, pcm, sample_rate)
            except Exception:
                result = True  # unsure: only Esc during this sentence
            if self._own_voice_check is check:
                self._sounds_like_wake = result
        threading.Thread(target=run, name="NovaOwnVoiceCheck", daemon=True).start()

    def unmute(self) -> None:
        """A new request: Nova may speak again after being cut off."""
        self._muted = False

    def _went_to_sleep(self) -> None:
        _beep(going_to_sleep=True)
        if self._sleep_callback:
            self._sleep_callback()

    def push_to_talk(self, on_start: Callable[[], None], on_result: Callable[[str], None],
                     on_error: Callable[[str], None], on_notice: Callable[[str], None] | None = None,
                     hold: threading.Event | None = None) -> None:
        """Record one command. With `hold`, record until the event is set (key released) instead of
        stopping at the first pause."""
        if self._thread and self._thread.is_alive():
            on_error("Wake listening is active; turn it off before push-to-talk.")
            return
        self._notice_callback = on_notice
        def run():
            try:
                model = self._load()
                sd = _sounddevice()
                KaldiRecognizer, _Model = _dependencies()
                on_start()
                audio: list[bytes] = []
                result = _transcribe_window(model, sd, KaldiRecognizer, hold or threading.Event(),
                                            HOLD_MAX_SECONDS if hold else COMMAND_SECONDS, self.input_key,
                                            self._emit_level, end_on_silence=hold is None, keep_audio=audio)
                result = self._better_transcript(result, audio)
                on_result(result)
            except Exception as exc:
                on_error(str(exc))
        threading.Thread(target=run, name="AlfredPushToTalk", daemon=True).start()

    @staticmethod
    def _make_sapi_voice(output_key: str | None):
        if sys.platform == "darwin":
            return _SayVoice(), None, None
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            outputs = voice.GetAudioOutputs("", "")
            chosen = None
            if output_key:
                for index in range(outputs.Count):
                    token = outputs.Item(index)
                    if str(token.GetDescription()) == output_key:
                        chosen = token
                        break
            fallback = bool(output_key and chosen is None)
            if chosen is not None:
                voice.AudioOutput = chosen
            _use_female_voice(voice)
            if fallback:
                return voice, pythoncom, "The saved speaker is unavailable; Windows' current default output is being used."
            return voice, pythoncom, None
        except Exception:
            pythoncom.CoUninitialize()
            raise

    def speak(self, text: str, done: Callable[[], None] | None = None,
              on_error: Callable[[str], None] | None = None,
              on_fallback: Callable[[str], None] | None = None) -> None:
        """Speak offline: the chosen natural voice when installed, else the selected Windows SAPI endpoint."""
        text = piper_voice.speakable(text)
        if not text.strip():
            if done:
                done()
            return
        if self._muted:  # cut off: the rest of that answer stays unsaid
            if done:
                done()
            return

        def run():
            self._speaking.set()
            self._stop_speaking.clear()
            self._interrupted = False
            self._now_saying = text
            self._sounds_like_wake = False
            pythoncom = None
            try:
                if self._natural_voice_for(text):
                    self._speak_natural(text)
                    return
                voice, pythoncom, fallback = self._make_sapi_voice(self.output_key)
                if fallback and on_fallback:
                    on_fallback(fallback)
                voice.Rate = 0
                voice.Volume = 100
                voice.Speak(text, SVSF_ASYNC)
                while not voice.WaitUntilDone(100):
                    if self._stop_speaking.is_set():
                        voice.Speak("", SVSF_ASYNC | SVSF_PURGE_BEFORE_SPEAK)
                        break
            except Exception as exc:
                if on_error:
                    on_error(f"Offline speech output failed: {exc}")
                elif self._error_callback:
                    self._error_callback(f"Offline speech output failed: {exc}")
            finally:
                if pythoncom is not None:
                    pythoncom.CoUninitialize()
                self._quiet_until = 0.0 if self._interrupted else time.monotonic() + ECHO_TAIL_SECONDS
                self._now_saying = ""
                self._speaking.clear()
                if done:
                    done()
        threading.Thread(target=run, name="AlfredSpeech", daemon=True).start()

    def _speak_natural(self, text: str) -> None:
        # shortcut: plays on Windows' default output device; the SAPI speaker choice applies to the built-in voice only.
        import numpy
        pcm, sample_rate = piper_voice.synthesize(self._natural_voice_for(text), text)
        sd = _sounddevice()
        self._her_audio_starts(pcm, sample_rate)
        sd.play(numpy.frombuffer(pcm, dtype=numpy.int16), sample_rate)
        while sd.get_stream().active:
            if self._stop_speaking.is_set():
                sd.stop()
                break
            time.sleep(0.05)

    def _natural_voice_for(self, text: str) -> str | None:
        """Vietnamese sentences get the Vietnamese voice when it is installed; others the chosen natural voice."""
        if piper_voice.is_vietnamese(text) and piper_voice.installed(piper_voice.VIETNAMESE):
            return piper_voice.VIETNAMESE
        if self.voice_name and piper_voice.installed(self.voice_name):
            return self.voice_name
        return None

    def set_voice(self, name: str | None) -> None:
        self.voice_name = name if name in piper_voice.VOICES else None
        save_voice_name(self.voice_name)

    def stop_speaking(self) -> None:
        """Cut the current reply off immediately (Esc, or the user starts talking)."""
        if self._speaking.is_set():
            self._stop_speaking.set()
        if self._sentences is not None:
            self._sentences.stop()

    def say(self, sentence: str) -> None:
        """Queue one sentence of a reply that is still being written."""
        if self._muted:
            return
        if self._sentences is None:
            self._sentences = SentenceSpeaker(
                self._prepare_sentence, self._play_sentence,
                on_busy=self._sentence_busy,
                on_error=lambda message: self._error_callback(message) if self._error_callback else None)
        self._sentences.say(sentence)

    def _prepare_sentence(self, text: str) -> tuple[str, object] | None:
        text = piper_voice.speakable(text)
        if not text.strip():
            return None
        natural = self._natural_voice_for(text)
        if natural:
            return "piper", piper_voice.synthesize(natural, text), text
        return "sapi", text, text

    def _play_sentence(self, prepared: tuple[str, object, str], stop: threading.Event) -> None:
        kind, payload, self._now_saying = prepared
        try:
            self._play_prepared(kind, payload, stop)
        finally:
            self._now_saying = ""

    def _play_prepared(self, kind: str, payload: object, stop: threading.Event) -> None:
        if kind == "piper":
            import numpy
            pcm, sample_rate = payload
            sd = _sounddevice()
            self._her_audio_starts(pcm, sample_rate)
            sd.play(numpy.frombuffer(pcm, dtype=numpy.int16), sample_rate)
            while sd.get_stream().active:
                if stop.is_set():
                    sd.stop()
                    break
                time.sleep(0.03)
            return
        self._sounds_like_wake = False  # the built-in voice: no copy to check, her text is checked for "Nova"
        voice, pythoncom, _fallback = self._make_sapi_voice(self.output_key)
        try:
            voice.Rate = 0
            voice.Volume = 100
            voice.Speak(payload, SVSF_ASYNC)
            while not voice.WaitUntilDone(80):
                if stop.is_set():
                    voice.Speak("", SVSF_ASYNC | SVSF_PURGE_BEFORE_SPEAK)
                    break
        finally:
            if pythoncom is not None:
                pythoncom.CoUninitialize()

    def test_input_level(self, on_result: Callable[[float, float, str], None],
                         on_error: Callable[[str], None]) -> None:
        def run():
            try:
                result = _measure_input(self.input_key)
                on_result(*result)
            except Exception as exc:
                on_error(str(exc))
        threading.Thread(target=run, name="AlfredMicTest", daemon=True).start()

    def test_output(self, on_done: Callable[[], None], on_error: Callable[[str], None],
                    on_fallback: Callable[[str], None] | None = None) -> None:
        """User-initiated short, quiet playback on the selected Windows SAPI output."""
        def run():
            pythoncom = None
            try:
                voice, pythoncom, fallback = self._make_sapi_voice(self.output_key)
                if fallback and on_fallback:
                    on_fallback(fallback)
                voice.Rate = 0
                voice.Volume = 8
                voice.Speak("Nova audio output test.", 0)
                on_done()
            except Exception as exc:
                on_error(f"Speaker playback test failed: {exc}")
            finally:
                if pythoncom is not None:
                    pythoncom.CoUninitialize()
        threading.Thread(target=run, name="AlfredSpeakerTest", daemon=True).start()


class _SayVoice:
    """macOS's own voice (`say`) behind the few SAPI calls Nova makes, so speaking and cutting off work the same."""
    _voice: str | None = None

    def __init__(self) -> None:
        self.Rate, self.Volume = 0, 100
        self.process: Any = None

    @classmethod
    def _pick(cls) -> str:
        if cls._voice is None:  # a female English voice, as on Windows; else the Mac's default voice
            import mac
            try:
                installed = mac.voices()
            except OSError:
                installed = []
            cls._voice = next((name for name in ("Samantha", "Ava", "Allison", "Susan") if name in installed), "")
        return cls._voice

    def Speak(self, text: str, flags: int = 0) -> None:  # noqa: N802 - SAPI's name
        import mac
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
        if not text:
            return
        loudness = "" if self.Volume >= 100 else f"[[volm {max(0, self.Volume) / 100:.2f}]] "
        self.process = mac.say(loudness + text, voice=self._pick())
        if not flags & SVSF_ASYNC:
            self.process.wait()

    def WaitUntilDone(self, milliseconds: int) -> bool:  # noqa: N802 - SAPI's name
        if self.process is None:
            return True
        try:
            self.process.wait(timeout=milliseconds / 1000)
            return True
        except subprocess.TimeoutExpired:
            return False
