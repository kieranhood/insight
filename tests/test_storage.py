from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from insight.model import Event, Metric, Reliability
from insight.storage.db import Database
from insight.storage.migrations import SCHEMA_VERSION
from insight.storage.writer import Writer
from insight.timeutil import utcnow


def test_migrating_empty_database_creates_backup(tmp_path: Path) -> None:
    path = tmp_path / "insight.db"
    sqlite3.connect(path).close()  # an existing, empty database file
    db = Database(path)
    backup = db.migrate()
    assert backup is not None and backup.exists()
    assert db.schema_version() == SCHEMA_VERSION
    # Re-running is a no-op and takes no further backup.
    assert db.migrate() is None


def test_fresh_install_needs_no_backup(tmp_path: Path) -> None:
    db = Database(tmp_path / "new" / "insight.db")
    assert db.migrate() is None
    assert db.schema_version() == SCHEMA_VERSION
    with db.read() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_newer_schema_refused(tmp_path: Path) -> None:
    path = tmp_path / "insight.db"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    conn.close()
    with pytest.raises(RuntimeError, match="newer"):
        Database(path).migrate()


@pytest.fixture
def writer(tmp_path: Path) -> Writer:
    db = Database(tmp_path / "insight.db")
    db.migrate()
    w = Writer(db)
    yield w
    w.close()


def test_batch_insert_10000_metrics(writer: Writer) -> None:
    start = utcnow()
    metrics = [
        Metric(
            source_id="sim",
            observed_at=start + timedelta(seconds=i),
            reliability=Reliability.RELIABLE,
            subject=f"device:{i % 50}",
            name="latency_ms",
            value=float(i),
            unit="ms",
        )
        for i in range(10_000)
    ]
    writer.add_metrics(metrics)
    writer.flush_sync()
    with writer.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 10_000
        assert conn.execute("SELECT COUNT(*) FROM series").fetchone()[0] == 50
        total = conn.execute("SELECT SUM(value) FROM metrics").fetchone()[0]
    assert total == sum(range(10_000))


def test_events_written(writer: Writer) -> None:
    event = Event(
        source_id="sim",
        observed_at=utcnow(),
        reliability=Reliability.RELIABLE,
        kind="failover",
        subject="wan",
        message="moved",
        data={"from": "Starlink"},
    )
    writer.add_events([event], systems=("peplink",))
    writer.flush_sync()
    with writer.db.read() as conn:
        row = conn.execute("SELECT kind, systems, data FROM events").fetchone()
    assert row["kind"] == "failover"
    assert "peplink" in row["systems"]


def test_failed_write_rolls_back(writer: Writer) -> None:
    def bad(conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO settings(key, value) VALUES ('a', '1')")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        writer.call_sync(bad)
    with writer.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0


def test_restore_backup_replaces_live_database(tmp_path: Path) -> None:
    path = tmp_path / "insight.db"
    db = Database(path)
    db.migrate()
    w = Writer(db)
    w.call_sync(
        lambda c: c.execute("INSERT INTO settings(key, value) VALUES ('marker', '\"before\"')")
    )
    w.close()
    conn = sqlite3.connect(path)
    snapshot = db._backup(conn, SCHEMA_VERSION)
    conn.close()
    w = Writer(db)
    w.call_sync(lambda c: c.execute("UPDATE settings SET value='\"after\"' WHERE key='marker'"))
    w.close()
    db.restore(snapshot.name)
    with db.read() as conn:
        assert (
            conn.execute("SELECT value FROM settings WHERE key='marker'").fetchone()[0]
            == '"before"'
        )
    assert len(db.backups()) == 2  # the replaced database was kept too
    with pytest.raises(FileNotFoundError):
        db.restore("nope.db")
