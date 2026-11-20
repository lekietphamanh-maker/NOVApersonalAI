"""This PC's live load and where the model runs: parsing Windows' GPU counters and Ollama's /api/ps, and the advice
shown when a Radeon card leaves the model on the processor."""
from __future__ import annotations

import unittest

import pc_monitor
from brain_router import advanced

GB = 1024 ** 3


class MonitorTests(unittest.TestCase):
    def test_the_busiest_graphics_card_from_windows_counters(self) -> None:
        text = "\n".join([
            r"\\pc\gpu engine(pid_10_luid_0x00000000_0x0000aaaa_phys_0_eng_0_engtype_3d)\utilization percentage|5",
            r"\\pc\gpu engine(pid_11_luid_0x00000000_0x0000bbbb_phys_0_eng_0_engtype_3d)\utilization percentage|40,5",
            r"\\pc\gpu engine(pid_12_luid_0x00000000_0x0000bbbb_phys_0_eng_0_engtype_3d)\utilization percentage|30",
            r"\\pc\gpu adapter memory(luid_0x00000000_0x0000aaaa_phys_0)\dedicated usage|268435456",
            r"\\pc\gpu adapter memory(luid_0x00000000_0x0000bbbb_phys_0)\dedicated usage|5368709120",
            "garbage line"])
        self.assertEqual(pc_monitor.parse_counters(text), {"gpu": 70.5, "vram_gb": 5.0})  # the RX card, not the iGPU
        self.assertEqual(pc_monitor.parse_counters(""), {})

    def test_where_ollama_says_each_model_runs(self) -> None:
        loaded = pc_monitor.placements({"models": [
            {"name": "qwen3:4b", "size": 4 * GB, "size_vram": 4 * GB, "context_length": 8192},
            {"name": "qwen3:8b", "size": 8 * GB, "size_vram": 6 * GB},
            {"name": "gemma3:4b", "size": 4 * GB, "size_vram": 0}]})
        self.assertEqual([model["where"] for model in loaded], ["GPU", "75% GPU / 25% CPU", "CPU"])
        self.assertEqual(pc_monitor.placements({}), [])

    def test_vulkan_advice_only_when_a_radeon_leaves_it_on_the_processor(self) -> None:
        on_cpu = pc_monitor.placements({"models": [{"name": "qwen3:4b", "size": 4 * GB, "size_vram": 0}]})
        on_gpu = pc_monitor.placements({"models": [{"name": "qwen3:4b", "size": 4 * GB, "size_vram": 4 * GB}]})
        tip = pc_monitor.gpu_tip("AMD Radeon RX 6600 XT", on_cpu)
        self.assertIn("gfx1032", tip)
        self.assertIn("OLLAMA_VULKAN=1", tip)
        self.assertEqual(pc_monitor.gpu_tip("AMD Radeon RX 6600 XT", on_gpu), "")
        self.assertEqual(pc_monitor.gpu_tip("NVIDIA GeForce RTX 3060", on_cpu), "")
        self.assertEqual(pc_monitor.gpu_tip("AMD Radeon RX 6600 XT", []), "")

    def test_ram_and_cpu_readings_are_numbers(self) -> None:
        used, total = pc_monitor.ram()
        self.assertGreaterEqual(total, used)
        self.assertGreaterEqual(pc_monitor.CpuMeter().percent(), 0)


class AutoRoutingTests(unittest.TestCase):
    def test_hard_questions(self) -> None:
        for text in ("compare postgres and sqlite for a news database", "debug this traceback please",
                     "prove that the square root of 2 is irrational", "def add(a, b): return a - b  fix it",
                     " ".join(["word"] * 50)):
            self.assertTrue(advanced(text), text)
        for text in ("what's the capital of France", "play some music", "how's the weather", "tell me a joke",
                     "compare"):
            self.assertFalse(advanced(text), text)


if __name__ == "__main__":
    unittest.main()
