"""Hardware-aware local model choice for both editions.

Desktop: recommend a Qwen3 size from RAM and graphics memory (recommend_model / choose_model).
USB: pick the largest installed model that fits (pick_best). Detection never downloads anything;
pull_model runs only after the user approves. A listed GPU is not proof Ollama uses it.
"""
from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import subprocess
from dataclasses import dataclass, asdict
from typing import Any, Callable
from urllib.request import Request, urlopen

try:
    import winreg
except ImportError:  # unit tests on other systems
    winreg = None

GIB = 1024 ** 3
# Small, explicit catalogue of tested-or-known Ollama options; only Qwen3:8b
# was smoke-tested in this project. No arbitrary model names are pulled.
UPGRADE_CATALOG = {
    "qwen3:8b": {"bytes": 5_600_000_000, "parameters": 8.2, "quality": 8,
                 "note": "Qwen3 8B Q4_K_M; smoke-tested here, size is approximate."},
}


@dataclass
class HardwareProfile:
    os: str
    architecture: str
    cpu: str
    total_ram_gib: float | None
    available_ram_gib: float | None
    gpus: list[dict[str, Any]]
    acceleration_status: str
    notes: list[str]

    def serializable(self) -> dict[str, Any]:
        return asdict(self)


def _ram() -> tuple[float | None, float | None]:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    try:
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return round(status.ullTotalPhys / GIB, 1), round(status.ullAvailPhys / GIB, 1)
    except (AttributeError, OSError):
        pass
    return None, None


def _cpu_name() -> str:
    try:
        if winreg is None:
            raise OSError
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except (OSError, AttributeError):
        return platform.processor() or platform.machine() or "CPU name unavailable"


# Each display adapter's driver key; qwMemorySize holds the real VRAM (WMI's AdapterRAM stops at 4 GB).
_DISPLAY_ADAPTERS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"


def _registry_gpus() -> list[dict[str, Any]]:
    adapters = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _DISPLAY_ADAPTERS) as adapter_class:
            for index in range(winreg.QueryInfoKey(adapter_class)[0]):
                subkey = winreg.EnumKey(adapter_class, index)
                if not subkey.isdigit():
                    continue
                try:
                    with winreg.OpenKey(adapter_class, subkey) as key:
                        name = str(winreg.QueryValueEx(key, "DriverDesc")[0])
                        vram = None
                        for value_name in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
                            try:
                                raw = winreg.QueryValueEx(key, value_name)[0]
                            except OSError:
                                continue
                            if isinstance(raw, bytes):
                                raw = int.from_bytes(raw[:8], "little")
                            if isinstance(raw, int) and raw > 0:
                                vram = round(raw / GIB, 1)
                                break
                        try:
                            driver = str(winreg.QueryValueEx(key, "DriverVersion")[0])
                        except OSError:
                            driver = "Unknown"
                except OSError:
                    continue
                if "basic display" not in name.casefold() and "basic render" not in name.casefold():
                    adapters.append({"name": name, "reported_vram_gib": vram, "driver_version": driver})
    except (OSError, AttributeError):
        return []
    return adapters


def _gpus() -> list[dict[str, Any]]:
    """Display adapters from the registry (fast, real VRAM), else from WMI (AdapterRAM can be capped)."""
    adapters = _registry_gpus()
    if adapters:
        return adapters
    script = (
        "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion "
        "| ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, timeout=8,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
        if result.returncode == 0 and result.stdout.strip():
            raw = json.loads(result.stdout)
            if isinstance(raw, dict):
                raw = [raw]
            adapters = []
            for item in raw if isinstance(raw, list) else []:
                if not isinstance(item, dict):
                    continue
                amount = item.get("AdapterRAM")
                # WMI uses a 32-bit value; treat very small values as a lower bound.
                vram = round(int(amount) / GIB, 1) if str(amount or "").isdigit() and int(amount) > 0 else None
                adapters.append({"name": str(item.get("Name") or "Unknown adapter"),
                                 "reported_vram_gib": vram,
                                 "driver_version": str(item.get("DriverVersion") or "Unknown")})
            if adapters:
                return adapters
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return []


def detect_hardware(ollama_ps: dict[str, Any] | None = None) -> HardwareProfile:
    total, available = _ram()
    gpus = _gpus()
    acceleration = "not confirmed yet; check Ollama placement after a reply"
    if ollama_ps and isinstance(ollama_ps.get("models"), list):
        placements = []
        for model in ollama_ps["models"]:
            value = str(model.get("size_vram", 0)) if isinstance(model, dict) else "0"
            try:
                if int(value) > 0:
                    placements.append("GPU/VRAM used")
                else:
                    placements.append("CPU/no VRAM reported")
            except ValueError:
                pass
        if placements:
            acceleration = "; ".join(placements)
    notes = []
    if gpus:
        notes.append("WMI VRAM can be incomplete; GPU acceleration is not guaranteed by detection.")
    else:
        notes.append("No display adapter details returned; CPU inference may still work.")
    return HardwareProfile(platform.platform(), platform.machine(), _cpu_name(), total, available,
                           gpus, acceleration, notes)


def model_info(item: dict[str, Any]) -> dict[str, Any]:
    details = item.get("details") or {}
    size = int(item.get("size") or 0)
    param_text = str(details.get("parameter_size") or "")
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*B", param_text, re.I)
    params = float(match.group(1)) if match else 0.0
    return {"name": str(item.get("name", "")), "size_bytes": size,
            "size_gib": round(size / GIB, 2), "parameters_b": params,
            "quantization": str(details.get("quantization_level") or "unknown"),
            "family": str(details.get("family") or "unknown")}


def select_practical_model(models: list[dict[str, Any]], profile: HardwareProfile,
                           reserve_gib: float | None = None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Pick the largest installed model fitting a conservative current-RAM budget.

    The 1.30 multiplier reserves KV/context/runtime overhead; the OS reserve is
    at least 3 GiB or 20% of physical memory, capped at 6 GiB. If none fits, the
    smallest installed model is still selected as an Ollama CPU/offload fallback
    and the caller should display the warning.
    """
    total = profile.total_ram_gib or 8.0
    available = profile.available_ram_gib or total
    reserve = reserve_gib if reserve_gib is not None else max(3.0, min(6.0, total * .20))
    budget = max(0.0, min(available, total - reserve) - reserve)
    ranked = [model_info(item) for item in models if isinstance(item, dict) and item.get("name")]
    ranked.sort(key=lambda item: (item["parameters_b"], item["size_bytes"]), reverse=True)
    for model in ranked:
        model["fits_ram_budget"] = bool(model["size_gib"] > 0 and model["size_gib"] * 1.30 <= budget)
    eligible = [model for model in ranked if model["fits_ram_budget"]]
    if eligible:
        return eligible[0], ranked
    return (ranked[-1] if ranked else None), ranked


def upgrade_offer(selected: dict[str, Any] | None, installed_names: set[str],
                  profile: HardwareProfile, free_disk_gib: float | None = None) -> dict[str, Any] | None:
    """Return a known model offer only when it is stronger and conservatively fits."""
    if not selected:
        current_parameters = 0.0
        current_name = ""
    else:
        current_parameters = float(selected.get("parameters_b") or 0)
        current_name = str(selected.get("name") or "")
    total = profile.total_ram_gib or 8.0
    available = profile.available_ram_gib or total
    reserve = max(3.0, min(6.0, total * .20))
    budget_gib = max(0.0, min(available, total - reserve) - reserve)
    for name, item in UPGRADE_CATALOG.items():
        params = float(item["parameters"])
        size_gib = item["bytes"] / GIB
        if name in installed_names or params <= current_parameters or params <= 0:
            continue
        if size_gib * 1.30 > budget_gib:
            continue
        if free_disk_gib is not None and free_disk_gib < size_gib * 1.10:
            continue
        return {"name": name, "size_bytes": item["bytes"], "size_gib": round(size_gib, 2),
                "parameters_b": params, "note": item["note"], "selected_name": current_name}
    return None


def pick_best(tags_response: dict[str, Any], profile: HardwareProfile) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    models = tags_response.get("models", []) if isinstance(tags_response, dict) else []
    return select_practical_model(models if isinstance(models, list) else [], profile)


# Desktop Edition sizes, best first: (model, download GB, graphics memory that runs it on the GPU,
# RAM that runs it acceptably on the CPU alone, or None when it is too slow without a GPU).
DESKTOP_MODELS: tuple[tuple[str, float, float, float | None], ...] = (
    ("qwen3:14b", 9.3, 12, None),
    ("qwen3:8b", 5.2, 6, 32),
    ("qwen3:4b", 2.5, 3, 12),
    ("qwen3:1.7b", 1.4, 0, 0),
)


@dataclass
class ModelChoice:
    model: str        # what Nova uses now
    recommended: str  # what suits this PC
    reason: str
    missing: bool     # the recommended model still needs a download (offered, never automatic)
    size_gb: float
    stronger: bool = True  # the recommended model is bigger than the one in use (else it is faster)


def graphics_memory_gib(profile: HardwareProfile) -> float:
    return max((float(gpu.get("reported_vram_gib") or 0) for gpu in profile.gpus), default=0.0)


def recommend_model(profile: HardwareProfile) -> tuple[str, float, str]:
    """The biggest Qwen3 that runs smoothly here: on the graphics card if it fits, else on the CPU."""
    ram = profile.total_ram_gib or 8.0
    vram = graphics_memory_gib(profile)
    for name, size_gb, gpu_gib, cpu_ram_gib in DESKTOP_MODELS:
        if gpu_gib and vram >= gpu_gib and ram >= 8:
            return name, size_gb, f"{vram:g} GB graphics card, {ram:g} GB RAM"
        if cpu_ram_gib is not None and ram >= cpu_ram_gib:
            return name, size_gb, f"{ram:g} GB RAM" + (f", {vram:g} GB graphics" if vram else ", no graphics card")
    name, size_gb, *_ = DESKTOP_MODELS[-1]
    return name, size_gb, "small PC"


def choose_model(setting: str | None, installed: list[str], profile: HardwareProfile) -> ModelChoice:
    """'auto' (default) uses the recommended model, or until it is downloaded the closest installed one."""
    recommended, size_gb, reason = recommend_model(profile)
    if setting and setting != "auto":
        return ModelChoice(setting, recommended, "chosen in settings", False, size_gb)
    if recommended in installed:
        return ModelChoice(recommended, recommended, reason, False, size_gb)
    order = [name for name, *_ in DESKTOP_MODELS]
    smaller_first = order[order.index(recommended):] + order[:order.index(recommended)][::-1]
    fallback = next((name for name in smaller_first if name in installed), None)
    model = fallback or (installed[0] if installed else recommended)
    stronger = model not in order or order.index(recommended) < order.index(model)
    return ModelChoice(model, recommended, reason, True, size_gb, stronger)


_TRANSIENT = ("502", "503", "504", "timeout", "timed out", "reset", "eof", "connection")


def pull_model(base_url: str, name: str, progress: Callable[[str], None], attempts: int = 3) -> None:
    """Download a model through Ollama's own API (works for the Desktop and the USB server). The model server
    sometimes drops out for a moment: retry, and Ollama carries on from what it already has."""
    import time
    for attempt in range(1, attempts + 1):
        try:
            _pull_once(base_url, name, progress)
            return
        except (OSError, RuntimeError) as exc:
            if attempt == attempts or not any(word in str(exc).lower() for word in _TRANSIENT):
                raise
            progress(f"{name} · the download server didn't answer; trying again ({attempt + 1}/{attempts})")
            time.sleep(5 * attempt)


def _pull_once(base_url: str, name: str, progress: Callable[[str], None]) -> None:
    request = Request(f"{base_url}/api/pull", data=json.dumps({"model": name, "stream": True}).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
    last = ""
    with urlopen(request, timeout=120) as response:
        for line in response:
            if not line.strip():
                continue
            update = json.loads(line)
            if update.get("error"):
                raise RuntimeError(str(update["error"]))
            total, done = update.get("total"), update.get("completed")
            text = f"Downloading {name} · {done * 100 // total}%" if total and done else f"{name} · {update.get('status', '')}"
            if text != last:
                progress(text)
                last = text
    if last.rsplit("· ", 1)[-1] != "success":
        raise RuntimeError("the download stopped before Ollama reported success")
