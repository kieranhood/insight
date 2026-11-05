"""Local accounts with crew and engineer roles, Argon2id hashing and sign-in throttling."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from insight.storage.db import Database
from insight.storage.writer import Writer
from insight.timeutil import from_iso, to_iso, utcnow

MAX_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=10)
LOCKOUT = timedelta(minutes=15)
MIN_PASSWORD_LENGTH = 10

_hasher = PasswordHasher()  # Argon2id with library-recommended parameters


class Role(StrEnum):
    CREW = "crew"
    ENGINEER = "engineer"


@dataclass(frozen=True)
class User:
    id: int
    username: str
    role: Role

    @property
    def is_engineer(self) -> bool:
        return self.role is Role.ENGINEER


class SignInResult(StrEnum):
    OK = "ok"
    INVALID = "invalid"
    LOCKED = "locked"


class AccountError(ValueError):
    pass


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _validate(username: str, password: str) -> None:
    if not username.strip():
        raise AccountError("A username is required.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccountError(f"Passwords must be at least {MIN_PASSWORD_LENGTH} characters.")


class AccountStore:
    def __init__(self, db: Database, writer: Writer) -> None:
        self.db = db
        self.writer = writer

    def has_users(self) -> bool:
        with self.db.read() as conn:
            return conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def has_engineer(self) -> bool:
        with self.db.read() as conn:
            row = conn.execute("SELECT 1 FROM users WHERE role='engineer' LIMIT 1").fetchone()
            return row is not None

    def create(self, username: str, password: str, role: Role) -> User:
        _validate(username, password)
        hashed = hash_password(password)
        now = to_iso(utcnow())

        def write(conn: sqlite3.Connection) -> int:
            try:
                cur = conn.execute(
                    "INSERT INTO users(username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                    (username.strip(), hashed, role.value, now),
                )
            except sqlite3.IntegrityError as exc:
                raise AccountError("That username is already in use.") from exc
            return int(cur.lastrowid or 0)

        return User(self.writer.call_sync(write), username.strip(), role)

    def create_first_engineer(self, username: str, password: str) -> User:
        if self.has_users():
            raise AccountError("Insight has already been set up.")
        return self.create(username, password, Role.ENGINEER)

    def get(self, user_id: int) -> User | None:
        with self.db.read() as conn:
            row = conn.execute(
                "SELECT id, username, role FROM users WHERE id=?", (user_id,)
            ).fetchone()
        return User(row["id"], row["username"], Role(row["role"])) if row else None

    def list(self) -> list[User]:
        with self.db.read() as conn:
            rows = conn.execute("SELECT id, username, role FROM users ORDER BY username").fetchall()
        return [User(r["id"], r["username"], Role(r["role"])) for r in rows]

    def set_password(self, user_id: int, password: str) -> None:
        _validate("x", password)
        hashed = hash_password(password)
        self.writer.call_sync(
            lambda c: c.execute("UPDATE users SET password_hash=? WHERE id=?", (hashed, user_id))
        )

    def set_role(self, user_id: int, role: Role) -> None:
        def write(conn: sqlite3.Connection) -> None:
            if role is Role.CREW:
                engineers = conn.execute(
                    "SELECT COUNT(*) FROM users WHERE role='engineer' AND id<>?", (user_id,)
                ).fetchone()[0]
                if engineers == 0:
                    raise AccountError("Insight must keep at least one engineer account.")
            conn.execute("UPDATE users SET role=? WHERE id=?", (role.value, user_id))

        self.writer.call_sync(write)

    def delete(self, user_id: int) -> None:
        def write(conn: sqlite3.Connection) -> None:
            row = conn.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
            if row and row["role"] == "engineer":
                others = conn.execute(
                    "SELECT COUNT(*) FROM users WHERE role='engineer' AND id<>?", (user_id,)
                ).fetchone()[0]
                if others == 0:
                    raise AccountError("Insight must keep at least one engineer account.")
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))

        self.writer.call_sync(write)

    def authenticate(
        self, username: str, password: str, now: datetime | None = None
    ) -> tuple[SignInResult, User | None]:
        now = now or utcnow()
        with self.db.read() as conn:
            row = conn.execute(
                "SELECT id, username, role, password_hash, failed_attempts, locked_until "
                "FROM users WHERE username=?",
                (username.strip(),),
            ).fetchone()
        if row is None:
            verify_password(_DUMMY_HASH, password)  # keep timing similar for unknown users
            return SignInResult.INVALID, None
        locked_until = from_iso(row["locked_until"])
        if locked_until is not None and now < locked_until:
            return SignInResult.LOCKED, None
        if verify_password(row["password_hash"], password):
            self.writer.call_sync(
                lambda c: c.execute(
                    "UPDATE users SET failed_attempts='[]', locked_until=NULL, last_sign_in_at=? WHERE id=?",
                    (to_iso(now), row["id"]),
                )
            )
            return SignInResult.OK, User(row["id"], row["username"], Role(row["role"]))
        recent = [
            t
            for t in (from_iso(x) for x in json.loads(row["failed_attempts"]))
            if t is not None and now - t <= FAILURE_WINDOW
        ]
        recent.append(now)
        lock = to_iso(now + LOCKOUT) if len(recent) >= MAX_FAILURES else None
        payload = json.dumps([to_iso(t) for t in recent])
        self.writer.call_sync(
            lambda c: c.execute(
                "UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?",
                (payload, lock, row["id"]),
            )
        )
        return (SignInResult.LOCKED if lock else SignInResult.INVALID), None


_DUMMY_HASH = hash_password("insight-timing-equaliser")
