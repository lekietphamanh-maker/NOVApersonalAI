"""Direct app control: real Word, Excel and PowerPoint files from what Nova writes, OBS through obs-websocket with
its password handshake, VS Code only for the owner's own folders, and the tools asking first where it matters."""
from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_control as apps
from tools import execute_tool


class DocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.opened: list[Path] = []

    def make(self, kind: str, content: str, chart: str = "none") -> str:
        return apps.make_document(kind, "Trip plan", content, chart, folder=self.folder, opener=self.opened.append)

    def test_word_keeps_headings_lists_and_bold(self) -> None:
        answer = self.make("word", "# Day 1\n- Ben Thanh market\n- **Pho** for lunch\n\n## Day 2\n1. Museum\nPlain line")
        from docx import Document
        document = Document(self.opened[0])
        styles = [(paragraph.style.name, paragraph.text) for paragraph in document.paragraphs]
        self.assertIn(("Heading 1", "Day 1"), styles)
        self.assertIn(("List Bullet", "Pho for lunch"), styles)
        self.assertIn(("List Number", "Museum"), styles)
        bold = [run.text for paragraph in document.paragraphs for run in paragraph.runs if run.bold]
        self.assertEqual(bold, ["Pho"])
        self.assertIn("a Word document", answer)
        self.make("word", "again")
        self.assertEqual(self.opened[1].name, "Trip plan (2).docx")  # never overwrites

    def test_excel_numbers_and_a_chart(self) -> None:
        answer = self.make("excel", "| Month | Spent |\n|---|---|\n| Jan | 1,200 |\n| Feb | 950.5 |", chart="bar")
        from openpyxl import load_workbook
        sheet = load_workbook(self.opened[0]).active
        self.assertEqual([[cell.value for cell in row] for row in sheet.iter_rows()],
                         [["Month", "Spent"], ["Jan", 1200], ["Feb", 950.5]])
        self.assertEqual(len(sheet._charts), 1)
        self.assertIn("2 rows and 2 columns and a bar chart", answer)
        with self.assertRaises(ValueError):
            self.make("excel", "just one line")

    def test_powerpoint_slides_from_an_outline(self) -> None:
        self.make("powerpoint", "# Why\n- It's fast\n- It's private\n# How\n- Ollama")
        from pptx import Presentation
        slides = Presentation(self.opened[0]).slides
        self.assertEqual([slide.shapes.title.text for slide in slides], ["Trip plan", "Why", "How"])
        self.assertEqual(slides[1].placeholders[1].text_frame.text, "It's fast\nIt's private")


class FakeSocket:
    def __init__(self, password: str = "", result: bool = True) -> None:
        self.sent: list[dict] = []
        auth = {"challenge": "ch", "salt": "sa"} if password else None
        self.replies = [{"op": 0, "d": {"authentication": auth} if auth else {}}, {"op": 2, "d": {}},
                        {"op": 7, "d": {"requestStatus": {"result": result, "code": 100 if result else 600, "comment": "nope"},
                                        "responseData": {"outputActive": True}}}]
        self.closed = False

    def recv(self) -> str:
        return json.dumps(self.replies.pop(0))

    def send(self, text: str) -> None:
        self.sent.append(json.loads(text))

    def close(self) -> None:
        self.closed = True


class ObsTests(unittest.TestCase):
    def test_the_password_handshake_and_a_request(self) -> None:
        socket = FakeSocket(password="secret")
        self.assertEqual(apps.obs("start_recording", password="secret", connect=lambda: socket), "Recording started.")
        secret = base64.b64encode(hashlib.sha256(b"secretsa").digest()).decode()
        expected = base64.b64encode(hashlib.sha256((secret + "ch").encode()).digest()).decode()
        self.assertEqual(socket.sent[0]["d"]["authentication"], expected)
        self.assertEqual(socket.sent[1]["d"]["requestType"], "StartRecord")
        self.assertTrue(socket.closed)

    def test_problems_are_said_plainly(self) -> None:
        with self.assertRaises(ValueError):
            apps.obs("start_recording", connect=lambda: FakeSocket(password="secret"))  # no password saved
        self.assertIn("OBS said no", apps.obs("stop_recording", connect=lambda: FakeSocket(result=False)))
        def refused():
            raise ConnectionRefusedError()
        with self.assertRaises(OSError) as caught:
            apps.obs("status", connect=refused)
        self.assertIn("WebSocket Server Settings", str(caught.exception))


class VsCodeTests(unittest.TestCase):
    def test_only_the_owners_folders(self) -> None:
        started: list = []
        home = Path(tempfile.mkdtemp())
        (home / "site").mkdir()
        (home / "site" / "index.html").write_text("<h1>hi</h1>")
        with patch.object(apps.Path, "home", lambda: home):
            answer = apps.vscode(str(home / "site" / "index.html"), 12, run=lambda *a, **k: started.append(a[0]),
                                 which=lambda name: "/bin/code")
            self.assertEqual(started[0], ["/bin/code", "--goto", f"{home / 'site' / 'index.html'}:12"])
            self.assertIn("at line 12", answer)
            with self.assertRaises(ValueError):
                apps.vscode("/etc", run=lambda *a, **k: None, which=lambda name: "/bin/code")


class ToolTests(unittest.TestCase):
    def test_going_live_asks_first(self) -> None:
        asked: list = []
        answer = execute_tool("obs", {"action": "start_streaming"}, None, lambda name, details: asked.append(name) or False)
        self.assertEqual((answer, asked), ("The owner declined; nothing was streamed.", ["obs_stream"]))


if __name__ == "__main__":
    unittest.main()
