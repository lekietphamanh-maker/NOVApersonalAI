"""Auto-tune: the strongest local model this PC runs smoothly, set up for it. It runs by itself after every update (and
when the PC's memory or graphics change), and from SETTINGS → This PC → Tune now.

1. Ollama's own settings for speed: flash attention, and a compact (8-bit) memory for what the model has read, which
   about doubles the context that fits in graphics memory. An AMD Radeon that Ollama leaves on the processor gets
   Vulkan. Ollama is restarted once when these change.
2. The biggest model the hardware should take (hardware_advisor), downloaded if missing, then measured for real: how
   much of it sits in graphics memory and how many tokens a second it writes. Too slow, or spilling out of graphics
   memory, and the next size down is measured instead.
3. The longest context that still keeps the whole model in graphics memory (32K, 16K, then 8K).

What it finds is kept in settings (model, context, speed, the version it was tuned for) and used from then on.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

from hardware_advisor import DESKTOP_MODELS, HardwareProfile, recommend_model

MIN_TOKENS_PER_SECOND = 12.0   # a sentence a second or so: speech never waits on the model
FULL_GPU = 0.97                # "all of it in graphics memory" (Ollama rounds)
CONTEXTS = (32768, 16384, 8192)
KEEP_LOADED = "2h"             # no reload pause between questions; Ollama still frees it after two quiet hours
SERVER_SETTINGS = {"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0"}
BENCH_PROMPT = "In three sentences, explain why the sky is blue."
SPARE_DISK_GB = 5


@dataclass
class Measure:
    model: str
    num_ctx: int
    tokens_per_second: float
    first_token_seconds: float
    on_gpu: float  # share of the loaded model in graphics memory, 0..1


@dataclass
class Tuning:
    model: str
    num_ctx: int
    keep_alive: str
    tokens_per_second: float
    first_token_seconds: float
    on_gpu: float
    reason: str
    version: str
    hardware: str
    tuned_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="minutes"))
    server: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        where = "all on the graphics card" if self.on_gpu >= FULL_GPU else (
            f"{round(self.on_gpu * 100)}% on the graphics card" if self.on_gpu > 0 else "on the processor")
        return (f"{self.model}, {where}, {self.tokens_per_second:.0f} tokens a second, first words in "
                f"{self.first_token_seconds:.1f} s, {self.num_ctx // 1024}K context")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def fingerprint(profile: HardwareProfile) -> str:
    """What the choice depends on: a new graphics card or more memory means tuning again."""
    gpus = ",".join(sorted(f"{gpu.get('name')}:{gpu.get('reported_vram_gib')}" for gpu in profile.gpus))
    return f"{profile.cpu}|{round(profile.total_ram_gib or 0)}GB|{gpus}"


def due(saved: dict[str, Any] | None, version: str, profile: HardwareProfile) -> bool:
    """Tune when it never ran, after an update, or when the hardware changed."""
    return not saved or saved.get("version") != version or saved.get("hardware") != fingerprint(profile)


def candidates(profile: HardwareProfile) -> list[tuple[str, float]]:
    """The recommended size first, then each smaller one (to fall back on)."""
    best, _size, _why = recommend_model(profile)
    names = [name for name, *_ in DESKTOP_MODELS]
    return [(name, size) for name, size, *_ in DESKTOP_MODELS[names.index(best):]]


def gpu_expected(profile: HardwareProfile) -> bool:
    best, *_ = recommend_model(profile)
    row = next(item for item in DESKTOP_MODELS if item[0] == best)
    vram = max((float(gpu.get("reported_vram_gib") or 0) for gpu in profile.gpus), default=0.0)
    return bool(row[2]) and vram >= row[2]


def good_enough(measure: Measure, wants_gpu: bool) -> bool:
    return measure.tokens_per_second >= MIN_TOKENS_PER_SECOND and (not wants_gpu or measure.on_gpu >= FULL_GPU)


class Ollama:
    """The few Ollama calls tuning needs (a class so tests can stand in for it)."""

    def __init__(self, base_url: str, opener: Callable[..., Any] = urlopen) -> None:
        self.base_url, self._open = base_url.rstrip("/"), opener

    def _json(self, path: str, body: dict | None = None, timeout: float = 600) -> dict[str, Any]:
        request = Request(f"{self.base_url}{path}", data=json.dumps(body).encode() if body is not None else None,
                          headers={"Content-Type": "application/json"})
        with self._open(request, timeout=timeout) as response:
            return json.loads(response.read() or b"{}")

    def installed(self) -> list[str]:
        return [str(item.get("name")) for item in self._json("/api/tags", timeout=15).get("models", [])]

    def unload(self, model: str) -> None:
        self._json("/api/generate", {"model": model, "keep_alive": 0}, timeout=60)

    def measure(self, model: str, num_ctx: int) -> Measure:
        """Loads the model with this context, has it write a little, and reads Ollama's own timings."""
        self.unload(model)  # a fresh load, so the context size really applies
        reply = self._json("/api/generate", {"model": model, "prompt": BENCH_PROMPT, "stream": False, "think": False,
                                             "keep_alive": "5m", "options": {"num_ctx": num_ctx, "num_predict": 96,
                                                                             "temperature": 0}})
        tokens, writing = int(reply.get("eval_count") or 0), int(reply.get("eval_duration") or 0) / 1e9
        reading = int(reply.get("prompt_eval_duration") or 0) / 1e9
        loaded = next((item for item in self._json("/api/ps", timeout=15).get("models", [])
                       if str(item.get("name")) == model), {})
        size, in_vram = int(loaded.get("size") or 0), int(loaded.get("size_vram") or 0)
        return Measure(model, num_ctx, round(tokens / writing, 1) if writing else 0.0,
                       round(reading + (writing / tokens if tokens else 0), 2), round(in_vram / size, 2) if size else 0.0)


def choose(ollama: Any, profile: HardwareProfile, pull: Callable[[str], None], disk_free_gb: float,
           progress: Callable[[str], None]) -> tuple[Measure, list[str]]:
    """The strongest model that runs smoothly here, with the longest context that keeps it on the graphics card."""
    wants_gpu = gpu_expected(profile)
    notes: list[str] = []
    installed = set(ollama.installed())
    fallback: Measure | None = None
    for name, size_gb in candidates(profile):
        if name not in installed:
            if disk_free_gb < size_gb + SPARE_DISK_GB:
                notes.append(f"{name} needs {size_gb:g} GB of disk; only {disk_free_gb:.0f} GB is free")
                continue
            progress(f"Downloading {name} ({size_gb:g} GB), the strongest model for this PC")
            pull(name)
            disk_free_gb -= size_gb
        best: Measure | None = None
        for num_ctx in CONTEXTS if wants_gpu else (8192,):
            progress(f"Measuring {name} with a {num_ctx // 1024}K context")
            measure = ollama.measure(name, num_ctx)
            if good_enough(measure, wants_gpu):
                best = measure
                break
            fallback = fallback if fallback and fallback.tokens_per_second >= measure.tokens_per_second else measure
        if best is not None:
            return best, notes
        notes.append(f"{name} was too slow here ({fallback.tokens_per_second:.0f} tokens a second)" if fallback else
                     f"{name} couldn't be measured")
    if fallback is None:
        raise RuntimeError("no model could be measured: is Ollama running?")
    return fallback, notes + ["kept the fastest one measured"]


# ---------- Ollama's own settings (environment variables), and restarting it ----------

def server_settings(profile: HardwareProfile, on_gpu: float | None) -> dict[str, str]:
    """Flash attention and the compact memory always; Vulkan for a Radeon that Ollama left on the processor."""
    wanted = dict(SERVER_SETTINGS)
    radeon = any("radeon" in str(gpu.get("name", "")).lower() for gpu in profile.gpus)
    if radeon and on_gpu is not None and on_gpu < 0.5:
        wanted["OLLAMA_VULKAN"] = "1"
    return wanted


def missing_settings(wanted: dict[str, str], environ: dict[str, str] | None = None) -> dict[str, str]:
    environ = os.environ if environ is None else environ
    return {name: value for name, value in wanted.items() if environ.get(name) != value}


def apply_settings(settings: dict[str, str], platform: str = sys.platform,
                   run: Callable[..., Any] = subprocess.run) -> None:
    """Saves them for this user (Windows: the user's environment; Mac: launchctl), so Ollama reads them on start."""
    for name, value in settings.items():
        os.environ[name] = value
    if platform == "win32":
        import ctypes
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
            for name, value in settings.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        result = ctypes.c_ulong()  # tell running programs (Explorer starts Ollama) that the environment changed
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 0x2, 3000, ctypes.byref(result))
    elif platform == "darwin":
        for name, value in settings.items():
            run(["launchctl", "setenv", name, value], capture_output=True, timeout=10)


def restart_ollama(base_url: str, platform: str = sys.platform, run: Callable[..., Any] = subprocess.run,
                   popen: Callable[..., Any] = subprocess.Popen, wait: Callable[[float], None] = time.sleep,
                   alive: Callable[[], bool] | None = None) -> bool:
    """Quits Ollama and starts it again so it reads its new settings. True when it answers again."""
    if alive is None:
        def alive() -> bool:
            try:
                with urlopen(f"{base_url.rstrip('/')}/api/version", timeout=3):
                    return True
            except OSError:
                return False
    if platform == "win32":
        flags = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
        for image in ("ollama app.exe", "ollama.exe"):
            run(["taskkill", "/f", "/im", image], capture_output=True, timeout=20, **flags)
        app = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama app.exe"
        if app.exists():
            popen([str(app)], **flags)
        else:
            popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)
    elif platform == "darwin":
        run(["osascript", "-e", 'quit app "Ollama"'], capture_output=True, timeout=20)
        wait(2)
        popen(["open", "-a", "Ollama"])
    else:
        return alive()
    for _ in range(40):
        wait(1)
        if alive():
            return True
    return False


def tune(ollama: Any, profile: HardwareProfile, version: str, pull: Callable[[str], None], disk_free_gb: float,
         restart: Callable[[dict[str, str]], bool], progress: Callable[[str], None] = lambda text: None,
         environ: dict[str, str] | None = None) -> Tuning:
    """The whole tune: Ollama's settings, then the model and its context, measured."""
    notes: list[str] = []
    server = server_settings(profile, None)
    if missing_settings(server, environ):
        progress("Turning on flash attention and compact memory in Ollama (restarts it once)")
        if not restart(missing_settings(server, environ)):
            notes.append("Ollama didn't come back after its restart; its new settings apply next time it starts")
    measure, more = choose(ollama, profile, pull, disk_free_gb, progress)
    notes += more
    vulkan = server_settings(profile, measure.on_gpu)
    if missing_settings(vulkan, environ):  # a Radeon left on the processor: Vulkan, then measure again
        progress("Your Radeon wasn't used: switching Ollama to Vulkan and measuring again")
        if restart(missing_settings(vulkan, environ)):
            measure, more = choose(ollama, profile, pull, disk_free_gb, progress)
            notes += more
        server = vulkan
    _best, _size, reason = recommend_model(profile)
    return Tuning(measure.model, measure.num_ctx, KEEP_LOADED, measure.tokens_per_second, measure.first_token_seconds,
                  measure.on_gpu, reason, version, fingerprint(profile), server=server, notes=notes)
