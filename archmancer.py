"""Archmancer: agent-system architecture knowledge, bundled from lehoanganhtai13/archmancer.

Eight skills covering the full lifecycle of agent systems — from task intake to delivery, trust and privacy,
context management, tools and models, diagnostics and evaluation. Nova searches and reads these docs when
the owner asks about designing, debugging or reviewing agent systems.

Nothing leaves the PC: the docs are bundled markdown files read locally.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

DOCS_DIR = Path(__file__).parent / "archmancer_docs"

SKILLS: dict[str, str] = {
    "agent-system-engineering": "The starting map: system responsibilities, architectural trade-offs, design/build/debug/optimize/review routes.",
    "agent-harness-model-and-tools": "Decision loops: workflows vs agent loops, model requests, tools, authorized actions, observed results.",
    "agent-runtime-and-interaction": "Task admission, scheduling, cancellation, recovery, streaming, reconnect, result delivery.",
    "agent-configuration-and-delivery": "Config validation, versioning, rollout, rollback, drift, proving which version served a run.",
    "agent-context-and-state": "Context assembly, history, compaction, prompt caching, memory, checkpoints.",
    "agent-evidence-and-knowledge": "Source access, retrieval, freshness, citations, corpus lifecycle, RAG.",
    "agent-diagnostics-evaluation-and-resource-control": "Tracing, evaluation, cost accounting, latency, budget limits.",
    "agent-trust-and-privacy": "Authorization, isolation, approval, credentials, prompt injection, retention, deletion.",
}

MAX_RESULT = 12_000


def _all_docs() -> list[tuple[str, str, Path]]:
    """(skill_name, doc_title, path) for every markdown file."""
    docs = []
    for skill_dir in sorted(DOCS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_name = skill_dir.name
        main = skill_dir / "SKILL.md"
        if main.is_file():
            docs.append((skill_name, skill_name, main))
        refs_dir = skill_dir / "references"
        if refs_dir.is_dir():
            for ref in sorted(refs_dir.glob("*.md")):
                docs.append((skill_name, ref.stem, ref))
    return docs


def list_skills() -> str:
    lines = ["Archmancer agent-system architecture skills:"]
    for name, description in SKILLS.items():
        lines.append(f"  {name}: {description}")
    return "\n".join(lines)


def search(query: str) -> str:
    """Keyword search across all Archmancer docs, returns the best matching passages."""
    words = re.findall(r"\w{3,}", query.lower())
    if not words:
        return list_skills()

    scored: list[tuple[int, str, str, Path]] = []
    for skill_name, doc_title, path in _all_docs():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        lower = text.lower()
        hits = sum(lower.count(w) for w in words)
        if hits > 0:
            scored.append((hits, skill_name, doc_title, path))

    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return f"No Archmancer docs match '{query}'. Available skills:\n{list_skills()}"

    result_parts: list[str] = []
    used = 0
    for _hits, skill_name, doc_title, path in scored[:5]:
        text = path.read_text(encoding="utf-8")
        passages = _extract_passages(text, words)
        if not passages:
            continue
        section = f"[{skill_name} / {doc_title}]\n" + "\n---\n".join(passages)
        if used + len(section) > MAX_RESULT:
            remaining = MAX_RESULT - used - 100
            if remaining > 200:
                result_parts.append(section[:remaining] + "\n...(truncated)")
            break
        result_parts.append(section)
        used += len(section)

    return "\n\n".join(result_parts) if result_parts else f"No relevant passages for '{query}'."


def read_skill(skill_name: str) -> str:
    """Read one skill's main doc (the SKILL.md overview)."""
    cleaned = skill_name.strip().lower().replace(" ", "-")
    for name in SKILLS:
        if cleaned in name or name in cleaned:
            path = DOCS_DIR / name / "SKILL.md"
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                return text[:MAX_RESULT] if len(text) > MAX_RESULT else text
    return f"Skill '{skill_name}' not found. Available: {', '.join(SKILLS)}"


def read_reference(skill_name: str, ref_name: str) -> str:
    """Read a specific reference doc within a skill."""
    cleaned_skill = skill_name.strip().lower().replace(" ", "-")
    cleaned_ref = ref_name.strip().lower().replace(" ", "-")
    for name in SKILLS:
        if cleaned_skill in name or name in cleaned_skill:
            refs_dir = DOCS_DIR / name / "references"
            if refs_dir.is_dir():
                for ref_path in refs_dir.glob("*.md"):
                    if cleaned_ref in ref_path.stem or ref_path.stem in cleaned_ref:
                        text = ref_path.read_text(encoding="utf-8")
                        return text[:MAX_RESULT] if len(text) > MAX_RESULT else text
            available = [p.stem for p in (DOCS_DIR / name / "references").glob("*.md")] if refs_dir.is_dir() else []
            return f"Reference '{ref_name}' not found in {name}. Available: {', '.join(available) or 'none'}"
    return f"Skill '{skill_name}' not found. Available: {', '.join(SKILLS)}"


def _extract_passages(text: str, words: list[str], max_passages: int = 3) -> list[str]:
    """Find the paragraphs that contain the most query words."""
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if len(p.strip()) > 40]
    scored = []
    for para in paragraphs:
        lower = para.lower()
        hits = sum(1 for w in words if w in lower)
        if hits > 0:
            scored.append((hits, para))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [para[:2000] for _, para in scored[:max_passages]]


def run(action: str, arguments: dict[str, Any]) -> str:
    if action == "list":
        return list_skills()
    if action == "search":
        return search(str(arguments.get("query") or ""))
    if action == "read":
        skill = str(arguments.get("skill") or "")
        ref = str(arguments.get("reference") or "")
        if ref:
            return read_reference(skill, ref)
        return read_skill(skill)
    return f"Unknown action '{action}'. Use: list, search, or read."
