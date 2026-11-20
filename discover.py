"""Discover: GitHub repos the owner might like, ranked by their interests and their own GitHub, learning from their picks.

Nova never installs code from GitHub into herself. "Add to Nova" pins the repo to one commit, records its license, and
hands it to Claude Code (read-only) to study; what comes back is a plan in outputs/ and, when the repo is a workflow or a
prompt, a skill note the owner reads and approves before it joins their skills. Skills are text, not code.

What shapes the ranking: the interests in Settings, the topics and languages of the owner's own and starred repos (when
they give their GitHub username), and every Add or Not for me so far (liked topics and languages count up, skipped ones
down). Results are cached for 12 hours; a GitHub token (optional, Settings) raises the rate limit.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

GITHUB = "https://api.github.com"
CACHE_HOURS = 12
PER_INTEREST = 10
SHOWN = 12
MAX_HISTORY = 400
RECENT_DAYS = 120
SKILL_FENCE = re.compile(r"```skill\s*\n(.*?)\n```", re.DOTALL)
REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
USER_NAME = re.compile(r"^[A-Za-z0-9-]{1,39}$")


TOKEN_SHAPE = re.compile(r"^(gh[pousr]_[A-Za-z0-9]{30,255}|github_pat_[A-Za-z0-9_]{30,255})$")


def token_path() -> Path:
    import os
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Alfred" / "github_token"


def stored_token() -> str | None:
    try:
        value = token_path().read_text(encoding="utf-8-sig").strip()
    except OSError:
        return None
    return value if TOKEN_SHAPE.match(value) else None


def save_token(value: str) -> None:
    """An optional GitHub token (read-only public access is enough): only raises the rate limit."""
    value = value.strip()
    if not TOKEN_SHAPE.match(value):
        raise ValueError("That doesn't look like a GitHub token (it starts with ghp_ or github_pat_).")
    token_path().parent.mkdir(parents=True, exist_ok=True)
    token_path().write_text(value, encoding="utf-8")


def forget_token() -> None:
    token_path().unlink(missing_ok=True)


class DiscoverError(RuntimeError):
    """GitHub couldn't be asked; said as the owner needs it."""


def words(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9+#]+", str(text).lower()) if len(word) > 1}


def profile(repos: list[dict[str, Any]]) -> dict[str, Counter]:
    """The topics and languages the owner's own and starred repos lean towards."""
    topics, languages = Counter(), Counter()
    for repo in repos:
        topics.update(repo.get("topics") or [])
        if repo.get("language"):
            languages[repo["language"]] += 1
    return {"topics": topics, "languages": languages}


def taste(history: dict[str, list[dict[str, Any]]]) -> dict[str, Counter]:
    """What the owner's Add and Not for me so far say: liked topics and languages up, skipped ones down."""
    topics, languages = Counter(), Counter()
    for decided, weight in (("accepted", 1), ("rejected", -1)):
        for item in history.get(decided, []):
            for topic in item.get("topics") or []:
                topics[topic] += weight
            if item.get("language"):
                languages[item["language"]] += weight
    return {"topics": topics, "languages": languages}


def rank(found: list[dict[str, Any]], interests: list[str], mine: dict[str, Counter], learned: dict[str, Counter],
         decided: set[str], now: datetime) -> list[dict[str, Any]]:
    """Scores each repo and says why, best first. Repos already added or skipped are left out."""
    wanted = [(interest, words(interest)) for interest in interests if words(interest)]
    ranked = []
    for repo in found:
        name = repo.get("full_name", "")
        if not name or name in decided or repo.get("archived") or repo.get("fork"):
            continue
        text = words(" ".join([name.replace("/", " "), repo.get("description") or "", " ".join(repo.get("topics") or [])]))
        topics, language = repo.get("topics") or [], repo.get("language") or ""
        stars = int(repo.get("stargazers_count") or 0)
        score, why = math.log10(stars + 1), []
        matched = [interest for interest, need in wanted if need <= text]
        if matched:
            score += 2.5
            why.append(f"matches your interest “{matched[0]}”")
        shared = [topic for topic in topics if mine["topics"].get(topic)]
        if shared:
            score += min(2.0, 0.5 * len(shared))
            why.append(f"topics like your repos ({', '.join(shared[:2])})")
        if language and mine["languages"].get(language):
            score += 0.75
            why.append(f"{language}, like your repos")
        liked = sum(learned["topics"].get(topic, 0) for topic in topics) + learned["languages"].get(language, 0)
        if liked:
            score += max(-3.0, min(3.0, 0.6 * liked))
            why.append("like ones you added" if liked > 0 else "like ones you skipped")
        pushed = _when(repo.get("pushed_at"))
        if pushed and now - pushed < timedelta(days=RECENT_DAYS):
            score += 0.5
            why.append(f"updated {max(0, (now - pushed).days)} days ago")
        why.append(f"{_short(stars)} stars")
        ranked.append({"repo": name, "url": repo.get("html_url") or f"https://github.com/{name}",
                       "about": " ".join(str(repo.get("description") or "").split())[:240], "stars": stars,
                       "language": language, "topics": topics[:8], "license": ((repo.get("license") or {}).get("spdx_id") or ""),
                       "score": round(score, 2), "why": "; ".join(why)})
    return sorted(ranked, key=lambda item: item["score"], reverse=True)


def _when(stamp: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


def _short(number: int) -> str:
    return f"{number / 1000:.1f}k" if number >= 1000 else str(number)


def skill_from(text: str) -> str | None:
    """The skill note Claude Code proposed in its study (```skill … ```), if it proposed one."""
    found = SKILL_FENCE.search(text or "")
    return found.group(1).strip() if found else None


def study_task(item: dict[str, Any]) -> str:
    """What Claude Code is asked: read the pinned repo (no running it) and say how Nova could use it."""
    return (f"Study the GitHub repository {item['repo']} at commit {item['sha']} ({item['url']}/tree/{item['sha']}); "
            f"its license is {item.get('license') or 'not stated'}. Read its README and main files from that commit only; "
            "never run or install anything from it. Then write, in Markdown: what it does in three lines; whether Nova "
            "(the owner's Windows voice assistant) could use it, and how: (a) as a Nova skill, when it is a workflow, a "
            "prompt or a method Nova can follow with her own tools; (b) as a separate project Claude Code could build "
            "in Documents/Nova Projects; or (c) not at all, with why. Note anything risky: what it would need access to, "
            "and whether the license allows the use. If (a), end with the skill note in a fenced block marked skill, in "
            "this format:\n```skill\n---\ntitle: <short title>\nsays: <phrases that start it, comma separated>\n"
            "schedule: manual\ntools: \nbrain: auto\noutput: yes\n---\n<what Nova should do, step by step>\n```")


class Discover:
    def __init__(self, path: Path, token: Callable[[], str | None] = lambda: None, opener: Callable[..., Any] = urlopen,
                 clock: Callable[[], float] = time.time) -> None:
        self.path, self.token, self._open, self.clock = Path(path), token, opener, clock
        self._lock = threading.Lock()

    # ---------- what's kept: decisions and the cache ----------

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def history(self) -> dict[str, list[dict[str, Any]]]:
        data = self._load()
        return {"accepted": data.get("accepted", []), "rejected": data.get("rejected", [])}

    # ---------- asking GitHub ----------

    def _get(self, path: str) -> Any:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "Nova-discover"}
        token = self.token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            with self._open(Request(GITHUB + path, headers=headers), timeout=20) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            if exc.code in (403, 429):
                raise DiscoverError("GitHub is limiting requests right now (a token in Settings raises the limit)") from None
            if exc.code == 401:
                raise DiscoverError("GitHub refused the token in Settings") from None
            raise DiscoverError(f"GitHub said {exc.code}") from None
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise DiscoverError(f"couldn't reach GitHub ({type(exc).__name__})") from None

    def _search(self, interest: str, since: str) -> list[dict[str, Any]]:
        query = f"{interest} stars:>30 pushed:>{since} archived:false"
        return self._get("/search/repositories?" + urlencode(
            {"q": query, "sort": "stars", "order": "desc", "per_page": PER_INTEREST})).get("items", [])

    def _owner_repos(self, username: str) -> list[dict[str, Any]]:
        if not USER_NAME.match(username or ""):
            return []
        name = quote(username)
        return list(self._get(f"/users/{name}/repos?sort=pushed&per_page=50") or []) + \
            list(self._get(f"/users/{name}/starred?per_page=50") or [])

    def suggestions(self, interests: list[str], username: str = "", force: bool = False) -> list[dict[str, Any]]:
        """The ranked suggestions (cached for 12 hours unless force). DiscoverError when GitHub can't be asked."""
        interests = [" ".join(str(interest).split())[:60] for interest in interests if str(interest).strip()][:8]
        data = self._load()
        cache = data.get("cache") or {}
        key = json.dumps([interests, username])
        if not force and cache.get("key") == key and self.clock() - float(cache.get("at", 0)) < CACHE_HOURS * 3600:
            found, mine = cache.get("found", []), cache.get("mine", [])
        else:
            since = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
            found = [repo for interest in (interests or ["developer tools"]) for repo in self._search(interest, since)]
            mine = [{"topics": repo.get("topics") or [], "language": repo.get("language")}
                    for repo in self._owner_repos(username)]
            with self._lock:
                data = self._load()
                data["cache"] = {"key": key, "at": self.clock(), "found": found, "mine": mine}
                self._save(data)
        unique = list({repo.get("full_name"): repo for repo in found}.values())
        decided = {item["repo"] for items in self.history().values() for item in items}
        own = {repo.get("full_name") for repo in unique if username and str(repo.get("full_name", "")).lower().startswith(username.lower() + "/")}
        ranked = rank(unique, interests, profile(mine), taste(self.history()), decided | own, datetime.now(timezone.utc))
        return ranked[:SHOWN]

    # ---------- the owner's choices ----------

    def pin(self, item: dict[str, Any]) -> dict[str, Any]:
        """The exact commit the study will read, and the license from GitHub: recorded with the decision."""
        if not REPO_NAME.match(str(item.get("repo", ""))):
            raise DiscoverError("that isn't a GitHub repository name")
        details = self._get(f"/repos/{item['repo']}")
        branch = quote(str(details.get("default_branch") or "main"))
        commit = self._get(f"/repos/{item['repo']}/commits/{branch}")
        return {**item, "sha": str(commit.get("sha", ""))[:40], "license": (details.get("license") or {}).get("spdx_id") or "",
                "topics": details.get("topics") or item.get("topics") or [], "language": details.get("language") or item.get("language", "")}

    def decide(self, item: dict[str, Any], added: bool) -> None:
        record = {key: item.get(key) for key in ("repo", "url", "sha", "license", "topics", "language")}
        record["at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with self._lock:
            data = self._load()
            for decided in ("accepted", "rejected"):
                data[decided] = [entry for entry in data.get(decided, []) if entry.get("repo") != record["repo"]]
            data["accepted" if added else "rejected"] = (data.get("accepted" if added else "rejected", []) + [record])[-MAX_HISTORY:]
            self._save(data)
