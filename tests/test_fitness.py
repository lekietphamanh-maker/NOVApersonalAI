"""Bluetooth Heart Rate Measurement parsing and the session statistics."""
from __future__ import annotations

import unittest

from fitness import HeartStats, describe, parse_heart_rate


class HeartRateTests(unittest.TestCase):
    def test_parsing_the_standard_measurement(self):
        self.assertEqual(parse_heart_rate(bytes([0x00, 72])), (72, []))                       # 8-bit, no RR
        self.assertEqual(parse_heart_rate(bytes([0x01, 0x2C, 0x01])), (300, []))              # 16-bit
        bpm, intervals = parse_heart_rate(bytes([0x10, 60, 0x00, 0x04, 0x00, 0x02]))           # RR: 1.0 s, 0.5 s
        self.assertEqual((bpm, intervals), (60, [1.0, 0.5]))
        self.assertEqual(parse_heart_rate(bytes([0x18, 65, 0x10, 0x00, 0x00, 0x04]))[1], [1.0])  # energy field skipped

    def test_statistics_and_variability(self):
        now = [0.0]
        stats = HeartStats(clock=lambda: now[0])
        for second, bpm in enumerate([60, 62, 64, 300, 58]):  # 300 is a glitch and is ignored
            now[0] = second * 30
            stats.add(bpm, [1.0, 1.05, 0.98, 1.02, 1.0, 1.04])
        summary = stats.summary()
        self.assertEqual((summary["bpm"], summary["low"], summary["high"], summary["average"]), (58, 58, 64, 61))
        self.assertIsNotNone(summary["rmssd"])
        self.assertIn("58 bpm now", describe(summary, "Polar H10"))
        self.assertIn("No heart rate yet", describe({}, ""))


if __name__ == "__main__":
    unittest.main()
