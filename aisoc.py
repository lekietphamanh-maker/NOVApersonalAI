"""AiSOC-inspired core for Nova: lightweight alert fusion, rule-based triage with MITRE ATT&CK mapping, and a
replayable decision ledger.

This is NOT the full AiSOC stack (beenuar/AiSOC): that is a large Docker SOC platform (Wazuh, TheHive, AI agents)
that cannot be embedded in Nova. This module is stdlib-only, makes no network calls and installs nothing: it groups
related alerts into incidents, scores them with transparent heuristics, maps techniques to MITRE ATT&CK, and records
every step in an append-only JSONL ledger that can be replayed. The local/Claude brain may supply a better rationale
through the rationale_hook; the hook is called synchronously and only supplies words, never the verdict.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

VERDICTS = ("resolved", "mitigated", "needs review")
SEVERITIES = ("critical", "high", "medium", "low")
_SEVERITY_RANK = {severity: index for index, severity in enumerate(SEVERITIES)}

# Technique name -> MITRE ATT&CK tactic and technique. A small table on purpose: the well-known techniques Nova
# is likely to meet, not the whole ATT&CK matrix.
MITRE = {
    "port scan": {"tactic": "Discovery", "technique_id": "T1046", "name": "Network Service Discovery"},
    "service fingerprinting": {"tactic": "Discovery", "technique_id": "T1007", "name": "System Service Discovery"},
    "directory enumeration": {"tactic": "Discovery", "technique_id": "T1083", "name": "File and Directory Discovery"},
    "path traversal": {"tactic": "Discovery", "technique_id": "T1083", "name": "File and Directory Discovery"},
    "archive slip": {"tactic": "Discovery", "technique_id": "T1083", "name": "File and Directory Discovery"},
    "metadata leak": {"tactic": "Collection", "technique_id": "T1005", "name": "Data from Local System"},
    "brute force": {"tactic": "Credential Access", "technique_id": "T1110", "name": "Brute Force"},
    "credential stuffing": {"tactic": "Credential Access", "technique_id": "T1110.004", "name": "Credential Stuffing"},
    "default credentials": {"tactic": "Credential Access", "technique_id": "T1078", "name": "Valid Accounts"},
    "sql injection": {"tactic": "Initial Access", "technique_id": "T1190", "name": "Exploit Public-Facing Application"},
    "cross-site scripting": {"tactic": "Initial Access", "technique_id": "T1189", "name": "Drive-by Compromise"},
    "command injection": {"tactic": "Execution", "technique_id": "T1059", "name": "Command and Scripting Interpreter"},
    "ssrf": {"tactic": "Initial Access", "technique_id": "T1090", "name": "Proxy"},
    "macro execution": {"tactic": "Execution", "technique_id": "T1204.002", "name": "Malicious File"},
    "malformed file": {"tactic": "Impact", "technique_id": "T1499", "name": "Endpoint Denial of Service"},
    "embedded link": {"tactic": "Command and Control", "technique_id": "T1071", "name": "Application Layer Protocol"},
    "phishing": {"tactic": "Initial Access", "technique_id": "T1566", "name": "Phishing"},
    "privilege escalation": {"tactic": "Privilege Escalation", "technique_id": "T1068",
                             "name": "Exploitation for Privilege Escalation"},
    "lateral movement": {"tactic": "Lateral Movement", "technique_id": "T1021", "name": "Remote Services"},
    "data exfiltration": {"tactic": "Exfiltration", "technique_id": "T1041", "name": "Exfiltration Over C2 Channel"},
    "command and control": {"tactic": "Command and Control", "technique_id": "T1071",
                            "name": "Application Layer Protocol"},
    "denial of service": {"tactic": "Impact", "technique_id": "T1498", "name": "Network Denial of Service"},
}

ALIASES = {
    "xss": "cross-site scripting",
    "cross site scripting": "cross-site scripting",
    "sqli": "sql injection",
    "sql-injection": "sql injection",
    "port scanning": "port scan",
    "credential-stuffing": "credential stuffing",
    "server-side request forgery": "ssrf",
}


def normalize_technique(name: Any) -> str:
    """Lowercase, one spacing, underscores as spaces, then the alias table. Hyphens stay: the table's keys use
    them ("cross-site scripting")."""
    text = re.sub(r"_+", " ", str(name or "")).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return ALIASES.get(text, text)


def mitre_lookup(technique: Any) -> dict[str, str] | None:
    """The MITRE entry for a technique name, or None when it isn't in the table."""
    key = normalize_technique(technique)
    entry = MITRE.get(key)
    return {"technique": key, **entry} if entry else None


def _severity(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in _SEVERITY_RANK else "medium"


def _when(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def fuse_alerts(alerts: list[dict[str, Any]], window_seconds: int = 600) -> list[dict[str, Any]]:
    """Group related alerts into incidents: same target and technique, close together in time. Alerts more than
    window_seconds after the last one in their group start a new incident, so a fresh attack isn't folded into an
    old one. Returns incidents newest first, each with its alerts."""
    groups: list[dict[str, Any]] = []
    for alert in alerts:
        target = " ".join(str(alert.get("target") or "").split()) or "unknown target"
        key = normalize_technique(alert.get("technique"))
        seen = _when(alert.get("time"))
        group = None
        for candidate in groups:  # the open group for this target and technique, if the gap fits the window
            if candidate["target"] != target or candidate["technique"] != key:
                continue
            if seen is None or candidate["last_seen"] is None:
                group = candidate
                break
            if (seen - candidate["last_seen"]).total_seconds() <= window_seconds:
                group = candidate
                break
            # window doesn't fit this (older) group: keep looking for a newer one
        if group is None:
            mitre = mitre_lookup(key)
            group = {"id": uuid.uuid4().hex[:8], "target": target, "technique": key,
                     "tactic": mitre["tactic"] if mitre else "unknown",
                     "technique_id": mitre["technique_id"] if mitre else "",
                     "severity": "low", "count": 0, "first_seen": None, "last_seen": None,
                     "alerts": [], "proven": False, "fix": ""}
            groups.append(group)
        group["alerts"].append(alert)
        group["count"] += 1
        group["proven"] = group["proven"] or bool(alert.get("proven"))
        if _SEVERITY_RANK[_severity(alert.get("severity"))] < _SEVERITY_RANK[group["severity"]]:
            group["severity"] = _severity(alert.get("severity"))
        if not group["fix"] and str(alert.get("fix") or "").strip():
            group["fix"] = str(alert["fix"]).strip()
        if seen is not None:
            group["first_seen"] = group["first_seen"] or seen
            group["last_seen"] = seen if group["last_seen"] is None or seen > group["last_seen"] else group["last_seen"]
    incidents = list(groups)
    for incident in incidents:
        incident["first_seen"] = incident["first_seen"].isoformat(timespec="seconds") if incident["first_seen"] else ""
        incident["last_seen"] = incident["last_seen"].isoformat(timespec="seconds") if incident["last_seen"] else ""
    incidents.sort(key=lambda item: (item["last_seen"], _SEVERITY_RANK[item["severity"]]), reverse=True)
    return incidents


def _verdict_record(verdict: str, confidence: float, rationale: str, technique: str, tactic: str,
                    technique_id: str, severity: str, proven: bool) -> dict[str, Any]:
    return {"verdict": verdict, "confidence": round(max(0.0, min(1.0, confidence)), 2), "rationale": rationale,
            "technique": technique, "tactic": tactic, "technique_id": technique_id,
            "severity": severity, "proven": proven}


def _heuristic(detail: str, severity: str, proven: bool, fix: str, mapped: bool) -> tuple[str, float, str]:
    """The rules: nothing proven is resolved; a proven hole with a known fix is mitigated; a proven hole with no
    fix on file, or a technique Nova can't map, needs a human to look."""
    if not mapped:
        return ("needs review", 0.5,
                f"Unknown technique: Nova has no MITRE mapping for it, so this needs a human to look. {detail}".strip())
    if not proven:
        return ("resolved", 0.9 if severity == "low" else 0.8,
                f"The probe did not prove a hole: {detail}".strip())
    if fix:
        confidence = 0.7 if severity == "critical" else 0.75 if severity == "high" else 0.8
        return ("mitigated", confidence, f"Proved: {detail} Mitigated by: {fix}".strip())
    return ("needs review", 0.8 if severity in ("critical", "high") else 0.7,
            f"Proved: {detail} No fix on file — needs a human to decide.".strip())


def _rationale(hook: Callable[[dict[str, Any]], str | None] | None, item: dict[str, Any],
               fallback: str) -> str:
    """The brain's words when it has them, the heuristic's otherwise. The hook only writes the rationale."""
    if hook is None:
        return fallback
    try:
        supplied = hook(item)
    except Exception:
        return fallback
    return str(supplied).strip() or fallback


def triage_alert(alert: dict[str, Any],
                 rationale_hook: Callable[[dict[str, Any]], str | None] | None = None) -> dict[str, Any]:
    """A verdict record for one alert: verdict, confidence, rationale, MITRE mapping, severity, proven."""
    mitre = mitre_lookup(alert.get("technique"))
    severity, proven = _severity(alert.get("severity")), bool(alert.get("proven"))
    detail = " ".join(str(alert.get("detail") or alert.get("title") or "").split())
    verdict, confidence, rationale = _heuristic(detail, severity, proven, str(alert.get("fix") or ""), mitre is not None)
    return _verdict_record(verdict, confidence, _rationale(rationale_hook, alert, rationale),
                           normalize_technique(alert.get("technique")), mitre["tactic"] if mitre else "unknown",
                           mitre["technique_id"] if mitre else "", severity, proven)


def triage_incident(incident: dict[str, Any],
                    rationale_hook: Callable[[dict[str, Any]], str | None] | None = None) -> dict[str, Any]:
    """A verdict record for a fused incident: the worst of its alerts decides (proven beats not, fix beats none)."""
    alerts = incident.get("alerts") or []
    proven_alert = next((alert for alert in alerts if alert.get("proven")), None)
    detail_alert = proven_alert or (alerts[0] if alerts else {})
    detail = " ".join(str(detail_alert.get("detail") or detail_alert.get("title") or "").split())
    if not alerts:
        detail = f"{incident.get('count', 0)} alerts, no detail kept."
    mitre = mitre_lookup(incident.get("technique"))
    severity, proven = _severity(incident.get("severity")), bool(incident.get("proven"))
    verdict, confidence, rationale = _heuristic(detail, severity, proven, str(incident.get("fix") or ""),
                                                mitre is not None)
    record = _verdict_record(verdict, confidence, _rationale(rationale_hook, incident, rationale),
                             normalize_technique(incident.get("technique")),
                             mitre["tactic"] if mitre else incident.get("tactic") or "unknown",
                             mitre["technique_id"] if mitre else incident.get("technique_id") or "",
                             severity, proven)
    record["incident_id"] = incident.get("id", "")
    record["count"] = incident.get("count", len(alerts))
    return record


def triage(item: dict[str, Any], ledger: "DecisionLedger | None" = None, actor: str = "aisoc",
           rationale_hook: Callable[[dict[str, Any]], str | None] | None = None) -> dict[str, Any]:
    """Triage an alert or an incident and return its verdict, writing the decision to the ledger when one is given.
    Returns {"verdict": verdict record, "ledger_entries": [the entries just written]}."""
    verdict = triage_incident(item, rationale_hook) if isinstance(item.get("alerts"), list) else triage_alert(item, rationale_hook)
    entries = []
    if ledger is not None:
        target = " ".join(str(item.get("target") or "").split())
        entries.append(ledger.append(actor, "triage",
                                     f"{verdict['technique']} on {target} "
                                     f"(severity {verdict['severity']}, proven={verdict['proven']})",
                                     verdict["verdict"], confidence=verdict["confidence"],
                                     technique_id=verdict["technique_id"],
                                     incident_id=verdict.get("incident_id", "")))
    return {"verdict": verdict, "ledger_entries": entries}


def overall_verdict(verdicts: list[dict[str, Any]]) -> dict[str, Any]:
    """The worst verdict wins: needs review over mitigated over resolved."""
    rank = {"needs review": 0, "mitigated": 1, "resolved": 2}
    if not verdicts:
        return {"verdict": "resolved", "confidence": 0.0, "rationale": "Nothing was triaged.",
                "counts": {"resolved": 0, "mitigated": 0, "needs review": 0}}
    worst = min(verdicts, key=lambda verdict: rank.get(verdict.get("verdict"), 2))
    counts = {name: sum(1 for verdict in verdicts if verdict.get("verdict") == name) for name in VERDICTS}
    summary = ", ".join(f"{number} {name}" for name, number in counts.items() if number)
    return {"verdict": worst["verdict"], "confidence": worst["confidence"],
            "rationale": f"AiSOC triaged {len(verdicts)} incident(s): {summary}.",
            "counts": counts}


class DecisionLedger:
    """Append-only list of every step: timestamp, actor, action, input summary, outcome. One JSON object per line,
    so replay is just reading the file back in order. Nothing here ever rewrites or deletes an entry."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, actor: str, action: str, input_summary: str, outcome: str, **extra: Any) -> dict[str, Any]:
        entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "actor": str(actor),
                 "action": str(action), "input": str(input_summary)[:500], "outcome": str(outcome)[:500], **extra}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

def replay_ledger(path: Path | str) -> list[dict[str, Any]]:
    """Re-read a ledger file, in order. A missing file replays as nothing; a damaged line is skipped."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries
