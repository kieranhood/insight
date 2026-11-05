"""The single database writer.

All writes run on one dedicated thread holding one connection, so SQLite never sees
competing writers. Metric and event inserts are buffered and written in batches.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TypeVar

from insight.model import Event, Metric
from insight.storage.db import Database, connect

log = logging.getLogger(__name__)
T = TypeVar("T")


class Writer:
    def __init__(self, db: Database, flush_interval: float = 0.5, max_batch: int = 5000) -> None:
        self.db = db
        self.flush_interval = flush_interval
        self.max_batch = max_batch
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="insight-writer")
        self._conn: sqlite3.Connection | None = None
        self._series: dict[tuple[str, str], int] = {}
        self._metrics: list[Metric] = []
        self._events: list[tuple[Event, tuple[str, ...]]] = []
        self._lock = threading.Lock()
        self._flush_task: asyncio.Task[None] | None = None

    # -- thread-confined helpers -------------------------------------------------
    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = connect(self.db.path)
        return self._conn

    def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        conn = self._connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = fn(conn)
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        return result

    # -- public API ----------------------------------------------------------------
    def submit(self, fn: Callable[[sqlite3.Connection], T]) -> Future[T]:
        return self._executor.submit(self._run, fn)

    def call_sync(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        return self.submit(fn).result()

    async def call(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        return await asyncio.wrap_future(self.submit(fn))

    def add_metrics(self, metrics: list[Metric]) -> None:
        with self._lock:
            self._metrics.extend(metrics)
            full = len(self._metrics) >= self.max_batch
        if full:
            self.flush_nowait()

    def add_events(self, events: list[Event], systems: tuple[str, ...] = ()) -> None:
        with self._lock:
            self._events.extend((e, systems) for e in events)

    def flush_nowait(self) -> Future[int]:
        with self._lock:
            metrics, self._metrics = self._metrics, []
            events, self._events = self._events, []
        return self.submit(lambda conn: self._write_batch(conn, metrics, events))

    async def flush(self) -> int:
        return await asyncio.wrap_future(self.flush_nowait())

    def flush_sync(self) -> int:
        return self.flush_nowait().result()

    def _series_id(self, conn: sqlite3.Connection, subject: str, name: str, unit: str) -> int:
        key = (subject, name)
        cached = self._series.get(key)
        if cached is not None:
            return cached
        conn.execute(
            "INSERT OR IGNORE INTO series(subject, name, unit) VALUES (?, ?, ?)",
            (subject, name, unit),
        )
        row = conn.execute("SELECT id FROM series WHERE subject=? AND name=?", key).fetchone()
        self._series[key] = int(row[0])
        return int(row[0])

    def _write_batch(
        self,
        conn: sqlite3.Connection,
        metrics: list[Metric],
        events: list[tuple[Event, tuple[str, ...]]],
    ) -> int:
        rows = [
            (
                self._series_id(conn, m.subject, m.name, m.unit),
                int(m.observed_at.timestamp()),
                m.value,
            )
            for m in metrics
        ]
        if rows:
            conn.executemany("INSERT INTO metrics(series_id, ts, value) VALUES (?, ?, ?)", rows)
        if events:
            conn.executemany(
                "INSERT INTO events(ts, kind, source_id, subject, devices, services, systems, message, data)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        int(e.observed_at.timestamp()),
                        e.kind,
                        e.source_id,
                        e.subject,
                        json.dumps(list(e.devices)),
                        json.dumps(list(e.services)),
                        json.dumps(list(systems)),
                        e.message,
                        json.dumps(e.data, default=str),
                    )
                    for e, systems in events
                ],
            )
        return len(rows) + len(events)

    async def run_periodic_flush(self) -> None:
        while True:
            await asyncio.sleep(self.flush_interval)
            try:
                await self.flush()
            except Exception:
                log.exception("database flush failed")

    def close(self) -> None:
        self.flush_sync()
        self._executor.submit(self._close_connection).result()
        self._executor.shutdown(wait=True)

    def _close_connection(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
