"""Archmancer knowledge base: bundled docs are searchable and readable."""
import archmancer


def test_list_skills():
    result = archmancer.list_skills()
    assert "agent-system-engineering" in result
    assert "agent-trust-and-privacy" in result
    assert len(archmancer.SKILLS) == 8


def test_search_finds_relevant_docs():
    result = archmancer.search("prompt injection")
    assert "injection" in result.lower()
    assert "[agent-" in result


def test_search_no_match():
    result = archmancer.search("xyznonexistent999")
    assert "Available skills" in result or "No Archmancer docs" in result


def test_read_skill():
    result = archmancer.read_skill("agent-system-engineering")
    assert "architecture" in result.lower() or "system" in result.lower()


def test_read_skill_fuzzy():
    result = archmancer.read_skill("trust")
    assert "trust" in result.lower() or "privacy" in result.lower()


def test_read_skill_not_found():
    result = archmancer.read_skill("nonexistent-skill")
    assert "not found" in result.lower()


def test_read_reference():
    result = archmancer.read_reference("agent-trust-and-privacy", "trust-and-privacy")
    assert len(result) > 100


def test_read_reference_not_found():
    result = archmancer.read_reference("agent-trust-and-privacy", "nonexistent-ref")
    assert "not found" in result.lower()


def test_run_list():
    result = archmancer.run("list", {})
    assert "agent-system-engineering" in result


def test_run_search():
    result = archmancer.run("search", {"query": "tool authorization"})
    assert len(result) > 50


def test_run_read():
    result = archmancer.run("read", {"skill": "context-and-state"})
    assert "context" in result.lower()


def test_run_unknown_action():
    result = archmancer.run("delete", {})
    assert "Unknown" in result


def test_all_docs_has_entries():
    docs = archmancer._all_docs()
    assert len(docs) >= 30
    skills_found = {d[0] for d in docs}
    assert len(skills_found) == 8
