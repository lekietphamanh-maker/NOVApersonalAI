"""Nova's library: the owner's projects, repos and ideas to build, sorted by topic, inside the second brain vault.

    <vault>/library/<Title>.md    one per project or idea, with Obsidian properties:
        ---
        status: "building"        idea | building | shipped | paused
        topic: "AI"
        repo: "https://github.com/you/project"   (or a folder on this PC)
        next: "Wire the voice commands"
        added: "2026-11-19"
        updated: "2026-11-19 14:05"
        ---
        # Title
        Topic: [[AI]]

        Notes…

Topics are the second brain's wiki pages (wiki/<Topic>.md) plus any topic a project names. Opening a topic shows its
projects and ideas, the wiki page's summary and newest facts. It is plain Markdown in the vault, so Obsidian shows it
and Syncthing shares it with the owner's other PC; one file per project keeps the two PCs off each other's files.
"""
from __future__ import annotations

import difflib
import json
import re
import threading
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from second_brain import page_name

STATUSES = ("idea", "building", "shipped", "paused")
STALE_DAYS = 7      # building, untouched this long: stalled
UNSORTED = "Unsorted"
FIELDS = ("status", "topic", "repo", "next", "added", "updated")
_LINK = re.compile(r"\[\[([^\]|#]+)")


@dataclass
class Project:
    title: str
    status: str = "idea"
    topic: str = ""
    repo: str = ""
    next: str = ""
    note: str = ""
    added: str = ""
    updated: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def plain(text: str) -> str:
    """For matching what was said: lower case, no accents (đ → d), single spaces."""
    text = unicodedata.normalize("NFKD", str(text).replace("đ", "d").replace("Đ", "D"))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


def _one_line(text: str, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def _check_repo(repo: str) -> str:
    repo = str(repo or "").strip().strip('"')
    if not repo:
        return ""
    if urlsplit(repo).scheme in ("http", "https") and urlsplit(repo).netloc:
        return repo[:400]
    if re.match(r"^[A-Za-z]:[\\/]", repo) or repo.startswith(("\\\\", "/")):
        return repo[:400]
    if re.fullmatch(r"(github\.com|gitlab\.com|codeberg\.org)/[\w.\-]+/[\w.\-]+/?", repo):
        return "https://" + repo
    raise ValueError("The repo must be a web link (https://…) or a whole folder path (C:\\…).")


def parse(text: str, title: str) -> Project:
    """A library file's properties and notes. Unknown properties are left alone (the owner may add their own)."""
    props: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].splitlines():
                key, colon, value = line.partition(":")
                if not colon:
                    continue
                value = value.strip()
                if value.startswith('"'):
                    try:
                        value = str(json.loads(value))
                    except ValueError:
                        value = value.strip('"')
                props[key.strip().lower()] = value.strip("'")
            body = text[end + 4:]
    lines = body.strip("\n").splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    if lines and lines[0].strip() == "":
        lines = lines[1:]
    if lines and lines[0].startswith("Topic: "):
        lines = lines[1:]
    status = props.get("status", "idea").lower()
    return Project(title=title, status=status if status in STATUSES else "idea", topic=props.get("topic", ""),
                   repo=props.get("repo", ""), next=props.get("next", ""), note="\n".join(lines).strip(),
                   added=props.get("added", ""), updated=props.get("updated", ""))


def render(project: Project) -> str:
    header = "".join(f"{key}: {json.dumps(getattr(project, key), ensure_ascii=False)}\n"
                     for key in FIELDS if getattr(project, key))
    body = f"# {project.title}\n\n" + (f"Topic: [[{project.topic}]]\n\n" if project.topic else "")
    return f"---\n{header}---\n{body}{project.note.strip()}\n".replace("\n\n\n", "\n\n")


def _when(stamp: str) -> datetime | None:
    for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(stamp[:16].strip(), pattern)
        except ValueError:
            continue
    return None


def _wiki_page(path: Path) -> dict:
    """A topic page's summary (its first paragraph), facts, sources and related topics."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    summary = next((line.strip() for line in lines[1:] if line.strip() and not line.startswith(("#", "-", "Related:"))), "")
    facts = [line[2:].strip() for line in lines if line.startswith("- ")]
    related: list[str] = []
    for line in lines:
        if line.startswith("Related:"):
            related += [page_name(link) for link in _LINK.findall(line)]
    return {"summary": summary[:300], "facts": facts, "sources": sum(1 for line in lines if line.startswith("## ")),
            "related": sorted(set(related) - {path.stem}), "updated": datetime.fromtimestamp(path.stat().st_mtime)}


class Library:
    def __init__(self, vault: Path) -> None:
        self.vault = Path(vault)
        self.folder = self.vault / "library"
        self.wiki = self.vault / "wiki"
        self._lock = threading.Lock()

    # ---- projects and ideas ----
    def _files(self) -> list[Path]:
        if not self.folder.is_dir():
            return []
        # Syncthing keeps both versions when the two PCs changed one file at once: the copy is not a second project.
        return sorted(path for path in self.folder.glob("*.md") if ".sync-conflict-" not in path.name)

    def projects(self) -> list[Project]:
        found = []
        for path in self._files():
            try:
                found.append(parse(path.read_text(encoding="utf-8", errors="replace"), path.stem))
            except OSError:
                continue
        return found

    def find(self, title: str) -> Project | None:
        """By title: exact (any case or accents), then the closest one that is clearly meant."""
        wanted = plain(title)
        if not wanted:
            return None
        projects = self.projects()
        for project in projects:
            if plain(project.title) == wanted:
                return project
        names = {plain(project.title): project for project in projects}
        close = difflib.get_close_matches(wanted, list(names), n=1, cutoff=0.72)
        if close:
            return names[close[0]]
        contains = [project for key, project in names.items() if wanted in key or (len(key) > 3 and key in wanted)]
        return contains[0] if len(contains) == 1 else None

    def _exact(self, title: str) -> Project | None:
        return next((project for project in self.projects() if plain(project.title) == plain(title)), None)

    def save(self, title: str, previous: str = "", status: str | None = None, topic: str | None = None,
             repo: str | None = None, next: str | None = None, note: str | None = None,  # noqa: A002
             new: bool = False) -> Project:
        """Make or change one. Fields left as None keep what was there; previous is its old title when renamed;
        new refuses a title that is already there (so a new idea never overwrites a project)."""
        name = page_name(title)
        if not name:
            raise ValueError("Give the project or idea a title.")
        if status is not None and status not in STATUSES:
            raise ValueError(f"The status is one of: {', '.join(STATUSES)}.")
        with self._lock:
            old = self._exact(previous) if previous else None
            same = self._exact(name)
            if same is not None and (new or (old is not None and plain(old.title) != plain(name))):
                raise ValueError(f"There is already one called {same.title} in the library: open it to change it.")
            old = old or same
            project = Project(title=name) if old is None else Project(**{**old.as_dict(), "title": name})
            if status is not None:
                project.status = status
            if topic is not None:
                project.topic = page_name(topic)
            if repo is not None:
                project.repo = _check_repo(repo)
            if next is not None:
                project.next = _one_line(next, 200)
            if note is not None:
                project.note = str(note).strip()[:4000]
            now = datetime.now()
            project.added = project.added or f"{now:%Y-%m-%d}"
            project.updated = f"{now:%Y-%m-%d %H:%M}"
            self.folder.mkdir(parents=True, exist_ok=True)
            target = self.folder / f"{name}.md"
            if old is not None and old.title != name:
                (self.folder / f"{old.title}.md").replace(target)  # a rename (also only the letters' case, on Windows)
            target.write_text(render(project), encoding="utf-8")
        return project

    def delete(self, title: str) -> bool:
        project = self.find(title)
        if project is None or plain(project.title) != plain(title):
            return False
        with self._lock:
            (self.folder / f"{project.title}.md").unlink(missing_ok=True)
        return True

    # ---- topics ----
    def _pages(self) -> dict[str, Path]:
        if not self.wiki.is_dir():
            return {}
        return {path.stem: path for path in self.wiki.glob("*.md") if path.stem != "index"}

    def topic_name(self, topic: str, pages: dict[str, Path] | None = None) -> str:
        """The wiki page's own spelling when there is one ("ai" → "AI"), else the project's."""
        topic = page_name(topic)
        if not topic:
            return UNSORTED
        pages = self._pages() if pages is None else pages
        return next((name for name in pages if plain(name) == plain(topic)), topic)

    def topics(self, projects: list[Project] | None = None) -> list[dict]:
        """Every topic with what is in it, the most recently active first."""
        pages = self._pages()
        projects = self.projects() if projects is None else projects
        topics: dict[str, dict] = {}
        for name, path in pages.items():
            try:
                page = _wiki_page(path)
            except OSError:
                continue
            topics[name] = {"name": name, "summary": page["summary"], "notes": len(page["facts"]), "sources": page["sources"],
                            "related": page["related"][:8], "updated": page["updated"], "ideas": 0, "projects": 0,
                            "needs": 0, "wiki": True}
        needing = {item["title"] for item in self.needs(projects)}
        for project in projects:
            name = self.topic_name(project.topic, pages)
            topic = topics.setdefault(name, {"name": name, "summary": "", "notes": 0, "sources": 0, "related": [],
                                             "updated": datetime.min, "ideas": 0, "projects": 0, "needs": 0, "wiki": False})
            topic["ideas" if project.status == "idea" else "projects"] += 1
            topic["needs"] += project.title in needing
            when = _when(project.updated)
            if when and when > topic["updated"]:
                topic["updated"] = when
        ordered = sorted(topics.values(), key=lambda topic: (topic["name"] == UNSORTED, -topic["updated"].timestamp()
                                                                if topic["updated"] > datetime.min else 0, topic["name"]))
        for topic in ordered:
            topic["updated"] = f"{topic['updated']:%Y-%m-%d %H:%M}" if topic["updated"] > datetime.min else ""
        return ordered

    def topic(self, name: str) -> dict:
        """One topic opened: its wiki summary, newest facts, related topics, projects and ideas."""
        pages = self._pages()
        name = self.topic_name(name, pages)
        page = {"summary": "", "facts": [], "sources": 0, "related": []}
        if name in pages:
            try:
                page = _wiki_page(pages[name])
            except OSError:
                pass
        projects = [project.as_dict() for project in self.projects() if self.topic_name(project.topic, pages) == name]
        return {"name": name, "summary": page["summary"], "facts": page["facts"][-12:][::-1], "notes": len(page["facts"]),
                "sources": page["sources"], "related": page["related"][:12], "projects": projects, "wiki": name in pages}

    # ---- what needs the owner ----
    def needs(self, projects: list[Project] | None = None, now: datetime | None = None) -> list[dict]:
        """Stalled builds first (longest first), then builds with their next step, then ideas to decide on."""
        now = now or datetime.now()
        ranked = []
        for project in self.projects() if projects is None else projects:
            when = _when(project.updated) or now
            days = max(0, (now - when).days)
            if project.status == "building":
                if days >= STALE_DAYS:
                    why, rank, order = f"Stalled {days} days" + (f" · next: {project.next}" if project.next else ""), 0, -days
                else:
                    why, rank, order = (f"Next: {project.next}" if project.next else "Building · no next step yet"), 1, -days
            elif project.status == "idea":
                why, rank, order = (f"Next: {project.next}" if project.next else "Idea · build it or park it?"), 2, days
            else:
                continue
            ranked.append((rank, order, project.title.casefold(), {**project.as_dict(), "why": why, "days": days}))
        return [item for *_key, item in sorted(ranked, key=lambda entry: entry[:3])]

    def snapshot(self) -> dict:
        projects = self.projects()
        return {"topics": self.topics(projects), "projects": [project.as_dict() for project in projects],
                "needs": self.needs(projects), "statuses": list(STATUSES), "folder": str(self.folder)}

    # ---- for voice: "open robotics", "go to the drone app" ----
    def match(self, text: str) -> dict | None:
        """The topic or project the owner named: {"kind": "topic" | "project", "name": …}, or None."""
        wanted = plain(re.sub(r"\b(topic|project|idea|repo|shelf)\b", " ", plain(text)))
        if not wanted:
            return None
        candidates = {plain(topic["name"]): ("topic", topic["name"]) for topic in self.topics()}
        candidates.update({plain(project.title): ("project", project.title) for project in self.projects()})
        if wanted in candidates:
            kind, name = candidates[wanted]
            return {"kind": kind, "name": name}
        close = difflib.get_close_matches(wanted, list(candidates), n=1, cutoff=0.75)
        if close:
            kind, name = candidates[close[0]]
            return {"kind": kind, "name": name}
        starts = [key for key in candidates if key.startswith(wanted) or wanted.startswith(key) and len(key) > 3]
        if len(starts) == 1:
            kind, name = candidates[starts[0]]
            return {"kind": kind, "name": name}
        return None

    # ---- for Nova's answers ----
    def needs_text(self) -> str:
        needs = self.needs()
        if not needs:
            return "Nothing in the library needs the owner right now (no builds or ideas waiting)."
        return "What needs the owner in their library (most urgent first):\n" + "\n".join(
            f"{index}. {item['title']} ({item['status']}, {self.topic_name(item['topic'])}): {item['why']}"
            for index, item in enumerate(needs[:10], start=1))

    def topic_text(self, name: str) -> str:
        topic = self.topic(name)
        if not topic["wiki"] and not topic["projects"]:
            names = ", ".join(item["name"] for item in self.topics()[:12]) or "none yet"
            return f"There is no topic called {name} in the library. Topics: {names}."
        lines = [f"Topic {topic['name']}: {topic['summary'] or 'no wiki page yet'} ({topic['notes']} notes in the wiki)."]
        lines += [f"- {item['title']} ({item['status']})" + (f": next {item['next']}" if item["next"] else "")
                  for item in topic["projects"]]
        if topic["facts"]:
            lines.append("Newest notes: " + " | ".join(topic["facts"][:5]))
        return "\n".join(lines)


# ---- voice commands while the Library is on screen: handled at once, without asking the model ----
_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "eleven": 11, "twelve": 12, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "mot": 1, "hai": 2,
            "ba": 3, "bon": 4, "nam": 5, "sau": 6, "bay": 7, "tam": 8, "chin": 9, "muoi": 10}
_SAID = {
    "next": {"next", "next one", "right", "go right", "forward", "tiep", "tiep theo", "ke tiep"},
    "previous": {"previous", "previous one", "prev", "left", "go left", "last one", "before", "lui", "truoc"},
    "open": {"open", "open it", "open this", "open this one", "pick", "pick it", "pick this", "pick this one", "select",
             "select this", "select it", "this one", "enter", "go in", "show me", "mo", "mo ra", "chon", "chon cai nay"},
    "back": {"back", "go back", "back up", "up", "out", "exit topic", "quay lai", "tro lai"},
    "close": {"close", "close it", "close library", "close the library", "exit", "exit library", "done", "dong",
              "dong thu vien", "thoat"},
}
_SHELVES = {"topics": "topics", "topic": "topics", "projects": "projects", "project": "projects", "repos": "projects",
            "ideas": "ideas", "idea": "ideas", "needs": "needs", "needs you": "needs", "needs me": "needs",
            "what needs me": "needs", "what needs you": "needs", "what needs my attention": "needs", "to do": "needs"}
_FILLER = re.compile(r"^(hey nova|ok nova|nova|please|can you|could you|now)\s+|\s+(please|now|thanks|thank you)$")


def parse_command(text: str) -> dict | None:
    """What the owner said to the Library on screen: {"command": next | previous | open | back | close | shelf | pick
    | find, …}, or None (a normal request for Nova)."""
    said = plain(text)
    for _ in range(3):
        said = _FILLER.sub("", said).strip()
    if not said or len(said.split()) > 8:
        return None
    for command, phrases in _SAID.items():
        if said in phrases:
            return {"command": command}
    shelf = re.sub(r"^(show me|show|go to|open|switch to|the)\s+", "", said)
    shelf = re.sub(r"^(my|the)\s+", "", shelf)
    if shelf in _SHELVES:
        return {"command": "shelf", "shelf": _SHELVES[shelf]}
    number = re.fullmatch(r"(?:open|pick|select|go to|show|choose|chon|mo)?\s*(?:number|card|so)?\s*(\d{1,3}|[a-z]+)", said)
    if number and (number.group(1).isdigit() or number.group(1) in _NUMBERS):
        value = int(number.group(1)) if number.group(1).isdigit() else _NUMBERS[number.group(1)]
        if value >= 1 and number.group(0) != number.group(1) or number.group(1).isdigit():
            return {"command": "pick", "number": value}
    named = re.fullmatch(r"(?:open|go to|show|show me|find|pick|jump to|take me to|mo)\s+(?:the\s+|my\s+)?(.+)", said)
    if named:
        return {"command": "find", "text": named.group(1)}
    return None
