"""On-board history: readings, the event timeline, daily summaries, retention and gaps."""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from insight.config_store import ConfigStore
from insight.storage.db import Database
from insight.storage.writer import Writer
from insight.timeutil import utcnow

INSIGHT_SCOPE = "insight"


def _ts(value: datetime) -> int:
    return int(value.timestamp())


def _dt(value: int) -> datetime:
    return datetime.fromtimestamp(value, UTC)


@dataclass(frozen=True)
class Point:
    at: datetime
    value: float | None  # None marks a gap


@dataclass(frozen=True)
class TimelineEvent:
    id: int
    at: datetime
    kind: str
    source_id: str | None
    subject: str
    devices: list[str]
    services: list[str]
    systems: list[str]
    message: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Gap:
    scope: str
    start: datetime
    end: datetime | None


class History:
    def __init__(self, db: Database, writer: Writer, config: ConfigStore) -> None:
        self.db = db
        self.writer = writer
        self.config = config

    # -- readings ------------------------------------------------------------------------
    def series_list(self, subject: str | None = None) -> list[tuple[str, str, str]]:
        with self.db.read() as conn:
            if subject:
                rows = conn.execute(
                    "SELECT subject, name, unit FROM series WHERE subject=? ORDER BY name",
                    (subject,),
                )
            else:
                rows = conn.execute("SELECT subject, name, unit FROM series ORDER BY subject, name")
            return [(r[0], r[1], r[2]) for r in rows]

    def readings(
        self,
        subject: str,
        name: str,
        start: datetime,
        end: datetime,
        *,
        gap_scopes: Iterable[str] = (),
        max_points: int = 2000,
    ) -> list[Point]:
        """Readings for one series in [start, end] only, with gaps marked as None points."""
        with self.db.read() as conn:
            row = conn.execute(
                "SELECT id FROM series WHERE subject=? AND name=?", (subject, name)
            ).fetchone()
            if row is None:
                return []
            rows = conn.execute(
                "SELECT ts, value FROM metrics WHERE series_id=? AND ts BETWEEN ? AND ? ORDER BY ts",
                (row[0], _ts(start), _ts(end)),
            ).fetchall()
        points = [Point(_dt(ts), value) for ts, value in rows]
        if len(points) > max_points:
            step = len(points) / max_points
            points = [points[int(i * step)] for i in range(max_points)]
        gaps = self.gaps(start, end, [INSIGHT_SCOPE, *gap_scopes])
        if not gaps:
            return points
        result: list[Point] = []
        gap_iter = sorted(gaps, key=lambda g: g.start)
        for point in points:
            for gap in gap_iter:
                if (
                    result
                    and result[-1].value is not None
                    and result[-1].at < gap.start <= point.at
                ):
                    result.append(Point(gap.start, None))
            if any(g.start <= point.at <= (g.end or end) for g in gap_iter):
                continue
            result.append(point)
        return result

    def daily(
        self, subject: str, name: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        with self.db.read() as conn:
            rows = conn.execute(
                "SELECT d.day, d.min, d.max, d.avg, d.count FROM metric_daily d JOIN series s ON s.id=d.series_id"
                " WHERE s.subject=? AND s.name=? AND d.day BETWEEN ? AND ? ORDER BY d.day",
                (subject, name, start.date().isoformat(), end.date().isoformat()),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- timeline ------------------------------------------------------------------------
    def timeline(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        system: str | None = None,
        device: str | None = None,
        service: str | None = None,
        kinds: Iterable[str] | None = None,
        limit: int = 500,
    ) -> list[TimelineEvent]:
        clauses: list[str] = ["1=1"]
        params: list[Any] = []
        if start is not None:
            clauses.append("ts >= ?")
            params.append(_ts(start))
        if end is not None:
            clauses.append("ts <= ?")
            params.append(_ts(end))
        for column, value in (("systems", system), ("devices", device), ("services", service)):
            if value:
                clauses.append(f"EXISTS (SELECT 1 FROM json_each(events.{column}) WHERE value = ?)")  # noqa: S608
                params.append(value)
        kind_list = list(kinds or [])
        if kind_list:
            clauses.append(f"kind IN ({','.join('?' for _ in kind_list)})")
            params.extend(kind_list)
        sql = (
            f"SELECT * FROM events WHERE {' AND '.join(clauses)} ORDER BY ts DESC, id DESC LIMIT ?"  # noqa: S608
        )
        params.append(limit)
        with self.db.read() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            TimelineEvent(
                id=r["id"],
                at=_dt(r["ts"]),
                kind=r["kind"],
                source_id=r["source_id"],
                subject=r["subject"],
                devices=json.loads(r["devices"]),
                services=json.loads(r["services"]),
                systems=json.loads(r["systems"]),
                message=r["message"],
                data=json.loads(r["data"]),
            )
            for r in rows
        ]

    def event_kinds(self) -> list[str]:
        with self.db.read() as conn:
            return [r[0] for r in conn.execute("SELECT DISTINCT kind FROM events ORDER BY kind")]

    # -- gaps ------------------------------------------------------------------------------
    def open_gap(self, scope: str, at: datetime) -> None:
        def write(conn: sqlite3.Connection) -> None:
            if (
                conn.execute(
                    "SELECT 1 FROM gaps WHERE scope=? AND end_ts IS NULL", (scope,)
                ).fetchone()
                is None
            ):
                conn.execute("INSERT INTO gaps(scope, start_ts) VALUES (?, ?)", (scope, _ts(at)))

        self.writer.call_sync(write)

    def close_gap(self, scope: str, at: datetime) -> None:
        self.writer.call_sync(
            lambda c: c.execute(
                "UPDATE gaps SET end_ts=? WHERE scope=? AND end_ts IS NULL", (_ts(at), scope)
            )
        )

    def record_gap(self, scope: str, start: datetime, end: datetime) -> None:
        self.writer.call_sync(
            lambda c: c.execute(
                "INSERT INTO gaps(scope, start_ts, end_ts) VALUES (?, ?, ?)",
                (scope, _ts(start), _ts(end)),
            )
        )

    def gaps(self, start: datetime, end: datetime, scopes: Iterable[str]) -> list[Gap]:
        scope_list = list(scopes)
        if not scope_list:
            return []
        marks = ",".join("?" for _ in scope_list)
        with self.db.read() as conn:
            rows = conn.execute(
                f"SELECT scope, start_ts, end_ts FROM gaps WHERE scope IN ({marks})"  # noqa: S608
                " AND start_ts <= ? AND (end_ts IS NULL OR end_ts >= ?) ORDER BY start_ts",
                (*scope_list, _ts(end), _ts(start)),
            ).fetchall()
        return [Gap(r[0], _dt(r[1]), _dt(r[2]) if r[2] is not None else None) for r in rows]

    def heartbeat(self, at: datetime | None = None) -> None:
        self.config.set("last_heartbeat", _ts(at or utcnow()))

    def record_downtime_since_last_heartbeat(
        self, now: datetime | None = None, tolerance_s: float = 180
    ) -> Gap | None:
        """Called at start-up: if Insight was not running for a while, record that as a gap."""
        now = now or utcnow()
        last = self.config.get("last_heartbeat")
        if not isinstance(last, int):
            return None
        stopped = _dt(last)
        if (now - stopped).total_seconds() <= tolerance_s:
            return None
        self.record_gap(INSIGHT_SCOPE, stopped, now)
        return Gap(INSIGHT_SCOPE, stopped, now)

    # -- retention ------------------------------------------------------------------------
    def rollup_day(self, day: str) -> None:
        """Daily summaries for one UTC day (YYYY-MM-DD): readings, events and findings."""
        start = int(datetime.fromisoformat(day).replace(tzinfo=UTC).timestamp())
        end = start + 86400

        def write(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT OR REPLACE INTO metric_daily(series_id, day, min, max, avg, count)"
                " SELECT series_id, ?, MIN(value), MAX(value), AVG(value), COUNT(*) FROM metrics"
                " WHERE ts >= ? AND ts < ? GROUP BY series_id",
                (day, start, end),
            )
            conn.execute(
                "INSERT OR REPLACE INTO event_daily(day, kind, count)"
                " SELECT ?, kind, COUNT(*) FROM events WHERE ts >= ? AND ts < ? GROUP BY kind",
                (day, start, end),
            )
            conn.execute(
                "INSERT OR REPLACE INTO finding_daily(day, rule_id, opened)"
                " SELECT ?, rule_id, COUNT(*) FROM findings WHERE first_detected_at >= ? AND first_detected_at < ?"
                " GROUP BY rule_id",
                (
                    day,
                    datetime.fromtimestamp(start, UTC).isoformat(),
                    datetime.fromtimestamp(end, UTC).isoformat(),
                ),
            )

        self.writer.call_sync(write)

    def nightly(self, now: datetime | None = None) -> dict[str, int]:
        """Roll up recent days, enforce retention and reclaim space."""
        now = now or utcnow()
        detail_days = int(self.config.get("retention_detail_days"))
        summary_days = int(self.config.get("retention_summary_days"))
        self.writer.flush_sync()
        with self.db.read() as conn:
            oldest = conn.execute("SELECT MIN(ts) FROM metrics").fetchone()[0]
            done = {r[0] for r in conn.execute("SELECT DISTINCT day FROM metric_daily")}
        today = now.date()
        first = _dt(oldest).date() if oldest is not None else today
        day = first
        while day < today:
            iso = day.isoformat()
            if iso not in done or (today - day).days <= 2:
                self.rollup_day(iso)
            day += timedelta(days=1)
        detail_cut = _ts(now - timedelta(days=detail_days))
        summary_cut = (now - timedelta(days=summary_days)).date().isoformat()
        finding_cut = (now - timedelta(days=summary_days)).isoformat()

        def prune(conn: sqlite3.Connection) -> dict[str, int]:
            removed = {
                "metrics": conn.execute("DELETE FROM metrics WHERE ts < ?", (detail_cut,)).rowcount,
                "events": conn.execute("DELETE FROM events WHERE ts < ?", (detail_cut,)).rowcount,
                "summaries": conn.execute(
                    "DELETE FROM metric_daily WHERE day < ?", (summary_cut,)
                ).rowcount
                + conn.execute("DELETE FROM event_daily WHERE day < ?", (summary_cut,)).rowcount
                + conn.execute("DELETE FROM finding_daily WHERE day < ?", (summary_cut,)).rowcount,
                "findings": conn.execute(
                    "DELETE FROM findings WHERE status='resolved' AND resolved_at < ?",
                    (finding_cut,),
                ).rowcount,
                "gaps": conn.execute(
                    "DELETE FROM gaps WHERE end_ts IS NOT NULL AND end_ts < ?", (detail_cut,)
                ).rowcount,
            }
            return removed

        removed = self.writer.call_sync(prune)
        self.writer.submit(lambda c: c.execute("PRAGMA incremental_vacuum(2000)")).result()
        self.writer.submit(lambda c: c.execute("ANALYZE")).result()
        return removed

    # -- disk space --------------------------------------------------------------------------
    def free_mb(self, path: Path) -> float:
        return shutil.disk_usage(path).free / 1_000_000

    def protect_disk(
        self, path: Path, *, free_mb: float | None = None, batch_days: int = 1
    ) -> dict[str, Any]:
        """If free space is low, remove the oldest detailed readings first. Never stops recording."""
        threshold = float(self.config.get("low_disk_free_mb"))
        free = self.free_mb(path) if free_mb is None else free_mb
        pruned = 0
        if free < threshold:
            with self.db.read() as conn:
                oldest = conn.execute("SELECT MIN(ts) FROM metrics").fetchone()[0]
            if oldest is not None:
                cut = oldest + 86400 * batch_days
                pruned = self.writer.call_sync(
                    lambda c: c.execute("DELETE FROM metrics WHERE ts < ?", (cut,)).rowcount
                )
                self.writer.submit(lambda c: c.execute("PRAGMA incremental_vacuum(2000)")).result()
        return {
            "low": free < threshold,
            "free_mb": round(free, 1),
            "threshold_mb": threshold,
            "pruned_rows": pruned,
        }
