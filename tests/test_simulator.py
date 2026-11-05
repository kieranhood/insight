from __future__ import annotations

import pytest

from insight.adapters.simulator import ROLES, SCENARIOS, SimulatorAdapter, SimulatorHub
from insight.collection.scheduler import Scheduler
from insight.model import Event
from insight.sources import SourceConfig
from insight.state import StateStore


def sim_sources(hub: str) -> list[SimulatorAdapter]:
    return [
        SimulatorAdapter(
            SourceConfig(
                id=f"sim-{role}",
                kind="simulator",
                name=f"Simulated {role}",
                address=role,
                reliability=reliability,
                options={"role": role, "hub": hub},
            )
        )
        for role, reliability in ROLES.items()
    ]


async def run_scenario(name: str) -> tuple[list[Event], StateStore]:
    SimulatorHub.reset_all()
    hub = SimulatorHub.get(name)
    hub.load(name)
    state = StateStore()
    sched = Scheduler(state)
    adapters = sim_sources(name)
    for a in adapters:
        sched.add(a)
    events: list[Event] = []
    for a in adapters:  # baseline cycle
        events.extend((await sched.run_once(a)).events)
    while hub.step():
        for a in adapters:
            events.extend((await sched.run_once(a)).events)
    return events, state


@pytest.mark.parametrize("name", sorted(SCENARIOS))
async def test_scenario_emits_expected_events(name: str) -> None:
    events, _ = await run_scenario(name)
    kinds = {e.kind for e in events}
    for expected in SCENARIOS[name].expect_events:
        assert expected in kinds, (name, expected, sorted(kinds))


async def test_baseline_is_quiet() -> None:
    events, state = await run_scenario("baseline")
    assert events == []
    assert all(state.is_fresh(sid) for sid in state.sources)


async def test_required_scenarios_exist() -> None:
    for name in ["failover", "ap_poe_loss", "dish_obstruction", "controller_outage", "dns_failure"]:
        assert name in SCENARIOS


async def test_failover_moves_traffic_to_cellular() -> None:
    events, state = await run_scenario("failover")
    failover = next(e for e in events if e.kind == "failover")
    assert failover.data["current"] == ["Cellular"]
    assert {link.name: link.in_use for link in state.wan_links()} == {
        "Starlink": False,
        "Cellular": True,
    }


async def test_controller_outage_marks_only_unifi_failed() -> None:
    _, state = await run_scenario("controller_outage")
    assert not state.is_fresh("sim-unifi")
    assert state.is_fresh("sim-peplink") and state.is_fresh("sim-ruckus-snmp")


async def test_poe_loss_makes_ap_unreachable_to_probes() -> None:
    _, state = await run_scenario("ap_poe_loss")
    reach = state.facts("sim-probes")["probe.device"]
    assert reach["mac:24:79:2a:00:00:04"]["reachable"] is False
    assert reach["mac:24:79:2a:00:00:01"]["reachable"] is True
