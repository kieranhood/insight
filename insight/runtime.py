"""The Runtime holds every long-lived component of a running Insight instance."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from insight.auth.accounts import AccountStore
from insight.auth.credentials import CredentialVault
from insight.auth.sessions import SessionStore
from insight.collection.scheduler import CollectionResult, Scheduler
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
        self.scheduler = Scheduler(self.state, hooks=[self._on_collection])
        self.reload_tls: Callable[[], None] = lambda: None
        self._tasks: list[asyncio.Task[None]] = []

    def record_cycle(self, at: datetime | None = None) -> None:
        self.last_cycle_at = at or utcnow()

    def load_sources(self) -> None:
        """Create adapters for every enabled configured source."""
        from insight.collection import registry

        for source in self.sources.list():
            if source.enabled:
                self.scheduler.add(registry.build(source))
        self._update_expected_interval()

    def _update_expected_interval(self) -> None:
        intervals = [a.interval_s for a in self.scheduler.adapters.values()]
        self.expected_cycle_interval = min(intervals) if intervals else 60.0

    async def _on_collection(self, result: CollectionResult) -> None:
        if result.snapshot is not None:
            self.writer.add_metrics(result.snapshot.metrics)
        if result.events:
            status = self.state.sources.get(result.source_id)
            systems = (status.kind,) if status else ()
            self.writer.add_events(result.events, systems=systems)
        self.record_cycle()

    async def start_background(self) -> None:
        """Start long-running background services (writer flushing, collection, probes...)."""
        flush = asyncio.create_task(self.writer.run_periodic_flush(), name="writer-flush")
        self._tasks.append(flush)
        if not self.scheduler.adapters:
            self.load_sources()
        self._update_expected_interval()
        self.scheduler.start()

    async def stop_background(self) -> None:
        await self.scheduler.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def close(self) -> None:
        self.writer.close()
