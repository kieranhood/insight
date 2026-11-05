from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from insight.collection.adapter import Adapter, AdapterInfo, AuthFailed, ParseFailed, Unreachable
from insight.collection.scheduler import CollectionResult, Scheduler
from insight.model import Reliability, Snapshot
from insight.sources import SourceConfig
from insight.state import FailureKind, SourceState, StateStore


def source(
    sid: str, rel: Reliability = Reliability.RELIABLE, interval: float = 0.05
) -> SourceConfig:
    return SourceConfig(
        id=sid, kind="fake", name=sid, address="x", reliability=rel, interval_s=interval
    )


class Fake(Adapter):
    info = AdapterInfo(
        kind="fake", label="Fake", reliability=Reliability.RELIABLE, default_interval_s=1
    )

    def __init__(self, src: SourceConfig, behaviour: str = "ok") -> None:
        super().__init__(src)
        self.behaviour = behaviour
        self.calls = 0

    @property
    def reliability(self) -> Reliability:
        return self.source.reliability

    @property
    def timeout_s(self) -> float:
        return 0.2

    async def collect(self, now: datetime) -> Snapshot:
        self.calls += 1
        if self.behaviour == "hang":
            await asyncio.sleep(3600)
        if self.behaviour == "unreachable":
            raise Unreachable("connection refused")
        if self.behaviour == "auth":
            raise AuthFailed("401 Unauthorized")
        if self.behaviour == "parse":
            raise ParseFailed("unexpected JSON")
        if self.behaviour == "bug":
            raise KeyError("oops")
        return self.new_snapshot(now)


async def test_hanging_adapter_does_not_delay_others() -> None:
    state = StateStore()
    sched = Scheduler(state, jitter=0)
    hanging, healthy = Fake(source("hang"), "hang"), Fake(source("ok"))
    sched.add(hanging)
    sched.add(healthy)
    sched.start()
    await asyncio.sleep(0.6)
    await sched.stop()
    assert healthy.calls >= 5
    assert state.sources["hang"].failure_kind is FailureKind.TIMEOUT
    assert state.sources["ok"].state is SourceState.OK


@pytest.mark.parametrize(
    ("behaviour", "kind"),
    [
        ("unreachable", FailureKind.UNREACHABLE),
        ("auth", FailureKind.AUTH),
        ("parse", FailureKind.PARSE),
        ("bug", FailureKind.PARSE),
    ],
)
async def test_failure_types_recorded(behaviour: str, kind: FailureKind) -> None:
    state = StateStore()
    sched = Scheduler(state)
    adapter = Fake(source("s"), behaviour)
    sched.add(adapter)
    result = await sched.run_once(adapter)
    assert result.snapshot is None
    assert [e.kind for e in result.events] == ["monitoring_failure"]
    assert state.sources["s"].failure_kind is kind
    assert not state.is_fresh("s")


async def test_recovery() -> None:
    state = StateStore()
    sched = Scheduler(state)
    adapter = Fake(source("s"), "unreachable")
    sched.add(adapter)
    await sched.run_once(adapter)
    adapter.behaviour = "ok"
    result = await sched.run_once(adapter)
    assert [e.kind for e in result.events] == ["monitoring_recovered"]
    assert state.is_fresh("s")


async def test_optional_failure_never_blocks_reliable() -> None:
    state = StateStore()
    seen: list[CollectionResult] = []

    async def hook(result: CollectionResult) -> None:
        seen.append(result)

    sched = Scheduler(state, hooks=[hook], jitter=0)
    optional = Fake(source("dish", Reliability.OPTIONAL), "parse")
    reliable = Fake(source("peplink"))
    sched.add(optional)
    sched.add(reliable)
    sched.start()
    await asyncio.sleep(0.4)
    await sched.stop()
    reliable_ok = [r for r in seen if r.source_id == "peplink" and r.snapshot is not None]
    assert len(reliable_ok) >= 3
    assert state.sources["dish"].state is SourceState.FAILED
    assert state.sources["dish"].reliability is Reliability.OPTIONAL
    assert state.is_fresh("peplink")


async def test_hook_errors_are_contained() -> None:
    async def bad_hook(result: CollectionResult) -> None:
        raise RuntimeError("hook bug")

    state = StateStore()
    sched = Scheduler(state, hooks=[bad_hook])
    adapter = Fake(source("s"))
    sched.add(adapter)
    result = await sched.run_once(adapter)
    assert result.snapshot is not None
