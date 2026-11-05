"""Wi-Fi infrastructure rules: AP offline, AP lost PoE/connection, switch offline, congestion."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from insight.diagnostics import (
    Action,
    Candidate,
    Confidence,
    Evidence,
    Input,
    Rule,
    Sample,
    Severity,
)
from insight.diagnostics.context import EvalContext
from insight.model import DeviceCategory, OnlineState


def access_point_keys(ctx: EvalContext) -> list[str]:
    keys = {k for k, d in ctx.devices().items() if d.category is DeviceCategory.ACCESS_POINT}
    keys |= set(ctx.access_points())
    return sorted(keys)


def _service_names(services: tuple[str, ...]) -> list[str]:
    names = {"guest_wifi": "guest Wi-Fi", "crew_wifi": "crew Wi-Fi", "internet": "internet"}
    return [names.get(s, s) for s in services]


def ap_down_evidence(ctx: EvalContext, key: str) -> tuple[bool, list[Evidence], bool]:
    """(down, evidence, directly_reported) for one access point."""
    evidence: list[Evidence] = []
    reported = False
    down = False
    ap = ctx.access_points().get(key)
    if ap is not None and ap.online is OnlineState.OFFLINE:
        down = reported = True
        evidence.append(
            ctx.ev(
                "The Wi-Fi system reports this access point as disconnected",
                ap.source_id,
                ap.observed_at,
            )
        )
    lost = ctx.events_since(["ap_disconnected"], timedelta(hours=2))
    joined = ctx.events_since(["ap_joined"], timedelta(hours=2))
    last_lost = max((e.observed_at for e in lost if key in e.devices), default=None)
    last_join = max((e.observed_at for e in joined if key in e.devices), default=None)
    if last_lost is not None and (last_join is None or last_join < last_lost):
        down = reported = True
        evidence.append(
            ctx.ev(
                "Unleashed reported it lost contact with this access point",
                "ruckus-syslog",
                last_lost,
            )
        )
    if ctx.available(Input.PROBES):
        info = ctx.probe("device").get(key)
        if info is not None and not info.get("reachable", True):
            down = True
            evidence.append(
                ctx.ev(
                    f"Insight's reachability checks failed {info.get('consecutive_failures', 'several')} times in a row",
                    ctx.source_of(Input.PROBES),
                    ip=info.get("ip"),
                )
            )
    if down and ctx.available(Input.WIFI_TOTALS):
        totals = ctx.facts(Input.WIFI_TOTALS, "wifi.totals") or {}
        if totals.get("ap_known") is not None:
            evidence.append(
                ctx.ev(
                    f"Wi-Fi system totals: {totals.get('ap_registered')} of {totals.get('ap_known')} access points registered",
                    ctx.source_of(Input.WIFI_TOTALS),
                )
            )
    return down, evidence, reported


def _facts(ctx: EvalContext, key: str, **extra: Any) -> dict[str, Any]:
    services = ctx.services_for_device(key)
    return {
        "where": ctx.where(key),
        "has_location": ctx.location(key) is not None,
        "device": ctx.device_name(key),
        "services": _service_names(services),
        **extra,
    }


class ApOffline(Rule):
    id = "ap_offline"
    title = "Wi-Fi access point offline"
    severity = Severity.WARNING
    min_duration = timedelta(seconds=90)
    clear_duration = timedelta(seconds=180)
    systems = ("ruckus",)
    purpose = "An access point is reported disconnected by the Wi-Fi system, or stops answering Insight's checks."
    samples = (
        Sample(
            Confidence.CONFIRMED,
            {
                "where": "Main deck, saloon",
                "has_location": True,
                "device": "AP-SALOON",
                "services": ["guest Wi-Fi"],
            },
        ),
        Sample(
            Confidence.PROBABLE,
            {
                "where": "one area of the yacht (its location hasn't been set yet)",
                "has_location": False,
                "device": "AP-CAB4",
                "services": [],
            },
        ),
    )

    def evaluate(self, ctx: EvalContext) -> list[Candidate]:
        found = []
        for key in access_point_keys(ctx):
            down, evidence, reported = ap_down_evidence(ctx, key)
            if not down:
                continue
            services = ctx.services_for_device(key)
            found.append(
                Candidate(
                    rule_id=self.id,
                    key=f"{self.id}:{key}",
                    confidence=Confidence.CONFIRMED if reported else Confidence.PROBABLE,
                    facts=_facts(ctx, key),
                    evidence=evidence,
                    devices=(key,),
                    services=services,
                    guests_affected=ctx.guests(services),
                    action=Action.CHECK,
                )
            )
        return found


class ApLostPoe(Rule):
    id = "ap_lost_poe"
    title = "Wi-Fi access point lost power or connection from its switch"
    severity = Severity.WARNING
    requires = (Input.SWITCHES, Input.PROBES)
    optional = (Input.POE,)
    min_duration = timedelta(seconds=60)
    clear_duration = timedelta(seconds=180)
    explains = ("ap_offline",)
    systems = ("unifi", "ruckus")
    purpose = "An access point's switch port lost link or PoE power and the access point stopped answering."
    samples = (
        Sample(
            Confidence.CONFIRMED,
            {
                "where": "Lower deck, guest cabin 4",
                "has_location": True,
                "device": "AP-CAB4",
                "services": ["guest Wi-Fi"],
                "switch": "SW-LD-01",
                "port": "1",
                "poe_w": 0.0,
                "link_up": False,
                "attachment": "LLDP",
            },
        ),
        Sample(
            Confidence.PROBABLE,
            {
                "where": "Lower deck, guest cabin 4",
                "has_location": True,
                "device": "AP-CAB4",
                "services": [],
                "switch": "SW-LD-01",
                "port": "1",
                "poe_w": None,
                "link_up": False,
                "attachment": "recorded by an engineer",
            },
        ),
    )

    def evaluate(self, ctx: EvalContext) -> list[Candidate]:
        topology = ctx.topology()
        ports = {(p.device_key, p.port_id): p for p in ctx.ports()}
        found = []
        for key in access_point_keys(ctx):
            attachment = topology.parent(key)
            if attachment is None or attachment.port_id is None:
                continue
            port = ports.get((attachment.parent_key, attachment.port_id))
            if port is None or ctx.device_reachable(key) is not False:
                continue
            poe_now = port.poe_power_w
            poe_lost = poe_now is not None and poe_now == 0 and (port.poe_enabled is not False)
            if not (port.link_up is False or poe_lost):
                continue
            confirmed = ctx.available(Input.POE) and poe_now is not None
            switch = ctx.device_name(attachment.parent_key)
            evidence = [
                ctx.ev(
                    f"{switch} port {port.port_id}: link {'down' if port.link_up is False else 'up'}"
                    + (
                        f", PoE {poe_now:.1f} W"
                        if poe_now is not None
                        else ", PoE power not available"
                    ),
                    port.source_id,
                    port.observed_at,
                    switch=switch,
                    port=port.port_id,
                ),
                ctx.ev(
                    f"{ctx.device_name(key)} is attached to that port ("
                    + (
                        "recorded by an engineer"
                        if attachment.manual
                        else "from the switch's neighbour data"
                    )
                    + ")",
                    port.source_id,
                ),
            ]
            for event in ctx.events_since(["poe_lost", "port_down"], timedelta(hours=1)):
                if (
                    attachment.parent_key in event.devices
                    and event.data.get("port") == port.port_id
                ):
                    evidence.append(ctx.ev(event.message, event.source_id, event.observed_at))
            _, down_evidence, _ = ap_down_evidence(ctx, key)
            evidence.extend(down_evidence)
            services = ctx.services_for_device(key)
            found.append(
                Candidate(
                    rule_id=self.id,
                    key=f"{self.id}:{key}",
                    confidence=Confidence.CONFIRMED if confirmed else Confidence.PROBABLE,
                    facts=_facts(
                        ctx,
                        key,
                        switch=switch,
                        port=port.port_id,
                        poe_w=poe_now,
                        link_up=port.link_up,
                        attachment="recorded by an engineer" if attachment.manual else "LLDP",
                    ),
                    evidence=evidence,
                    devices=(key, attachment.parent_key),
                    services=services,
                    guests_affected=ctx.guests(services),
                    action=Action.CHECK,
                )
            )
        return found


class SwitchOffline(Rule):
    id = "switch_offline"
    title = "Network switch offline"
    severity = Severity.CRITICAL
    requires = (Input.SWITCHES,)
    min_duration = timedelta(seconds=60)
    clear_duration = timedelta(seconds=180)
    explains = ("ap_offline", "ap_lost_poe")
    systems = ("unifi",)
    purpose = "A switch is reported offline (or its uplink is down); everything behind it is listed as affected."
    samples = (
        Sample(
            Confidence.CONFIRMED,
            {
                "where": "Lower deck comms cabinet",
                "has_location": True,
                "device": "SW-LD-01",
                "services": ["guest Wi-Fi", "crew Wi-Fi"],
                "affected_places": ["Lower deck, guest cabin 4", "Lower deck, guest cabin 6"],
                "affected_count": 3,
            },
        ),
        Sample(
            Confidence.PROBABLE,
            {
                "where": "one area of the yacht (its location hasn't been set yet)",
                "has_location": False,
                "device": "SW-LD-01",
                "services": [],
                "affected_places": [],
                "affected_count": 0,
            },
        ),
    )

    def evaluate(self, ctx: EvalContext) -> list[Candidate]:
        merged = ctx.state.devices(ctx.now)
        topology = ctx.topology()
        found = []
        for key, device in merged.items():
            if device.category is not DeviceCategory.SWITCH:
                continue
            reported_offline = device.fresh and device.online is OnlineState.OFFLINE
            unreachable = ctx.device_reachable(key) is False
            if not (reported_offline or unreachable):
                continue
            downstream = topology.downstream(key)
            places = sorted({loc for k in downstream if (loc := ctx.location(k))})
            services = ctx.wifi_services_for_aps(downstream)
            evidence = []
            if reported_offline:
                evidence.append(
                    ctx.ev(
                        f"The controller reports {device.name or key} as offline",
                        device.source_ids[0] if device.source_ids else None,
                        device.observed_at,
                    )
                )
            if unreachable:
                evidence.append(
                    ctx.ev(
                        f"Insight's reachability checks to {device.name or key} are failing",
                        ctx.source_of(Input.PROBES),
                    )
                )
            if downstream:
                evidence.append(
                    ctx.ev(
                        "Behind this switch: " + ", ".join(ctx.device_name(k) for k in downstream),
                        None,
                    )
                )
            found.append(
                Candidate(
                    rule_id=self.id,
                    key=f"{self.id}:{key}",
                    confidence=Confidence.CONFIRMED if reported_offline else Confidence.PROBABLE,
                    facts=_facts(ctx, key, affected_places=places, affected_count=len(downstream))
                    | {"services": _service_names(services)},
                    evidence=evidence,
                    devices=(key, *downstream),
                    services=services,
                    guests_affected=ctx.guests(services),
                    action=Action.CHECK,
                )
            )
        return found


class WifiCongestion(Rule):
    id = "wifi_congestion"
    title = "Wi-Fi busy in one area"
    severity = Severity.WARNING
    optional = (Input.WIFI_DETAIL,)
    optional_essential = True
    min_duration = timedelta(seconds=300)
    clear_duration = timedelta(seconds=600)
    systems = ("ruckus",)
    purpose = (
        "An access point reports very high channel utilisation or a very high number of clients."
    )
    samples = (
        Sample(
            Confidence.PROBABLE,
            {
                "where": "Main deck, saloon",
                "has_location": True,
                "device": "AP-SALOON",
                "services": ["guest Wi-Fi"],
                "util": {"2.4GHz": 92.0},
                "clients": 48,
            },
        ),
    )

    def evaluate(self, ctx: EvalContext) -> list[Candidate]:
        util_limit = float(ctx.config["threshold_channel_util_pct"])
        client_limit = int(ctx.config["threshold_ap_clients"])
        found = []
        for key, ap in ctx.access_points().items():
            if ap.online is not OnlineState.ONLINE:
                continue
            busy = {
                band: pct for band, pct in ap.channel_utilisation_pct.items() if pct >= util_limit
            }
            crowded = ap.client_count is not None and ap.client_count >= client_limit
            if not busy and not crowded:
                continue
            services = ctx.services_for_device(key)
            evidence = [
                ctx.ev(
                    f"{band} channel {ap.channels.get(band, '?')} is {pct:.0f}% busy",
                    ap.source_id,
                    ap.observed_at,
                )
                for band, pct in busy.items()
            ]
            if crowded:
                evidence.append(
                    ctx.ev(
                        f"{ap.client_count} devices connected to this access point",
                        ap.source_id,
                        ap.observed_at,
                    )
                )
            found.append(
                Candidate(
                    rule_id=self.id,
                    key=f"{self.id}:{key}",
                    confidence=Confidence.PROBABLE,
                    facts=_facts(ctx, key, util=busy, clients=ap.client_count),
                    evidence=evidence,
                    devices=(key,),
                    services=services,
                    guests_affected=ctx.guests(services),
                    action=Action.NONE,
                )
            )
        return found
