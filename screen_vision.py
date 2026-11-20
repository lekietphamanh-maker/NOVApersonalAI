"""Seeing the screen with Claude, the way Clicky does: every SCREEN list comes with a screenshot of the window, and the
number drawn on each control is its element number. What this module keeps small: only the newest screenshot and SCREEN
list are sent (older element numbers are invalid anyway, and pictures are the expensive part), and a long job sends the
request plus only the newest steps, with a digest of the rest."""
from __future__ import annotations

import re
from typing import Any

VISION_NOTE = """

You can SEE the screen: every SCREEN list comes with a screenshot of that window, and the number drawn on each control in the picture is its element number in the list. Use the picture to understand the page (layout, pictures, what is selected, error messages, where things are); act only by element number from the newest SCREEN."""
KEPT_WORK_MESSAGES = 30
SCREEN_LIST = re.compile(r"\n\nSCREEN [0-9a-f]{8}:")
OLDER_SCREEN = "\n\nSCREEN: (older screen left out)"
OLDER_PICTURE = {"type": "text", "text": "(older screenshot left out)"}


def with_screenshot(text: str, image: str | None) -> list[dict[str, Any]]:
    """Message or tool-result content: the text, then the screenshot when there is one. Always a list of blocks, so
    older screens are found and left out the same way everywhere."""
    blocks: list[dict[str, Any]] = [{"type": "text", "text": text}]
    if image:
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}})
    return blocks


def _blocks(messages: list[dict[str, Any]]):
    """Every text and image block, in order, also inside tool results: (holder list, index, block)."""
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for index, block in enumerate(content):
            if not isinstance(block, dict):
                continue  # Claude's own reply blocks (SDK objects): never a screen or a picture
            if block.get("type") == "tool_result" and isinstance(block.get("content"), list):
                for inner_index, inner in enumerate(block["content"]):
                    yield block["content"], inner_index, inner
            else:
                yield content, index, block


def only_newest_screen(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A copy to send: older screenshots become a short note and older SCREEN lists are cut off; the newest stay."""
    copied = _copy(messages)
    found = list(_blocks(copied))
    pictures = [item for item in found if item[2].get("type") == "image"]
    screens = [item for item in found if item[2].get("type") == "text" and SCREEN_LIST.search(item[2].get("text", ""))]
    for holder, index, _block in pictures[:-1]:
        holder[index] = OLDER_PICTURE
    for holder, index, block in screens[:-1]:
        text = block["text"]
        holder[index] = {**block, "text": text[:SCREEN_LIST.search(text).start()] + OLDER_SCREEN}
    return copied


def recent_steps(messages: list[dict[str, Any]], request: int, keep: int = KEPT_WORK_MESSAGES) -> list[dict[str, Any]]:
    """The history and the request (messages up to `request`), then only the newest `keep` messages of the job, cut
    where Claude's turn begins (so every tool result keeps its call and turns still alternate). The steps left out
    are named in a note added to the request."""
    work = messages[request + 1:]
    if len(work) <= keep:
        return messages
    cut = len(work) - keep
    while cut < len(work) and work[cut].get("role") != "assistant":
        cut += 1
    done = [f"{block.name}({', '.join(f'{key}={str(value)[:40]}' for key, value in (block.input or {}).items())})"
            for message in work[:cut] if message.get("role") == "assistant"
            for block in message.get("content") or [] if getattr(block, "type", "") == "tool_use"]
    note = {"type": "text", "text": f"({len(done)} earlier steps of this job are done and left out to save room. The newest "
                                    f"ones: {'; '.join(done[-60:])[-2000:]}. Keep going until the job is done.)"}
    asked = messages[request]
    content = asked["content"] if isinstance(asked["content"], list) else [{"type": "text", "text": asked["content"]}]
    return [*messages[:request], {**asked, "content": [*content, note]}, *work[cut:]]


def _copy(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copies of the messages and of their block lists (blocks themselves are replaced, never changed)."""
    copied = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            content = [{**block, "content": list(block["content"])}
                       if isinstance(block, dict) and isinstance(block.get("content"), list) else block for block in content]
        copied.append({**message, "content": content})
    return copied
