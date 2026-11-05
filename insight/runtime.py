"""The Runtime holds every long-lived component of a running Insight instance."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import Any

from insight.auth.accounts import AccountStore
from insight.auth.credentials import CredentialVault
from insight.auth.sessions import SessionStore
from insight.collection.scheduler import CollectionResult, Scheduler
from insight.config_store import ConfigStore
from insight.diagnostics.context import EvalContext
from insight.diagnostics.engine import Engine
from insight.diagnostics.rules import all_rules
from insight.diagnostics.store import FindingStore
from insight.discovery import DiscoveryStore
from insight.history import History
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
        self.history = History(self.db, self.writer, self.config)
        self.disk_status: dict[str, Any] = {}
        self.engine = Engine(self.db, self.writer, all_rules())
        self.findings = FindingStore(self.db)
        self.evaluation_interval = 15.0
        self.discovery = DiscoveryStore(self.db, self.writer, self.inventory)
        self.discovery_run: Any = None
        self._listeners: list[asyncio.BaseTransport] = []
        self.scheduler = Scheduler(self.state, hooks=[self._on_collection])
        self.reload_tls: Callable[[], None] = lambda: None
        self._tasks: list[asyncio.Task[None]] = []
        self.recent_events: deque[Event] = deque(maxlen=2000)
        self._syslog: asyncio.DatagramTransport | None = None

    def record_cycle(self, at: datetime | None = None) -> None:
        self.last_cycle_at = at or utcnow()

    def load_sources(self) -> None:
        """Create adapters for every enabled configured source, plus Insight's own probes."""
        from insight.collection import registry
        from insight.probes import ProbesAdapter, probes_source

        if not any(
            s.kind == "simulator" and s.options.get("role") == "probes" for s in self.sources.list()
        ):
            self.scheduler.add(
                ProbesAdapter(
                    probes_source(), inventory=self.inventory, config=self.config, state=self.state
                )
            )
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
            result.events.extend(
                await asyncio.to_thread(self.discovery.observe_snapshot, result.snapshot)
            )
        for event in result.events:
            scope = f"source:{result.source_id}"
            if event.kind == "monitoring_failure":
                await asyncio.to_thread(self.history.open_gap, scope, event.observed_at)
            elif event.kind == "monitoring_recovered":
                await asyncio.to_thread(self.history.close_gap, scope, event.observed_at)
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
        await asyncio.to_thread(self.history.record_downtime_since_last_heartbeat)
        self._tasks.append(asyncio.create_task(self._housekeeping(), name="housekeeping"))
        self._tasks.append(asyncio.create_task(self._evaluation_loop(), name="diagnostics"))
        if not self.scheduler.adapters:
            self.load_sources()
        self._update_expected_interval()
        self.scheduler.start()
        if self.settings.syslog_port:
            await self.start_syslog()
        if self.settings.listen_announcements:
            from insight.discovery.listeners import start_listeners

            self._listeners = await start_listeners(self.on_announcement)

    def source_kinds(self) -> dict[str, str]:
        """Effective kind per source; simulator sources count as the role they play."""
        kinds = {sid: status.kind for sid, status in self.state.sources.items()}
        for source in self.sources.list():
            if source.kind == "simulator":
                kinds[source.id] = str(source.options.get("role") or source.address)
        return kinds

    def eval_context(self, now: datetime | None = None) -> EvalContext:
        return EvalContext(
            now=now or utcnow(),
            state=self.state,
            inventory=self.inventory,
            config=self.config.all(),
            recent_events=list(self.recent_events),
            source_kinds=self.source_kinds(),
            disk=dict(self.disk_status),
        )

    def evaluate(self, now: datetime | None = None) -> list[Event]:
        """One diagnostic cycle. Returns the finding events it produced (already recorded)."""
        events = self.engine.evaluate(self.eval_context(now))
        if events:
            self.writer.add_events(events, systems=("insight",))
            self.recent_events.extend(events)
        return events

    async def _evaluation_loop(self) -> None:
        while True:
            await asyncio.sleep(self.evaluation_interval)
            try:
                await asyncio.to_thread(self.evaluate)
            except Exception:
                log.exception("diagnostic evaluation failed")

    async def _housekeeping(self) -> None:
        """Heartbeat (for downtime gaps), disk protection every 10 minutes, retention nightly."""
        last_nightly = 0.0
        last_disk = 0.0
        loop = asyncio.get_running_loop()
        while True:
            try:
                await asyncio.to_thread(self.history.heartbeat)
                if loop.time() - last_disk >= 600:
                    self.disk_status = await asyncio.to_thread(
                        self.history.protect_disk, self.settings.data_dir
                    )
                    last_disk = loop.time()
                if loop.time() - last_nightly >= 86400:
                    await asyncio.to_thread(self.history.nightly)
                    last_nightly = loop.time()
            except Exception:
                log.exception("housekeeping failed")
            await asyncio.sleep(60)

    def on_announcement(self, announcement: Any) -> None:
        event = self.discovery.observe_announcement(
            ip=announcement.ip,
            name=announcement.name,
            services=announcement.services,
            server=announcement.server,
        )
        if event is not None:
            self.on_internal_event(event)

    def on_internal_event(self, event: Event) -> None:
        self.writer.add_events([event], systems=("insight",))
        self.recent_events.append(event)

    async def start_discovery_run(self, started_by: str) -> Any:
        """Start an engineer-requested active sweep of the selected subnets."""
        from insight.discovery import DISCOVERY_SOURCE_ID
        from insight.discovery.sweep import SweepRun, plan, sweep
        from insight.model import Reliability

        if self.discovery_run is not None and self.discovery_run.running:
            return self.discovery_run
        run = SweepRun(
            started_by=started_by,
            plan=plan(
                list(self.config.get("discovery_selected_subnets")),
                list(self.config.get("discovery_excluded_subnets")),
            ),
        )

        def event(kind: str, message: str) -> None:
            self.on_internal_event(
                Event(
                    source_id=DISCOVERY_SOURCE_ID,
                    observed_at=utcnow(),
                    reliability=Reliability.RELIABLE,
                    kind=kind,
                    subject="discovery",
                    message=message,
                    data={
                        "started_by": started_by,
                        "subnets": run.plan.selected,
                        "excluded": run.plan.excluded,
                    },
                )
            )

        def found(ip: str, observations: dict[str, Any]) -> None:
            self.discovery.record(
                mac=None,
                ip=ip,
                name=None,
                how="found by a discovery run",
                observations=observations,
            )

        async def go() -> None:
            await sweep(run, found)
            event(
                "discovery_run_finished",
                f"Discovery run {'cancelled' if run.cancelled else 'finished'}: "
                f"{run.scanned} addresses checked, {len(run.found)} answered",
            )

        event(
            "discovery_run_started",
            f"{started_by} started a discovery run on {', '.join(run.plan.selected)}",
        )
        run.task = asyncio.create_task(go(), name="discovery-run")
        self.discovery_run = run
        return run

    def cancel_discovery_run(self) -> None:
        if self.discovery_run is not None:
            self.discovery_run.cancelled = True

    async def stop_background(self) -> None:
        for transport in self._listeners:
            transport.close()
        self._listeners.clear()
        if self.discovery_run is not None and self.discovery_run.task is not None:
            self.discovery_run.cancelled = True
            await asyncio.gather(self.discovery_run.task, return_exceptions=True)
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
