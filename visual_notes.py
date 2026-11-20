"""Offline idea maps for Nova: spoken map commands and the saved maps file (the HUD draws them)."""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path



def _store_path() -> Path:
    base = Path(os.environ.get("ALFRED_DATA_DIR") or Path.home() / ".local" / "share" / "alfred")
    return base / "visual_notes.json"


def _clean_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", raw).strip()
        if line:
            lines.append(line[:140])
    return lines[:24]


def parse_spoken_visual_command(text: str) -> dict[str, object] | None:
    """Parse explicit, deterministic voice-to-map commands; no model/network needed."""
    text = re.sub(r"^\s*alfred[,:\s-]*", "", text, flags=re.IGNORECASE).strip()
    edit_patterns = [
        ("add", r"^(?:please\s+)?(?:add|include|put)\s+(?:a\s+)?(?:branch\s+)?(.+?)\s+(?:to|into|in)\s+(?:the\s+)?(?:(?:visual|idea|mind)\s+)?(?:note|map)[.!?]*$"),
        ("remove", r"^(?:please\s+)?remove\s+(.+?)\s+from\s+(?:the\s+)?(?:(?:visual|idea|mind)\s+)?(?:note|map)[.!?]*$"),
        ("title", r"^(?:please\s+)?(?:change|set|rename)\s+(?:the\s+)?(?:(?:visual|idea|mind)\s+)?(?:note|map)(?:\s+title)?\s+(?:to|as)\s+(.+?)[.!?]*$"),
        ("title", r"^(?:please\s+)?(?:change|set|rename)\s+(?:the\s+)?(?:map\s+)?title\s+(?:to|as)\s+(.+?)[.!?]*$"),
    ]
    for action, pattern in edit_patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            return {"action": action, "value": match.group(1).strip(" .,!? ")[:140]}
    create_cues = ("visualize", "visualise", "visual note", "mind map", "idea map", "concept map", "diagram")
    found = [(text.casefold().find(cue), cue) for cue in create_cues if cue in text.casefold()]
    if found:
        pos, cue = min(found)
        rest = text[pos + len(cue):].strip(" :,-")
        rest = re.sub(r"^(?:my\s+)?(?:idea|notes?)\s*(?:about|for|on|is)?\s*", "", rest, flags=re.IGNORECASE)
        rest = re.sub(r"^(?:of|about|for|on)\s+", "", rest, flags=re.IGNORECASE).strip()
        if not rest:
            return {"action": "replace", "title": "My idea", "items": ["Say an idea or topic to add branches"]}
        # Prefer explicit punctuation; otherwise interpret an 'and' list as spoken branches.
        if rest.startswith(":"):
            entries = _clean_lines(re.sub(r"[,;]|\b(?:and|then|plus)\b", "\n", rest[1:], flags=re.IGNORECASE))
            title = entries[0] if entries else "My idea"
            items = entries[1:] or entries
        elif ":" in rest:
            head, tail = rest.split(":", 1)
            title = head.strip(" ,.-") or "My idea"
            items = _clean_lines(re.sub(r"[,;]|\b(?:and|then|plus)\b", "\n", tail, flags=re.IGNORECASE))
        else:
            chunks = _clean_lines(re.sub(r"[,;]|\b(?:and|then|plus)\b", "\n", rest, flags=re.IGNORECASE))
            title = chunks[0] if chunks else "My idea"
            items = chunks[1:] if len(chunks) > 1 else chunks[:]
        return {"action": "replace", "title": title[:80], "items": items[:12] or [title[:140]]}

    patterns = [
        ("add", r"^(?:please\s+)?(?:add|include|put)\s+(?:a\s+)?(?:branch\s+)?(.+?)\s+(?:to|into|in)\s+(?:the\s+)?(?:(?:visual|idea|mind)\s+)?(?:note|map)[.!?]*$"),
        ("remove", r"^(?:please\s+)?remove\s+(.+?)\s+from\s+(?:the\s+)?(?:(?:visual|idea|mind)\s+)?(?:note|map)[.!?]*$"),
        ("title", r"^(?:please\s+)?(?:change|set|rename)\s+(?:the\s+)?(?:map\s+)?title\s+(?:to|as)\s+(.+?)[.!?]*$"),
    ]
    for action, pattern in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            return {"action": action, "value": match.group(1).strip(" .,!?")[:140]}
    return None


def _outline_lines(outline: str) -> list[str]:
    """Non-empty lines, indentation kept (an indented line is a sub-idea)."""
    return [line.rstrip()[:160] for line in str(outline).splitlines() if line.strip()][:300]


def clean_positions(positions: object) -> dict[str, list[float]]:
    """Where the user dragged ideas: {"idea > sub-idea": [dx, dy]}, relative to the parent, kept small and finite."""
    cleaned: dict[str, list[float]] = {}
    if not isinstance(positions, dict):
        return cleaned
    for key, value in list(positions.items())[:400]:
        if (isinstance(key, str) and len(key) <= 400 and isinstance(value, (list, tuple)) and len(value) == 2
                and all(isinstance(number, (int, float)) and number == number for number in value)):
            cleaned[key] = [round(max(-8.0, min(8.0, float(number))), 3) for number in value]
    return cleaned


def clean_details(details: object) -> dict[str, str]:
    """Notes written on ideas: {"idea > sub-idea": "text"}, bounded."""
    if not isinstance(details, dict):
        return {}
    return {key: value[:4000] for key, value in list(details.items())[:400]
            if isinstance(key, str) and len(key) <= 400 and isinstance(value, str) and value.strip()}


# ---- the outline as a tree (the same rules as the HUD's mindmap.js) ----

def parse_outline(outline: str) -> list[dict]:
    """One idea per line; indent (2 spaces a level) or "A > B" for sub-ideas. Nodes: {"label", "children"}."""
    roots: list[dict] = []
    stack: list[dict] = []
    for raw in str(outline).splitlines():
        if not raw.strip():
            continue
        indent = len(raw[:len(raw) - len(raw.lstrip())].replace("\t", "  "))
        text = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", raw).strip()
        parts = [part.strip() for part in text.split(">") if part.strip()]
        if not parts:
            continue
        if len(parts) > 1:
            siblings, stack = roots, []
            for label in parts:
                node = next((item for item in siblings if item["label"].casefold() == label.casefold()), None)
                if node is None:
                    node = {"label": label, "children": []}
                    siblings.append(node)
                stack.append(node)
                siblings = node["children"]
            continue
        level = min(indent // 2, len(stack))
        node = {"label": text, "children": []}
        (roots if level == 0 else stack[level - 1]["children"]).append(node)
        stack = stack[:level] + [node]
    return roots


def serialize(roots: list[dict]) -> str:
    lines: list[str] = []

    def walk(node: dict, depth: int) -> None:
        lines.append("  " * depth + node["label"])
        for child in node["children"]:
            walk(child, depth + 1)
    for root in roots:
        walk(root, 0)
    return "\n".join(lines)


def find_idea(roots: list[dict], name: str) -> list[dict] | None:
    """The chain of nodes down to the idea called `name` (exact name first, then one containing it)."""
    wanted = " ".join(str(name).split()).casefold()
    for exact in (True, False):
        def search(nodes: list[dict], chain: list[dict]) -> list[dict] | None:
            for node in nodes:
                label = node["label"].casefold()
                if label == wanted if exact else wanted in label:
                    return chain + [node]
                found = search(node["children"], chain + [node])
                if found:
                    return found
            return None
        found = search(roots, [])
        if found:
            return found
    return None


def add_ideas(outline: str, under: list[str] | str | None, ideas: list[str]) -> tuple[str, int, str]:
    """Add ideas under an idea (a path of names, or one name to look up), or as main ideas.
    Returns the new outline, how many were added, and where they went."""
    roots = parse_outline(outline)
    siblings, place = roots, ""
    if isinstance(under, str) and under.strip():
        chain = find_idea(roots, under)
        if chain:
            siblings, place = chain[-1]["children"], chain[-1]["label"]
    elif isinstance(under, list) and under:
        nodes = roots
        for name in under:
            node = next((item for item in nodes if item["label"].casefold() == str(name).casefold()), None)
            if node is None:
                break
            siblings, place, nodes = node["children"], node["label"], node["children"]
    added = 0
    for idea in ideas:
        label = " ".join(str(idea).replace(">", " ").split())[:80]
        taken = {item["label"].casefold() for item in siblings} | {place.casefold()}
        if label and label.casefold() not in taken and len(siblings) < 12:
            siblings.append({"label": label, "children": []})
            added += 1
    return serialize(roots), added, place


IDEAS_FORMAT = {"type": "object", "properties": {"ideas": {"type": "array", "items": {"type": "string"}}},
                "required": ["ideas"]}


def suggest_ideas(agent, title: str, outline: str, path: list[str]) -> list[str]:
    """✦ Ask Nova: new ideas for one spot on the map from the local model, as structured JSON."""
    from agent import _http_json
    target = path[-1] if path else title
    where = f" (inside {' > '.join(path[:-1])})" if len(path) > 1 else ""
    prompt = (f"Brainstorm map about: {title}\nThe map so far (indented = sub-idea):\n{outline.strip() or '(empty)'}\n\n"
              f"Suggest 5 new, specific ideas to add under \"{target}\"{where}. Each 1 to 5 words. Don't repeat ideas "
              "already on the map. Use the map's language.")
    response = _http_json(f"{agent.base_url}/api/chat", {
        "model": agent.model, "stream": False, "think": False, "format": IDEAS_FORMAT, "keep_alive": "5m",
        "messages": [{"role": "system", "content": "You help the user brainstorm. Reply with JSON only."},
                     {"role": "user", "content": prompt}],
        "options": {"temperature": 0.7, "num_predict": 300}}, timeout=120)
    ideas = json.loads(response.get("message", {}).get("content") or "{}").get("ideas", [])
    return [" ".join(idea.split())[:80] for idea in ideas if isinstance(idea, str) and idea.strip()][:8]


MAP_COLORS = ("gold", "orange", "red", "pink", "violet", "blue", "cyan", "green")


def clean_styles(styles: object) -> dict[str, dict[str, str]]:
    """Colour and icon per idea: {"idea > sub-idea": {"color": "red", "icon": "🔥"}}; unknown colours are dropped."""
    cleaned: dict[str, dict[str, str]] = {}
    if not isinstance(styles, dict):
        return cleaned
    for key, value in list(styles.items())[:400]:
        if not (isinstance(key, str) and len(key) <= 400 and isinstance(value, dict)):
            continue
        style = {}
        if value.get("color") in MAP_COLORS:
            style["color"] = value["color"]
        icon = value.get("icon")
        if isinstance(icon, str) and icon.strip() and len(icon.strip()) <= 8:
            style["icon"] = icon.strip()
        if style:
            cleaned[key] = style
    return cleaned


def clean_links(links: object) -> list[list[str]]:
    """Cross-links between ideas in any branches: [["a", "b > c"], ["a", "d", "causes"], …] (an optional short
    label third), no self-links or duplicates."""
    cleaned: list[list[str]] = []
    seen: set[frozenset[str]] = set()
    for link in links if isinstance(links, list) else []:
        if not (isinstance(link, (list, tuple)) and len(link) in (2, 3)
                and all(isinstance(end, str) and 0 < len(end) <= 400 for end in link[:2])):
            continue
        pair = frozenset(link[:2])
        label = " ".join(link[2].split())[:40] if len(link) == 3 and isinstance(link[2], str) else ""
        if len(pair) == 2 and pair not in seen:
            seen.add(pair)
            cleaned.append([link[0], link[1], label] if label else [link[0], link[1]])
        if len(cleaned) >= 60:
            break
    return cleaned


def clean_extras(source: object) -> dict[str, object]:
    """Everything a map keeps besides its outline, cleaned; missing parts are empty."""
    source = source if isinstance(source, dict) else {}
    return {"positions": clean_positions(source.get("positions")), "details": clean_details(source.get("details")),
            "styles": clean_styles(source.get("styles")), "links": clean_links(source.get("links"))}


def load_maps() -> list[dict[str, str]]:
    try:
        data = json.loads(_store_path().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_map(title: str, outline: str, extras: object = None) -> list[dict[str, str]]:
    """Save (or replace by title) one map; newest first; returns all maps."""
    title, outline = " ".join(str(title).split())[:80], "\n".join(_outline_lines(outline))
    if not title or not outline:
        raise ValueError("Add a title and at least one idea first.")
    now = datetime.now().astimezone().isoformat(timespec="minutes")
    maps = [item for item in load_maps() if item.get("title", "").casefold() != title.casefold()]
    maps = ([{"title": title, "outline": outline, **clean_extras(extras), "saved": now}] + maps)[:100]
    _write(maps)
    return maps


def delete_map(title: str) -> list[dict[str, str]]:
    maps = [item for item in load_maps() if item.get("title", "").casefold() != str(title).casefold()]
    _write(maps)
    return maps


def _write(maps: list[dict]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="alfred-notes-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(maps, handle, ensure_ascii=False, indent=2)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def apply_command(current: dict[str, str], command: dict[str, object]) -> dict[str, str]:
    """The map after one spoken command (replace, add, remove or title)."""
    title, lines = current.get("title") or "My idea", _outline_lines(current.get("outline") or "")
    action = command.get("action")
    if action == "replace":
        title = str(command.get("title") or "My idea")[:80]
        lines = [str(item)[:140] for item in (command.get("items") or [])][:12] or ["Main idea"]
    elif action == "add":
        value = str(command.get("value") or "").strip()[:140]
        if value and value.casefold() not in {line.strip().casefold() for line in lines}:
            lines.append(value)
    elif action == "remove":
        value = str(command.get("value") or "").strip().casefold()
        lines = [line for line in lines if value not in line.casefold()] or ["Main idea"]
    elif action == "title":
        title = str(command.get("value") or "My idea")[:80]
    return {"title": title, "outline": "\n".join(lines)}
