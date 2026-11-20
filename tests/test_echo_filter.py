"""The echo filter: it finds how late Nova's voice reaches the mic, turns her echo down, keeps your voice, changes
nothing when she is silent, and a long pause between answers costs no memory."""
from __future__ import annotations

import unittest

import numpy

import echo_filter

RATE = echo_filter.RATE


def syllables(seed: int, seconds: float) -> numpy.ndarray:
    """Speech-like test sound: bursts of coloured noise, 4 a second, with short gaps."""
    rng = numpy.random.default_rng(seed)
    noise = numpy.convolve(rng.normal(0, 1, int(seconds * RATE)), numpy.hanning(9), mode="same")
    envelope = numpy.clip(numpy.sin(numpy.arange(len(noise)) * 2 * numpy.pi * 4 / RATE + seed), 0, None)
    return (noise / noise.std() * envelope * 6000).astype(numpy.float32)


def filtered(suppressor: echo_filter.EchoSuppressor, mic: numpy.ndarray) -> numpy.ndarray:
    pcm = numpy.clip(mic, -32768, 32767).astype(numpy.int16)
    blocks = [suppressor.clean(pcm[start:start + 4000].tobytes(), (start + 4000) / RATE)
              for start in range(0, len(pcm), 4000)]
    return numpy.frombuffer(b"".join(blocks), dtype=numpy.int16).astype(numpy.float32)


def level(samples: numpy.ndarray) -> float:
    return float(10 * numpy.log10(numpy.mean(samples.astype(numpy.float64) ** 2) + 1e-9))


class EchoFilterTests(unittest.TestCase):
    def test_finds_how_late_her_voice_arrives(self) -> None:
        playback = syllables(1, 3.0)
        max_lag = int(echo_filter.MAX_DELAY * RATE)
        for lag in (0, 1600, 4800):
            mic = numpy.concatenate([numpy.zeros(lag), playback])[: len(playback)]
            start = 16_000
            earlier = playback[start - max_lag:start + 4000]
            self.assertEqual(echo_filter.estimate_delay(mic[start:start + 4000], earlier, max_lag), lag)

    def test_nothing_changes_while_she_is_silent(self) -> None:
        suppressor = echo_filter.EchoSuppressor()
        you = syllables(2, 2.0)
        self.assertEqual(suppressor.clean(you[:4000].astype(numpy.int16).tobytes()), you[:4000].astype(numpy.int16).tobytes())
        suppressor.play(numpy.zeros(4 * RATE, numpy.int16).tobytes(), RATE, started_at=0.0)
        out = filtered(suppressor, you)
        hop = echo_filter.HOP  # the stream starts with one hop faded in
        self.assertLessEqual(float(numpy.max(numpy.abs(out[hop:] - you.astype(numpy.int16)[hop:len(out)]))), 1.0)

    def test_her_echo_is_turned_down_and_your_voice_kept(self) -> None:
        her = syllables(3, 6.0)
        delay = int(0.12 * RATE)
        echo = 0.8 * numpy.concatenate([numpy.zeros(delay), her])[: len(her)]
        echo[1:] += 0.3 * echo[:-1]  # a little room colour
        you = numpy.zeros_like(her)
        you[4 * RATE:5 * RATE] = syllables(4, 1.0)

        def run(mic: numpy.ndarray) -> numpy.ndarray:
            suppressor = echo_filter.EchoSuppressor()
            suppressor.play(numpy.clip(her, -32768, 32767).astype(numpy.int16).tobytes(), RATE, started_at=0.0)
            return filtered(suppressor, mic)

        hers_only, both = run(echo), run(echo + you)
        her_part = slice(2 * RATE, 4 * RATE)
        self.assertLessEqual(level(hers_only[her_part]), level(echo[her_part]) - 6, "her echo wasn't turned down")
        your_part = slice(4 * RATE, 5 * RATE)
        kept = (both - hers_only)[your_part]
        self.assertGreaterEqual(level(kept), level(you[your_part]) - 4, "your voice was cut along with hers")

    def test_a_long_pause_between_answers_costs_no_memory(self) -> None:
        suppressor = echo_filter.EchoSuppressor()
        one_second = syllables(5, 1.0).astype(numpy.int16).tobytes()
        suppressor.play(one_second, RATE, started_at=100.0)
        suppressor.play(one_second, RATE, started_at=100.0 + 3600)  # an hour later
        self.assertLessEqual(len(suppressor._reference), 2 * RATE)
        suppressor.play(syllables(6, 1.0).astype(numpy.int16).tobytes(), 24_000, started_at=3701.0)  # Kokoro's rate
        self.assertLessEqual(len(suppressor._reference), int(echo_filter.KEEP * RATE))


if __name__ == "__main__":
    unittest.main()
