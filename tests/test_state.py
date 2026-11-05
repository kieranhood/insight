from __future__ import annotations

from datetime import timedelta

from insight.model import OnlineState, Reliability
from insight.state import FailureKind, SourceState, StateStore
from insight.timeutil import utcnow
from tests.factories import ap, dev, port, snap, wan

SW = "f0:9f:c2:00:00:10"
AP1 = "24:79:2a:00:00:01"


def store(*sources: tuple[str, Reliability]) -> StateStore:
    s = StateStore()
    for sid, rel in sources:
        s.configure_source(sid, name=sid, kind=sid, reliability=rel, interval_s=60)
    return s


def test_port_down_event() -> None:
    s = store(("unifi", Reliability.RELIABLE))
    t0 = utcnow()
    s.apply(snap("unifi", t0, ports=[port("unifi", SW, "12", t0, link_up=True, neighbour_mac=AP1)]))
    events = s.apply(
        snap(
            "unifi",
            t0 + timedelta(seconds=60),
            ports=[port("unifi", SW, "12", link_up=False, neighbour_mac=AP1)],
        )
    )
    assert [e.kind for e in events] == ["port_down"]
    assert f"mac:{AP1}" in events[0].devices


def test_poe_lost_event() -> None:
    s = store(("unifi", Reliability.RELIABLE))
    s.apply(snap("unifi", ports=[port("unifi", SW, "12", link_up=True, poe_power_w=7.2)]))
    events = s.apply(snap("unifi", ports=[port("unifi", SW, "12", link_up=True, poe_power_w=0.0)]))
    assert [e.kind for e in events] == ["poe_lost"]


def test_failover_event() -> None:
    s = store(("peplink", Reliability.RELIABLE))
    s.apply(
        snap(
            "peplink",
            wan_links=[
                wan("peplink", "1", "Starlink", in_use=True),
                wan("peplink", "2", "Cellular", in_use=False),
            ],
        )
    )
    events = s.apply(
        snap(
            "peplink",
            wan_links=[
                wan("peplink", "1", "Starlink", in_use=False),
                wan("peplink", "2", "Cellular", in_use=True),
            ],
        )
    )
    failovers = [e for e in events if e.kind == "failover"]
    assert len(failovers) == 1
    assert failovers[0].data == {"previous": ["Starlink"], "current": ["Cellular"]}


def test_device_seen_by_two_sources_is_merged() -> None:
    s = store(("unifi", Reliability.RELIABLE), ("ruckus-web", Reliability.OPTIONAL))
    s.apply(snap("unifi", devices=[dev("unifi", AP1, name="ap-saloon")]))
    s.apply(
        snap(
            "ruckus-web",
            rel=Reliability.OPTIONAL,
            devices=[
                dev(
                    "ruckus-web",
                    AP1,
                    rel=Reliability.OPTIONAL,
                    name="Saloon AP",
                    model="R650",
                    firmware="200.15",
                )
            ],
        )
    )
    merged = s.devices()
    assert list(merged) == [f"mac:{AP1}"]
    d = merged[f"mac:{AP1}"]
    assert d.name == "ap-saloon"  # reliable source wins
    assert d.model == "R650"  # filled from the optional source
    assert sorted(d.source_ids) == ["ruckus-web", "unifi"]


def test_failure_and_recovery_events_and_freshness() -> None:
    s = store(("unifi", Reliability.RELIABLE))
    t0 = utcnow()
    s.apply(snap("unifi", t0))
    assert s.is_fresh("unifi", t0)
    first = s.record_failure(
        "unifi", FailureKind.UNREACHABLE, "timed out", t0 + timedelta(seconds=60)
    )
    again = s.record_failure(
        "unifi", FailureKind.UNREACHABLE, "timed out", t0 + timedelta(seconds=120)
    )
    assert [e.kind for e in first] == ["monitoring_failure"]
    assert again == []
    assert s.sources["unifi"].state is SourceState.FAILED
    assert not s.is_fresh("unifi", t0 + timedelta(seconds=120))
    recovered = s.apply(snap("unifi", t0 + timedelta(seconds=180)))
    assert [e.kind for e in recovered] == ["monitoring_recovered"]


def test_stale_after_three_intervals() -> None:
    s = store(("unifi", Reliability.RELIABLE))
    t0 = utcnow()
    s.apply(snap("unifi", t0))
    assert s.is_fresh("unifi", t0 + timedelta(seconds=179))
    assert not s.is_fresh("unifi", t0 + timedelta(seconds=181))


def test_ap_offline_event() -> None:
    s = store(("ruckus-web", Reliability.OPTIONAL))
    s.apply(
        snap(
            "ruckus-web",
            rel=Reliability.OPTIONAL,
            access_points=[ap("ruckus-web", AP1, name="Saloon")],
        )
    )
    events = s.apply(
        snap(
            "ruckus-web",
            rel=Reliability.OPTIONAL,
            access_points=[ap("ruckus-web", AP1, name="Saloon", online=OnlineState.OFFLINE)],
        )
    )
    assert [e.kind for e in events] == ["ap_offline"]
