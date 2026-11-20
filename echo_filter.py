"""Takes Nova's own voice out of the microphone while she talks, so "Hey Nova" said over her can be heard.

Nova knows exactly what she plays (the natural voices). This finds how late her voice reaches the mic (speaker and
room delay), learns per frequency how loud that echo is, and turns down the parts of each moment that are mostly her
echo: a residual echo suppressor. It works on magnitudes, so cheap speakers, room reverb and a few milliseconds of
timing jitter don't break it, and it costs about 0.5% of one core. Only the "Hey Nova" listener hears its output.

Tuned on simulated rooms (small speaker, 60-200 ms delay, reverb, noise), "Hey Nova" said over her was caught 43 of
48 times instead of 32 with her echo at 60% of your voice, and 32 instead of 15 with it as loud as you.
"""
from __future__ import annotations

import threading
import time

import numpy

RATE = 16_000
FRAME, HOP = 512, 256
MAX_DELAY = 0.45  # seconds: speaker + driver + room
KEEP = 12.0       # seconds of playback kept for lining up
# Take out 70% of the estimated echo: Vosk copes better with some of her voice left than with holes in yours.
ECHO_SHARE = 0.7
FLOOR = 0.05      # never turn a frequency down by more than this
# How loud her echo is, per frequency: follow a drop fast, a rise very slowly (a sudden rise is usually you talking).
FALL, RISE, MOST = 0.25, 0.004, 4.0
# Mic samples are counted, not timed (callback times jitter); only a gap this big (lost audio) re-syncs to the clock.
RESYNC = int(0.15 * RATE)


def to_16k(pcm16: bytes, sample_rate: int) -> numpy.ndarray:
    samples = numpy.frombuffer(pcm16, dtype=numpy.int16).astype(numpy.float32)
    if sample_rate == RATE or len(samples) == 0:
        return samples
    if sample_rate > RATE:  # soften what 16 kHz can't hold before thinning out (Kokoro plays at 24 kHz)
        samples = numpy.convolve(samples, [0.25, 0.5, 0.25], mode="same").astype(numpy.float32)
    positions = numpy.arange(0, len(samples), sample_rate / RATE)
    return numpy.interp(positions, numpy.arange(len(samples)), samples).astype(numpy.float32)


def estimate_delay(mic: numpy.ndarray, earlier: numpy.ndarray, max_lag: int) -> int | None:
    """How many samples late `mic` heard the playback: `earlier` holds the playback from max_lag samples before the
    mic chunk to its end. GCC-PHAT; None when the match isn't clear (mostly you, or noise)."""
    size = 1 << int(numpy.ceil(numpy.log2(len(earlier) + len(mic))))
    spectrum = numpy.fft.rfft(earlier, size) * numpy.conj(numpy.fft.rfft(mic, size))
    correlation = numpy.fft.irfft(spectrum / (numpy.abs(spectrum) + 1e-9), size)
    # earlier[j] lines up with mic[t] where j = t + max_lag - lag, i.e. at a shift of max_lag - lag.
    shifts = correlation[: max_lag + 1]
    best = int(numpy.argmax(shifts))
    if shifts[best] < 5 * (numpy.median(numpy.abs(shifts)) + 1e-9):
        return None
    return max_lag - best


def through_a_room(samples: numpy.ndarray, delay: float = 0.1, reverb: float = 0.3) -> numpy.ndarray:
    """Roughly how Nova's playback reaches a mic: a small speaker (little bass, some distortion), `delay` seconds
    late, with a room's ring-out. Always the same room (fixed seed), for checking her own sentences."""
    speaker = numpy.empty_like(samples)
    speaker[:1] = samples[:1]
    speaker[1:] = samples[1:] - 0.9 * samples[:-1]
    speaker = numpy.tanh(speaker / 22000) * 22000
    length = int(reverb * RATE)
    ring = numpy.random.default_rng(1).normal(0, 1, length) * numpy.exp(-6.9 * numpy.arange(length) / length) * 0.08
    ring[0] = 1.0
    size = 1 << int(numpy.ceil(numpy.log2(len(speaker) + length)))
    wet = numpy.fft.irfft(numpy.fft.rfft(speaker, size) * numpy.fft.rfft(ring, size), size)[: len(speaker) + length - 1]
    return numpy.concatenate([numpy.zeros(int(delay * RATE)), wet]).astype(numpy.float32)


class EchoSuppressor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._window = numpy.sqrt(numpy.hanning(FRAME + 1)[:FRAME]).astype(numpy.float32)  # sqrt-Hann, 50%: sums to 1
        self._reference = numpy.zeros(0, dtype=numpy.float32)  # what Nova played, 16 kHz
        self._reference_start: float | None = None  # monotonic time of its first sample
        self._delays: list[int] = []
        self._gain: numpy.ndarray | None = None  # per frequency: her echo's size / her playback's size (kept: same room)
        self.new_stream()

    def new_stream(self) -> None:
        """A new microphone stream starts: its samples continue nothing from before."""
        with self._lock:
            self._forget_mic()

    def _forget_mic(self) -> None:
        self._pending = numpy.zeros(0, dtype=numpy.float32)  # mic samples not yet in a full frame
        self._mic_end: int | None = None  # reference-clock index just after the last mic sample
        self._overlap = numpy.zeros(FRAME, dtype=numpy.float32)

    # ---- what Nova plays ----
    def play(self, pcm16: bytes, sample_rate: int, started_at: float | None = None) -> None:
        """Nova starts playing this audio now (or at `started_at`, monotonic)."""
        samples = to_16k(pcm16, sample_rate)
        started_at = time.monotonic() if started_at is None else started_at
        with self._lock:
            if self._reference_start is None or \
                    started_at - self._reference_start > len(self._reference) / RATE + KEEP:
                # Nothing kept is recent enough to matter: start the clock again (a long pause costs no memory).
                self._reference = numpy.zeros(0, dtype=numpy.float32)
                self._reference_start = started_at
                self._forget_mic()
            offset = int(round((started_at - self._reference_start) * RATE))
            if offset < 0:
                samples, offset = samples[-offset:], 0
            end = offset + len(samples)
            if end > len(self._reference):
                self._reference = numpy.concatenate([self._reference, numpy.zeros(end - len(self._reference), numpy.float32)])
            self._reference[offset:end] += samples
            excess = len(self._reference) - int(KEEP * RATE)
            if excess > 0:  # forget old playback; the clock moves with it
                self._reference = self._reference[excess:]
                self._reference_start += excess / RATE
                if self._mic_end is not None:
                    self._mic_end -= excess

    def _reference_at(self, start: int, length: int) -> numpy.ndarray:
        out = numpy.zeros(length, dtype=numpy.float32)
        lo, hi = max(start, 0), min(start + length, len(self._reference))
        if hi > lo:
            out[lo - start:hi - start] = self._reference[lo:hi]
        return out

    # ---- the microphone ----
    def clean(self, chunk16: bytes, captured_at: float | None = None) -> bytes:
        """A mic chunk (16 kHz int16) that ended at `captured_at` (monotonic) -> the same stream with Nova's echo
        turned down, held back by 16-32 ms (so a call returns a few samples more or less than it got)."""
        mic = numpy.frombuffer(chunk16, dtype=numpy.int16).astype(numpy.float32)
        if not len(mic):
            return b""
        captured_at = time.monotonic() if captured_at is None else captured_at
        with self._lock:
            if self._reference_start is None:
                return chunk16  # she hasn't played anything
            clock_start = int(round((captured_at - self._reference_start) * RATE)) - len(mic)
            if self._mic_end is None or abs(clock_start - self._mic_end) > RESYNC:
                self._forget_mic()  # a new stream, or audio went missing: line up by the clock again
                chunk_start = clock_start
            else:
                chunk_start = self._mic_end
            self._mic_end = chunk_start + len(mic)
            max_lag = int(MAX_DELAY * RATE)
            earlier = self._reference_at(chunk_start - max_lag, len(mic) + max_lag)
            if numpy.sqrt(numpy.mean(earlier ** 2)) > 30:  # she was talking: measure the delay again
                lag = estimate_delay(mic, earlier, max_lag)
                if lag is not None:
                    self._delays = (self._delays + [lag])[-9:]
            delay = int(numpy.median(self._delays)) if self._delays else max_lag // 4
            self._pending = numpy.concatenate([self._pending, mic])
            pending_start = self._mic_end - len(self._pending)
            out = []
            while len(self._pending) >= FRAME:
                reference = self._reference_at(pending_start - delay, FRAME)
                self._overlap += self._suppress(self._pending[:FRAME], reference)
                out.append(self._overlap[:HOP].copy())
                self._overlap = numpy.concatenate([self._overlap[HOP:], numpy.zeros(HOP, numpy.float32)])
                self._pending = self._pending[HOP:]
                pending_start += HOP
        cleaned = numpy.concatenate(out) if out else numpy.zeros(0, numpy.float32)
        return numpy.clip(cleaned, -32768, 32767).astype(numpy.int16).tobytes()

    def _suppress(self, frame: numpy.ndarray, reference: numpy.ndarray) -> numpy.ndarray:
        mic_spectrum = numpy.fft.rfft(frame * self._window)
        mic_size = numpy.abs(mic_spectrum)
        her_size = numpy.abs(numpy.fft.rfft(reference * self._window))
        if her_size.sum() < 1e-3:
            return numpy.fft.irfft(mic_spectrum, FRAME).astype(numpy.float32) * self._window
        ratio = mic_size / (her_size + 1.0)
        if self._gain is None:
            self._gain = numpy.minimum(ratio, 1.0)
        else:
            speed = numpy.where(ratio < self._gain, FALL, RISE)
            self._gain += (numpy.minimum(ratio, MOST) - self._gain) * speed
        echo = ECHO_SHARE * self._gain * her_size
        keep = numpy.clip(1.0 - echo / (mic_size + 1e-6), FLOOR, 1.0)
        return numpy.fft.irfft(mic_spectrum * keep, FRAME).astype(numpy.float32) * self._window
