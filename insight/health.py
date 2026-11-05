"""Health status for each system, each crew-facing service and the yacht overall.

Missing data is UNKNOWN, never a fault. Status changes are recorded as events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from insight.diagnostics import Input, Severity
from insight.diagnostics.context import EvalContext
from insight.diagnostics.store import Finding
from insight.inventory import Service
from insight.model import Event, LinkState, OnlineState, Reliability


class Status(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"

    @property
    def worse_rank(self) -> int:
        """For 'worst of': CRITICAL > DEGRADED > HEALTHY > UNKNOWN."""
        return {"CRITICAL": 3, "DEGRADED": 2, "HEALTHY": 1, "UNKNOWN": 0}[self.value]


@dataclass
class HealthItem:
    id: str
    name: str
    status: Status
    reason: str
    updated_at: datetime | None
    findings: list[Finding] = field(default_factory=list)
    set_up: bool = True


@dataclass
class HealthReport:
    overall: HealthItem
    services: list[HealthItem]
    systems: list[HealthItem]
    active_issues: int

    def item(self, item_id: str) -> HealthItem | None:
        for it in [self.overall, *self.services, *self.systems]:
            if it.id == item_id:
                return it
        return None


SYSTEMS: list[tuple[str, str, tuple[Input, ...]]] = [
    ("peplink", "Peplink router", (Input.WAN,)),
    ("starlink", "Starlink", (Input.WAN, Input.DISH)),
    ("unifi", "UniFi switching", (Input.SWITCHES,)),
    ("ruckus", "Ruckus Wi-Fi", (Input.WIFI_TOTALS, Input.WIFI_DETAIL)),
]

SERVICE_NAMES = {s.value: s.label for s in Service}


def _from_findings(findings: list[Finding]) -> Status:
    serious = [f for f in findings if f.severity is not Severity.INFO]
    if any(f.severity is Severity.CRITICAL for f in serious):
        return Status.CRITICAL
    if serious:
        return Status.DEGRADED
    return Status.HEALTHY


def _freshest(ctx: EvalContext, inputs: tuple[Input, ...]) -> datetime | None:
    times = [
        s.last_success_at
        for inp in inputs
        for s in ctx.sources_for(inp)
        if s.last_success_at is not None
    ]
    return max(times) if times else None


def _not_monitoring(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.rule_id != "monitoring_source_unavailable"]


def compute(ctx: EvalContext, open_findings: list[Finding]) -> HealthReport:
    systems = [_system(ctx, sid, name, inputs, open_findings) for sid, name, inputs in SYSTEMS]
    systems = [s for s in systems if s.set_up]
    services = [
        _internet(ctx, open_findings),
        _wifi(ctx, Service.GUEST_WIFI, open_findings),
        _wifi(ctx, Service.CREW_WIFI, open_findings),
    ]
    known = [s for s in services if s.status is not Status.UNKNOWN]
    if known:
        worst = max(known, key=lambda s: s.status.worse_rank)
        overall_status = worst.status
        reason = (
            "All services are working normally."
            if overall_status is Status.HEALTHY
            else f"{worst.name}: {worst.reason}"
        )
    else:
        overall_status = Status.UNKNOWN
        reason = "Insight can't currently check any service."
    updated = [s.updated_at for s in services if s.updated_at is not None]
    issue_ids = {f.id for f in _not_monitoring(open_findings) if f.severity is not Severity.INFO}
    overall = HealthItem(
        "overall",
        "Yacht systems",
        overall_status,
        reason,
        max(updated) if updated else None,
        [f for f in open_findings if f.id in issue_ids],
    )
    return HealthReport(overall, services, systems, len(issue_ids))


def _system(
    ctx: EvalContext,
    system_id: str,
    name: str,
    inputs: tuple[Input, ...],
    open_findings: list[Finding],
) -> HealthItem:
    configured = any(ctx.configured(i) for i in inputs)
    if system_id == "starlink":
        configured = ctx.starlink() is not None or ctx.configured(Input.DISH)
    if not configured:
        return HealthItem(system_id, name, Status.UNKNOWN, "Not set up.", None, set_up=False)
    updated = _freshest(ctx, inputs)
    related = [f for f in open_findings if system_id in f.systems or _relates(system_id, f)]
    reliable = [
        s for inp in inputs for s in ctx.sources_for(inp) if s.reliability is Reliability.RELIABLE
    ]
    reliable_fresh = any(ctx.state.is_fresh(s.source_id, ctx.now) for s in reliable)
    any_fresh = any(ctx.available(i) for i in inputs)
    if system_id == "starlink":
        link = ctx.starlink()
        if link is None and not ctx.available(Input.DISH):
            return HealthItem(
                system_id,
                name,
                Status.UNKNOWN,
                "Insight can't currently check Starlink.",
                updated,
                related,
            )
        status = _from_findings(_not_monitoring(related))
        if link is not None and link.state is not LinkState.CONNECTED:
            status = Status.CRITICAL
        reason = (
            "Working normally."
            if status is Status.HEALTHY
            else "; ".join(f.title for f in related)
            or f"The Starlink link is {link.state.value if link else 'unknown'}."
        )
        return HealthItem(system_id, name, status, reason, updated, related)
    if not (reliable_fresh if reliable else any_fresh):
        return HealthItem(
            system_id,
            name,
            Status.UNKNOWN,
            f"Insight can't currently check the {name}.",
            updated,
            related,
        )
    status = _from_findings(_not_monitoring(related))
    if system_id == "unifi":
        offline = [
            d
            for d in ctx.state.devices(ctx.now).values()
            if d.fresh and d.online is OnlineState.OFFLINE and d.category.value == "switch"
        ]
        if offline and status is Status.HEALTHY:
            status = Status.DEGRADED
    reason = (
        "Working normally."
        if status is Status.HEALTHY
        else "; ".join(f.title for f in _not_monitoring(related))
    )
    return HealthItem(system_id, name, status, reason, updated, related)


def _relates(system_id: str, finding: Finding) -> bool:
    if system_id == "starlink":
        return finding.rule_id.startswith("starlink") or (
            finding.rule_id in ("failover_to_backup", "primary_link_degraded")
            and "starlink"
            in str(finding.facts.get("primary", finding.facts.get("link", ""))).lower()
        )
    if system_id == "ruckus":
        return finding.rule_id in ("ap_offline", "ap_lost_poe", "wifi_congestion")
    if system_id == "unifi":
        return finding.rule_id in ("switch_offline", "ap_lost_poe")
    return False


def _internet(ctx: EvalContext, open_findings: list[Finding]) -> HealthItem:
    name = SERVICE_NAMES[Service.INTERNET.value]
    updated = _freshest(ctx, (Input.WAN, Input.PROBES))
    related = [f for f in _not_monitoring(open_findings) if Service.INTERNET.value in f.services]
    if not (ctx.available(Input.WAN) or ctx.available(Input.PROBES)):
        return HealthItem(
            "internet",
            name,
            Status.UNKNOWN,
            "Insight can't currently check the internet.",
            updated,
            related,
        )
    status = _from_findings(related)
    reason = (
        "Working normally." if status is Status.HEALTHY else "; ".join(f.title for f in related)
    )
    return HealthItem("internet", name, status, reason, updated, related)


def _wifi(ctx: EvalContext, service: Service, open_findings: list[Finding]) -> HealthItem:
    name = service.label
    mapping = ctx.inventory.mappings()[service]
    if not any(mapping.values()):
        return HealthItem(
            service.value,
            name,
            Status.UNKNOWN,
            "Not set up yet: no Wi-Fi network has been assigned to it.",
            None,
            [],
            set_up=False,
        )
    inputs = (Input.WIFI_TOTALS, Input.WIFI_DETAIL, Input.PROBES)
    updated = _freshest(ctx, inputs)
    related = [f for f in _not_monitoring(open_findings) if service.value in f.services]
    wifi_visible = ctx.available(Input.WIFI_TOTALS) or ctx.available(Input.WIFI_DETAIL)
    if not wifi_visible:
        return HealthItem(
            service.value,
            name,
            Status.UNKNOWN,
            "Insight can't currently check the Wi-Fi.",
            updated,
            related,
        )
    serving = [k for k in ctx.access_points() if service.value in ctx.services_for_device(k)] or [
        k for k in mapping["device"]
    ]
    down = {
        d
        for f in related
        if f.rule_id in ("ap_offline", "ap_lost_poe", "switch_offline")
        for d in f.devices
    }
    if serving and all(k in down for k in serving):
        status = Status.CRITICAL
    elif related:
        status = Status.DEGRADED
    else:
        status = Status.HEALTHY
    reason = (
        "Working normally." if status is Status.HEALTHY else "; ".join(f.title for f in related)
    )
    return HealthItem(service.value, name, status, reason, updated, related)


class StatusTracker:
    """Remembers the last statuses and emits status_change events when they change."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.last: dict[str, str] = dict(initial or {})

    def changes(self, report: HealthReport, now: datetime) -> list[Event]:
        events: list[Event] = []
        for item in [report.overall, *report.services, *report.systems]:
            before = self.last.get(item.id)
            if before == item.status.value:
                continue
            self.last[item.id] = item.status.value
            if before is None:
                continue  # first observation is not a change
            is_service = item.id in SERVICE_NAMES
            events.append(
                Event(
                    source_id="insight-health",
                    observed_at=now,
                    reliability=Reliability.RELIABLE,
                    kind="status_change",
                    subject=f"status:{item.id}",
                    message=f"{item.name} changed from {before} to {item.status.value}",
                    services=(item.id,) if is_service else (),
                    data={
                        "item": item.id,
                        "before": before,
                        "after": item.status.value,
                        "reason": item.reason,
                    },
                )
            )
        return events
