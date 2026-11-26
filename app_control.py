"""Direct app control: Nova works through an app's own files or remote control instead of clicking through its window.

- Word, Excel and PowerPoint: Nova writes the real .docx / .xlsx / .pptx (headings, lists, tables, a chart, slides)
  and opens it. It's quicker than clicking, can't misclick, and the file is the same one Office makes.
- OBS: its built-in remote control (obs-websocket, Tools → WebSocket Server Settings): record, stream, switch scene.
- VS Code: its own `code` command opens a project, file or line.

Each action answers "done" with what was made, or why it couldn't, so Nova knows. Clicking on the screen stays the
fallback for everything else.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

DOCUMENTS = Path.home() / "Documents" / "Nova Documents"
OBS_URL = "ws://127.0.0.1:4455"
EXTENSIONS = {"word": ".docx", "excel": ".xlsx", "powerpoint": ".pptx"}


def safe_name(title: str) -> str:
    name = re.sub(r"[^\w .,'()-]", "", " ".join(str(title).split()))[:80].strip(" .") or "Untitled"
    return name


def free_path(folder: Path, title: str, extension: str) -> Path:
    """A file name that doesn't overwrite anything: "Budget.xlsx", then "Budget (2).xlsx"…"""
    folder.mkdir(parents=True, exist_ok=True)
    base = safe_name(title)
    path, number = folder / f"{base}{extension}", 2
    while path.exists():
        path, number = folder / f"{base} ({number}){extension}", number + 1
    return path


# ---------- Word ----------

def write_word(path: Path, title: str, text: str) -> int:
    """Markdown-ish text into a real document: "# " and "## " headings, "- " bullets, "1. " numbered items, "**bold**"."""
    from docx import Document
    document = Document()
    document.add_heading(title, level=0)
    count = 0
    for line in str(text).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        heading = re.match(r"^(#{1,3})\s+(.*)", stripped)
        if heading:
            document.add_heading(heading[2], level=len(heading[1]))
        elif re.match(r"^[-*•]\s+", stripped):
            _runs(document.add_paragraph(style="List Bullet"), re.sub(r"^[-*•]\s+", "", stripped))
        elif re.match(r"^\d+[.)]\s+", stripped):
            _runs(document.add_paragraph(style="List Number"), re.sub(r"^\d+[.)]\s+", "", stripped))
        else:
            _runs(document.add_paragraph(), stripped)
        count += 1
    document.save(path)
    return count


def _runs(paragraph: Any, text: str) -> None:
    for index, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if part:
            paragraph.add_run(part).bold = index % 2 == 1


# ---------- Excel ----------

def table_rows(text: str) -> list[list[Any]]:
    """Rows from CSV or a Markdown table; numbers become numbers so sums and charts work."""
    lines = [line.strip() for line in str(text).strip().splitlines() if line.strip()]
    if lines and lines[0].startswith("|"):
        rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines
                if not re.fullmatch(r"\|?[\s:|-]+\|?", line)]
    else:
        rows = list(csv.reader(io.StringIO("\n".join(lines))))
    def value(cell: str) -> Any:
        plain = cell.replace(",", "").replace("$", "").replace("%", "").strip()
        try:
            return float(plain) if "." in plain else int(plain)
        except ValueError:
            return cell
    return [[value(cell) if row_index else cell for cell in row] for row_index, row in enumerate(rows)]


def write_excel(path: Path, title: str, text: str, chart: str = "none") -> tuple[int, int]:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, LineChart, PieChart, Reference
    from openpyxl.styles import Font
    rows = table_rows(text)
    if len(rows) < 2:
        raise ValueError("give the table as rows (CSV or a Markdown table), with a header row")
    book = Workbook()
    sheet = book.active
    sheet.title = safe_name(title)[:31]
    for row in rows:
        sheet.append(row)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = min(48, max(10, *(len(str(cell.value or "")) + 2 for cell in column)))
    numeric = [index for index in range(2, len(rows[0]) + 1)
               if all(isinstance(row[index - 1], (int, float)) for row in rows[1:] if len(row) >= index)]
    if chart in ("bar", "line", "pie") and numeric:
        drawn = {"bar": BarChart, "line": LineChart, "pie": PieChart}[chart]()
        drawn.title = safe_name(title)
        drawn.add_data(Reference(sheet, min_col=numeric[0], max_col=numeric[0] if chart == "pie" else numeric[-1],
                                 min_row=1, max_row=len(rows)), titles_from_data=True)
        drawn.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=len(rows)))
        sheet.add_chart(drawn, f"{chr(ord('A') + len(rows[0]) + 1)}2")
    book.save(path)
    return len(rows) - 1, len(rows[0])


# ---------- PowerPoint ----------

def slides_from(text: str) -> list[tuple[str, list[str]]]:
    """An outline into slides: "# Title" starts a slide, "- point" adds a bullet."""
    slides: list[tuple[str, list[str]]] = []
    for line in str(text).splitlines():
        stripped = line.strip()
        if re.match(r"^#{1,3}\s+", stripped):
            slides.append((re.sub(r"^#{1,3}\s+", "", stripped), []))
        elif stripped and slides:
            slides[-1][1].append(re.sub(r"^[-*•\d.)]+\s*", "", stripped))
        elif stripped:
            slides.append((stripped, []))
    return slides


def write_powerpoint(path: Path, title: str, text: str) -> int:
    from pptx import Presentation
    deck = Presentation()
    cover = deck.slides.add_slide(deck.slide_layouts[0])
    cover.shapes.title.text = title
    slides = slides_from(text)
    for heading, points in slides:
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = heading
        body = slide.placeholders[1].text_frame
        body.text = points[0] if points else ""
        for point in points[1:]:
            body.add_paragraph().text = point
    deck.save(path)
    return len(slides) + 1


def open_file(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - a file Nova just made, opened in its own app


def make_document(kind: str, title: str, content: str, chart: str = "none", folder: Path = DOCUMENTS,
                  opener: Callable[[Path], None] = open_file) -> str:
    if kind not in EXTENSIONS:
        raise ValueError("kind is word, excel or powerpoint")
    path = free_path(folder, title, EXTENSIONS[kind])
    if kind == "word":
        made = f"a Word document with {write_word(path, safe_name(title), content)} paragraphs"
    elif kind == "excel":
        rows, columns = write_excel(path, title, content, chart)
        made = f"an Excel sheet with {rows} rows and {columns} columns" + (f" and a {chart} chart" if chart != "none" else "")
    else:
        made = f"a PowerPoint deck with {write_powerpoint(path, safe_name(title), content)} slides"
    opener(path)
    return f"Made {made}: {path} (opened)."


# ---------- OBS (obs-websocket 5) ----------

OBS_REQUESTS = {"status": "GetRecordStatus", "start_recording": "StartRecord", "stop_recording": "StopRecord",
                "start_streaming": "StartStream", "stop_streaming": "StopStream", "list_scenes": "GetSceneList",
                "switch_scene": "SetCurrentProgramScene"}


def obs_auth(password: str, salt: str, challenge: str) -> str:
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


def obs(action: str, scene: str = "", password: str = "", connect: Callable[..., Any] | None = None) -> str:
    """One OBS request through obs-websocket (on this PC only)."""
    if action not in OBS_REQUESTS:
        raise ValueError(f"OBS can: {', '.join(OBS_REQUESTS)}")
    if connect is None:
        import websocket
        connect = lambda: websocket.create_connection(OBS_URL, timeout=5)  # noqa: E731
    try:
        socket = connect()
    except OSError as exc:
        raise OSError("OBS isn't reachable: open OBS and turn on Tools → WebSocket Server Settings → Enable") from exc
    try:
        hello = json.loads(socket.recv())["d"]
        identify: dict[str, Any] = {"rpcVersion": 1}
        if hello.get("authentication"):
            if not password:
                raise ValueError("OBS asks for its WebSocket password: put it in Settings → Need to → Direct app control")
            identify["authentication"] = obs_auth(password, hello["authentication"]["salt"], hello["authentication"]["challenge"])
        socket.send(json.dumps({"op": 1, "d": identify}))
        json.loads(socket.recv())  # Identified
        data = {"sceneName": " ".join(scene.split())[:100]} if action == "switch_scene" else {}
        socket.send(json.dumps({"op": 6, "d": {"requestType": OBS_REQUESTS[action], "requestId": "nova",
                                              "requestData": data}}))
        reply = json.loads(socket.recv())["d"]
    finally:
        socket.close()
    status = reply.get("requestStatus") or {}
    if not status.get("result"):
        return f"OBS said no: {status.get('comment') or status.get('code')}."
    found = reply.get("responseData") or {}
    if action == "status":
        return "OBS is recording." if found.get("outputActive") else "OBS isn't recording."
    if action == "list_scenes":
        names = [item.get("sceneName") for item in reversed(found.get("scenes") or [])]
        return f"OBS scenes: {', '.join(names)}. On now: {found.get('currentProgramSceneName')}."
    return {"start_recording": "Recording started.", "stop_recording": "Recording stopped.",
            "start_streaming": "Streaming started.", "stop_streaming": "Streaming stopped.",
            "switch_scene": f"Switched to the scene {scene}."}[action]


# ---------- VS Code ----------

def vscode(target: str, line: int = 0, run: Callable[..., Any] = subprocess.Popen,
           which: Callable[[str], str | None] = shutil.which) -> str:
    """Opens a folder or file (at a line) in VS Code. Only things in the owner's own folders."""
    path = Path(os.path.expandvars(os.path.expanduser(str(target).strip().strip('"'))))
    projects = Path.home() / "Documents" / "Nova Projects"
    if not path.is_absolute():
        path = projects / path
    if not path.exists():
        raise ValueError(f"there's no {path}")
    home = Path.home().resolve()  # resolved like the path: short names (RUNNER~1) and junctions compare equal
    if home not in path.resolve().parents and path.resolve() != home:
        raise ValueError("Nova opens only things in your own folders in VS Code")
    code = which("code") or which("code.cmd")
    if code is None:
        raise ValueError("VS Code's `code` command isn't on this PC (install VS Code, or in it: Shell Command: Install 'code')")
    if sys.platform == "win32" and re.search(r'[&|<>^%!"]', str(path)):
        raise ValueError("that path has characters VS Code's launcher (a batch file) would run as commands")
    where = f"{path}:{line}" if line and path.is_file() else str(path)
    run([code, "--goto", where] if line and path.is_file() else [code, where],
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}))
    return f"Opened {path.name} in VS Code" + (f" at line {line}." if line and path.is_file() else ".")
