"""What Nova needs from macOS, in one place: key state for the hotkeys (Quartz), the built-in voice (say), volume,
media and opening apps (AppleScript and open), memory and chip (sysctl), and a Keychain-held key for secrets.

Plain ctypes and the system's own commands: nothing extra to install. Windows code paths never import this module;
on the Mac they call it instead of user32, SAPI, winreg or DPAPI.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
import secrets
import subprocess
from pathlib import Path
from typing import Any, Callable

Runner = Callable[..., subprocess.CompletedProcess]

# Windows virtual-key codes (what Nova's settings store) → macOS key codes. Ctrl, Alt and Win are Control, Option
# and Command; each has a left and a right key.
KEYCODES: dict[int, tuple[int, ...]] = {
    0x10: (0x38, 0x3C), 0x11: (0x3B, 0x3E), 0x12: (0x3A, 0x3D), 0x5B: (0x37, 0x36), 0x5C: (0x36,),
    0x1B: (0x35,), 0x08: (0x33,), 0x09: (0x30,), 0x0D: (0x24, 0x4C), 0x20: (0x31,), 0x14: (0x39,),
    0x21: (0x74,), 0x22: (0x79,), 0x23: (0x77,), 0x24: (0x73,), 0x25: (0x7B,), 0x26: (0x7E,), 0x27: (0x7C,),
    0x28: (0x7D,), 0x2E: (0x75,), 0xC0: (0x32,), 0xBA: (0x29,), 0xBB: (0x18,), 0xBC: (0x2B,), 0xBD: (0x1B,),
    0xBE: (0x2F,), 0xBF: (0x2C,), 0xDB: (0x21,), 0xDC: (0x2A,), 0xDD: (0x1E,), 0xDE: (0x27,),
    **{0x70 + index: (code,) for index, code in enumerate(
        (0x7A, 0x78, 0x63, 0x76, 0x60, 0x61, 0x62, 0x64, 0x65, 0x6D, 0x67, 0x6F, 0x69, 0x6B, 0x71, 0x6A, 0x40, 0x4F,
         0x50, 0x5A))},
    **{ord(letter): (code,) for letter, code in zip(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        (0x00, 0x0B, 0x08, 0x02, 0x0E, 0x03, 0x05, 0x04, 0x22, 0x26, 0x28, 0x25, 0x2E, 0x2D, 0x1F, 0x23, 0x0C, 0x0F,
         0x01, 0x11, 0x20, 0x09, 0x0D, 0x07, 0x10, 0x06))},
    **{ord(digit): (code,) for digit, code in zip("0123456789", (0x1D, 0x12, 0x13, 0x14, 0x15, 0x17, 0x16, 0x1A, 0x1C, 0x19))},
}
KEY_NAMES = {0x11: "Control", 0x12: "Option", 0x5B: "Command", 0x5C: "Command", 0x08: "Delete", 0x0D: "Return"}
COMBINED_SESSION = 0  # kCGEventSourceStateCombinedSessionState
KEYCHAIN_SERVICE = "nova-personal-ai"  # no spaces: `security -i` gets it unquoted


class _Quartz:
    """CoreGraphics' key state (needs Input Monitoring for Nova in System Settings → Privacy & Security)."""

    def __init__(self) -> None:
        path = ctypes.util.find_library("ApplicationServices")
        self.library = ctypes.cdll.LoadLibrary(path) if path else None
        if self.library is not None:
            self.library.CGEventSourceKeyState.argtypes = [ctypes.c_int32, ctypes.c_uint16]
            self.library.CGEventSourceKeyState.restype = ctypes.c_bool

    def held(self, keycode: int) -> bool:
        return bool(self.library and self.library.CGEventSourceKeyState(COMBINED_SESSION, keycode))

    def may_listen(self, ask: bool) -> bool:
        """Whether Nova may read keys while another app is in front; ask=True shows macOS's own request."""
        if self.library is None:
            return False
        function = self.library.CGRequestListenEventAccess if ask else self.library.CGPreflightListenEventAccess
        function.restype = ctypes.c_bool
        return bool(function())


_quartz: _Quartz | None = None


def quartz() -> _Quartz:
    global _quartz
    if _quartz is None:
        _quartz = _Quartz()
    return _quartz


def key_held(virtual_key: int) -> bool:
    return any(quartz().held(code) for code in KEYCODES.get(virtual_key, ()))


# ---------- the system's own commands ----------

def osascript(script: str, run: Runner = subprocess.run) -> str:
    result = run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise OSError((result.stderr or "AppleScript failed").strip()[:200])
    return (result.stdout or "").strip()


def say(text: str, voice: str = "", rate: int = 0, popen: Callable[..., Any] = subprocess.Popen) -> Any:
    """Speaks with macOS's own voice (text through stdin, so nothing in it is read as an option)."""
    arguments = ["say"] + (["-v", voice] if voice else []) + (["-r", str(rate)] if rate else [])
    process = popen(arguments, stdin=subprocess.PIPE, text=True)
    process.stdin.write(text)
    process.stdin.close()
    return process


def voices(run: Runner = subprocess.run) -> list[str]:
    """English (and Vietnamese) voices installed on this Mac, by name."""
    result = run(["say", "-v", "?"], capture_output=True, text=True, timeout=10)
    found = []
    for line in (result.stdout or "").splitlines():
        match = re.match(r"^(.+?)\s{2,}(\w\w[_-]\w\w)", line)
        if match and match[2][:2] in ("en", "vi"):
            found.append(match[1].strip())
    return found


def volume(run: Runner = subprocess.run) -> int:
    return int(osascript("output volume of (get volume settings)", run) or 0)


def set_volume(percent: int, run: Runner = subprocess.run) -> None:
    osascript(f"set volume output volume {max(0, min(100, int(percent)))}", run)


def change_volume(action: str, times: int = 1, run: Runner = subprocess.run) -> None:
    """volume_up / volume_down move by 6% a step, like a key press; mute toggles."""
    if action == "mute":
        muted = osascript("output muted of (get volume settings)", run) == "true"
        osascript(f"set volume output muted {'false' if muted else 'true'}", run)
        return
    step = 6 * max(1, min(times, 16)) * (1 if action == "volume_up" else -1)
    set_volume(volume(run) + step, run)


PLAYERS = ("Spotify", "Music")
MEDIA_VERBS = {"play_pause": "playpause", "next": "next track", "previous": "previous track"}


def media(action: str, run: Runner = subprocess.run) -> str:
    """Play/pause, next or previous in the player that's running (Spotify first, then Apple Music)."""
    verb = MEDIA_VERBS[action]
    for player in PLAYERS:
        if osascript(f'application "{player}" is running', run) == "true":
            osascript(f'tell application "{player}" to {verb}', run)
            return player
    raise OSError("no music player is open (Spotify or Music)")


def now_playing(run: Runner = subprocess.run) -> dict[str, str] | None:
    for player in PLAYERS:
        try:
            if osascript(f'application "{player}" is running', run) != "true":
                continue
            text = osascript(f'tell application "{player}" to if player state is playing then '
                             'return (name of current track) & "\\n" & (artist of current track)', run)
        except OSError:
            continue
        if text:
            title, _, artist = text.partition("\n")
            return {"title": title, "artist": artist, "player": player}
    return None


def open_app(name: str, run: Runner = subprocess.run) -> None:
    result = run(["open", "-a", name], capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise OSError(f"there's no app called {name} on this Mac")


def open_path(target: str | Path, run: Runner = subprocess.run) -> None:
    run(["open", str(target)], capture_output=True, timeout=15)


def sysctl(name: str, run: Runner = subprocess.run) -> str:
    try:
        return (run(["sysctl", "-n", name], capture_output=True, text=True, timeout=5).stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def memory_gib(run: Runner = subprocess.run) -> tuple[float | None, float | None]:
    """(total, available) RAM. Available counts free, inactive and purgeable pages, as Activity Monitor does."""
    total = sysctl("hw.memsize", run)
    if not total.isdigit():
        return None, None
    total_gib = int(total) / 1024 ** 3
    try:
        stats = run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return round(total_gib, 1), None
    page = int(re.search(r"page size of (\d+)", stats)[1]) if re.search(r"page size of (\d+)", stats) else 16384
    pages = {key.strip(): int(value) for key, value in re.findall(r"^(Pages [\w ]+):\s+(\d+)\.", stats, re.MULTILINE)}
    free = sum(pages.get(key, 0) for key in ("Pages free", "Pages inactive", "Pages purgeable", "Pages speculative"))
    return round(total_gib, 1), round(free * page / 1024 ** 3, 1)


def gpu_share(total_gib: float) -> float:
    """How much of the unified memory macOS lets the GPU use (about 2/3, or 3/4 on Macs with more than 36 GB)."""
    return round(total_gib * (0.75 if total_gib > 36 else 0.66), 1)


def chip(run: Runner = subprocess.run) -> str:
    return sysctl("machdep.cpu.brand_string", run) or "Apple silicon"


def find_browser() -> Path | None:
    """A Chromium browser for Nova's own app window (no tabs or bars), if one is installed."""
    for app in ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium", "Arc"):
        for base in (Path("/Applications"), Path.home() / "Applications"):
            binary = base / f"{app}.app" / "Contents" / "MacOS" / app
            if binary.is_file():
                return binary
    return None


# ---------- secrets: AES-GCM with a key kept in the login Keychain ----------

def _security(commands: str, run: Runner = subprocess.run) -> subprocess.CompletedProcess:
    """`security -i` reads its commands from stdin, so the key never shows on a command line."""
    return run(["security", "-i"], input=commands + "\n", capture_output=True, text=True, timeout=15)


def keychain_key(account: str = "secrets", run: Runner = subprocess.run) -> bytes:
    """Nova's 32-byte secrets key for this Mac user, made once and kept in the login Keychain."""
    found = run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
                capture_output=True, text=True, timeout=15)
    if found.returncode == 0 and re.fullmatch(r"[0-9a-f]{64}", found.stdout.strip()):
        return bytes.fromhex(found.stdout.strip())
    key = secrets.token_bytes(32)
    made = _security(f"add-generic-password -U -s {KEYCHAIN_SERVICE} -a {account} -w {key.hex()}", run)
    if made.returncode != 0:
        raise OSError("Nova couldn't keep its key in your Keychain")
    return key


def protect(data: bytes, key: Callable[[], bytes] = keychain_key) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    return b"NOVA1" + nonce + AESGCM(key()).encrypt(nonce, data, None)


def unprotect(data: bytes, key: Callable[[], bytes] = keychain_key) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not data.startswith(b"NOVA1"):
        raise ValueError("not something Nova sealed on this Mac")
    return AESGCM(key()).decrypt(data[5:17], data[17:], None)


def tool_folders(home: Path | None = None) -> list[str]:
    """Where Homebrew, nvm, Volta and Claude Code's installer put commands. An app started from Finder doesn't get
    the shell's PATH, so Nova adds these (the newest Node from nvm first)."""
    home = home or Path.home()
    folders = [Path("/opt/homebrew/bin"), Path("/usr/local/bin"), home / ".local" / "bin", home / ".claude" / "local",
               home / ".volta" / "bin"]
    nvm = home / ".nvm" / "versions" / "node"
    if nvm.is_dir():
        def numbers(path: Path) -> tuple[int, ...]:
            return tuple(int(part) for part in re.findall(r"\d+", path.name)[:3])
        folders += [path / "bin" for path in sorted(nvm.iterdir(), key=numbers, reverse=True)]
    return [str(folder) for folder in folders if folder.is_dir()]


def cpu_ticks() -> tuple[float, float]:
    """(busy, total) CPU ticks since the Mac started, from the kernel's host statistics."""
    try:
        system = ctypes.CDLL("/usr/lib/libSystem.dylib")
        ticks, count = (ctypes.c_uint * 4)(), ctypes.c_uint(4)
        if system.host_statistics(system.mach_host_self(), 3, ticks, ctypes.byref(count)) != 0:  # HOST_CPU_LOAD_INFO
            return 0.0, 0.0
    except OSError:
        return 0.0, 0.0
    user, kernel, idle, nice = ticks
    return float(user + kernel + nice), float(user + kernel + nice + idle)


def type_text(text: str, run: Runner = subprocess.run) -> None:
    """Types into the app in front (System Events; needs Accessibility for Nova in Privacy & Security)."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    osascript(f'tell application "System Events" to keystroke "{escaped}"', run)
