"""Server-side sessions with idle expiry and per-session CSRF tokens."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from insight.auth.accounts import AccountStore, Role, User
from insight.config_store import ConfigStore
from insight.storage.db import Database
from insight.storage.writer import Writer
from insight.timeutil import from_iso, to_iso, utcnow

COOKIE_NAME = "insight_session"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Session:
    user: User
    csrf_token: str
    token_hash: str


class SessionStore:
    def __init__(
        self, db: Database, writer: Writer, accounts: AccountStore, config: ConfigStore
    ) -> None:
        self.db = db
        self.writer = writer
        self.accounts = accounts
        self.config = config

    def idle_timeout(self, role: Role) -> timedelta:
        key = (
            "session_idle_minutes_engineer"
            if role is Role.ENGINEER
            else "session_idle_minutes_crew"
        )
        return timedelta(minutes=float(self.config.get(key)))

    def create(self, user: User, now: datetime | None = None) -> tuple[str, Session]:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        stamp = to_iso(now or utcnow())
        token_hash = _hash(token)
        self.writer.call_sync(
            lambda c: c.execute(
                "INSERT INTO sessions(token_hash, user_id, csrf_token, created_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (token_hash, user.id, csrf, stamp, stamp),
            )
        )
        return token, Session(user, csrf, token_hash)

    def validate(self, token: str | None, now: datetime | None = None) -> Session | None:
        if not token:
            return None
        now = now or utcnow()
        token_hash = _hash(token)
        with self.db.read() as conn:
            row = conn.execute(
                "SELECT user_id, csrf_token, last_seen_at FROM sessions WHERE token_hash=?",
                (token_hash,),
            ).fetchone()
        if row is None:
            return None
        user = self.accounts.get(row["user_id"])
        last_seen = from_iso(row["last_seen_at"])
        if user is None or last_seen is None or now - last_seen > self.idle_timeout(user.role):
            self.revoke(token)
            return None
        # Only write when it moves the expiry meaningfully, to keep reads cheap.
        if now - last_seen > timedelta(seconds=30):
            self.writer.call_sync(
                lambda c: c.execute(
                    "UPDATE sessions SET last_seen_at=? WHERE token_hash=?",
                    (to_iso(now), token_hash),
                )
            )
        return Session(user, row["csrf_token"], token_hash)

    def revoke(self, token: str) -> None:
        token_hash = _hash(token)
        self.writer.call_sync(
            lambda c: c.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
        )

    def revoke_user(self, user_id: int) -> None:
        self.writer.call_sync(
            lambda c: c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        )

    def purge_expired(self, now: datetime | None = None) -> int:
        now = now or utcnow()
        cutoff = to_iso(
            now - timedelta(minutes=float(self.config.get("session_idle_minutes_crew")))
        )

        def write(conn: sqlite3.Connection) -> int:
            return conn.execute("DELETE FROM sessions WHERE last_seen_at < ?", (cutoff,)).rowcount

        return self.writer.call_sync(write)


def csrf_matches(expected: str, supplied: str | None) -> bool:
    return bool(supplied) and secrets.compare_digest(expected, supplied or "")
