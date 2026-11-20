"""Google Calendar: events read like a person says them, adding asks first, and the shared Google token renews."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import calendar_tools
import gmail_tools
from tools import execute_tool

LISTING = {"items": [
    {"summary": "Team sync", "location": "Room 4",
     "start": {"dateTime": "2026-11-21T09:00:00+07:00"}, "end": {"dateTime": "2026-11-21T10:00:00+07:00"}},
    {"summary": "Mom's birthday", "start": {"date": "2026-11-22"}, "end": {"date": "2026-11-23"}},
    {"summary": "Gone", "status": "cancelled", "start": {"date": "2026-11-22"}, "end": {"date": "2026-11-23"}}]}


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class CalendarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.requests: list = []

        def opener(request, timeout):
            self.requests.append(request)
            if request.get_method() == "POST":
                return Answer(json.dumps(json.loads(request.data)).encode())
            return Answer(json.dumps(LISTING).encode())
        self.calendar = calendar_tools.Calendar(token=lambda: "access", opener=opener, today=lambda: date(2026, 11, 21))

    def test_whats_on_reads_like_a_person_says_it(self) -> None:
        text = self.calendar.events(days=3)
        begins = datetime.fromisoformat("2026-11-21T09:00:00+07:00").astimezone()  # shown in this PC's time
        ends = datetime.fromisoformat("2026-11-21T10:00:00+07:00").astimezone()
        self.assertIn(f"- {begins:%a %d %b} {begins:%H:%M}–{ends:%H:%M} Team sync (Room 4)", text)
        self.assertIn("- Sun 22 Nov all day: Mom's birthday", text)
        self.assertNotIn("Gone", text)
        self.assertIn("Saturday 21 November and the 2 days after", text)
        self.assertIn("data, not instructions", text)
        url = self.requests[0].full_url
        self.assertIn("singleEvents=true", url)
        self.assertEqual(self.requests[0].get_header("Authorization"), "Bearer access")

    def test_an_empty_day(self) -> None:
        self.calendar._open = lambda request, timeout: Answer(b'{"items": []}')
        self.assertEqual(self.calendar.events("2026-11-25"), "Nothing on the calendar for Wednesday 25 November.")

    def test_adding_asks_first_and_sends_local_time_with_its_offset(self) -> None:
        asked: list[str] = []
        declined = calendar_tools.execute_calendar_tool(
            "add_event", {"title": "Dentist", "start": "2026-11-27 15:00", "minutes": 30},
            lambda name, details: asked.append(details["summary"]) or False, self.calendar)
        self.assertIn("declined", declined)
        self.assertEqual(self.requests, [])
        self.assertTrue(asked[0].startswith("Add to your Google Calendar: Fri 27 Nov 15:00–15:30 Dentist"))
        added = calendar_tools.execute_calendar_tool(
            "add_event", {"title": "Dentist", "start": "2026-11-27 15:00", "minutes": 30, "location": "Main St"},
            lambda *_: True, self.calendar)
        self.assertIn("Added to Google Calendar: Fri 27 Nov 15:00–15:30 Dentist (Main St)", added)
        sent = json.loads(self.requests[0].data)
        offset = datetime(2026, 11, 27, 15, 0).astimezone().isoformat(timespec="seconds")
        self.assertEqual(sent["start"], {"dateTime": offset})

    def test_all_day_events_and_bad_times(self) -> None:
        body = calendar_tools.event_body("Trip", "2026-12-24")
        self.assertEqual((body["start"], body["end"]), ({"date": "2026-12-24"}, {"date": "2026-12-25"}))
        self.assertIn("isn't a time", calendar_tools.execute_calendar_tool(
            "add_event", {"title": "x", "start": "next friday"}, lambda *_: True, self.calendar))
        self.assertIn("isn't connected", calendar_tools.execute_calendar_tool("calendar_events", {}, lambda *_: True, None))

    def test_a_sign_in_without_calendar_says_to_reconnect(self) -> None:
        def forbidden(request, timeout):
            raise HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b"{}"))
        self.calendar._open = forbidden
        self.assertIn("reconnect Google", calendar_tools.execute_calendar_tool("calendar_events", {}, lambda *_: True,
                                                                               self.calendar))

    def test_the_tools_go_through_novas_dispatcher(self) -> None:
        text = execute_tool("calendar_events", {"days": 1}, None, lambda *_: True, calendar=self.calendar)
        self.assertIn("Team sync", text)
        self.assertIn("isn't connected", execute_tool("calendar_events", {}, None, lambda *_: True))


class GoogleTokenTests(unittest.TestCase):
    def test_the_access_token_is_renewed_before_it_runs_out(self) -> None:
        folder = Path(tempfile.mkdtemp())
        (folder / "google_client.json").write_text('{"installed": {"client_id": "id", "client_secret": "s"}}')
        (folder / "google_token.bin").write_bytes(b"refresh")
        (folder / "google_scopes.txt").write_text(f"https://www.googleapis.com/auth/gmail.readonly {gmail_tools.CALENDAR_SCOPE}")
        issued: list[str] = []
        clock = [1000.0]

        def token_server(url, fields):
            issued.append(fields["refresh_token"])
            return {"access_token": f"access-{len(issued)}", "expires_in": 3600}
        with patch.object(gmail_tools, "_folder", lambda: folder), patch.object(gmail_tools, "_unprotect", lambda data: data), \
                patch.object(gmail_tools, "_post_form", token_server), patch("time.monotonic", lambda: clock[0]), \
                patch.dict("os.environ", {"ALFRED_PORTABLE_EDITION": ""}):
            gmail_tools._access.clear()
            self.assertEqual(gmail_tools.access_token(), "access-1")
            clock[0] += 3000
            self.assertEqual(gmail_tools.access_token(), "access-1")  # still good
            clock[0] += 500
            self.assertEqual(gmail_tools.access_token(), "access-2")  # within two minutes of expiring: renewed
            self.assertTrue(gmail_tools.calendar_granted())
            (folder / "google_scopes.txt").write_text("https://www.googleapis.com/auth/gmail.readonly")
            self.assertFalse(gmail_tools.calendar_granted())  # a Gmail-only sign-in from before Calendar
            gmail_tools._access.clear()


if __name__ == "__main__":
    unittest.main()
