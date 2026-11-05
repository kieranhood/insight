from __future__ import annotations

from datetime import timedelta

import pytest

from insight.adapters.simulator import ROLES
from insight.diagnostics import Candidate, Confidence, Input, Rule, Severity
from insight.diagnostics.context import EvalContext
from insight.diagnostics.engine import Engine, render
from insight.diagnostics.lint import lint_crew_text
from insight.diagnostics.rules import RULE_CLASSES, all_rules
from insight.runtime import Runtime
from tests.sim import Sim


# 14.1 -------------------------------------------------------------------------------------
def test_every_rule_has_templates_and_samples_render() -> None:
    for rule in all_rules():
        assert rule.samples, rule.id
        for sample in rule.samples:
            rendered = render(rule, sample.confidence, sample.facts)
            assert rendered.title and rendered.crew and rendered.summary, rule.id
            assert rendered.next_steps, rule.id


def test_metadata_is_declared() -> None:
    ids = [cls.id for cls in RULE_CLASSES]
    assert len(ids) == len(set(ids))
    for cls in RULE_CLASSES:
        assert cls.title and cls.severity and cls.purpose
        for explained in cls.explains:
            assert explained in ids, (cls.id, explained)


# 14.4 -------------------------------------------------------------------------------------
def test_wording_lint_passes_for_every_sample() -> None:
    for rule in all_rules():
        for sample in rule.samples:
            crew = render(rule, sample.confidence, sample.facts).crew
            assert lint_crew_text(crew, sample.confidence) == [], (rule.id, sample.confidence, crew)


def test_wording_lint_catches_bad_text() -> None:
    bad = "The AP at 10.20.1.41 (24:79:2a:00:00:01) on port 12 lost PoE and the DNS server failed."
    problems = lint_crew_text(bad, Confidence.PROBABLE)
    assert any("IP address" in p for p in problems)
    assert any("MAC address" in p for p in problems)
    assert any("port number" in p for p in problems)
    assert any("'PoE'" in p for p in problems) and any("'DNS'" in p for p in problems)
    assert any("hedged" in p for p in problems)
    assert lint_crew_text("Wi-Fi is down.", Confidence.MONITORING_FAILURE)


# 14.2 -------------------------------------------------------------------------------------
async def test_monitoring_failure_instead_of_fault(runtime: Runtime) -> None:
    sim = Sim(runtime, "controller_outage")
    await sim.play()
    open_ids = set(sim.open_findings())
    assert "monitoring_source_unavailable" in open_ids
    assert "switch_offline" not in open_ids and "ap_lost_poe" not in open_ids
    finding = sim.open_findings()["monitoring_source_unavailable"]
    assert finding.confidence is Confidence.MONITORING_FAILURE  # type: ignore[attr-defined]
    assert "can't currently check the network switches" in finding.crew_text  # type: ignore[attr-defined]


async def test_optional_missing_downgrades_to_insufficient(runtime: Runtime) -> None:
    roles = {k: v for k, v in ROLES.items() if k != "starlink"}
    sim = Sim(runtime, "primary_degraded", roles=roles)
    await sim.play()
    finding = sim.open_findings()["primary_link_degraded"]
    assert finding.confidence is Confidence.INSUFFICIENT  # type: ignore[attr-defined]
    assert "detailed information from the Starlink dish isn't available" in finding.crew_text  # type: ignore[attr-defined]


async def test_essential_optional_missing_skips_rule(runtime: Runtime) -> None:
    roles = {k: v for k, v in ROLES.items() if k != "ruckus-web"}
    sim = Sim(runtime, "wifi_congestion", roles=roles)
    await sim.play()
    assert "wifi_congestion" not in sim.open_findings()


async def test_cause_absorbs_symptoms(runtime: Runtime) -> None:
    sim = Sim(runtime, "switch_offline")
    await sim.play()
    findings = sim.open_findings()
    assert "switch_offline" in findings
    assert "ap_offline" not in findings and "ap_lost_poe" not in findings
    switch = findings["switch_offline"]
    assert len(switch.devices) >= 4  # type: ignore[attr-defined]  # switch + its three APs
    assert "guest cabin 4" in switch.crew_text  # type: ignore[attr-defined]


class Flicker(Rule):
    id = "test_flicker"
    title = "Test flicker"
    severity = Severity.WARNING
    min_duration = timedelta(seconds=60)
    clear_duration = timedelta(seconds=60)
    on = True

    def evaluate(self, ctx: EvalContext) -> list[Candidate]:
        if not self.on:
            return []
        return [
            Candidate(
                rule_id=self.id,
                key=self.id,
                confidence=Confidence.CONFIRMED,
                facts={},
                evidence=[ctx.ev("x", None)],
            )
        ]


@pytest.fixture
def flicker_engine(runtime: Runtime, monkeypatch: pytest.MonkeyPatch) -> tuple[Engine, Flicker]:
    import insight.diagnostics.engine as engine_mod

    rule = Flicker()
    monkeypatch.setattr(
        engine_mod,
        "render",
        lambda r, c, f: engine_mod.Rendered("Test flicker", "crew may", "s", "e", [], []),
    )
    return Engine(runtime.db, runtime.writer, [rule]), rule


# 14.3 -------------------------------------------------------------------------------------
def test_brief_blip_opens_nothing(runtime: Runtime, flicker_engine: tuple[Engine, Flicker]) -> None:
    engine, rule = flicker_engine
    ctx = runtime.eval_context()
    assert engine.evaluate(ctx) == []
    rule.on = False
    ctx.now += timedelta(seconds=30)
    assert engine.evaluate(ctx) == []
    rule.on = True
    ctx.now += timedelta(seconds=30)
    assert engine.evaluate(ctx) == []
    assert runtime.findings.open() == []


def test_opens_after_min_and_resolves_after_clear(
    runtime: Runtime, flicker_engine: tuple[Engine, Flicker]
) -> None:
    engine, rule = flicker_engine
    ctx = runtime.eval_context()
    engine.evaluate(ctx)
    ctx.now += timedelta(seconds=61)
    assert [e.kind for e in engine.evaluate(ctx)] == ["finding_opened"]
    rule.on = False
    ctx.now += timedelta(seconds=30)
    assert engine.evaluate(ctx) == []  # first seen clear
    ctx.now += timedelta(seconds=30)
    assert engine.evaluate(ctx) == []  # clear for 30 s: still open
    ctx.now += timedelta(seconds=31)
    assert [e.kind for e in engine.evaluate(ctx)] == ["finding_resolved"]
    resolved = runtime.findings.query(status="resolved")
    assert len(resolved) == 1 and resolved[0].resolved_at is not None


def test_recurring_problem_marked_intermittent(
    runtime: Runtime, flicker_engine: tuple[Engine, Flicker]
) -> None:
    engine, rule = flicker_engine
    ctx = runtime.eval_context()
    kinds: list[str] = []
    for _ in range(4):
        rule.on = True
        for _ in range(3):
            kinds += [e.kind for e in engine.evaluate(ctx)]
            ctx.now += timedelta(seconds=31)
        rule.on = False
        for _ in range(3):
            kinds += [e.kind for e in engine.evaluate(ctx)]
            ctx.now += timedelta(seconds=31)
    assert kinds.count("finding_opened") == 1  # one finding, reopened rather than recreated
    assert kinds.count("finding_reopened") == 3
    rows = runtime.findings.query()
    assert len(rows) == 1 and rows[0].intermittent


def test_open_findings_survive_restart(
    runtime: Runtime, flicker_engine: tuple[Engine, Flicker]
) -> None:
    engine, rule = flicker_engine
    ctx = runtime.eval_context()
    engine.evaluate(ctx)
    ctx.now += timedelta(seconds=61)
    engine.evaluate(ctx)
    restarted = Engine(runtime.db, runtime.writer, [rule])
    ctx.now += timedelta(seconds=15)
    assert restarted.evaluate(ctx) == []  # still the same open finding
    assert len(runtime.findings.open()) == 1


def test_requires_unavailable_input_skips_rule(runtime: Runtime) -> None:
    class NeedsWan(Flicker):
        id = "test_needs_wan"
        requires = (Input.WAN,)

    engine = Engine(runtime.db, runtime.writer, [NeedsWan()])
    assert engine.candidates(runtime.eval_context()) == []
