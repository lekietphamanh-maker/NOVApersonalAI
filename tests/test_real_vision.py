"""Real vision models in Ollama name what the camera shows (CI: ALFRED_TEST_VISION=1 with Ollama running).
The quick detector calls this burger photo a "sandwich"; a vision model should do better. On CI's CPU-only machine
qwen2.5vl:3b said "Burger" in 51 s; moondream (1.7 GB) answered faster but couldn't tell, so qwen2.5vl stays."""
from __future__ import annotations

import io
import os
import time
import unittest
from urllib.request import urlopen

PHOTO = "https://storage.googleapis.com/mediapipe-assets/burger.jpg"  # MediaPipe's public test image


def small_jpeg(data: bytes) -> bytes:
    """What creative mode sends: at most 384 px on the long side."""
    from PIL import Image
    image = Image.open(io.BytesIO(data)).convert("RGB")
    image.thumbnail((384, 384))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=85)
    return out.getvalue()


@unittest.skipUnless(os.environ.get("ALFRED_TEST_VISION") == "1", "needs a running Ollama (ALFRED_TEST_VISION=1)")
class RealVisionTests(unittest.TestCase):
    base_url = "http://127.0.0.1:11434"

    def name_with(self, model: str) -> tuple[str, float]:
        import vision
        from hardware_advisor import pull_model
        pull_model(self.base_url, model, lambda _text: None)
        with urlopen(PHOTO, timeout=60) as response:
            photo = small_jpeg(response.read())
        vision.warm_up(self.base_url, model)
        started = time.monotonic()
        name = vision.identify(self.base_url, model, photo, guess="sandwich", timeout=900)
        took = time.monotonic() - started
        print(f"{model}: {name!r} in {took:.0f} s (CPU only, model already loaded)", flush=True)
        return name, took

    def test_the_default_vision_model_names_a_photo(self):
        import vision
        name, _took = self.name_with(vision.VISION_MODEL)
        self.assertRegex(name.lower(), r"burger|hamburger|cheeseburger")



if __name__ == "__main__":
    unittest.main()
