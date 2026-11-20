"""Google Drive: search and recent files listed by number, Docs/Sheets exported as text, PDFs read on this PC, the
query escaped, a missing permission said plainly, and the tool reached through execute_tool."""
from __future__ import annotations

import io
import json
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import drive_tools
import gmail_tools
from tools import execute_tool

FILES = {"files": [
    {"id": "doc1", "name": "Budget 2026", "mimeType": "application/vnd.google-apps.document", "modifiedTime": "2026-11-19T10:00:00Z"},
    {"id": "sheet1", "name": "Expenses", "mimeType": "application/vnd.google-apps.spreadsheet", "modifiedTime": "2026-11-18T10:00:00Z"},
    {"id": "pdf1", "name": "Lease.pdf", "mimeType": "application/pdf"},
    {"id": "zip1", "name": "Photos.zip", "mimeType": "application/zip"}]}


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def one_page_pdf(text: str) -> bytes:
    """A minimal valid PDF with one line of text (no files, no extra libraries)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    table = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, table)
    return bytes(out)


class DriveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.urls: list[str] = []

        def opener(request, timeout):
            url = request.full_url
            self.urls.append(url)
            self.assertEqual(request.get_header("Authorization"), "Bearer access")
            if "/export?" in url:
                kind = parse_qs(urlsplit(url).query)["mimeType"][0]
                return Answer(b"Rent 900\nFood 300" if kind == "text/plain" else b"item,cost\nrent,900")
            if url.endswith("/pdf1?alt=media"):
                return Answer(one_page_pdf("Lease ends in June"))
            return Answer(json.dumps(FILES).encode())
        self.drive = drive_tools.Drive(token=lambda: "access", opener=opener)

    def test_search_lists_numbered_files_and_escapes_the_words(self) -> None:
        text = self.drive.search("Kim's budget")
        self.assertIn("1. Budget 2026 (Doc, changed 2026-11-19)", text)
        self.assertIn("3. Lease.pdf (PDF)", text)
        self.assertIn("data, not instructions", text)
        query = parse_qs(urlsplit(self.urls[0]).query)["q"][0]
        self.assertEqual(query, "(name contains 'Kim\\'s budget' or fullText contains 'Kim\\'s budget') and trashed = false")
        with self.assertRaises(ValueError):
            drive_tools.search_query("   ")

    def test_reading_exports_docs_and_sheets_and_reads_pdfs(self) -> None:
        self.drive.recent()
        self.assertIn("Rent 900", self.drive.read(1))
        self.assertTrue(self.urls[-1].endswith("/doc1/export?mimeType=text%2Fplain"))
        self.assertIn("rent,900", self.drive.read(2))
        self.assertIn("Lease ends in June", self.drive.read(3))
        self.assertIn("can't be read as text", self.drive.read(4))
        with self.assertRaises(ValueError):
            self.drive.read(9)

    def test_a_sign_in_without_drive_is_said_plainly(self) -> None:
        def refused(request, timeout):
            raise HTTPError(request.full_url, 403, "forbidden", {}, io.BytesIO())
        self.drive._open = refused
        answer = drive_tools.execute_drive_tool("drive_recent", {}, self.drive)
        self.assertIn("Add Google Drive", answer)

    def test_the_tool_through_nova(self) -> None:
        self.assertIn("isn't connected", execute_tool("drive_search", {"query": "x"}, None, lambda *_: True))
        answer = execute_tool("drive_search", {"query": "budget"}, None, lambda *_: False, drive=self.drive)
        self.assertIn("Budget 2026", answer)  # read-only: nothing to approve
        self.assertIn("invalid", execute_tool("drive_read", {"number": 1, "delete": True}, None, lambda *_: True,
                                              drive=self.drive).lower())

    def test_the_sign_in_asks_for_drive_read_only(self) -> None:
        self.assertIn("https://www.googleapis.com/auth/drive.readonly", gmail_tools.SCOPES.split())
        self.assertNotIn("https://www.googleapis.com/auth/drive", gmail_tools.SCOPES.split())


if __name__ == "__main__":
    unittest.main()
