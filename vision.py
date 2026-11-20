"""Name anything the camera sees with a local vision model in Ollama. The photo goes only to Ollama on this PC."""
from __future__ import annotations

import base64

VISION_MODEL = "qwen2.5vl:3b"  # fits next to the chat model on an 8 GB graphics card; runs on CPU elsewhere
VISION_GB = 3.2
# Families that can see images. gemma3 1b/270m are text-only.
_FAMILIES = ("qwen2.5vl", "qwen3-vl", "llava", "llama3.2-vision", "minicpm-v", "moondream", "gemma3")
_TEXT_ONLY = ("gemma3:1b", "gemma3:270m")

PROMPT = ("This is a close-up from a webcam. What is the main thing the person is holding or showing? "
          "Answer with its name and at most 10 words of detail (color, brand or text on it if you can read it). "
          "No full sentence, no 'the person is holding'. If you can't tell, give your best guess and say 'maybe'.")


DESCRIBE = ("This is a photo the user just took with their webcam. Describe it in one short sentence (at most 25 "
            "words): who or what is in it, what they are doing, the mood. Plain words, no emoji.")


def find_vision_model(installed: list[str]) -> str | None:
    """The vision model to use among the installed ones: ours first, then any other that can see."""
    if VISION_MODEL in installed:
        return VISION_MODEL
    for name in installed:
        if name.startswith(_FAMILIES) and not name.startswith(_TEXT_ONLY):
            return name
    return None


def warm_up(base_url: str, model: str) -> None:
    """Load the model into memory ahead of the first question (creative mode just opened)."""
    from agent import _http_json
    _http_json(f"{base_url}/api/generate", {"model": model, "keep_alive": "10m"}, timeout=300)


def identify(base_url: str, model: str, jpeg: bytes, guess: str = "", timeout: int = 240) -> str:
    """A short name for what is in the photo, e.g. 'blue Hydro Flask water bottle'. Without a fast graphics card
    this can take a minute: the image is small (≤ 384 px) to keep it as quick as it can be."""
    from agent import _http_json
    hint = f" A simple detector guessed '{guess}'; it is often wrong." if guess else ""
    response = _http_json(f"{base_url}/api/chat", {
        "model": model, "stream": False, "keep_alive": "10m",
        "messages": [{"role": "user", "content": PROMPT + hint, "images": [base64.b64encode(jpeg).decode()]}],
        "options": {"temperature": 0.2, "num_predict": 40}}, timeout=timeout)
    text = " ".join(str(response.get("message", {}).get("content", "")).split())
    return text.strip(" .\"'")[:120] or "something I can't make out"


def describe(base_url: str, model: str, jpeg: bytes, timeout: int = 240) -> str:
    """One sentence about a whole photo (the Describer camera). The photo is shrunk to 512 px first: much faster."""
    from agent import _http_json
    response = _http_json(f"{base_url}/api/chat", {
        "model": model, "stream": False, "keep_alive": "10m",
        "messages": [{"role": "user", "content": DESCRIBE, "images": [base64.b64encode(shrink(jpeg, 512)).decode()]}],
        "options": {"temperature": 0.3, "num_predict": 60}}, timeout=timeout)
    text = " ".join(str(response.get("message", {}).get("content", "")).split())
    return text.strip(" \"'") or "I couldn't make out what's in it."


def shrink(jpeg: bytes, longest: int) -> bytes:
    import io
    from PIL import Image
    try:
        image = Image.open(io.BytesIO(jpeg)).convert("RGB")
    except OSError:
        return jpeg
    if max(image.size) <= longest:
        return jpeg
    image.thumbnail((longest, longest))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=88)
    return out.getvalue()
