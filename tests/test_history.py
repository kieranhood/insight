from __future__ import annotations

from datetime import UTC, datetime, timedelta

from insight.history import INSIGHT_SCOPE
from insight.model import Event, Metric, Reliability
from insight.runtime import Runtime
from insight.timeutil import utcnow

R = Reliability.RELIABLE
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def metrics(
    subject: str, name: str, start: datetime, minutes: int, value: float = 1.0
) -> list[Metric]:
    return [
        Metric(
            source_id="s",
            observed_at=start + timedelta(minutes=i),
            reliability=R,
            subject=subject,
            name=name,
            value=value + i,
        )
        for i in range(minutes)
    ]


def event(
    kind: str,
    at: datetime,
    *,
    devices: tuple[str, ...] = (),
    services: tuple[str, ...] = (),
    source: str = "pep",
) -> Event:
    return Event(
        source_id=source,
        observed_at=at,
        reliability=R,
        kind=kind,
        subject="x",
        message=kind,
        devices=devices,
        services=services,
    )


# 13.1 -----------------------------------------------------------------------------------------
def test_query_returns_only_requested_range(runtime: Runtime) -> None:
    runtime.writer.add_metrics(
        metrics("wan:pep:1", "latency_ms", NOW - timedelta(hours=48), 48 * 60)
    )
    runtime.writer.flush_sync()
    points = runtime.history.readings("wan:pep:1", "latency_ms", NOW - timedelta(hours=24), NOW)
    assert points
    assert all(NOW - timedelta(hours=24) <= p.at <= NOW for p in points)
    assert len(points) <= 2000  # downsampled for slow links
    assert runtime.history.readings("wan:pep:1", "nope", NOW - timedelta(hours=1), NOW) == []


# 13.2 -----------------------------------------------------------------------------------------
def test_timeline_filters(runtime: Runtime) -> None:
    ap = "mac:24:79:2a:00:00:01"
    runtime.writer.add_events([event("failover", NOW - timedelta(hours=5))], systems=("peplink",))
    runtime.writer.add_events(
        [event("ap_disconnected", NOW - timedelta(hours=3), devices=(ap,), source="ruckus-syslog")],
        systems=("ruckus",),
    )
    runtime.writer.add_events(
        [event("status_change", NOW - timedelta(hours=2), services=("guest_wifi",))],
        systems=("insight",),
    )
    runtime.writer.add_events(
        [event("ap_disconnected", NOW - timedelta(days=10), devices=(ap,))], systems=("ruckus",)
    )
    runtime.writer.flush_sync()
    h = runtime.history
    assert [e.kind for e in h.timeline(start=NOW - timedelta(hours=6), end=NOW)] == [
        "status_change",
        "ap_disconnected",
        "failover",
    ]
    assert [e.kind for e in h.timeline(system="peplink")] == ["failover"]
    assert len(h.timeline(device=ap)) == 2
    assert len(h.timeline(device=ap, start=NOW - timedelta(days=7))) == 1
    assert [e.kind for e in h.timeline(service="guest_wifi")] == ["status_change"]
    assert [e.kind for e in h.timeline(kinds=["failover", "status_change"])] == [
        "status_change",
        "failover",
    ]


# 13.3 -----------------------------------------------------------------------------------------
def test_nightly_ages_out_detail_and_keeps_rollups(runtime: Runtime) -> None:
    old = NOW - timedelta(days=40)
    runtime.writer.add_metrics(metrics("probe:internet", "rtt_ms", old.replace(hour=0), 60, 10.0))
    runtime.writer.add_metrics(
        metrics("probe:internet", "rtt_ms", NOW - timedelta(hours=2), 60, 20.0)
    )
    runtime.writer.add_events([event("failover", old)], systems=("peplink",))
    runtime.writer.flush_sync()
    removed = runtime.history.nightly(NOW)
    assert removed["metrics"] == 60 and removed["events"] == 1
    assert (
        runtime.history.readings(
            "probe:internet", "rtt_ms", old - timedelta(days=1), old + timedelta(days=1)
        )
        == []
    )
    daily = runtime.history.daily(
        "probe:internet", "rtt_ms", old - timedelta(days=1), old + timedelta(days=1)
    )
    assert len(daily) == 1 and daily[0]["count"] == 60 and daily[0]["min"] == 10.0
    with runtime.db.read() as conn:
        assert (
            conn.execute("SELECT count FROM event_daily WHERE kind='failover'").fetchone()[0] == 1
        )


def test_retention_is_configurable(runtime: Runtime) -> None:
    runtime.config.set("retention_detail_days", 60)
    runtime.writer.add_metrics(metrics("probe:internet", "rtt_ms", NOW - timedelta(days=40), 5))
    runtime.writer.flush_sync()
    assert runtime.history.nightly(NOW)["metrics"] == 0


# 13.4 (pruning part; the finding is tested with the diagnostic rules) ----------------------------
def test_low_disk_prunes_oldest_first(runtime: Runtime) -> None:
    runtime.writer.add_metrics(metrics("probe:internet", "rtt_ms", NOW - timedelta(days=5), 30))
    runtime.writer.add_metrics(metrics("probe:internet", "rtt_ms", NOW - timedelta(hours=1), 30))
    runtime.writer.flush_sync()
    status = runtime.history.protect_disk(runtime.settings.data_dir, free_mb=100)
    assert status["low"] is True and status["pruned_rows"] == 30
    remaining = runtime.history.readings("probe:internet", "rtt_ms", NOW - timedelta(days=6), NOW)
    assert len(remaining) == 30 and all(p.at > NOW - timedelta(days=1) for p in remaining)
    assert runtime.history.protect_disk(runtime.settings.data_dir, free_mb=10_000)["low"] is False


# 13.5 -----------------------------------------------------------------------------------------
def test_insight_stopped_two_hours_is_a_gap(runtime: Runtime) -> None:
    stopped = NOW - timedelta(hours=3)
    runtime.writer.add_metrics(metrics("probe:internet", "rtt_ms", NOW - timedelta(hours=4), 60))
    runtime.writer.add_metrics(metrics("probe:internet", "rtt_ms", NOW - timedelta(hours=1), 60))
    runtime.writer.flush_sync()
    runtime.history.heartbeat(stopped)
    gap = runtime.history.record_downtime_since_last_heartbeat(NOW - timedelta(hours=1))
    assert gap is not None and gap.scope == INSIGHT_SCOPE
    points = runtime.history.readings("probe:internet", "rtt_ms", NOW - timedelta(hours=5), NOW)
    gaps = [p for p in points if p.value is None]
    assert len(gaps) == 1 and gaps[0].at == stopped
    assert not any(
        stopped < p.at < NOW - timedelta(hours=1) and p.value is not None for p in points
    )


def test_short_restart_is_not_a_gap(runtime: Runtime) -> None:
    runtime.history.heartbeat(NOW - timedelta(seconds=60))
    assert runtime.history.record_downtime_since_last_heartbeat(NOW) is None


async def test_monitoring_failure_opens_and_recovery_closes_gap(runtime: Runtime) -> None:
    from tests.test_scheduler import Fake, source

    adapter = Fake(source("unifi"), "unreachable")
    runtime.scheduler.add(adapter)
    await runtime.scheduler.run_once(adapter)
    adapter.behaviour = "ok"
    await runtime.scheduler.run_once(adapter)
    gaps = runtime.history.gaps(
        utcnow() - timedelta(minutes=5), utcnow() + timedelta(minutes=1), ["source:unifi"]
    )
    assert len(gaps) == 1 and gaps[0].end is not None
