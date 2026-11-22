"""Network lab: a JARVIS-style network panel for the home — speed, status, devices, history and alerts,
in one place, so Nova's owner never has to open a speed-test site or a router page to answer "how fast is my
internet?" or "who's on my Wi-Fi?".

Everything here is measured on this PC, with free local tools and no account, key or cloud: ping and arp and
ipconfig/netsh (Windows, with a plain-socket fallback elsewhere), and Cloudflare's public speed-test endpoints
(speed.cloudflare.com/__down and __up — free, no key, made for exactly this). No number is ever made up: a
measurement that fails comes back as a plain sentence saying what failed, and the UI shows "unreachable" rather
than a guessed value. When the PC is offline, every card says so and nothing pretends otherwise.

History lives in one JSON file under the data dir (the last 50 speed tests) and known devices in another, so
Nova can say when today's speed is well below usual, or when a device that was here last time has gone quiet.
Nothing leaves the PC: the only network calls are the measurements themselves (ping, the speed-test download
and upload, and a public-IP lookup), and no device list or speed history is ever sent anywhere.
"""
from __future__ import annotations

import json
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

TIMEOUT_SECONDS = 15
PING_TIMEOUT_MS = 1000
SPEED_DOWN_BYTES = 25_000_000   # 25 MB from Cloudflare: big enough to measure, small enough to be quick
SPEED_UP_BYTES = 10_000_000     # 10 MB up
HISTORY_MAX = 50
SWEEP_WORKERS = 32
SWEEP_PING_TIMEOUT_MS = 200
SWEEP_TIMEOUT_SECONDS = 5
USER_AGENT = "Nova-Network-Lab/1.0 (personal use; local measurements only)"
DOWN_URL = "https://speed.cloudflare.com/__down?bytes=%d"
UP_URL = "https://speed.cloudflare.com/__up"
PUBLIC_IP_URL = "https://api.ipify.org"
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_MAC = re.compile(r"(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}")
_PING_MS = re.compile(r"time[=<]\s*(\d+(?:\.\d+)?)\s*ms", re.IGNORECASE)


def _default_runner(cmd: list[str]) -> str:
    """One local command, its stdout as text. Raises on failure or timeout; callers turn that into words."""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise RuntimeError(f"command {cmd[0]} exited {result.returncode}")
    return result.stdout


def _default_fetch(url: str, data: bytes | None = None) -> bytes:
    """One public GET (or POST when data is given), the raw bytes back. Raises on any network failure."""
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT},
                                     method="POST" if data is not None else "GET")
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def _short_error(error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        return f"HTTP {error.code} from the test server"
    if isinstance(error, (TimeoutError, urllib.error.URLError)):
        return "the request timed out or the network is down"
    return " ".join(str(error).split())[:100] or "an unknown error"


def mbps(byte_count: int, seconds: float) -> float | None:
    """Bits per second, in megabits — or None when the timing is unusable (never a fake number)."""
    if seconds <= 0 or byte_count < 0:
        return None
    return byte_count * 8 / seconds / 1_000_000


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def parse_ping(output: str) -> float | None:
    """The reply time in ms from ping output (Windows `time=12ms` and `time<1ms`, Unix `time=12.3 ms`),
    or None when the host didn't answer."""
    match = _PING_MS.search(output or "")
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def parse_ipconfig(output: str) -> dict[str, Any]:
    """The local network from `ipconfig` output: IPv4 address, subnet mask, gateway and DNS servers.
    Missing fields stay "" — never guessed."""
    info: dict[str, Any] = {"ipv4": "", "mask": "", "gateway": "", "dns": []}
    current: str | None = None
    for raw in (output or "").splitlines():
        line = raw.strip()
        lowered = line.lower()
        if "ipv4 address" in lowered or "ipv4-address" in lowered:
            found = _IP.search(line)
            info["ipv4"] = found.group(0) if found else ""
            current = None
        elif "subnet mask" in lowered:
            found = _IP.search(line)
            info["mask"] = found.group(0) if found else ""
            current = None
        elif "default gateway" in lowered:
            found = _IP.search(line)
            info["gateway"] = found.group(0) if found else ""
            current = None
        elif "dns servers" in lowered:
            found = _IP.search(line)
            if found:
                info["dns"].append(found.group(0))
            current = "dns"
        elif current == "dns" and _IP.search(line):
            info["dns"].append(_IP.search(line).group(0))  # type: ignore[union-attr]
        elif line and ":" not in line:
            current = None
    return info


def parse_netsh_wlan(output: str) -> dict[str, str]:
    """The Wi-Fi name and signal from `netsh wlan show interfaces`: SSID and signal %, or "" when not on Wi-Fi."""
    info = {"ssid": "", "signal": ""}
    for raw in (output or "").splitlines():
        line = raw.strip()
        lowered = line.lower()
        if lowered.startswith("ssid") and ":" in line:
            info["ssid"] = line.split(":", 1)[1].strip()
        elif lowered.startswith("signal") and ":" in line:
            info["signal"] = line.split(":", 1)[1].strip()
    return info


def parse_arp(output: str) -> list[dict[str, str]]:
    """Devices from `arp -a` output: one {ip, mac} per line that has both. The interface header lines have
    neither, so they are skipped on their own."""
    devices: list[dict[str, str]] = []
    for raw in (output or "").splitlines():
        ip = _IP.search(raw)
        mac = _MAC.search(raw)
        if ip and mac:
            devices.append({"ip": ip.group(0), "mac": mac.group(0).lower().replace("-", ":")})
    return devices


def _is_private(ip: str) -> bool:
    return (ip.startswith("10.") or ip.startswith("192.168.")
            or bool(re.match(r"172\.(1[6-9]|2\d|3[01])\.", ip)))


def network_prefix(ipv4: str, mask: str) -> str | None:
    """The /24 prefix to sweep (e.g. 192.168.1.) from an address and mask, or None when it isn't a /24."""
    if mask != "255.255.255.0":
        return None
    parts = ipv4.split(".")
    if len(parts) != 4 or not all(part.isdigit() for part in parts):
        return None
    return ".".join(parts[:3]) + "."


def speed_alert(history: list[dict[str, Any]], latest_down: float | None) -> str:
    """"Much slower than usual" when the latest download is under half the median of the tests before it.
    Needs at least 3 earlier tests, so one slow day never cries wolf on its own."""
    if latest_down is None:
        return ""
    earlier = [float(entry["down_mbps"]) for entry in history[:-1]
               if isinstance(entry.get("down_mbps"), (int, float)) and entry["down_mbps"] > 0]
    if len(earlier) < 3:
        return ""
    usual = _median(earlier)
    if usual is None or usual <= 0 or latest_down >= 0.5 * usual:
        return ""
    return (f"Speed alert: {latest_down:.0f} Mbps is well below your usual {usual:.0f} Mbps "
            f"(median of your last {len(earlier)} tests).")


def missing_devices(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Devices that were on the network last scan but aren't now — off, asleep, or gone. Matches by MAC."""
    now = {device["mac"] for device in current if device.get("mac")}
    return [device for device in previous if device.get("mac") and device["mac"] not in now]


class NetworkPanel:
    """One lab's worth of home networking: `act(action, arguments)` answers the Network tab's cards, and
    `answer` says the same thing as plain text for Nova to speak. It measures, it never invents: every
    failure is a sentence, and the history file is the only memory it keeps."""

    def __init__(self, data_dir: str | Path | None = None,
                 runner: Callable[[list[str]], str] | None = None,
                 fetcher: Callable[..., bytes] | None = None,
                 clock: Callable[[], float] | None = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else Path.cwd() / ".network"
        self._run = runner or _default_runner
        self._fetch = fetcher or _default_fetch
        self._clock = clock or time.monotonic

    # ---------- storage (one JSON file each, capped, never a crash) ----------

    def _load_json(self, name: str) -> list[dict[str, Any]]:
        try:
            data = json.loads((self._data_dir / name).read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _save_json(self, name: str, rows: list[dict[str, Any]]) -> None:
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            (self._data_dir / name).write_text(json.dumps(rows, indent=1), encoding="utf-8")
        except OSError:
            pass  # history is a bonus; a failed save must never break a measurement

    @property
    def history(self) -> list[dict[str, Any]]:
        return self._load_json("network_history.json")

    @property
    def known_devices(self) -> list[dict[str, Any]]:
        return self._load_json("network_devices.json")

    def _record_test(self, entry: dict[str, Any]) -> None:
        rows = self.history + [entry]
        self._save_json("network_history.json", rows[-HISTORY_MAX:])

    def _record_devices(self, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Fold this scan into the known-devices file (first seen kept, last seen refreshed) and return
        the devices that were known before but are missing now."""
        known = self.known_devices
        by_mac = {device["mac"]: device for device in known if device.get("mac")}
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        missing = missing_devices(known, devices)
        for device in devices:
            mac = device.get("mac")
            if not mac:
                continue
            if mac in by_mac:
                by_mac[mac]["last_seen"] = now
                by_mac[mac]["ip"] = device.get("ip", by_mac[mac].get("ip", ""))
            else:
                by_mac[mac] = {"mac": mac, "ip": device.get("ip", ""), "first_seen": now, "last_seen": now}
        self._save_json("network_devices.json", list(by_mac.values()))
        self._save_json("network_last_missing.json", missing)
        return missing

    # ---------- measurements ----------

    def _ping(self, host: str, timeout_ms: int = PING_TIMEOUT_MS) -> float | None:
        import sys
        cmd = (["ping", "-n", "1", "-w", str(timeout_ms), host] if sys.platform == "win32"
               else ["ping", "-c", "1", "-W", str(max(1, timeout_ms // 1000)), host])
        try:
            return parse_ping(self._run(cmd))
        except Exception:  # noqa: BLE001 - an unanswered ping is a missing number, never a crash
            return None

    def _local_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {"ipv4": "", "mask": "", "gateway": "", "dns": [], "ssid": "", "signal": ""}
        try:
            info.update(parse_ipconfig(self._run(["ipconfig"])))
        except Exception:  # noqa: BLE001 - ipconfig may not exist; the socket fallback below still answers
            pass
        if not info["ipv4"]:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                    probe.connect(("8.8.8.8", 80))
                    info["ipv4"] = probe.getsockname()[0]
            except OSError:
                pass
        try:
            info.update(parse_netsh_wlan(self._run(["netsh", "wlan", "show", "interfaces"])))
        except Exception:  # noqa: BLE001 - not on Wi-Fi, or netsh isn't here; the rest still stands
            pass
        return info

    def _public_ip(self) -> str:
        try:
            return self._fetch(PUBLIC_IP_URL).decode("utf-8", "replace").strip()
        except Exception:  # noqa: BLE001 - the public IP is a bonus line; its failure is silence
            return ""

    def _speed_test(self) -> tuple[dict[str, Any] | None, str]:
        """A real download and upload against Cloudflare's speed-test endpoints, timed with the clock.
        Returns the numbers, or None and the plain reason it couldn't be measured."""
        try:
            start = self._clock()
            payload = self._fetch(DOWN_URL % SPEED_DOWN_BYTES)
            down = mbps(len(payload), self._clock() - start)
            start = self._clock()
            self._fetch(UP_URL, data=b"0" * SPEED_UP_BYTES)
            up = mbps(SPEED_UP_BYTES, self._clock() - start)
        except Exception as error:  # noqa: BLE001 - any network failure is a sentence for the UI
            return None, (f"Couldn't run the speed test ({_short_error(error)}). "
                          "Check Nova is online and try again.")
        if down is None or up is None:
            return None, "The speed test ran but the timing came back unusable — try again."
        entry = {"time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                 "down_mbps": round(down, 1), "up_mbps": round(up, 1)}
        ping = self._ping("1.1.1.1")
        if ping is not None:
            entry["ping_ms"] = round(ping, 1)
        self._record_test(entry)
        return entry, ""

    def _scan_devices(self) -> tuple[list[dict[str, str]] | None, str, list[dict[str, Any]]]:
        """A sweep of the local /24 (ping each address, then read the ARP table for MACs). Returns the
        devices, or None and the reason, plus the devices missing since the last scan."""
        info = self._local_info()
        prefix = network_prefix(info.get("ipv4", ""), info.get("mask", ""))
        if prefix is None:
            return None, ("Couldn't work out your local network — the address or subnet mask is missing. "
                          "Check Nova is on Wi-Fi or Ethernet and try again."), []
        found: list[str] = []
        lock = threading.Lock()

        def probe(host: str) -> None:
            if self._ping(host, SWEEP_PING_TIMEOUT_MS) is not None:
                with lock:
                    found.append(host)

        threads = [threading.Thread(target=probe, args=(f"{prefix}{n}",), daemon=True)
                   for n in range(1, 255) if f"{prefix}{n}" != info.get("ipv4")]
        # Run in waves so 254 threads never pile up at once.
        for start in range(0, len(threads), SWEEP_WORKERS):
            wave = threads[start:start + SWEEP_WORKERS]
            for thread in wave:
                thread.start()
            for thread in wave:
                thread.join(timeout=SWEEP_TIMEOUT_SECONDS)
        try:
            devices = parse_arp(self._run(["arp", "-a"]))
        except Exception:  # noqa: BLE001 - no ARP table, no MACs; the ping answers still count
            devices = [{"ip": host, "mac": ""} for host in found]
        seen = {device["ip"] for device in devices}
        for host in found:
            if host not in seen:
                devices.append({"ip": host, "mac": ""})
        devices = [device for device in devices if _is_private(device["ip"])]
        devices.sort(key=lambda device: [int(part) for part in device["ip"].split(".")])
        missing = self._record_devices(devices)
        return devices, "", missing

    # ---------- the cards ----------

    def _act_status(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        info = self._local_info()
        gateway_ping = self._ping(info["gateway"]) if info.get("gateway") else None
        internet_ping = self._ping("1.1.1.1")
        public_ip = self._public_ip()
        lines: list[str] = []
        if info.get("ssid"):
            lines.append(f"Wi-Fi: {info['ssid']}" + (f" — signal {info['signal']}" if info.get("signal") else "") + ".")
        elif info.get("ipv4"):
            lines.append("Wired (Ethernet) — no Wi-Fi in use.")
        else:
            lines.append("Not connected to a local network right now.")
        if info.get("ipv4"):
            lines.append(f"This PC: {info['ipv4']}" + (f" (mask {info['mask']})" if info.get("mask") else "") + ".")
        if info.get("gateway"):
            lines.append(f"Router (gateway): {info['gateway']}" + (f" — answers in {gateway_ping:.0f} ms" if gateway_ping is not None else " — not answering pings right now") + ".")
        if info.get("dns"):
            lines.append("DNS: " + ", ".join(info["dns"]) + ".")
        if public_ip:
            lines.append(f"Public IP (what the internet sees): {public_ip}.")
        if internet_ping is not None:
            lines.append(f"Internet latency: {internet_ping:.0f} ms to 1.1.1.1.")
        elif info.get("ipv4"):
            lines.append("Internet latency: unreachable — the internet isn't answering right now.")
        return {"ok": True, "title": "Network status", "lines": lines}

    def _act_speed(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        result, problem = self._speed_test()
        if result is None:
            return {"ok": False, "error": problem}
        lines = [f"Download {result['down_mbps']:.1f} Mbps · upload {result['up_mbps']:.1f} Mbps"
                 + (f" · ping {result['ping_ms']:.0f} ms" if result.get("ping_ms") is not None else "") + ".",
                 "Measured just now against Cloudflare's speed-test server — a real download and upload, not an estimate."]
        alert = speed_alert(self.history, result["down_mbps"])
        if alert:
            lines.append(alert)
        return {"ok": True, "title": "Speed test", "lines": lines, "result": result,
                "history": self.history}

    def _act_devices(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        devices, problem, missing = self._scan_devices()
        if devices is None:
            return {"ok": False, "error": problem}
        lines = [f"{len(devices)} device{'s' if len(devices) != 1 else ''} on your network right now (this scan)."]
        for device in devices:
            lines.append(f"{device['ip']}" + (f" — {device['mac']}" if device.get("mac") else " — no MAC in the table") + ".")
        if missing:
            lines.append("Not seen this time (were here last scan): " +
                         ", ".join(device.get("ip", device["mac"]) for device in missing) +
                         ". They may just be off or asleep.")
        lines.append("A scan only finds devices that answer — a sleeping phone or a quiet gadget may not show up.")
        return {"ok": True, "title": "Devices on your network", "lines": lines,
                "devices": devices, "missing": missing}

    def _act_history(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        rows = self.history
        if not rows:
            return {"ok": True, "title": "Speed history",
                    "lines": ["No speed tests saved yet — run one and it'll appear here."],
                    "history": []}
        downs = [float(row["down_mbps"]) for row in rows if isinstance(row.get("down_mbps"), (int, float))]
        lines = [f"{len(rows)} test{'s' if len(rows) != 1 else ''} saved on this PC."]
        usual = _median(downs)
        if usual is not None:
            lines.append(f"Usual download: {usual:.0f} Mbps (median) · best {max(downs):.0f} · slowest {min(downs):.0f}.")
        alert = speed_alert(rows, downs[-1] if downs else None)
        if alert:
            lines.append(alert)
        for row in rows[-5:]:
            lines.append(f"{row.get('time', '?')}: {row.get('down_mbps', '?')} down / {row.get('up_mbps', '?')} up Mbps"
                         + (f" · {row.get('ping_ms')} ms ping" if row.get("ping_ms") is not None else "") + ".")
        return {"ok": True, "title": "Speed history", "lines": lines, "history": rows}

    def _act_alerts(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        rows = self.history
        alerts: list[str] = []
        if rows:
            downs = [float(row["down_mbps"]) for row in rows if isinstance(row.get("down_mbps"), (int, float))]
            alert = speed_alert(rows, downs[-1] if downs else None)
            if alert:
                alerts.append(alert)
        missing = self._load_json("network_last_missing.json")
        if missing:
            alerts.append("Gone quiet since the last device scan: " +
                          ", ".join(device.get("ip", device["mac"]) for device in missing) +
                          ". They may just be off or asleep — run a fresh scan to check.")
        if not alerts:
            return {"ok": True, "title": "Alerts",
                    "lines": ["Nothing to flag: speed is in its usual range and no device has gone quiet."]}
        return {"ok": True, "title": "Alerts", "lines": alerts}

    def answer(self, action: str, arguments: dict[str, Any]) -> str:
        """The same card as plain text, for Nova to say out loud (the `network` tool)."""
        result = self.act(action, arguments)
        if not result["ok"]:
            return str(result["error"])
        return "\n".join([str(result.get("title") or "Network")] + [str(line) for line in result.get("lines", [])])

    def act(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """One card's answer: status, speed, devices, history or alerts. Never invents a number."""
        handler = {"status": self._act_status, "speed": self._act_speed, "devices": self._act_devices,
                   "history": self._act_history, "alerts": self._act_alerts}.get(str(action or "").strip().lower())
        if handler is None:
            return {"ok": False,
                    "error": "Not done: the action is status, speed, devices, history or alerts."}
        try:
            return handler(arguments if isinstance(arguments, dict) else {})
        except Exception as error:  # noqa: BLE001 - a card must answer, even when something unexpected breaks
            return {"ok": False, "error": f"Network hit a problem ({' '.join(str(error).split())[:120]}). Try again."}
