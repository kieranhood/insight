"""The Runtime holds every long-lived component of a running Insight instance."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from insight.auth.accounts import AccountStore
from insight.auth.credentials import CredentialVault
from insight.auth.sessions import SessionStore
from insight.config_store import ConfigStore
from insight.settings import Settings
from insight.sources import SourceStore
from insight.state import StateStore
from insight.storage.db import Database
from insight.storage.writer import Writer
from insight.timeutil import utcnow


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.started_at: datetime = utcnow()
        self.last_cycle_at: datetime | None = None
        self.expected_cycle_interval: float = 60.0

        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(settings.data_dir / "insight.db")
        self.db.migrate()
        self.writer = Writer(self.db)
        self.config = ConfigStore(self.db, self.writer)
        self.accounts = AccountStore(self.db, self.writer)
        self.sessions = SessionStore(self.db, self.writer, self.accounts, self.config)
        self.vault = CredentialVault(settings.data_dir / "secret.key")
        self.sources = SourceStore(self.db, self.writer, self.vault)
        self.state = StateStore()
        self.reload_tls: Callable[[], None] = lambda: None
        self._tasks: list[asyncio.Task[None]] = []

    async def start_background(self) -> None:
        """Start long-running background services (writer flushing, collection, probes...)."""
        self._tasks.append(
            asyncio.create_task(self.writer.run_periodic_flush(), name="writer-flush")
        )

    async def stop_background(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def record_cycle(self, at: datetime | None = None) -> None:
        self.last_cycle_at = at or utcnow()

    def close(self) -> None:
        self.writer.close()
