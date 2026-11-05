"""Configured integration sources, with their credentials encrypted at rest."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Any

from insight.auth.credentials import CredentialVault, masked
from insight.model import Reliability
from insight.storage.db import Database
from insight.storage.writer import Writer
from insight.timeutil import to_iso, utcnow


@dataclass
class SourceConfig:
    id: str
    kind: str
    name: str
    address: str
    reliability: Reliability
    enabled: bool = True
    credentials: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    interval_s: float | None = None

    def public(self) -> dict[str, Any]:
        """A representation safe to show in the interface or return from an API."""
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "address": self.address,
            "reliability": self.reliability.value,
            "enabled": self.enabled,
            "credentials": masked(self.credentials),
            "options": self.options,
            "interval_s": self.interval_s,
        }


def new_source_id(kind: str) -> str:
    return f"{re.sub(r'[^a-z0-9]+', '-', kind.lower())}-{uuid.uuid4().hex[:6]}"


class SourceStore:
    def __init__(self, db: Database, writer: Writer, vault: CredentialVault) -> None:
        self.db = db
        self.writer = writer
        self.vault = vault

    def _from_row(self, row: sqlite3.Row) -> SourceConfig:
        return SourceConfig(
            id=row["id"],
            kind=row["kind"],
            name=row["name"],
            address=row["address"],
            reliability=Reliability(row["reliability"]),
            enabled=bool(row["enabled"]),
            credentials=self.vault.decrypt(row["credentials"]),
            options=json.loads(row["options"]),
            interval_s=row["interval_s"],
        )

    def list(self) -> list[SourceConfig]:
        with self.db.read() as conn:
            rows = conn.execute("SELECT * FROM sources ORDER BY created_at").fetchall()
        return [self._from_row(r) for r in rows]

    def get(self, source_id: str) -> SourceConfig | None:
        with self.db.read() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        return self._from_row(row) if row else None

    def save(self, source: SourceConfig) -> SourceConfig:
        blob = self.vault.encrypt(source.credentials) if source.credentials else None
        values = (
            source.id,
            source.kind,
            source.name,
            source.address,
            source.reliability.value,
            int(source.enabled),
            blob,
            json.dumps(source.options),
            source.interval_s,
            to_iso(utcnow()),
        )
        self.writer.call_sync(
            lambda c: c.execute(
                "INSERT INTO sources(id, kind, name, address, reliability, enabled, credentials, options,"
                " interval_s, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, name=excluded.name,"
                " address=excluded.address, reliability=excluded.reliability, enabled=excluded.enabled,"
                " credentials=excluded.credentials, options=excluded.options, interval_s=excluded.interval_s",
                values,
            )
        )
        return source

    def update_credentials(self, source_id: str, updates: dict[str, Any]) -> None:
        """Replace credential fields. Blank values keep the stored value (they are never shown)."""
        source = self.get(source_id)
        if source is None:
            raise KeyError(source_id)
        for name, value in updates.items():
            if value not in (None, ""):
                source.credentials[name] = value
        self.save(source)

    def delete(self, source_id: str) -> None:
        self.writer.call_sync(lambda c: c.execute("DELETE FROM sources WHERE id=?", (source_id,)))
