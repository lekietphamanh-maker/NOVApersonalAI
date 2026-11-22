"""Network lab: every number it shows is measured, so the tests check the measuring, not the network.
The parsers are tested against fixed command output, the speed maths against a fake clock, and the panel
itself against a fake runner and fetcher — no real ping, download or scan ever runs in a test."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import network

IPCONFIG = """
Windows IP Configuration

Wireless LAN adapter Wi-Fi:

   IPv4 Address. . . . . . . . . . . : 192.168.1.42
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . : 192.168.1.1
   DNS Servers . . . . . . . . . . . : 1.1.1.1
                                       8.8.8.8
"""

NETSH = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    SSID                   : HomeNet-5G
    Signal                 : 82%
"""

ARP = """
Interface: 192.168.1.42 --- 0x4
  Internet Address      Physical Address      Type
  192.168.1.1           aa-bb-cc-11-22-33     dynamic
  192.168.1.50          12-34-56-78-9a-bc     dynamic
"""


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeFetch:
    """A fetcher that returns fixed-size payloads and advances the clock as if the bytes took time."""

    def __init__(self, clock: FakeClock, down_seconds: float = 2.0, up_seconds: float = 4.0) -> None:
        self.clock = clock
        self.down_seconds = down_seconds
        self.up_seconds = up_seconds

    def __call__(self, url: str, data: bytes | None = None) -> bytes:
        if "__down" in url:
            self.clock.now += self.down_seconds
            return b"0" * network.SPEED_DOWN_BYTES
        if "__up" in url:
            self.clock.now += self.up_seconds
            return b""
        if "api.ipify.org" in url:
            return b"203.0.113.7"
        raise AssertionError(f"unexpected URL in test: {url}")


def fake_runner_factory(ping_hosts: set[str], arp_ips: set[str] | None = None) -> Any:
    """A runner that answers ping for the hosts in `ping_hosts`, and an ARP table listing `arp_ips`
    (the ping hosts by default) — the table only shows devices that are actually there."""

    def run(cmd: list[str]) -> str:
        if cmd[0] == "ping":
            host = cmd[-1]
            if host in ping_hosts:
                return "Reply from 192.168.1.1: bytes=32 time=3ms TTL=64" if host == "192.168.1.1" else \
                    "Reply from 1.1.1.1: bytes=32 time=12ms TTL=57"
            return "Request timed out."
        if cmd[0] == "ipconfig":
            return IPCONFIG
        if cmd[:2] == ["netsh", "wlan"]:
            return NETSH
        if cmd[0] == "arp":
            lines = ["Interface: 192.168.1.42 --- 0x4",
                     "  Internet Address      Physical Address      Type"]
            macs = {"192.168.1.1": "aa-bb-cc-11-22-33", "192.168.1.50": "12-34-56-78-9a-bc"}
            for ip in sorted(arp_ips if arp_ips is not None else ping_hosts):
                if ip in macs:
                    lines.append(f"  {ip}           {macs[ip]}     dynamic")
            return "\n".join(lines)
        raise AssertionError(f"unexpected command in test: {cmd}")

    return run


class ParserTests(unittest.TestCase):
    def test_parse_ipconfig(self) -> None:
        info = network.parse_ipconfig(IPCONFIG)
        self.assertEqual(info["ipv4"], "192.168.1.42")
        self.assertEqual(info["mask"], "255.255.255.0")
        self.assertEqual(info["gateway"], "192.168.1.1")
        self.assertEqual(info["dns"], ["1.1.1.1", "8.8.8.8"])

    def test_parse_ipconfig_empty_is_blank_not_guessed(self) -> None:
        self.assertEqual(network.parse_ipconfig(""), {"ipv4": "", "mask": "", "gateway": "", "dns": []})

    def test_parse_netsh_wlan(self) -> None:
        self.assertEqual(network.parse_netsh_wlan(NETSH), {"ssid": "HomeNet-5G", "signal": "82%"})

    def test_parse_arp_normalises_macs(self) -> None:
        devices = network.parse_arp(ARP)
        self.assertEqual(devices, [{"ip": "192.168.1.1", "mac": "aa:bb:cc:11:22:33"},
                                   {"ip": "192.168.1.50", "mac": "12:34:56:78:9a:bc"}])

    def test_parse_ping_variants(self) -> None:
        self.assertEqual(network.parse_ping("Reply from 1.1.1.1: bytes=32 time=12ms TTL=57"), 12.0)
        self.assertEqual(network.parse_ping("Reply from 1.1.1.1: bytes=32 time<1ms TTL=57"), 1.0)
        self.assertEqual(network.parse_ping("64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=12.3 ms"), 12.3)
        self.assertIsNone(network.parse_ping("Request timed out."))
        self.assertIsNone(network.parse_ping(""))

    def test_network_prefix(self) -> None:
        self.assertEqual(network.network_prefix("192.168.1.42", "255.255.255.0"), "192.168.1.")
        self.assertIsNone(network.network_prefix("10.0.0.5", "255.255.0.0"))
        self.assertIsNone(network.network_prefix("not-an-ip", "255.255.255.0"))

    def test_mbps(self) -> None:
        self.assertAlmostEqual(network.mbps(25_000_000, 2.0), 100.0)
        self.assertIsNone(network.mbps(100, 0))
        self.assertIsNone(network.mbps(100, -1))


class AlertTests(unittest.TestCase):
    def history(self, downs: list[float]) -> list[dict[str, Any]]:
        return [{"time": f"2026-11-2{i}", "down_mbps": down} for i, down in enumerate(downs)]

    def test_speed_alert_fires_below_half_median(self) -> None:
        rows = self.history([100, 102, 98, 40])
        self.assertIn("40 Mbps", network.speed_alert(rows, 40))
        self.assertIn("100 Mbps", network.speed_alert(rows, 40))

    def test_speed_alert_quiet_when_normal(self) -> None:
        self.assertEqual(network.speed_alert(self.history([100, 102, 98, 90]), 90), "")

    def test_speed_alert_needs_three_earlier_tests(self) -> None:
        self.assertEqual(network.speed_alert(self.history([100, 40]), 40), "")

    def test_missing_devices_by_mac(self) -> None:
        previous = [{"ip": "192.168.1.1", "mac": "aa:bb:cc:11:22:33"},
                    {"ip": "192.168.1.50", "mac": "12:34:56:78:9a:bc"}]
        current = [{"ip": "192.168.1.1", "mac": "aa:bb:cc:11:22:33"}]
        self.assertEqual(network.missing_devices(previous, current), [previous[1]])
        self.assertEqual(network.missing_devices(previous, previous), [])


class PanelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def panel(self, ping_hosts: set[str] | None = None) -> network.NetworkPanel:
        return network.NetworkPanel(data_dir=Path(self.tmp.name),
                                    runner=fake_runner_factory(ping_hosts or {"192.168.1.1", "1.1.1.1"}),
                                    fetcher=FakeFetch(self.clock), clock=self.clock)

    def test_speed_measures_real_numbers_and_saves_history(self) -> None:
        panel = self.panel()
        result = panel.act("speed", {})
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["result"]["down_mbps"], 100.0)
        self.assertAlmostEqual(result["result"]["up_mbps"], 20.0)
        self.assertEqual(result["result"]["ping_ms"], 12.0)
        self.assertEqual(len(panel.history), 1)
        self.assertEqual(panel.history[0]["down_mbps"], 100.0)

    def test_speed_alert_after_a_slow_test(self) -> None:
        panel = self.panel()
        for _ in range(3):
            panel.act("speed", {})
        panel._fetch = FakeFetch(self.clock, down_seconds=10.0, up_seconds=4.0)  # 20 Mbps, not 100
        result = panel.act("speed", {})
        self.assertTrue(result["ok"])
        self.assertTrue(any("Speed alert" in line for line in result["lines"]))

    def test_speed_failure_is_a_sentence_not_a_crash(self) -> None:
        def failing_fetch(url: str, data: bytes | None = None) -> bytes:
            raise ConnectionError("boom")

        panel = network.NetworkPanel(data_dir=Path(self.tmp.name), runner=fake_runner_factory(set()),
                                     fetcher=failing_fetch, clock=self.clock)
        result = panel.act("speed", {})
        self.assertFalse(result["ok"])
        self.assertIn("Couldn't run the speed test", result["error"])
        self.assertEqual(panel.history, [])

    def test_status_reports_local_and_public(self) -> None:
        panel = self.panel()
        result = panel.act("status", {})
        self.assertTrue(result["ok"])
        text = "\n".join(result["lines"])
        self.assertIn("HomeNet-5G", text)
        self.assertIn("192.168.1.42", text)
        self.assertIn("192.168.1.1", text)
        self.assertIn("203.0.113.7", text)
        self.assertIn("12 ms", text)

    def test_status_offline_says_unreachable(self) -> None:
        def failing_fetch(url: str, data: bytes | None = None) -> bytes:
            raise ConnectionError("boom")

        panel = network.NetworkPanel(data_dir=Path(self.tmp.name),
                                     runner=fake_runner_factory(set()), fetcher=failing_fetch, clock=self.clock)
        result = panel.act("status", {})
        self.assertTrue(result["ok"])
        text = "\n".join(result["lines"])
        self.assertIn("not answering pings", text)
        self.assertIn("unreachable", text)

    def test_devices_scan_and_missing_alert(self) -> None:
        panel = self.panel(ping_hosts={"192.168.1.1", "192.168.1.50", "1.1.1.1"})
        first = panel.act("devices", {})
        self.assertTrue(first["ok"])
        self.assertEqual(len(first["devices"]), 2)
        self.assertEqual(first["missing"], [])
        # Second scan: the phone (.50) stops answering, so it is missing.
        panel._run = fake_runner_factory({"192.168.1.1", "1.1.1.1"})
        second = panel.act("devices", {})
        self.assertEqual(len(second["missing"]), 1)
        self.assertEqual(second["missing"][0]["ip"], "192.168.1.50")
        alerts = panel.act("alerts", {})
        self.assertTrue(any("192.168.1.50" in line for line in alerts["lines"]))

    def test_history_empty_then_filled(self) -> None:
        panel = self.panel()
        empty = panel.act("history", {})
        self.assertIn("No speed tests saved yet", empty["lines"][0])
        panel.act("speed", {})
        filled = panel.act("history", {})
        self.assertIn("Usual download: 100 Mbps", "\n".join(filled["lines"]))

    def test_history_file_caps_at_50(self) -> None:
        panel = self.panel()
        rows = [{"time": "2026-11-01", "down_mbps": 100.0, "up_mbps": 20.0} for _ in range(60)]
        panel._save_json("network_history.json", rows)
        panel._record_test({"time": "2026-11-02", "down_mbps": 100.0, "up_mbps": 20.0})
        self.assertEqual(len(panel.history), 50)

    def test_unknown_action_and_answer(self) -> None:
        panel = self.panel()
        self.assertFalse(panel.act("explode", {})["ok"])
        text = panel.answer("status", {})
        self.assertIn("Network status", text)
        self.assertIn("HomeNet-5G", text)

    def test_broken_history_file_is_empty_not_a_crash(self) -> None:
        (Path(self.tmp.name) / "network_history.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(self.panel().history, [])


if __name__ == "__main__":
    unittest.main()
