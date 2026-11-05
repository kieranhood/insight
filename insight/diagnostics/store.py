"""Reading stored findings for the views."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from insight.diagnostics import Action, Confidence, Severity
from insight.storage.db import Database
from insight.timeutil import from_iso, utcnow


@dataclass(frozen=True)
class StoredEvidence:
    observed_at: datetime | None
    source_id: str | None
    description: str
    data: dict[str, Any]


@dataclass
class Finding:
    id: int
    rule_id: str
    key: str
    status: str
    title: str
    severity: Severity
    confidence: Confidence
    intermittent: bool
    first_detected_at: datetime
    last_observed_at: datetime
    resolved_at: datetime | None
    systems: list[str]
    services: list[str]
    devices: list[str]
    facts: dict[str, Any]
    crew_text: str
    engineer_text: str
    summary: str
    likely_causes: list[str]
    next_steps: list[str]
    action: Action
    guests_affected: bool
    evidence: list[StoredEvidence] = field(default_factory=list)

    @property
    def open(self) -> bool:
        return self.status == "open"

    @property
    def confirmed(self) -> bool:
        return self.confidence is Confidence.CONFIRMED


def _row(row: sqlite3.Row) -> Finding:
    return Finding(
        id=row["id"],
        rule_id=row["rule_id"],
        key=row["dedupe_key"],
        status=row["status"],
        title=row["title"],
        severity=Severity(row["severity"]),
        confidence=Confidence(row["confidence"]),
        intermittent=bool(row["intermittent"]),
        first_detected_at=from_iso(row["first_detected_at"]) or utcnow(),
        last_observed_at=from_iso(row["last_observed_at"]) or utcnow(),
        resolved_at=from_iso(row["resolved_at"]),
        systems=json.loads(row["systems"]),
        services=json.loads(row["services"]),
        devices=json.loads(row["devices"]),
        facts=json.loads(row["facts"]),
        crew_text=row["crew_text"],
        engineer_text=row["engineer_text"],
        summary=row["summary"],
        likely_causes=json.loads(row["likely_causes"]),
        next_steps=json.loads(row["next_steps"]),
        action=Action(row["action"]),
        guests_affected=bool(row["guests_affected"]),
    )


def _sort_key(f: Finding) -> tuple[int, float]:
    return (-f.severity.rank, -f.first_detected_at.timestamp())


class FindingStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def open(self) -> list[Finding]:
        with self.db.read() as conn:
            rows = conn.execute("SELECT * FROM findings WHERE status='open'").fetchall()
        return sorted((_row(r) for r in rows), key=_sort_key)

    def resolved_since(self, since: timedelta, now: datetime | None = None) -> list[Finding]:
        cutoff = ((now or utcnow()) - since).isoformat()
        with self.db.read() as conn:
            rows = conn.execute(
                "SELECT * FROM findings WHERE status='resolved' AND resolved_at >= ? ORDER BY resolved_at DESC",
                (cutoff,),
            ).fetchall()
        return [_row(r) for r in rows]

    def query(
        self, status: str | None = None, limit: int = 200, rule_id: str | None = None
    ) -> list[Finding]:
        clauses: list[str] = ["1=1"]
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if rule_id:
            clauses.append("rule_id=?")
            params.append(rule_id)
        sql = f"SELECT * FROM findings WHERE {' AND '.join(clauses)} ORDER BY first_detected_at DESC LIMIT ?"  # noqa: S608
        with self.db.read() as conn:
            rows = conn.execute(sql, (*params, limit)).fetchall()
        return [_row(r) for r in rows]

    def for_device(self, key: str, limit: int = 50) -> list[Finding]:
        with self.db.read() as conn:
            rows = conn.execute(
                "SELECT * FROM findings WHERE EXISTS (SELECT 1 FROM json_each(findings.devices) WHERE value=?)"
                " ORDER BY first_detected_at DESC LIMIT ?",
                (key, limit),
            ).fetchall()
        return [_row(r) for r in rows]

    def get(self, finding_id: int) -> Finding | None:
        with self.db.read() as conn:
            row = conn.execute("SELECT * FROM findings WHERE id=?", (finding_id,)).fetchone()
            if row is None:
                return None
            evidence = conn.execute(
                "SELECT observed_at, source_id, description, data FROM finding_evidence WHERE finding_id=? ORDER BY id",
                (finding_id,),
            ).fetchall()
        finding = _row(row)
        finding.evidence = [
            StoredEvidence(
                from_iso(e["observed_at"]), e["source_id"], e["description"], json.loads(e["data"])
            )
            for e in evidence
        ]
        return finding
