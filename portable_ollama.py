"""Optional USB-edition Ollama child process, isolated to its relative model store."""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


def start_if_configured() -> subprocess.Popen | None:
    if os.environ.get("ALFRED_PORTABLE_OLLAMA") != "1":
        return None
    api_url = os.environ.get("ALFRED_API_URL", "http://127.0.0.1:11435").rstrip("/")
    try:
        with urlopen(api_url + "/api/version", timeout=1):
            raise RuntimeError("Port 11435 is already in use. Close the other service before starting USB Nova; Nova will not attach to an unverified model store.")
    except RuntimeError:
        raise
    except Exception:
        pass
    executable = Path(os.environ.get("ALFRED_OLLAMA_EXE", ""))
    models = Path(os.environ.get("OLLAMA_MODELS", ""))
    if not executable.is_file() or not models.is_dir():
        raise RuntimeError("Portable Ollama runtime or model store is missing from this USB folder.")
    child_env = os.environ.copy()
    # Only bind this app's own server to loopback; never expose it on the LAN.
    child_env["OLLAMA_HOST"] = "127.0.0.1:11435"
    child_env["OLLAMA_MODELS"] = str(models.resolve())
    child_env["OLLAMA_NO_CLOUD"] = "1"
    child_env["OLLAMA_KEEP_ALIVE"] = "5m"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen([str(executable), "serve"], cwd=str(executable.parent), env=child_env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=flags)
    deadline = time.monotonic() + 45
    last_error = "local service did not respond"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("The USB Ollama runtime exited during startup. Check that this is a 64-bit Windows PC and that the USB drive is writable.")
        try:
            with urlopen(api_url + "/api/version", timeout=2):
                return process
        except (URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
            time.sleep(0.5)
    process.terminate()
    try:
        process.wait(timeout=4)
    except subprocess.TimeoutExpired:
        process.kill()
    raise RuntimeError(f"USB Ollama did not become ready in time ({last_error}).")


def stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)
