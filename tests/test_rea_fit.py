"""REA auto-fit: scoring a report against Nova's capabilities, the no-fit case, blueprint parts, the wiring
into a finished REA job, and the approval-gated handoff (study read-only; code installed only after the owner
approves)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import rea_fit
import reverse_engineering
from lab_jobs import JobLog

CHART_REPORT = """This app scans candlestick charts every minute, watches tickers and sends price alerts when a stock
breaks out. Its portfolio view tracks positions and dividends, and its trading screen shows the day's movers."""

BLUEPRINT = {"parts": [{"id": "scanner", "name": "Chart scanner", "kind": "logic",
                        "summary": "Scans candlestick charts for breakouts",
                        "findings": ["watches tickers for price alerts"]},
                       {"id": "ui", "name": "Main window", "kind": "ui", "summary": "The window",
                        "findings": []}],
             "links": []}

REPORT_WITH_BLUEPRINT = (CHART_REPORT + "\n\n```json\n" + json.dumps(BLUEPRINT) + "\n```\n")


def finding(area: str) -> dict:
    return {"area": area, "score": 60, "what": f"{area} in trading-app: candlestick, ticker",
            "improves": "News, brief and weather", "how": "Its chart scanner could join the morning brief.",
            "evidence": ["candlestick", "ticker"], "parts": ["scanner"]}


class ScoringTests(unittest.TestCase):
    def test_chart_scanning_matches_trading_finance(self) -> None:
        result = rea_fit.score_report(CHART_REPORT, target="trading-app")
        areas = {item["area"]: item for item in result["findings"]}
        self.assertIn("Trading & finance", areas)
        fit = areas["Trading & finance"]
        self.assertEqual(fit["improves"], "News, brief and weather")
        self.assertIn("candlestick", fit["evidence"])
        self.assertIn("ticker", fit["evidence"])
        self.assertGreaterEqual(fit["score"], 20)
        self.assertIn("Trading & finance", result["message"])

    def test_no_overlap_returns_no_findings(self) -> None:
        result = rea_fit.score_report("A knitting app that counts stitches and suggests yarn colours "
                                      "for a scarf, with a row counter.", target="knit-app")
        self.assertEqual(result["findings"], [])
        self.assertIn("Nothing in this report fits", result["message"])

    def test_blueprint_parts_are_extracted(self) -> None:
        cleaned, plan = reverse_engineering.blueprint(REPORT_WITH_BLUEPRINT)
        self.assertEqual([part["id"] for part in plan["parts"]], ["scanner", "ui"])
        result = rea_fit.score_report(cleaned, plan, target="trading-app")
        fit = next(item for item in result["findings"] if item["area"] == "Trading & finance")
        self.assertIn("scanner", fit["parts"])  # the matching blueprint part is named, not just the keywords
        self.assertGreaterEqual(fit["score"], 20)

    def test_one_keyword_alone_is_not_enough(self) -> None:
        result = rea_fit.score_report("It mentions a stock once, and nothing else.", target="x")
        self.assertEqual(result["findings"], [])

    def test_scoring_is_deterministic(self) -> None:
        first = rea_fit.score_report(CHART_REPORT, BLUEPRINT, target="trading-app")
        second = rea_fit.score_report(CHART_REPORT, BLUEPRINT, target="trading-app")
        self.assertEqual(first, second)

    def test_findings_are_best_first_and_json_safe(self) -> None:
        result = rea_fit.score_report(CHART_REPORT + " It also does speech recognition with transcription and a wake word.",
                                      BLUEPRINT, target="trading-app")
        scores = [item["score"] for item in result["findings"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        json.dumps(result)  # must survive the job record

    def test_fit_summary(self) -> None:
        self.assertEqual(rea_fit.fit_summary([]), "")
        self.assertIn("Trading & finance (60)", rea_fit.fit_summary([finding("Trading & finance")]))


class HandoffTests(unittest.TestCase):
    def test_extract_repo(self) -> None:
        self.assertEqual(rea_fit.extract_repo("See https://github.com/morluto/rea for the source."), "morluto/rea")
        self.assertEqual(rea_fit.extract_repo("a local folder, no repo here"), "")

    def test_study_task_is_read_only_and_asks_first_about_installs(self) -> None:
        task = rea_fit.study_task(finding("Trading & finance"), "https://github.com/a/trading-app",
                                  report="outputs/report.md",
                                  pin={"repo": "a/trading-app", "sha": "abc123",
                                       "url": "https://github.com/a/trading-app", "license": "MIT"})
        self.assertIn("at commit abc123", task)
        self.assertIn("do not run or install anything from it during this study", task)
        self.assertIn("Nova will ask the owner first", task)
        self.assertIn("MIT", task)
        self.assertIn("News, brief and weather", task)

    def test_study_task_without_a_repo_uses_the_report(self) -> None:
        task = rea_fit.study_task(finding("Trading & finance"), "My Trading App", report="outputs/report.md")
        self.assertIn("outputs/report.md", task)
        self.assertIn("do not run or install anything from it during this study", task)
        self.assertIn("Nova will ask the owner first", task)

    def test_handoff_prepares_only(self) -> None:
        made = rea_fit.handoff(finding("Trading & finance"), "https://github.com/a/trading-app",
                               report="outputs/report.md")
        self.assertTrue(made["title"].startswith("Rea fit: Trading & finance"))
        self.assertIn("```skill", made["skill_note"])  # a draft note for the owner to read and approve
        self.assertIn("study_task", made)
        self.assertIn("never installs", made["note"])

    def test_skill_note_draft_is_a_draft(self) -> None:
        note = rea_fit.skill_note_draft(finding("Trading & finance"), "trading-app")
        self.assertIn("title: Trading & finance from trading-app", note)
        self.assertIn("schedule: manual", note)


class JobWiringTests(unittest.TestCase):
    def _rea(self, tmp: Path) -> tuple[reverse_engineering.ReverseEngineering, list, list, list]:
        saved, noted, done = [], [], []

        def save(title: str, text: str) -> Path:
            path = tmp / "report.md"
            path.write_text(text, encoding="utf-8")
            saved.append(path)
            return path

        rea = reverse_engineering.ReverseEngineering(
            save=save, library=lambda title, note: noted.append(note),
            done=lambda title, result, ok: done.append((title, result, ok)),
            workspace=tmp, command=lambda: "claude", jobs=JobLog(tmp / "jobs.json"))
        return rea, saved, noted, done

    def test_finished_job_stores_its_fits(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            rea, _, noted, done = self._rea(tmp)
            job = rea.jobs.add("rea", title="t", target="trading-app")
            rea.running.append("t")
            with mock.patch.object(reverse_engineering, "run", return_value=REPORT_WITH_BLUEPRINT):
                rea._work(job["id"], "t", "trading-app", "trading-app", "", tmp / "job", "claude")
            stored = rea.jobs.get(job["id"])
            self.assertEqual(stored["status"], "done")
            self.assertEqual([item["area"] for item in stored["fit"]], ["Trading & finance"])
            self.assertEqual(stored["counts"], {"parts": 2})
            self.assertTrue((tmp / "job" / "fit.json").exists())
            self.assertIn("Fit: Trading & finance", noted[0])
            self.assertTrue(done[0][2])

    def test_scoring_failure_still_finishes_the_job(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            rea, _, _, done = self._rea(tmp)
            job = rea.jobs.add("rea", title="t", target="trading-app")
            rea.running.append("t")
            with mock.patch.object(reverse_engineering, "run", return_value=REPORT_WITH_BLUEPRINT), \
                    mock.patch.object(rea_fit, "score_report", side_effect=RuntimeError("boom")):
                rea._work(job["id"], "t", "trading-app", "trading-app", "", tmp / "job", "claude")
            stored = rea.jobs.get(job["id"])
            self.assertEqual(stored["status"], "done")
            self.assertEqual(stored["fit"], [])
            self.assertTrue(done[0][2])


if __name__ == "__main__":
    unittest.main()
