"""The real wake-word loop on speech from Windows' own voices: "Hey Nova, …" must wake it with the right request,
ordinary sentences (also ones that sound close) must not, and after waking it keeps listening without the name.
Prints every result, so misses can be tuned. tests/wake_accents.py runs the same checks with espeak accents."""
from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
import wave
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

POSITIVE = [("Hey Nova, what time is it?", "time"), ("Hey Nova, turn the volume down.", "volume"),
            ("Hey Nova, open notepad.", "notepad")]
NEGATIVE = ["I told my friend about the weather today.", "What is the capital of Vietnam?", "No way, that is not over.",
            "Hey, no problem.", "Hey now, look at this.", "Okay, nobody is home now."]
CHUNK = 8000  # bytes: 4000 samples at 16 kHz, like the real microphone stream
# She "started playing" this long before her first chunk is delivered; that chunk holds the 0.25 s before delivery,
# so her voice reaches the mic 0.1 s after she plays it.
SPEAKER_DELAY = 0.35


def sapi_speech(text: str, voice_token) -> bytes:
    """16 kHz mono 16-bit speech from a Windows voice."""
    import numpy
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        voice.Voice = voice_token
        path = str(Path(tempfile.mkdtemp()) / "speech.wav")
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        stream.Open(path, 3, False)
        voice.AudioOutputStream = stream
        voice.Speak(text)
        stream.Close()
    finally:
        pythoncom.CoUninitialize()
    with wave.open(path) as recording:
        rate, channels, width = recording.getframerate(), recording.getnchannels(), recording.getsampwidth()
        frames = recording.readframes(recording.getnframes())
    samples = numpy.frombuffer(frames, dtype=numpy.int16 if width == 2 else numpy.uint8).astype(numpy.float32)
    if width == 1:
        samples = (samples - 128) * 256
    samples = samples.reshape(-1, channels).mean(axis=1)
    positions = numpy.arange(0, len(samples), rate / 16_000)
    return numpy.interp(positions, numpy.arange(len(samples)), samples).astype(numpy.int16).tobytes()


@unittest.skipUnless(sys.platform == "win32", "needs Windows voices")
class WakeWordTests(unittest.TestCase):
    def listen(self, *speeches, gap: float = 1.0, follow_up: float | None = None, wait: float = 15) -> dict:
        """Play the speeches to the real wake loop like sound in a room, with `gap` seconds of silence between them.
        A ("nova", speech) item is Nova's own voice, played while she is marked as talking (after your request).
        An ("interrupt", her text, her speech, your speech, seconds) item is Nova talking with you saying something
        over her that many seconds in; her voice reaches the mic at 40% (speakers at a normal volume), and once she
        is cut off only yours plays.
        Her voice reaches the mic 0.1 s after she plays it, and the echo filter gets a copy of what she plays, as
        with the natural voices. Sound that arrives while the mic stream is closed is lost, as in a real room."""
        import numpy
        import voice
        silence = bytes(CHUNK)
        timeline: list[tuple[str, object]] = [("audio", silence)] * 2
        def pieces(audio: bytes) -> list[bytes]:
            return [audio[i:i + CHUNK].ljust(CHUNK, b"\0") for i in range(0, len(audio), CHUNK)]
        for speech in speeches:
            if isinstance(speech, tuple) and speech[0] == "interrupt":
                _kind, her_text, hers, yours, seconds = speech
                her_wave = numpy.frombuffer(hers, dtype=numpy.int16).astype(numpy.float32) * 0.4
                your_wave = numpy.zeros_like(her_wave)
                start = int(seconds * 16_000)
                your_part = numpy.frombuffer(yours, dtype=numpy.int16).astype(numpy.float32)[: max(0, len(her_wave) - start)]
                your_wave[start:start + len(your_part)] = your_part
                both = numpy.clip(her_wave + your_wave, -32768, 32767).astype(numpy.int16).tobytes()
                timeline.append(("cut_in", (her_text, hers)))
                timeline += [("both", pair) for pair in zip(pieces(both), pieces(your_wave.astype(numpy.int16).tobytes()))]
                timeline.append(("talking", False))
            else:
                novas = isinstance(speech, tuple)
                audio = speech[1] if novas else speech
                timeline += [("talking", audio)] if novas else []
                timeline += [("audio", piece) for piece in pieces(audio)]
                timeline += [("talking", False)] if novas else []
            timeline += [("audio", silence)] * max(4, round(gap * 4))
        microphone: dict = {"callback": None}
        opened, played, stop = threading.Event(), threading.Event(), threading.Event()

        @contextmanager
        def fake_microphone(_sd, _key, callback, blocksize=4000):
            microphone["callback"] = callback
            opened.set()
            try:
                yield None
            finally:
                microphone["callback"] = None

        def play() -> None:
            opened.wait(60)  # the sound starts once the mic is first listening (the model loads first)
            novas_turn = False
            due = time.monotonic()  # her answer plays in real time, on a fixed schedule like a real mic's clock
            for kind, value in timeline:
                if stop.is_set():
                    return
                if kind == "talking":
                    if value:  # Nova answers only after she heard the request, as in real life
                        deadline = time.monotonic() + 20
                        while not heard and time.monotonic() < deadline and not stop.is_set():
                            time.sleep(0.05)
                        controller._her_audio_starts(value, 16_000, started_at=time.monotonic() - SPEAKER_DELAY)
                    novas_turn = bool(value)
                    if value or controller._sentences_busy:
                        controller._sentence_busy(bool(value))
                    continue
                if kind == "cut_in":  # Nova starts talking (no request first), saying this text
                    her_text, hers = value
                    novas_turn = True
                    controller._now_saying = her_text
                    controller._her_audio_starts(hers, 16_000, started_at=time.monotonic() - SPEAKER_DELAY)
                    controller._sentence_busy(True)
                    continue
                if kind == "both":
                    if not barged.is_set():
                        value = value[0]
                    elif any(value[1]):
                        value = value[1]  # once cut off, only your voice is left
                    else:
                        continue  # the rest of her answer is gone: nothing to wait through
                if microphone["callback"] is not None:
                    microphone["callback"](value, 4000, None, None)
                due = max(due + (0.25 if novas_turn else 0.02), time.monotonic() - 0.25)
                time.sleep(max(0.0, due - time.monotonic()))
            played.set()
            while not stop.wait(0.05):
                if microphone["callback"] is not None:
                    microphone["callback"](silence, 4000, None, None)

        woke, slept, barged, heard = threading.Event(), threading.Event(), threading.Event(), []
        controller = voice.VoiceController()

        class Speaker:  # stands in for Nova's sentence speaker: stopping it ends her talking
            busy = False

            def stop(self) -> None:
                if controller._sentences_busy:
                    controller._sentence_busy(False)
        controller._sentences = Speaker()
        patches = [patch.object(voice, "_open_input", fake_microphone), patch.object(voice, "_sounddevice", lambda: object()),
                   patch.object(voice, "_beep", lambda going_to_sleep=False: None)]
        if follow_up is not None:
            patches.append(patch.object(voice, "FOLLOW_UP_SECONDS", follow_up))
        for active in patches:
            active.start()
        try:
            controller.start_wake(on_wake=woke.set, on_command=heard.append, on_sleep=slept.set, on_barge_in=barged.set,
                                  on_error=lambda error: heard.append(f"ERROR {error}"))
            threading.Thread(target=play, daemon=True).start()
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline and not (slept.is_set() or (follow_up is None and heard and played.is_set())):
                time.sleep(0.1)
            stop.set()
            controller.stop_wake()
        finally:
            for active in patches:
                active.stop()
        return {"woke": woke.is_set(), "heard": heard, "slept": slept.is_set(), "cut_off": barged.is_set()}

    def check_voices(self, speak, voices, nova_voices=()) -> None:
        """Hey Nova requests are heard right, near-misses don't wake it, and a follow-up needs no name. Nova's own
        lines are read by the first of `nova_voices` (women's voices first, like hers) that isn't the speaker's."""
        hits, false_wakes, follow_ups, self_heard, cut_offs, self_cut, results = 0, [], 0, [], 0, [], []
        cut_off_tries = 0
        key = lambda voice: getattr(voice, "Id", voice)  # noqa: E731  (a Windows voice token, or an espeak name)
        for name, voice_id in voices:
            nova = next((other for other in nova_voices if key(other) != key(voice_id)), voice_id)

            def hers(text: str, nova=nova) -> bytes:
                return speak(text, nova)
            for phrase, keyword in POSITIVE:
                result = self.listen(speak(phrase, voice_id))
                results.append(f"{name} | {phrase!r} -> {result}")
                hits += any(keyword in command.lower() for command in result["heard"])
            for phrase in NEGATIVE:
                result = self.listen(speak(phrase, voice_id), wait=8)
                results.append(f"{name} | {phrase!r} -> {result}")
                if result["woke"] or result["heard"]:
                    false_wakes.append(f"{name}: {phrase}")
            # The name once, then a request without it, then silence: it goes back to sleep by itself.
            result = self.listen(speak("Hey Nova.", voice_id), speak("Open notepad.", voice_id), follow_up=6, wait=25)
            results.append(f"{name} | follow-up -> {result}")
            follow_ups += any("note" in command.lower() for command in result["heard"]) and result["slept"]
            # Nova answers out loud in the follow-up window: her own voice must never count as a request.
            result = self.listen(speak("Hey Nova, what time is it?", voice_id),
                                 ("nova", hers("It is three o'clock. Do you want me to open notepad and type hello?")),
                                 gap=2.0, follow_up=10, wait=45)
            results.append(f"{name} | Nova answers -> {result}")
            if len(result["heard"]) != 1 or "note" in " ".join(result["heard"]).lower():
                self_heard.append(f"{name}: {result['heard']}")
            # Talking over Nova: "Hey Nova, what about Friday?" in one breath stops her mid-sentence and is the new
            # request. (Not with her own voice: no one sounds exactly like her, and nothing could tell them apart.)
            answer = ("The weather today is warm and sunny with a light breeze from the sea, and tomorrow looks "
                      "much the same, so it is a good week to spend some time outside.")
            for seconds in ((1.5, 3.0, 4.5) if key(nova) != key(voice_id) else ()):
                cut_off_tries += 1
                result = self.listen(("interrupt", answer, hers(answer), speak("Hey Nova, what about Friday?", voice_id), seconds),
                                     gap=1.5, follow_up=8, wait=45)
                results.append(f"{name} | cut Nova off {seconds} s in -> {result}")
                cut_offs += result["cut_off"] and any("friday" in command.lower() for command in result["heard"])
            # Her own voice never cuts her off, not even when she says the name herself.
            for text in (answer, "To wake me up, just say Hey Nova and then ask your question."):
                result = self.listen(("interrupt", text, hers(text), b"", 0.0), gap=1.0, follow_up=3, wait=30)
                results.append(f"{name} | Nova alone ({text[:24]}...) -> {result}")
                if result["cut_off"]:
                    self_cut.append(f"{name}: {text[:30]}")
        print("\n".join(results))
        total = len(POSITIVE) * len(voices)
        print(f"wake word: {hits}/{total} requests heard correctly; false wakes: {len(false_wakes)}; "
              f"follow-ups: {follow_ups}/{len(voices)}; Nova heard herself: {len(self_heard)}; "
              f"cut her off: {cut_offs}/{cut_off_tries}; she cut herself off: {len(self_cut)}")
        self.assertEqual(false_wakes, [], "an ordinary sentence woke Nova")
        self.assertEqual(self_heard, [], "Nova took her own voice for a request")
        self.assertEqual(self_cut, [], "Nova's own voice cut her off")
        self.assertGreaterEqual(cut_offs, cut_off_tries * 2 / 3, "saying Hey Nova over her didn't stop her often enough")
        self.assertGreaterEqual(hits, total * 2 / 3, "the wake word missed too often")
        self.assertGreaterEqual(follow_ups, len(voices) * 2 / 3, "the follow-up window failed too often")

    def test_wake_word_with_windows_voices(self):
        import win32com.client
        tokens = win32com.client.Dispatch("SAPI.SpVoice").GetVoices()
        voices = [tokens.Item(i) for i in range(tokens.Count) if "english" in tokens.Item(i).GetDescription().lower()
                  or "en-" in tokens.Item(i).GetAttribute("Language").lower() or tokens.Item(i).GetAttribute("Language") in ("409", "809")]
        self.assertTrue(voices, "no English Windows voice on this machine")
        nova_voices = sorted(voices, key=lambda token: token.GetAttribute("Gender") != "Female")  # Nova is a woman
        self.check_voices(sapi_speech, [(token.GetDescription(), token) for token in voices[:3]], nova_voices=nova_voices)


if __name__ == "__main__":
    unittest.main()
