"""Runs each source on its own schedule, isolated from every other source."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from insight.collection.adapter import Adapter, CollectionError
from insight.model import Event, Snapshot
from insight.state import FailureKind, StateStore
from insight.timeutil import utcnow

log = logging.getLogger(__name__)

ResultHook = Callable[["CollectionResult"], Awaitable[None]]


@dataclass
class CollectionResult:
    source_id: str
    at: datetime
    snapshot: Snapshot | None
    events: list[Event]


class Scheduler:
    def __init__(
        self,
        state: StateStore,
        hooks: list[ResultHook] | None = None,
        jitter: float = 0.1,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.state = state
        self.hooks = hooks or []
        self.jitter = jitter
        self.clock = clock
        self.adapters: dict[str, Adapter] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self.last_attempt_at: datetime | None = None
        self.running = False

    def add(self, adapter: Adapter) -> None:
        source = adapter.source
        self.state.configure_source(
            source.id,
            name=source.name,
            kind=source.kind,
            reliability=adapter.reliability,
            interval_s=adapter.interval_s,
        )
        self.adapters[source.id] = adapter

    def start(self) -> None:
        self.running = True
        for source_id in self.adapters:
            self._start_one(source_id)

    def _start_one(self, source_id: str) -> None:
        if source_id not in self._tasks or self._tasks[source_id].done():
            self._tasks[source_id] = asyncio.create_task(
                self._loop(source_id), name=f"collect:{source_id}"
            )

    async def replace(self, adapter: Adapter) -> None:
        await self.remove(adapter.source.id, forget_state=False)
        self.add(adapter)
        if self.running:
            self._start_one(adapter.source.id)

    async def remove(self, source_id: str, forget_state: bool = True) -> None:
        task = self._tasks.pop(source_id, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        adapter = self.adapters.pop(source_id, None)
        if adapter:
            await adapter.close()
        if forget_state:
            self.state.remove_source(source_id)

    async def stop(self) -> None:
        self.running = False
        for source_id in list(self._tasks):
            await self.remove(source_id, forget_state=False)

    async def _loop(self, source_id: str) -> None:
        # Spread sources out so they are not all polled at the same moment.
        await asyncio.sleep(random.uniform(0, self.jitter) * self.adapters[source_id].interval_s)  # noqa: S311
        while True:
            adapter = self.adapters.get(source_id)
            if adapter is None:
                return
            await self.run_once(adapter)
            delay = adapter.interval_s * (1 + random.uniform(-self.jitter, self.jitter))  # noqa: S311
            await asyncio.sleep(max(0.05, delay))

    async def run_once(self, adapter: Adapter) -> CollectionResult:
        """One collection attempt for one source. Never raises."""
        source_id = adapter.source.id
        at = self.clock()
        snapshot: Snapshot | None = None
        try:
            snapshot = await asyncio.wait_for(adapter.collect(at), timeout=adapter.timeout_s)
            events = self.state.apply(snapshot)
        except CollectionError as exc:
            events = self.state.record_failure(source_id, exc.kind, exc.message, at)
        except TimeoutError:
            events = self.state.record_failure(
                source_id, FailureKind.TIMEOUT, f"no response within {adapter.timeout_s:.0f} s", at
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # an adapter bug or unexpected data must not stop collection
            log.exception("unexpected error collecting from %s", source_id)
            events = self.state.record_failure(
                source_id, FailureKind.PARSE, f"unexpected data or error: {type(exc).__name__}", at
            )
        self.last_attempt_at = self.clock()
        result = CollectionResult(source_id, at, snapshot, events)
        for hook in self.hooks:
            try:
                await hook(result)
            except Exception:
                log.exception("collection hook failed for %s", source_id)
        return result
