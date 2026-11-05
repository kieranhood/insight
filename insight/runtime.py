"""The Runtime holds every long-lived component of a running Insight instance."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable
from datetime import datetime

from insight.auth.accounts import AccountStore
from insight.auth.credentials import CredentialVault
from insight.auth.sessions import SessionStore
from insight.collection.scheduler import CollectionResult, Scheduler
from insight.config_store import ConfigStore
from insight.inventory import Inventory
from insight.model import Event
from insight.settings import Settings
from insight.sources import SourceStore
from insight.state import StateStore
from insight.storage.db import Database
from insight.storage.writer import Writer
from insight.timeutil import utcnow

log = logging.getLogger(__name__)


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
        self.inventory = Inventory(self.db, self.writer)
        self.scheduler = Scheduler(self.state, hooks=[self._on_collection])
        self.reload_tls: Callable[[], None] = lambda: None
        self._tasks: list[asyncio.Task[None]] = []
        self.recent_events: deque[Event] = deque(maxlen=2000)
        self._syslog: asyncio.DatagramTransport | None = None

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
            result.events.extend(await asyncio.to_thread(self.inventory.sync, result.snapshot))
        if result.events:
            status = self.state.sources.get(result.source_id)
            systems = (status.kind,) if status else ()
            self.writer.add_events(result.events, systems=systems)
            self.recent_events.extend(result.events)
        self.record_cycle()

    def on_pushed_event(self, event: Event) -> None:
        """Events pushed to Insight (syslog), rather than collected by polling."""
        self.writer.add_events([event], systems=("ruckus",))
        self.recent_events.append(event)

    def syslog_senders(self) -> set[str]:
        """Accept syslog only from Ruckus equipment Insight knows about (any, if none known yet)."""
        hosts = {
            s.address.split("://")[-1].split(":")[0]
            for s in self.sources.list()
            if s.kind.startswith("ruckus")
        }
        hosts |= {
            d.ip for d in self.inventory.devices().values() if d.ip and d.manufacturer == "Ruckus"
        }
        return hosts

    async def start_syslog(self) -> None:
        from insight.adapters.ruckus import start_syslog

        try:
            self._syslog = await start_syslog(
                self.settings.bind_host,
                self.settings.syslog_port,
                self.on_pushed_event,
                self.syslog_senders,
            )
        except OSError as exc:
            log.warning("syslog receiver not started on UDP %s: %s", self.settings.syslog_port, exc)

    async def start_background(self) -> None:
        """Start long-running background services (writer flushing, collection, probes...)."""
        flush = asyncio.create_task(self.writer.run_periodic_flush(), name="writer-flush")
        self._tasks.append(flush)
        if not self.scheduler.adapters:
            self.load_sources()
        self._update_expected_interval()
        self.scheduler.start()
        if self.settings.syslog_port:
            await self.start_syslog()

    async def stop_background(self) -> None:
        if self._syslog is not None:
            self._syslog.close()
            self._syslog = None
        await self.scheduler.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def close(self) -> None:
        self.writer.close()
