from __future__ import annotations

import unittest

from hardware_advisor import HardwareProfile, choose_model, pick_best, recommend_model, upgrade_offer


class HardwareAdvisorTests(unittest.TestCase):
    def setUp(self):
        self.profile = HardwareProfile("Windows", "AMD64", "CPU", 32, 20,
                                       [{"name": "GPU", "reported_vram_gib": 4}],
                                       "not confirmed", [])
        self.models = [
            {"name": "tiny:3b", "size": 2_000_000_000,
             "details": {"parameter_size": "3B", "quantization_level": "Q4_K_M"}},
            {"name": "mid:8b", "size": 5_500_000_000,
             "details": {"parameter_size": "8B", "quantization_level": "Q4_K_M"}},
            {"name": "huge:30b", "size": 20_000_000_000,
             "details": {"parameter_size": "30B", "quantization_level": "Q4_K_M"}},
        ]

    def test_selects_largest_fitting_installed_model(self):
        selected, ranked = pick_best({"models": self.models}, self.profile)
        self.assertEqual(selected["name"], "mid:8b")
        self.assertEqual(ranked[0]["name"], "huge:30b")

    def test_falls_back_to_smallest_installed_when_none_fit(self):
        low = HardwareProfile("Windows", "AMD64", "CPU", 8, 4, [], "unknown", [])
        selected, _ = pick_best({"models": self.models}, low)
        self.assertEqual(selected["name"], "tiny:3b")

    def test_known_upgrade_offer_needs_fit_and_storage(self):
        selected = {"name": "baseline:7b", "parameters_b": 7.6}
        offer = upgrade_offer(selected, {"baseline:7b"}, self.profile, free_disk_gib=20)
        self.assertEqual(offer["name"], "qwen3:8b")
        self.assertIsNone(upgrade_offer(selected, {"baseline:7b"}, self.profile, free_disk_gib=1))
        poor = HardwareProfile("Windows", "AMD64", "CPU", 8, 4, [], "unknown", [])
        self.assertIsNone(upgrade_offer(selected, {"baseline:7b"}, poor, free_disk_gib=20))


def pc(ram: float, vram: float | None = None) -> HardwareProfile:
    gpus = [{"name": "GPU", "reported_vram_gib": vram}] if vram is not None else []
    return HardwareProfile("Windows", "AMD64", "CPU", ram, ram / 2, gpus, "unknown", [])


class DesktopModelChoiceTests(unittest.TestCase):
    def test_model_size_follows_the_pc(self):
        self.assertEqual(recommend_model(pc(32, 8))[0], "qwen3:8b")     # RX 6600 XT, 32 GB
        self.assertEqual(recommend_model(pc(32, 16))[0], "qwen3:14b")
        self.assertEqual(recommend_model(pc(32))[0], "qwen3:8b")        # strong CPU-only desktop
        self.assertEqual(recommend_model(pc(16, 0.5))[0], "qwen3:4b")   # laptop with integrated graphics
        self.assertEqual(recommend_model(pc(16, 4))[0], "qwen3:4b")
        self.assertEqual(recommend_model(pc(8))[0], "qwen3:1.7b")
        self.assertIn("8 GB graphics card", recommend_model(pc(32, 8))[2])

    def test_auto_uses_the_closest_installed_model_until_the_download(self):
        choice = choose_model("auto", ["qwen3:8b"], pc(32, 16))
        self.assertEqual((choice.model, choice.recommended, choice.missing), ("qwen3:8b", "qwen3:14b", True))
        choice = choose_model("auto", ["qwen3:14b", "qwen3:1.7b"], pc(16, 4))
        self.assertEqual(choice.model, "qwen3:1.7b")                    # smaller first: bigger would be slow
        self.assertFalse(choose_model(None, ["qwen3:8b"], pc(32, 8)).missing)
        self.assertEqual(choose_model("auto", [], pc(32, 8)).model, "qwen3:8b")

    def test_a_model_picked_in_settings_wins(self):
        choice = choose_model("llama3.2:3b", ["llama3.2:3b"], pc(32, 16))
        self.assertEqual((choice.model, choice.missing), ("llama3.2:3b", False))



class PullRetryTests(unittest.TestCase):
    def test_a_server_hiccup_is_retried_but_a_missing_model_is_not(self) -> None:
        from unittest.mock import patch
        import hardware_advisor
        calls: list[int] = []

        def flaky(_base_url, _name, _progress):
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("pull model manifest: 503: upstream connect error")
        with patch.object(hardware_advisor, "_pull_once", flaky), patch("time.sleep", lambda _seconds: None):
            hardware_advisor.pull_model("http://x", "m", lambda _text: None)
        self.assertEqual(len(calls), 3)
        calls.clear()

        def missing(_base_url, _name, _progress):
            calls.append(1)
            raise RuntimeError("pull model manifest: file does not exist")
        with patch.object(hardware_advisor, "_pull_once", missing), patch("time.sleep", lambda _seconds: None):
            with self.assertRaises(RuntimeError):
                hardware_advisor.pull_model("http://x", "m", lambda _text: None)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
