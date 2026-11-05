from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from insight.adapters.simulator import ROLES, SimulatorAdapter
from insight.diagnostics import Action, Confidence
from insight.diagnostics.lint import lint_crew_text
from insight.runtime import Runtime
from tests.sim import Sim


async def play(runtime: Runtime, scenario: str, roles: dict | None = None, cycles: int = 12) -> Sim:
    sim = Sim(runtime, scenario, roles=roles)
    await sim.play(cycles_per_step=cycles)
    for finding in runtime.findings.query():
        assert lint_crew_text(finding.crew_text, finding.confidence) == [], (
            finding.rule_id,
            finding.crew_text,
        )
        assert finding.evidence or runtime.findings.get(finding.id).evidence, finding.rule_id  # type: ignore[union-attr]
    return sim


def only(sim: Sim, rule_id: str) -> Any:
    findings = sim.open_findings()
    assert rule_id in findings, sorted(findings)
    return findings[rule_id]


# 15.1 internet ---------------------------------------------------------------------------
async def test_internet_unavailable(runtime: Runtime) -> None:
    sim = await play(runtime, "internet_down")
    f = only(sim, "internet_unavailable")
    assert f.confidence is Confidence.CONFIRMED and f.severity.value == "critical"
    assert set(sim.open_findings()) == {"internet_unavailable"}  # failover/DNS symptoms absorbed
    assert f.guests_affected and f.action is Action.CONTACT


async def test_failover_with_data_cost_note(runtime: Runtime) -> None:
    sim = await play(runtime, "failover")
    f = only(sim, "failover_to_backup")
    assert f.confidence is Confidence.CONFIRMED
    assert "main internet connection (Starlink) is unavailable" in f.crew_text
    assert "mobile data, which can be expensive" in f.crew_text
    assert f.action is Action.NONE


async def test_primary_link_degraded(runtime: Runtime) -> None:
    sim = await play(runtime, "primary_degraded")
    f = only(sim, "primary_link_degraded")
    assert f.confidence is Confidence.INSUFFICIENT
    assert "can't yet tell why" in f.crew_text
    full = runtime.findings.get(f.id)
    assert full is not None and any("loss" in e.description for e in full.evidence)


async def test_all_paths_degraded(runtime: Runtime) -> None:
    sim = await play(runtime, "all_paths_degraded")
    f = only(sim, "all_paths_degraded")
    assert f.confidence is Confidence.PROBABLE
    assert "primary_link_degraded" not in sim.open_findings()
    assert len(f.likely_causes) >= 2  # several explanations, none named definite


# 15.2 DNS ---------------------------------------------------------------------------------
async def test_dns_failure(runtime: Runtime) -> None:
    sim = await play(runtime, "dns_failure")
    f = only(sim, "dns_failure")
    assert f.confidence is Confidence.PROBABLE
    assert "DNS problem is suspected" in f.summary and "IP connectivity works" in f.summary
    full = runtime.findings.get(f.id)
    assert full is not None and len(full.evidence) == 3


# 15.3 Starlink ------------------------------------------------------------------------------
async def test_obstruction_with_dish_data(runtime: Runtime) -> None:
    sim = await play(runtime, "dish_obstruction")
    f = only(sim, "starlink_obstructed")
    assert f.confidence is Confidence.CONFIRMED and f.action is Action.NONE
    assert "Nothing needs to be fixed on board" in f.crew_text
    assert "primary_link_degraded" not in sim.open_findings()


async def test_obstruction_without_dish_data_falls_back(runtime: Runtime) -> None:
    roles = {k: v for k, v in ROLES.items() if k != "starlink"}
    sim = await play(runtime, "dish_obstruction", roles=roles)
    findings = sim.open_findings()
    assert "starlink_obstructed" not in findings
    assert findings["primary_link_degraded"].confidence is Confidence.INSUFFICIENT  # type: ignore[attr-defined]


async def test_dish_alert(runtime: Runtime) -> None:
    sim = await play(runtime, "dish_alert")
    f = only(sim, "starlink_dish_alert")
    assert f.title == "The Starlink dish is too hot and has slowed itself down"


async def test_dish_alert_needs_dish_data(runtime: Runtime) -> None:
    roles = {k: v for k, v in ROLES.items() if k != "starlink"}
    sim = await play(runtime, "dish_alert", roles=roles)
    assert "starlink_dish_alert" not in sim.open_findings()


# 15.4 cellular ---------------------------------------------------------------------------------
async def test_weak_cellular(runtime: Runtime) -> None:
    sim = await play(runtime, "weak_cellular")
    f = only(sim, "weak_cellular_signal")
    assert f.confidence is Confidence.CONFIRMED
    assert "RSRP -118.0" in f.summary
    assert "RSRP" not in f.crew_text


# 15.5 Wi-Fi infrastructure --------------------------------------------------------------------
async def test_ap_lost_poe_confirmed(runtime: Runtime) -> None:
    sim = await play(runtime, "ap_poe_loss")
    f = only(sim, "ap_lost_poe")
    assert f.confidence is Confidence.CONFIRMED
    assert "Lower deck, guest cabin 4" in f.crew_text  # location for crew
    assert "SW-LD-01 port 1" in f.summary  # switch and port for engineers
    assert "ap_offline" not in sim.open_findings()


async def test_ap_lost_connection_without_poe_data_is_probable(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = SimulatorAdapter._unifi

    def no_poe(self: SimulatorAdapter, w: Any, snap: Any, now: Any) -> None:
        original(self, w, snap, now)
        snap.ports = [dataclasses.replace(p, poe_power_w=None) for p in snap.ports]
        snap.facts["unifi.poe_data"] = False

    monkeypatch.setattr(SimulatorAdapter, "_unifi", no_poe)
    sim = await play(runtime, "ap_poe_loss")
    f = only(sim, "ap_lost_poe")
    assert f.confidence is Confidence.PROBABLE
    assert "PoE power data not available" in f.summary


async def test_switch_outage_grouped(runtime: Runtime) -> None:
    sim = await play(runtime, "switch_offline")
    assert set(sim.open_findings()) == {"switch_offline"}
    f = only(sim, "switch_offline")
    assert (
        "guest cabin 4" in f.crew_text
        and "guest cabin 6" in f.crew_text
        and "crew mess" in f.crew_text
    )


async def test_single_ap_offline(runtime: Runtime) -> None:
    sim = await play(runtime, "ap_offline")
    f = only(sim, "ap_offline")
    assert f.confidence is Confidence.CONFIRMED and "Main deck, saloon" in f.crew_text
    assert "guest_wifi" in f.services and f.guests_affected


async def test_internet_fine_but_ap_offline(runtime: Runtime) -> None:
    sim = await play(runtime, "ap_offline")
    assert "internet_unavailable" not in sim.open_findings()


# 15.6 congestion -------------------------------------------------------------------------------
async def test_wifi_congestion(runtime: Runtime) -> None:
    sim = await play(runtime, "wifi_congestion")
    f = only(sim, "wifi_congestion")
    assert f.confidence is Confidence.PROBABLE and "saloon" in f.crew_text


async def test_congestion_needs_optional_data(runtime: Runtime) -> None:
    roles = {k: v for k, v in ROLES.items() if k != "ruckus-web"}
    sim = await play(runtime, "wifi_congestion", roles=roles)
    assert "wifi_congestion" not in sim.open_findings()


# 15.7 monitoring ----------------------------------------------------------------------------------
async def test_controller_outage_is_monitoring_failure_only(runtime: Runtime) -> None:
    sim = await play(runtime, "controller_outage")
    findings = sim.open_findings()
    assert set(findings) == {"monitoring_source_unavailable"}
    f = findings["monitoring_source_unavailable"]
    assert f.confidence is Confidence.MONITORING_FAILURE  # type: ignore[attr-defined]


async def test_optional_source_failure_is_information(runtime: Runtime) -> None:
    sim = await play(runtime, "ruckus_web_broken")
    f = only(sim, "monitoring_source_unavailable")
    assert f.severity.value == "information"
    assert "doesn't mean anything is wrong" in f.crew_text


# Intermittent problems -----------------------------------------------------------------------------
async def test_intermittent_ap(runtime: Runtime) -> None:
    await play(runtime, "intermittent_ap")
    findings = [f for f in runtime.findings.query() if f.rule_id == "ap_offline"]
    assert len(findings) == 1 and findings[0].intermittent


# 13.4 low disk -> finding ------------------------------------------------------------------------
async def test_low_disk_raises_finding(runtime: Runtime) -> None:
    runtime.disk_status = runtime.history.protect_disk(runtime.settings.data_dir, free_mb=200)
    events = runtime.evaluate()
    assert [e.kind for e in events] == ["finding_opened"]
    f = runtime.findings.open()[0]
    assert f.rule_id == "low_disk_space" and "removing its oldest records" in f.crew_text


def test_rules_doc_covers_every_rule() -> None:
    from pathlib import Path

    from insight.diagnostics.rules import RULE_CLASSES

    doc = (Path(__file__).parents[1] / "docs" / "rules.md").read_text()
    for cls in RULE_CLASSES:
        assert f"## `{cls.id}`" in doc, cls.id
