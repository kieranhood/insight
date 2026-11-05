"""The evaluation pipeline and finding lifecycle.

Each cycle:
 1. check every rule's inputs against data freshness;
 2. sources a rule depends on that are failing produce monitoring-failure findings instead;
 3. rules whose essential optional data is missing are skipped (the rules themselves
    downgrade to "insufficient information" when non-essential optional data is missing);
 4. evaluate the rules;
 5. drop symptom findings explained by a cause that fired;
 6. apply minimum and clearing durations, and detect intermittent problems;
 7. store what changed, and record openings and resolutions in the timeline.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, Template

from insight.diagnostics import Action, Candidate, Confidence, Rule, Severity
from insight.diagnostics.context import EvalContext
from insight.model import Event, Reliability
from insight.storage.db import Database
from insight.storage.writer import Writer
from insight.timeutil import from_iso, to_iso

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
ENGINE_SOURCE_ID = "insight-diagnostics"
FLAP_WINDOW = timedelta(hours=1)  # not scaled
FLAP_COUNT = 3

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    undefined=StrictUndefined,
    autoescape=False,  # noqa: S701 - plain text; escaped by the web templates when displayed
    trim_blocks=True,
    lstrip_blocks=True,
)


def _join_and(items: list[str]) -> str:
    """'a, b and c'; uses semicolons when the items themselves contain commas."""
    items = [str(i) for i in items]
    if len(items) <= 1:
        return items[0] if items else ""
    sep = "; " if any("," in i for i in items) else ", "
    return sep.join(items[:-1]) + (";" if sep == "; " else "") + " and " + items[-1]


_env.filters["join_and"] = _join_and
_env.filters["minutes"] = lambda s: (
    f"{max(1, round(float(s) / 60))} minute{'s' if round(float(s) / 60) != 1 else ''}"
)


@dataclass
class Rendered:
    title: str
    crew: str
    summary: str
    engineer: str
    likely_causes: list[str]
    next_steps: list[str]


def template_for(rule_id: str) -> Template:
    return _env.get_template(f"{rule_id}.j2")


def render(rule: Rule, confidence: Confidence, facts: dict[str, Any]) -> Rendered:
    template = template_for(rule.id)
    variables = {
        **facts,
        "confidence": confidence.value,
        "confirmed": confidence is Confidence.CONFIRMED,
    }

    def block(name: str) -> str:
        if name not in template.blocks:
            return ""
        return "".join(template.blocks[name](template.new_context(variables))).strip()

    def lines(name: str) -> list[str]:
        return [line.strip(" -") for line in block(name).splitlines() if line.strip(" -")]

    return Rendered(
        title=block("title") or rule.title,
        crew=" ".join(block("crew").split()),
        summary=" ".join(block("summary").split()),
        engineer=block("engineer"),
        likely_causes=lines("causes"),
        next_steps=lines("steps"),
    )


@dataclass
class Tracked:
    """In-memory lifecycle state for one problem key."""

    key: str
    rule_id: str
    pending_since: datetime | None = None
    clear_since: datetime | None = None
    finding_id: int | None = None
    opened_at: list[datetime] = field(default_factory=list)
    resolved_at: datetime | None = None
    intermittent: bool = False


class Engine:
    def __init__(
        self, db: Database, writer: Writer, rules: list[Rule], duration_scale: float = 1.0
    ) -> None:
        self.scale = duration_scale
        self.db = db
        self.writer = writer
        self.rules = {r.id: r for r in rules}
        self.tracked: dict[str, Tracked] = {}
        self.last_candidates: list[Candidate] = []
        self._load_open()

    def _load_open(self) -> None:
        with self.db.read() as conn:
            rows = conn.execute(
                "SELECT id, rule_id, dedupe_key, first_detected_at, intermittent FROM findings WHERE status='open'"
            ).fetchall()
        for row in rows:
            opened = from_iso(row["first_detected_at"])
            self.tracked[row["dedupe_key"]] = Tracked(
                key=row["dedupe_key"],
                rule_id=row["rule_id"],
                finding_id=row["id"],
                opened_at=[opened] if opened else [],
                intermittent=bool(row["intermittent"]),
            )

    # -- stages 1-5 ------------------------------------------------------------------------
    def candidates(self, ctx: EvalContext) -> list[Candidate]:
        found: list[Candidate] = []
        for rule in self.rules.values():
            if rule.id == "monitoring_source_unavailable":
                continue
            missing = [inp for inp in rule.requires if not ctx.available(inp)]
            if missing:
                continue  # covered by monitoring-failure findings for the failing sources
            if rule.optional_essential and not all(ctx.available(inp) for inp in rule.optional):
                continue
            try:
                found.extend(rule.evaluate(ctx))
            except Exception:
                log.exception("rule %s failed", rule.id)
        monitoring = self.rules.get("monitoring_source_unavailable")
        if monitoring is not None:
            found.extend(monitoring.evaluate(ctx))
        return self.group(found)

    def group(self, found: list[Candidate]) -> list[Candidate]:
        """Drop symptom candidates that a firing cause explains (same or overlapping devices)."""
        kept: list[Candidate] = []
        for cand in found:
            explained = False
            for cause in found:
                if cause is cand or cand.rule_id not in self.rules[cause.rule_id].explains:
                    continue
                if not cand.devices or not cause.devices or set(cand.devices) & set(cause.devices):
                    explained = True
                    break
            if not explained:
                kept.append(cand)
        return kept

    # -- stages 6-7 ------------------------------------------------------------------------
    def evaluate(self, ctx: EvalContext) -> list[Event]:
        current = {c.key: c for c in self.candidates(ctx)}
        self.last_candidates = list(current.values())
        events: list[Event] = []
        now = ctx.now
        for key, cand in current.items():
            rule = self.rules[cand.rule_id]
            track = self.tracked.get(key)
            if track is None:
                track = self.tracked[key] = Tracked(key=key, rule_id=cand.rule_id)
            track.clear_since = None
            if track.finding_id is not None and track.resolved_at is None:
                self._update(track, rule, cand, now)
                continue
            if track.pending_since is None:
                track.pending_since = now
            if now - track.pending_since < rule.min_duration * self.scale:
                continue
            reopened = (
                track.finding_id is not None
                and track.resolved_at is not None
                and now - track.resolved_at <= FLAP_WINDOW
            )
            track.opened_at = [t for t in track.opened_at if now - t <= FLAP_WINDOW] + [now]
            track.intermittent = track.intermittent or len(track.opened_at) >= FLAP_COUNT
            if reopened:
                self._reopen(track, rule, cand, now)
                events.append(self._event("finding_reopened", track, cand, rule, now))
            else:
                self._open(track, rule, cand, now)
                events.append(self._event("finding_opened", track, cand, rule, now))
            track.resolved_at = None
            track.pending_since = None
        for key, track in list(self.tracked.items()):
            if key in current:
                continue
            track.pending_since = None
            if track.finding_id is None or track.resolved_at is not None:
                if track.resolved_at is not None and now - track.resolved_at > FLAP_WINDOW:
                    del self.tracked[key]
                continue
            known = self.rules.get(track.rule_id)
            clear_after = (known.clear_duration if known else timedelta(seconds=120)) * self.scale
            if track.clear_since is None:
                track.clear_since = now
            if now - track.clear_since >= clear_after:
                self._resolve(track, now)
                track.resolved_at = now
                events.append(self._resolved_event(track, now))
        return events

    # -- persistence -------------------------------------------------------------------------
    def _values(self, rule: Rule, cand: Candidate) -> dict[str, Any]:
        rendered = render(rule, cand.confidence, cand.facts)
        severity = cand.severity or rule.severity
        return {
            "title": rendered.title,
            "severity": severity.value,
            "confidence": cand.confidence.value,
            "systems": json.dumps(list(cand.systems or rule.systems)),
            "services": json.dumps(list(cand.services)),
            "devices": json.dumps(list(cand.devices)),
            "facts": json.dumps(cand.facts, default=str),
            "crew_text": rendered.crew,
            "engineer_text": rendered.engineer,
            "summary": rendered.summary,
            "likely_causes": json.dumps(rendered.likely_causes),
            "next_steps": json.dumps(rendered.next_steps),
            "action": cand.action.value,
            "guests_affected": int(cand.guests_affected),
        }

    def _write_evidence(self, conn: sqlite3.Connection, finding_id: int, cand: Candidate) -> None:
        conn.execute("DELETE FROM finding_evidence WHERE finding_id=?", (finding_id,))
        conn.executemany(
            "INSERT INTO finding_evidence(finding_id, observed_at, source_id, description, data) VALUES (?,?,?,?,?)",
            [
                (
                    finding_id,
                    to_iso(e.observed_at) or "",
                    e.source_id,
                    e.description,
                    json.dumps(e.data, default=str),
                )
                for e in cand.evidence
            ],
        )

    def _open(self, track: Tracked, rule: Rule, cand: Candidate, now: datetime) -> None:
        values = self._values(rule, cand)

        def write(conn: sqlite3.Connection) -> int:
            cur = conn.execute(
                "INSERT INTO findings(rule_id, dedupe_key, status, title, severity, confidence, intermittent,"
                " first_detected_at, last_observed_at, systems, services, devices, facts, crew_text, engineer_text,"
                " summary, likely_causes, next_steps, action, guests_affected)"
                " VALUES (?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rule.id,
                    track.key,
                    values["title"],
                    values["severity"],
                    values["confidence"],
                    int(track.intermittent),
                    to_iso(now),
                    to_iso(now),
                    values["systems"],
                    values["services"],
                    values["devices"],
                    values["facts"],
                    values["crew_text"],
                    values["engineer_text"],
                    values["summary"],
                    values["likely_causes"],
                    values["next_steps"],
                    values["action"],
                    values["guests_affected"],
                ),
            )
            finding_id = int(cur.lastrowid or 0)
            self._write_evidence(conn, finding_id, cand)
            return finding_id

        track.finding_id = self.writer.call_sync(write)

    def _update(self, track: Tracked, rule: Rule, cand: Candidate, now: datetime) -> None:
        values = self._values(rule, cand)
        finding_id = track.finding_id

        def write(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE findings SET last_observed_at=?, title=?, severity=?, confidence=?, intermittent=?,"
                " systems=?, services=?, devices=?, facts=?, crew_text=?, engineer_text=?, summary=?,"
                " likely_causes=?, next_steps=?, action=?, guests_affected=? WHERE id=?",
                (
                    to_iso(now),
                    values["title"],
                    values["severity"],
                    values["confidence"],
                    int(track.intermittent),
                    values["systems"],
                    values["services"],
                    values["devices"],
                    values["facts"],
                    values["crew_text"],
                    values["engineer_text"],
                    values["summary"],
                    values["likely_causes"],
                    values["next_steps"],
                    values["action"],
                    values["guests_affected"],
                    finding_id,
                ),
            )
            if finding_id is not None:
                self._write_evidence(conn, finding_id, cand)

        self.writer.call_sync(write)

    def _reopen(self, track: Tracked, rule: Rule, cand: Candidate, now: datetime) -> None:
        finding_id = track.finding_id
        self.writer.call_sync(
            lambda c: c.execute(
                "UPDATE findings SET status='open', resolved_at=NULL WHERE id=?", (finding_id,)
            )
        )
        self._update(track, rule, cand, now)

    def _resolve(self, track: Tracked, now: datetime) -> None:
        finding_id = track.finding_id
        self.writer.call_sync(
            lambda c: c.execute(
                "UPDATE findings SET status='resolved', resolved_at=? WHERE id=?",
                (to_iso(now), finding_id),
            )
        )

    def _event(
        self, kind: str, track: Tracked, cand: Candidate, rule: Rule, now: datetime
    ) -> Event:
        title = render(rule, cand.confidence, cand.facts).title
        verb = "reopened" if kind == "finding_reopened" else "opened"
        return Event(
            source_id=ENGINE_SOURCE_ID,
            observed_at=now,
            reliability=Reliability.RELIABLE,
            kind=kind,
            subject=f"finding:{track.finding_id}",
            message=f"Issue {verb}: {title}" + (" (intermittent)" if track.intermittent else ""),
            devices=cand.devices,
            services=cand.services,
            data={
                "finding_id": track.finding_id,
                "rule_id": rule.id,
                "confidence": cand.confidence.value,
            },
        )

    def _resolved_event(self, track: Tracked, now: datetime) -> Event:
        with self.db.read() as conn:
            row = conn.execute(
                "SELECT title, devices, services FROM findings WHERE id=?", (track.finding_id,)
            ).fetchone()
        return Event(
            source_id=ENGINE_SOURCE_ID,
            observed_at=now,
            reliability=Reliability.RELIABLE,
            kind="finding_resolved",
            subject=f"finding:{track.finding_id}",
            message=f"Issue resolved: {row['title'] if row else track.rule_id}",
            devices=tuple(json.loads(row["devices"])) if row else (),
            services=tuple(json.loads(row["services"])) if row else (),
            data={"finding_id": track.finding_id, "rule_id": track.rule_id},
        )


__all__ = ["Action", "Candidate", "Confidence", "Engine", "Rendered", "Severity", "render"]
