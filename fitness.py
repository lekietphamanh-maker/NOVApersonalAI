"""Live heart rate from any band, watch or chest strap that shares it over the standard Bluetooth Heart Rate
service: Polar (H10, Verity Sense, watches), Garmin ("broadcast heart rate"), Wahoo, Coros, many Amazfit and
Xiaomi bands. Everything stays on this PC; nothing is saved.
"""
from __future__ import annotations

import asyncio
import math
import threading
import time
from collections import deque
from typing import Any, Callable

HEART_RATE_SERVICE = "0000180d-0000-1000-8000-00805f9b34fb"
HEART_RATE_MEASUREMENT = "00002a37-0000-1000-8000-00805f9b34fb"


def parse_heart_rate(data: bytes) -> tuple[int, list[float]]:
    """Beats per minute and the beat-to-beat (RR) intervals in seconds from one Heart Rate Measurement."""
    flags = data[0]
    if flags & 0x01:
        bpm, index = int.from_bytes(data[1:3], "little"), 3
    else:
        bpm, index = data[1], 2
    if flags & 0x08:
        index += 2  # energy expended, not used
    intervals = []
    if flags & 0x10:
        while index + 1 < len(data):
            intervals.append(int.from_bytes(data[index:index + 2], "little") / 1024)
            index += 2
    return bpm, intervals


class HeartStats:
    """Session statistics: now, average, lowest, highest and heart rate variability (RMSSD, last minute)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.beats: deque[tuple[float, int]] = deque(maxlen=7200)
        self.intervals: deque[tuple[float, float]] = deque(maxlen=600)

    def add(self, bpm: int, intervals: list[float]) -> None:
        now = self.clock()
        if 25 <= bpm <= 240:
            self.beats.append((now, bpm))
        for interval in intervals:
            if 0.25 <= interval <= 2.5:
                self.intervals.append((now, interval))

    def summary(self) -> dict[str, Any]:
        if not self.beats:
            return {}
        values = [bpm for _when, bpm in self.beats]
        recent = [interval for when, interval in self.intervals if self.clock() - when <= 60]
        differences = [(b - a) * 1000 for a, b in zip(recent, recent[1:])]
        rmssd = round(math.sqrt(sum(d * d for d in differences) / len(differences))) if len(differences) >= 5 else None
        return {"bpm": values[-1], "average": round(sum(values) / len(values)), "low": min(values), "high": max(values),
                "rmssd": rmssd, "minutes": round((self.beats[-1][0] - self.beats[0][0]) / 60, 1)}


def describe(summary: dict[str, Any], device: str) -> str:
    if not summary:
        return "No heart rate yet. The band may need a moment, or it is not sharing heart rate."
    text = (f"Heart rate from {device or 'the band'}: {summary['bpm']} bpm now; over the last {summary['minutes']} minutes "
            f"average {summary['average']}, lowest {summary['low']}, highest {summary['high']}.")
    if summary.get("rmssd") is not None:
        text += f" Heart rate variability (RMSSD, last minute): {summary['rmssd']} ms."
    return text + " (A consumer sensor, not medical advice.)"


class HeartRateMonitor:
    def __init__(self, on_reading: Callable[[dict[str, Any]], None], on_status: Callable[[str], None]) -> None:
        self.on_reading, self.on_status = on_reading, on_status
        self.stats = HeartStats()
        self.device = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        self._stop.clear()  # turned off and on within one scan: the running loop just carries on
        if self.running:
            return
        self.stats = HeartStats()
        self._thread = threading.Thread(target=lambda: asyncio.run(self._run()), name="AlfredHeartRate", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def summary_text(self) -> str:
        return describe(self.stats.summary(), self.device)

    async def _run(self) -> None:
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError:
            self.on_status("Bluetooth support is missing from this build.")
            return
        while not self._stop.is_set():
            self.on_status("Looking for a heart-rate band… (wear it, and on Garmin turn on Broadcast heart rate)")
            try:
                found = await BleakScanner.find_device_by_filter(
                    lambda _device, advertisement: HEART_RATE_SERVICE in [uuid.lower() for uuid in advertisement.service_uuids],
                    timeout=20)
            except Exception as exc:  # no Bluetooth adapter, Bluetooth off, ...
                self.on_status(f"Bluetooth is not available: {exc}")
                return
            if found is None:
                await asyncio.sleep(5)
                continue
            self.device = found.name or "heart-rate band"
            try:
                async with BleakClient(found) as client:
                    self.on_status(f"Connected to {self.device}")

                    def reading(_characteristic, data: bytearray) -> None:
                        bpm, intervals = parse_heart_rate(bytes(data))
                        self.stats.add(bpm, intervals)
                        self.on_reading({"device": self.device, **self.stats.summary()})

                    await client.start_notify(HEART_RATE_MEASUREMENT, reading)
                    while client.is_connected and not self._stop.is_set():
                        await asyncio.sleep(0.5)
            except Exception as exc:
                self.on_status(f"Lost {self.device}: {exc}. Reconnecting…")
                await asyncio.sleep(3)
        self.on_status("Heart rate off")
