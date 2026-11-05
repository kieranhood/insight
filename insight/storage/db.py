"""SQLite database: WAL mode, versioned migrations with automatic pre-migration backup."""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from insight.storage.migrations import MIGRATIONS, SCHEMA_VERSION
from insight.timeutil import utcnow

log = logging.getLogger(__name__)


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


class Database:
    """Owns the database file. Writes go through the single Writer; reads use short-lived connections."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.backup_dir = path.parent / "backups"

    def schema_version(self) -> int:
        with self.read() as conn:
            return int(conn.execute("PRAGMA user_version").fetchone()[0])

    def migrate(self) -> Path | None:
        """Apply pending migrations. Returns the backup file taken first, if any."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists()
        conn = connect(self.path)
        try:
            current = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if current > SCHEMA_VERSION:
                raise RuntimeError(
                    f"database schema v{current} is newer than this Insight (v{SCHEMA_VERSION}); "
                    "restore a backup or run a newer image"
                )
            if current == SCHEMA_VERSION:
                return None
            backup = self._backup(conn, current) if existed else None
            for version in range(current, SCHEMA_VERSION):
                log.info("applying schema migration v%d -> v%d", version, version + 1)
                conn.executescript(
                    "BEGIN;\n"
                    + MIGRATIONS[version]
                    + f"\nPRAGMA user_version={version + 1};\nCOMMIT;"
                )
            return backup
        finally:
            conn.close()

    def _backup(self, conn: sqlite3.Connection, version: int) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
        target = self.backup_dir / f"insight-v{version}-{stamp}.db"
        dest = sqlite3.connect(target)
        try:
            conn.backup(dest)
        finally:
            dest.close()
        log.info("backed up database to %s before migrating", target)
        return target

    @contextlib.contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = connect(self.path)
        try:
            yield conn
        finally:
            conn.close()
