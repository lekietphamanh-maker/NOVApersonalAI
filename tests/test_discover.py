"""Discover: ranking by interests, the owner's GitHub and their picks; caching; pinning to a commit with its license;
the read-only study task; a proposed skill read out of the study; and the voice tool."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError

import discover
from tools import execute_tool

NOW = datetime(2026, 11, 20, tzinfo=timezone.utc)


def repo(name: str, stars: int, about: str = "", topics: tuple = (), language: str = "Python", days: int = 10, **extra) -> dict:
    return {"full_name": name, "html_url": f"https://github.com/{name}", "description": about, "stargazers_count": stars,
            "topics": list(topics), "language": language, "pushed_at": (NOW - timedelta(days=days)).isoformat(), **extra}


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class RankTests(unittest.TestCase):
    def test_interests_your_github_and_your_picks_shape_the_order(self) -> None:
        found = [repo("a/popular", 50_000, "a web framework", language="Go", days=400),
                 repo("b/gamedev", 900, "game dev engine in Python", ("game-engine",)),
                 repo("c/agents", 2_000, "voice agents", ("ai-agents",), "TypeScript"),
                 repo("d/fork", 99_999, "game dev", fork=True), repo("e/old", 99_999, "game dev", archived=True)]
        mine = discover.profile([{"topics": ["ai-agents"], "language": "TypeScript"}])
        ranked = discover.rank(found, ["game dev"], mine, discover.taste({}), set(), NOW)
        self.assertEqual([item["repo"] for item in ranked][:2], ["b/gamedev", "c/agents"])
        self.assertIn("matches your interest “game dev”", ranked[0]["why"])
        self.assertIn("topics like your repos (ai-agents)", ranked[1]["why"])
        self.assertNotIn("d/fork", [item["repo"] for item in ranked])  # forks and archived repos are left out
        learned = discover.taste({"rejected": [{"topics": ["game-engine"], "language": "Python"}] * 3})
        again = discover.rank(found, ["game dev"], mine, learned, {"c/agents"}, NOW)
        self.assertNotIn("c/agents", [item["repo"] for item in again])  # already decided
        self.assertIn("like ones you skipped", next(item for item in again if item["repo"] == "b/gamedev")["why"])

    def test_a_proposed_skill_is_read_from_the_study(self) -> None:
        study = "It does X.\n\n```skill\n---\ntitle: Tidy downloads\nsays: tidy my downloads\n---\nSort the files.\n```\n"
        self.assertTrue(discover.skill_from(study).startswith("---\ntitle: Tidy downloads"))
        self.assertIsNone(discover.skill_from("No skill here."))
        task = discover.study_task({"repo": "a/b", "sha": "abc123", "url": "https://github.com/a/b", "license": "MIT"})
        self.assertIn("at commit abc123", task)
        self.assertIn("never run or install anything", task)
        self.assertIn("MIT", task)


class GitHubTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[str] = []
        self.clock = [1000.0]

        def opener(request, timeout):
            url = request.full_url
            self.calls.append(url)
            if "/search/repositories" in url:
                return Answer(json.dumps({"items": [repo("x/tool", 5000, "game dev helper")]}).encode())
            if url.endswith("/users/sam/repos?sort=pushed&per_page=50") or url.endswith("/users/sam/starred?per_page=50"):
                return Answer(json.dumps([repo("sam/mine", 3, topics=("game-engine",))]).encode())
            if url.endswith("/repos/x/tool"):
                return Answer(json.dumps({"default_branch": "dev", "license": {"spdx_id": "Apache-2.0"},
                                          "topics": ["game-engine"], "language": "Python"}).encode())
            if url.endswith("/repos/x/tool/commits/dev"):
                return Answer(json.dumps({"sha": "f" * 40}).encode())
            raise AssertionError(url)
        self.discover = discover.Discover(Path(tempfile.mkdtemp()) / "d.json", opener=opener, clock=lambda: self.clock[0])

    def test_suggestions_are_cached_and_your_own_repos_are_left_out(self) -> None:
        first = self.discover.suggestions(["game dev"], "sam")
        self.assertEqual([item["repo"] for item in first], ["x/tool"])
        asked = len(self.calls)
        self.discover.suggestions(["game dev"], "sam")
        self.assertEqual(len(self.calls), asked)  # from the cache
        self.clock[0] += 13 * 3600
        self.discover.suggestions(["game dev"], "sam")
        self.assertGreater(len(self.calls), asked)  # stale after 12 hours

    def test_adding_pins_the_commit_and_records_the_license(self) -> None:
        item = self.discover.suggestions(["game dev"])[0]
        pinned = self.discover.pin(item)
        self.assertEqual((pinned["sha"], pinned["license"]), ("f" * 40, "Apache-2.0"))
        self.discover.decide(pinned, added=True)
        history = self.discover.history()
        self.assertEqual(history["accepted"][0]["sha"], "f" * 40)
        self.assertEqual(self.discover.suggestions(["game dev"]), [])  # decided: not suggested again
        self.discover.decide(pinned, added=False)  # changing your mind moves it
        self.assertEqual((len(self.discover.history()["accepted"]), len(self.discover.history()["rejected"])), (0, 1))
        with self.assertRaises(discover.DiscoverError):
            self.discover.pin({"repo": "../../etc"})

    def test_limits_are_said_plainly(self) -> None:
        def limited(request, timeout):
            raise HTTPError(request.full_url, 403, "rate limited", {}, io.BytesIO())
        self.discover._open = limited
        with self.assertRaises(discover.DiscoverError) as caught:
            self.discover.suggestions(["x"], force=True)
        self.assertIn("token in Settings", str(caught.exception))


class ToolTests(unittest.TestCase):
    def test_the_voice_tool(self) -> None:
        said: list[tuple[str, int]] = []
        result = execute_tool("discover", {"action": "add", "number": 2}, None, lambda *_: True,
                              discover=lambda action, number: said.append((action, number)) or "studying")
        self.assertEqual((result, said), ("studying", [("add", 2)]))
        self.assertIn("isn't available", execute_tool("discover", {"action": "list"}, None, lambda *_: True))

    def test_tokens_are_checked_before_they_are_kept(self) -> None:
        with self.assertRaises(ValueError):
            discover.save_token("password123")
        self.assertTrue(discover.TOKEN_SHAPE.match("ghp_" + "a" * 36))


if __name__ == "__main__":
    unittest.main()
