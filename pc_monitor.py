"""This PC's load and where the AI model really runs: CPU, RAM, GPU and graphics memory (Windows performance
counters), and Ollama's own report (/api/ps) of how much of each loaded model sits in graphics memory. Nothing here is
assumed: a GPU share is only shown when Ollama reports it.
"""
from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import time
from typing import Any

GIB = 1024 ** 3
COUNTERS = ("\\GPU Engine(*engtype_3D)\\Utilization Percentage", "\\GPU Adapter Memory(*)\\Dedicated Usage")
_POWERSHELL = ("(Get-Counter -Counter '{0}','{1}' -ErrorAction SilentlyContinue).CounterSamples | "
               "ForEach-Object {{ $_.Path + '|' + $_.CookedValue }}").format(*COUNTERS)


def ram() -> tuple[float, float]:
    """(used, total) GB."""
    if sys.platform == "win32":
        class Status(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("free", ctypes.c_ulonglong), ("page_total", ctypes.c_ulonglong), ("page_free", ctypes.c_ulonglong),
                        ("virtual_total", ctypes.c_ulonglong), ("virtual_free", ctypes.c_ulonglong),
                        ("extended", ctypes.c_ulonglong)]
        status = Status()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return (status.total - status.free) / GIB, status.total / GIB
        return 0.0, 0.0
    info = {}
    try:
        for line in open("/proc/meminfo", encoding="ascii"):
            name, value = line.split(":", 1)
            info[name] = int(value.split()[0]) * 1024
    except OSError:
        return 0.0, 0.0
    return (info.get("MemTotal", 0) - info.get("MemAvailable", 0)) / GIB, info.get("MemTotal", 0) / GIB


class CpuMeter:
    """CPU use since the last reading, in percent."""

    def __init__(self) -> None:
        self._last = self._times()

    @staticmethod
    def _times() -> tuple[float, float]:
        """(busy, total) time so far."""
        if sys.platform == "win32":
            idle, kernel, user = (ctypes.c_ulonglong() for _ in range(3))
            ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
            total = kernel.value + user.value  # kernel time includes idle time
            return total - idle.value, total
        try:
            fields = [int(value) for value in open("/proc/stat", encoding="ascii").readline().split()[1:]]
        except OSError:
            return 0.0, 0.0
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        return sum(fields) - idle, sum(fields)

    def percent(self) -> float:
        busy, total = self._times()
        last_busy, last_total = self._last
        self._last = (busy, total)
        return round(100 * (busy - last_busy) / (total - last_total), 1) if total > last_total else 0.0


def parse_counters(text: str) -> dict[str, float]:
    """Get-Counter samples ("path|value" lines) → the busiest graphics card's 3D use (%) and its memory in use (GB)."""
    engines: dict[str, float] = {}
    memory: dict[str, float] = {}
    for line in text.splitlines():
        path, _, value = line.rpartition("|")
        try:
            number = float(value.replace(",", "."))
        except ValueError:
            continue
        adapter = re.search(r"luid_(0x[0-9a-f]+_0x[0-9a-f]+)", path, re.IGNORECASE)
        key = adapter.group(1).lower() if adapter else "gpu"
        if "utilization percentage" in path.lower():
            engines[key] = engines.get(key, 0.0) + number
        elif "dedicated usage" in path.lower():
            memory[key] = memory.get(key, 0.0) + number
    if not engines and not memory:
        return {}
    busiest = max(memory, key=memory.get) if memory else max(engines, key=engines.get)
    return {"gpu": round(min(100.0, engines.get(busiest, max(engines.values(), default=0.0))), 1),
            "vram_gb": round(memory.get(busiest, 0.0) / GIB, 2)}


def gpu_counters(timeout: float = 8) -> dict[str, float]:
    """The graphics card's load from Windows performance counters ({} elsewhere or if they can't be read)."""
    if sys.platform != "win32":
        return {}
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _POWERSHELL],
                                capture_output=True, text=True, timeout=timeout, check=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_counters(result.stdout)


def placements(ps: dict[str, Any]) -> list[dict[str, Any]]:
    """Ollama's /api/ps: each loaded model, its size and how much of it is in graphics memory."""
    loaded = []
    for model in (ps or {}).get("models") or []:
        size, in_vram = float(model.get("size") or 0), float(model.get("size_vram") or 0)
        share = round(100 * in_vram / size) if size else 0
        loaded.append({"name": model.get("name") or model.get("model", "?"), "size_gb": round(size / GIB, 1),
                       "vram_gb": round(in_vram / GIB, 1), "gpu_percent": share,
                       "where": "GPU" if share >= 99 else "CPU" if share <= 0 else f"{share}% GPU / {100 - share}% CPU",
                       "context": model.get("context_length")})
    return loaded


def gpu_tip(gpu_names: str, loaded: list[dict[str, Any]]) -> str:
    """Advice when the model runs on the processor although the PC has an AMD Radeon card."""
    if not loaded or not re.search(r"radeon|amd", gpu_names, re.IGNORECASE):
        return ""
    if all(model["gpu_percent"] >= 99 for model in loaded):
        return ""
    on_cpu = any(model["gpu_percent"] <= 0 for model in loaded)
    lines = ["The model runs " + ("on the processor" if on_cpu else "partly on the processor") + ", so answers are slower."]
    if re.search(r"6600|6650|gfx1032", gpu_names, re.IGNORECASE):
        lines.append("Ollama's AMD (ROCm) support on Windows doesn't include the RX 6600 / 6600 XT (gfx1032), so "
                     "Ollama uses Vulkan for it instead.")
    lines.append("Update Ollama to the newest version (Vulkan is on by default there). With an older Ollama, set the "
                 "user environment variable OLLAMA_VULKAN=1 and restart Ollama. Then load the model again and check this "
                 "line. If it still says processor: a smaller model (qwen3:4b, gemma3:4b) fits in 8 GB, and Ollama's "
                 "server log names the GPU it found.")
    if not on_cpu:
        lines.append("Part of the model is in the processor's memory because it doesn't fit in graphics memory with "
                     "this context; a smaller model or shorter context fits whole.")
    return " ".join(lines)
