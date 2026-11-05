from __future__ import annotations

from insight.health import Status
from insight.inventory import Service
from insight.runtime import Runtime
from tests.sim import Sim


async def report_after(runtime: Runtime, scenario: str, **kw: object) -> tuple[Sim, object]:
    sim = Sim(runtime, scenario, **kw)  # type: ignore[arg-type]
    await sim.play(cycles_per_step=12)
    return sim, runtime.health(sim.now)


async def test_status_values_and_healthy_baseline(runtime: Runtime) -> None:
    _sim, report = await report_after(runtime, "baseline")
    items = [report.overall, *report.services, *report.systems]  # type: ignore[attr-defined]
    assert {i.status for i in items} <= set(Status)
    assert report.overall.status is Status.HEALTHY  # type: ignore[attr-defined]
    assert {s.id: s.status for s in report.systems} == {  # type: ignore[attr-defined]
        "peplink": Status.HEALTHY,
        "starlink": Status.HEALTHY,
        "unifi": Status.HEALTHY,
        "ruckus": Status.HEALTHY,
    }


async def test_failover_makes_internet_degraded(runtime: Runtime) -> None:
    _, report = await report_after(runtime, "failover")
    internet = report.item("internet")  # type: ignore[attr-defined]
    assert internet.status is Status.DEGRADED
    assert internet.findings and internet.findings[0].rule_id == "failover_to_backup"
    assert internet.updated_at is not None
    assert report.item("starlink").status is Status.CRITICAL  # type: ignore[attr-defined]
    assert report.overall.status is Status.DEGRADED  # type: ignore[attr-defined]


async def test_one_ap_down_degrades_guest_wifi(runtime: Runtime) -> None:
    _, report = await report_after(runtime, "ap_offline")
    assert report.item("guest_wifi").status is Status.DEGRADED  # type: ignore[attr-defined]
    assert report.item("internet").status is Status.HEALTHY  # type: ignore[attr-defined]


async def test_internet_down_is_critical_overall(runtime: Runtime) -> None:
    _, report = await report_after(runtime, "internet_down")
    assert report.item("internet").status is Status.CRITICAL  # type: ignore[attr-defined]
    assert report.overall.status is Status.CRITICAL  # type: ignore[attr-defined]
    assert report.item("guest_wifi").status is Status.HEALTHY  # type: ignore[attr-defined]


async def test_wifi_monitoring_lost_is_unknown_not_critical(runtime: Runtime) -> None:
    sim = Sim(runtime, "baseline")
    await sim.settle(4)
    sim.hub.world.down_roles.update({"ruckus-snmp", "ruckus-web"})
    await sim.settle(10)
    report = runtime.health(sim.now)
    assert report.item("ruckus").status is Status.UNKNOWN
    assert report.item("guest_wifi").status is Status.UNKNOWN
    assert "can't currently check" in report.item("guest_wifi").reason
    assert report.overall.status is Status.HEALTHY  # unknown services don't make the yacht unknown


async def test_unmapped_service_is_unknown_not_set_up(runtime: Runtime) -> None:
    sim = Sim(runtime, "baseline")
    await sim.settle(4)
    runtime.inventory.unmap(Service.CREW_WIFI, "ssid", "Crew")
    item = runtime.health(sim.now).item("crew_wifi")
    assert item is not None and item.status is Status.UNKNOWN and "Not set up" in item.reason


async def test_overall_unknown_only_when_every_service_unknown(runtime: Runtime) -> None:
    report = runtime.health()
    assert all(s.status is Status.UNKNOWN for s in report.services)
    assert report.overall.status is Status.UNKNOWN


# 16.2 --------------------------------------------------------------------------------------
async def test_degraded_service_lists_findings_and_changes_are_recorded(runtime: Runtime) -> None:
    sim = Sim(runtime, "failover")
    events = await sim.play(cycles_per_step=12)
    changes = [e for e in events if e.kind == "status_change"]
    internet_change = [e for e in changes if e.data["item"] == "internet"]
    assert internet_change and internet_change[0].data == {
        "item": "internet",
        "before": "HEALTHY",
        "after": "DEGRADED",
        "reason": internet_change[0].data["reason"],
    }
    assert internet_change[0].services == ("internet",)
    sim.hub.load("baseline")
    events = await sim.settle(12)
    recovered = [e for e in events if e.kind == "status_change" and e.data["item"] == "internet"]
    assert recovered and recovered[-1].data["after"] == "HEALTHY"
    runtime.writer.flush_sync()
    assert runtime.history.timeline(service="internet", kinds=["status_change"])
