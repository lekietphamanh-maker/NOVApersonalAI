"""AiSOC-inspired core (aisoc.py): MITRE mapping, alert fusion into incidents, triage verdicts, and the
append-only decision ledger with replay. Stdlib only, no network, nothing installed."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import aisoc


def alert(technique: str, target: str = "http://localhost:3000", severity: str = "medium",
          proven: bool = False, fix: str = "", time: str = "2026-11-21T20:00:00",
          detail: str = "probe detail") -> dict:
    return {"technique": technique, "target": target, "severity": severity, "proven": proven,
            "fix": fix, "time": time, "detail": detail}


class MitreTests(unittest.TestCase):
    def test_known_techniques_map_to_tactic_and_id(self) -> None:
        self.assertEqual(aisoc.mitre_lookup("port scan"),
                         {"technique": "port scan", "tactic": "Discovery", "technique_id": "T1046",
                          "name": "Network Service Discovery"})
        self.assertEqual(aisoc.mitre_lookup("brute force")["technique_id"], "T1110")
        self.assertEqual(aisoc.mitre_lookup("brute force")["tactic"], "Credential Access")
        self.assertEqual(aisoc.mitre_lookup("sql injection")["technique_id"], "T1190")
        self.assertEqual(aisoc.mitre_lookup("cross-site scripting")["technique_id"], "T1189")

    def test_aliases_and_case_do_not_matter(self) -> None:
        self.assertEqual(aisoc.mitre_lookup("XSS")["technique"], "cross-site scripting")
        self.assertEqual(aisoc.mitre_lookup("SQLi")["technique"], "sql injection")
        self.assertEqual(aisoc.mitre_lookup("  Port   Scan ")["technique_id"], "T1046")

    def test_unknown_technique_has_no_mapping(self) -> None:
        self.assertIsNone(aisoc.mitre_lookup("zero-day moonbeam"))
        self.assertIsNone(aisoc.mitre_lookup(""))


class FusionTests(unittest.TestCase):
    def test_same_target_and_technique_fuse_into_one_incident(self) -> None:
        incidents = aisoc.fuse_alerts([alert("port scan", time="2026-11-21T20:00:00"),
                                       alert("port scan", time="2026-11-21T20:03:00"),
                                       alert("port scan", time="2026-11-21T20:05:00")])
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["count"], 3)
        self.assertEqual((incidents[0]["first_seen"], incidents[0]["last_seen"]),
                         ("2026-11-21T20:00:00", "2026-11-21T20:05:00"))

    def test_different_technique_or_target_stay_apart(self) -> None:
        incidents = aisoc.fuse_alerts([alert("port scan"), alert("brute force"),
                                       alert("port scan", target="http://localhost:4000")])
        self.assertEqual(len(incidents), 3)

    def test_a_fresh_attack_after_the_window_is_a_new_incident(self) -> None:
        incidents = aisoc.fuse_alerts([alert("port scan", time="2026-11-21T20:00:00"),
                                       alert("port scan", time="2026-11-21T21:00:00")], window_seconds=600)
        self.assertEqual(len(incidents), 2)
        self.assertEqual([incident["count"] for incident in incidents], [1, 1])

    def test_an_alert_joins_the_recent_group_not_the_old_one(self) -> None:
        # Old group at 20:00, fresh group at 21:00, then an alert at 21:03: it must join the
        # fresh group (2 incidents total), not spawn a third one by stopping at the old group.
        incidents = aisoc.fuse_alerts([alert("port scan", time="2026-11-21T20:00:00"),
                                       alert("port scan", time="2026-11-21T21:00:00"),
                                       alert("port scan", time="2026-11-21T21:03:00")], window_seconds=600)
        self.assertEqual(len(incidents), 2)
        self.assertEqual([incident["count"] for incident in incidents], [2, 1])  # newest first

    def test_incident_takes_the_worst_severity_and_any_proof(self) -> None:
        incidents = aisoc.fuse_alerts([alert("brute force", severity="low"),
                                       alert("brute force", severity="high", proven=True,
                                             fix="Lock the account.")])
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["severity"], "high")
        self.assertTrue(incidents[0]["proven"])
        self.assertEqual(incidents[0]["fix"], "Lock the account.")
        self.assertEqual(incidents[0]["technique_id"], "T1110")


class TriageTests(unittest.TestCase):
    def test_verdict_shape(self) -> None:
        verdict = aisoc.triage_alert(alert("port scan"))
        self.assertEqual(set(verdict), {"verdict", "confidence", "rationale", "technique", "tactic",
                                        "technique_id", "severity", "proven"})
        self.assertIn(verdict["verdict"], aisoc.VERDICTS)
        self.assertTrue(0.0 <= verdict["confidence"] <= 1.0)

    def test_nothing_proven_is_resolved(self) -> None:
        verdict = aisoc.triage_alert(alert("port scan", severity="low"))
        self.assertEqual((verdict["verdict"], verdict["confidence"]), ("resolved", 0.9))
        self.assertIn("did not prove", verdict["rationale"])

    def test_proven_with_a_fix_is_mitigated(self) -> None:
        verdict = aisoc.triage_alert(alert("sql injection", severity="critical", proven=True,
                                           fix="Use parameterised queries."))
        self.assertEqual(verdict["verdict"], "mitigated")
        self.assertIn("parameterised queries", verdict["rationale"])

    def test_proven_without_a_fix_needs_review(self) -> None:
        verdict = aisoc.triage_alert(alert("brute force", severity="high", proven=True))
        self.assertEqual(verdict["verdict"], "needs review")
        self.assertIn("No fix on file", verdict["rationale"])

    def test_unknown_technique_needs_review_at_low_confidence(self) -> None:
        verdict = aisoc.triage_alert(alert("zero-day moonbeam", severity="critical", proven=True))
        self.assertEqual((verdict["verdict"], verdict["confidence"]), ("needs review", 0.5))
        self.assertEqual(verdict["technique_id"], "")

    def test_the_brain_hook_supplies_the_rationale_not_the_verdict(self) -> None:
        verdict = aisoc.triage_alert(alert("port scan"),
                                     rationale_hook=lambda item: "The brain says: just a scan, ignore it.")
        self.assertEqual(verdict["verdict"], "resolved")
        self.assertEqual(verdict["rationale"], "The brain says: just a scan, ignore it.")
        fallback = aisoc.triage_alert(alert("port scan"), rationale_hook=lambda item: "")
        self.assertIn("did not prove", fallback["rationale"])

    def test_triage_writes_to_the_ledger_and_returns_its_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = aisoc.DecisionLedger(Path(tmp) / "ledger.jsonl")
            result = aisoc.triage(alert("brute force", severity="high", proven=True), ledger=ledger)
            self.assertEqual(result["verdict"]["verdict"], "needs review")
            self.assertEqual(len(result["ledger_entries"]), 1)
            self.assertEqual(result["ledger_entries"][0]["action"], "triage")
            self.assertEqual(result["ledger_entries"][0]["outcome"], "needs review")
            self.assertEqual(aisoc.replay_ledger(ledger.path), result["ledger_entries"])

    def test_overall_verdict_is_the_worst_one(self) -> None:
        overall = aisoc.overall_verdict([{"verdict": "resolved", "confidence": 0.9},
                                         {"verdict": "mitigated", "confidence": 0.8},
                                         {"verdict": "needs review", "confidence": 0.7}])
        self.assertEqual((overall["verdict"], overall["confidence"]), ("needs review", 0.7))
        self.assertEqual(overall["counts"], {"resolved": 1, "mitigated": 1, "needs review": 1})
        self.assertEqual(aisoc.overall_verdict([])["verdict"], "resolved")


class LedgerTests(unittest.TestCase):
    def test_append_then_replay_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            ledger = aisoc.DecisionLedger(path)
            first = ledger.append("shannon", "attack_step", "port scan on localhost", "landed=True proven=False")
            second = ledger.append("aisoc", "triage", "port scan on localhost", "resolved", confidence=0.9)
            for entry in (first, second):
                self.assertEqual(set(entry) >= {"ts", "actor", "action", "input", "outcome"}, True)
            replayed = aisoc.replay_ledger(path)
            self.assertEqual([entry["action"] for entry in replayed], ["attack_step", "triage"])
            self.assertEqual(replayed[1]["confidence"], 0.9)
            self.assertEqual(replayed[0]["ts"], first["ts"])
            self.assertEqual(aisoc.replay_ledger(path), replayed)

    def test_append_only_a_missing_file_replays_as_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(aisoc.replay_ledger(Path(tmp) / "nope.jsonl"), [])
            path = Path(tmp) / "ledger.jsonl"
            ledger = aisoc.DecisionLedger(path)
            ledger.append("nova", "simulate_start", "web localhost:3000", "simulation started")
            ledger.append("nova", "simulate_start", "web localhost:3000", "simulation started")
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
