"""Auto-tune: the strongest model that runs smoothly on this PC, the longest context that keeps it on the graphics card,
Ollama's own speed settings (and Vulkan for a Radeon left on the processor), and tuning again after an update."""
from __future__ import annotations

import json
import unittest

import auto_tune
from hardware_advisor import HardwareProfile

RX_6600_XT = HardwareProfile("Windows 11", "AMD64", "Ryzen 5 5600X", 32.0, 24.0,
                             [{"name": "AMD Radeon RX 6600 XT", "reported_vram_gib": 8.0}], "", [])
NO_GPU = HardwareProfile("Windows 11", "AMD64", "Intel i5", 16.0, 10.0, [], "", [])


class FakeOllama:
    """Speeds and graphics-memory shares by (model, context), like a real 8 GB card would give."""

    def __init__(self, installed: list[str], results: dict[tuple[str, int], tuple[float, float]]) -> None:
        self._installed, self.results, self.measured = list(installed), results, []

    def installed(self) -> list[str]:
        return list(self._installed)

    def measure(self, model: str, num_ctx: int) -> auto_tune.Measure:
        self.measured.append((model, num_ctx))
        speed, share = self.results.get((model, num_ctx), (5.0, 0.0))
        return auto_tune.Measure(model, num_ctx, speed, 0.4, share)


class ChooseTests(unittest.TestCase):
    def test_the_biggest_context_that_keeps_it_on_the_card(self) -> None:
        ollama = FakeOllama(["qwen3:8b"], {("qwen3:8b", 32768): (30.0, 0.71), ("qwen3:8b", 16384): (41.0, 1.0)})
        measure, notes = auto_tune.choose(ollama, RX_6600_XT, pull=self.fail, disk_free_gb=100, progress=lambda _: None)
        self.assertEqual((measure.model, measure.num_ctx, measure.on_gpu), ("qwen3:8b", 16384, 1.0))
        self.assertEqual(ollama.measured, [("qwen3:8b", 32768), ("qwen3:8b", 16384)])
        self.assertEqual(notes, [])

    def test_missing_models_are_downloaded_and_a_slow_one_steps_down(self) -> None:
        pulled: list[str] = []
        ollama = FakeOllama(["qwen3:4b"], {("qwen3:4b", 32768): (55.0, 1.0)})  # 8b spills to the CPU at every size
        measure, notes = auto_tune.choose(ollama, RX_6600_XT, pull=pulled.append, disk_free_gb=100, progress=lambda _: None)
        self.assertEqual(pulled, ["qwen3:8b"])
        self.assertEqual(measure.model, "qwen3:4b")
        self.assertIn("qwen3:8b was too slow here", notes[0])

    def test_no_room_on_disk_skips_the_download(self) -> None:
        ollama = FakeOllama(["qwen3:4b"], {("qwen3:4b", 32768): (55.0, 1.0)})
        measure, notes = auto_tune.choose(ollama, RX_6600_XT, pull=self.fail, disk_free_gb=6, progress=lambda _: None)
        self.assertEqual(measure.model, "qwen3:4b")
        self.assertIn("needs 5.2 GB of disk", notes[0])

    def test_without_a_graphics_card_speed_decides(self) -> None:
        ollama = FakeOllama(["qwen3:4b", "qwen3:1.7b"], {("qwen3:4b", 8192): (8.0, 0.0), ("qwen3:1.7b", 8192): (19.0, 0.0)})
        measure, _ = auto_tune.choose(ollama, NO_GPU, pull=self.fail, disk_free_gb=100, progress=lambda _: None)
        self.assertEqual((measure.model, measure.num_ctx), ("qwen3:1.7b", 8192))

    @staticmethod
    def fail(name: str) -> None:
        raise AssertionError(f"downloaded {name}")


class TuneTests(unittest.TestCase):
    def test_ollama_settings_then_vulkan_for_a_radeon_on_the_processor(self) -> None:
        restarts: list[dict] = []
        environ: dict[str, str] = {}
        ollama = FakeOllama(["qwen3:8b"], {})  # first everything runs on the processor (no ROCm for gfx1032)

        def restart(settings: dict) -> bool:
            restarts.append(settings)
            environ.update(settings)
            if "OLLAMA_VULKAN" in settings:
                ollama.results = {("qwen3:8b", 32768): (38.0, 1.0)}
            return True
        result = auto_tune.tune(ollama, RX_6600_XT, "v2.9.0", pull=lambda name: None, disk_free_gb=100,
                                restart=restart, environ=environ)
        self.assertEqual(restarts, [{"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0"}, {"OLLAMA_VULKAN": "1"}])
        self.assertEqual((result.model, result.num_ctx, result.on_gpu, result.version), ("qwen3:8b", 32768, 1.0, "v2.9.0"))
        self.assertEqual(result.server["OLLAMA_VULKAN"], "1")
        self.assertIn("all on the graphics card, 38 tokens a second", result.summary())
        json.dumps(result.as_dict())  # kept in settings as it is

    def test_tuned_again_after_an_update_or_new_hardware(self) -> None:
        saved = {"version": "v2.8.0", "hardware": auto_tune.fingerprint(RX_6600_XT)}
        self.assertFalse(auto_tune.due(saved, "v2.8.0", RX_6600_XT))
        self.assertTrue(auto_tune.due(saved, "v2.9.0", RX_6600_XT))
        self.assertTrue(auto_tune.due(saved, "v2.8.0", NO_GPU))
        self.assertTrue(auto_tune.due(None, "v2.8.0", RX_6600_XT))


class MeasureTests(unittest.TestCase):
    def test_speed_and_placement_come_from_ollamas_own_numbers(self) -> None:
        asked: list = []

        class Answer:
            def __init__(self, body: dict) -> None:
                self.body = json.dumps(body).encode()

            def read(self) -> bytes:
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def opener(request, timeout):
            body = json.loads(request.data) if request.data else None
            asked.append((request.full_url.rsplit("/", 1)[-1], body))
            if request.full_url.endswith("/api/ps"):
                return Answer({"models": [{"name": "qwen3:8b", "size": 8_000, "size_vram": 6_000}]})
            if body and body.get("prompt"):
                return Answer({"eval_count": 80, "eval_duration": 2_000_000_000, "prompt_eval_duration": 300_000_000})
            return Answer({})
        measure = auto_tune.Ollama("http://127.0.0.1:11434", opener).measure("qwen3:8b", 16384)
        self.assertEqual((measure.tokens_per_second, measure.on_gpu, measure.first_token_seconds), (40.0, 0.75, 0.33))
        self.assertEqual(asked[0][1], {"model": "qwen3:8b", "keep_alive": 0})  # unloaded first, so the context applies
        self.assertEqual(asked[1][1]["options"]["num_ctx"], 16384)


if __name__ == "__main__":
    unittest.main()
