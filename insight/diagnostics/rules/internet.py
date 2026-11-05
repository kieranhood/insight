"""Internet rules: unavailable, failover, primary degraded, all paths degraded, DNS, weak cellular."""

from __future__ import annotations

from datetime import timedelta

from insight.diagnostics import Action, Candidate, Confidence, Input, Rule, Sample, Severity
from insight.diagnostics.context import EvalContext
from insight.inventory import Service
from insight.model import LinkState, WanLink, WanType

INTERNET = (Service.INTERNET.value,)


def _usable(link: WanLink) -> bool:
    return link.state is LinkState.CONNECTED and link.health_ok is not False


def _primary(links: list[WanLink]) -> WanLink | None:
    enabled = [lk for lk in links if lk.state is not LinkState.DISABLED and lk.priority is not None]
    return min(enabled, key=lambda lk: lk.priority or 0) if enabled else None


def _link_label(link: WanLink) -> str:
    if link.wan_type is WanType.CELLULAR:
        return f"{link.name} (mobile data)"
    return link.name


class InternetUnavailable(Rule):
    id = "internet_unavailable"
    title = "Internet unavailable"
    severity = Severity.CRITICAL
    min_duration = timedelta(seconds=60)
    explains = (
        "failover_to_backup",
        "primary_link_degraded",
        "all_paths_degraded",
        "dns_failure",
        "weak_cellular_signal",
    )
    systems = ("peplink", "probes")
    purpose = "Every internet path is down, according to the router and/or Insight's own checks."
    samples = (
        Sample(
            Confidence.CONFIRMED,
            {"links": ["Starlink", "Cellular"], "router_says_down": True, "probes_say_down": True},
        ),
        Sample(
            Confidence.PROBABLE,
            {"links": ["Starlink"], "router_says_down": False, "probes_say_down": True},
        ),
    )

    def evaluate(self, ctx: EvalContext) -> list[Candidate]:
        evidence = []
        router_down: bool | None = None
        if ctx.available(Input.WAN):
            links = [lk for lk in ctx.wan_links() if lk.state is not LinkState.DISABLED]
            if links:
                router_down = not any(_usable(lk) for lk in links)
                for lk in links:
                    evidence.append(
                        ctx.ev(
                            f"{lk.name}: {lk.state.value}, health check {'failing' if lk.health_ok is False else 'passing' if lk.health_ok else 'not reported'}",
                            lk.source_id,
                            lk.observed_at,
                            link=lk.name,
                            state=lk.state.value,
                        )
                    )
        probes_down: bool | None = None
        if ctx.available(Input.PROBES):
            internet = ctx.probe("internet")
            if internet:
                probes_down = not internet.get("reachable", True)
                evidence.append(
                    ctx.ev(
                        "Insight's internet checks: "
                        + (
                            "all targets failing"
                            if internet.get("all_targets_failed")
                            else "at least one target answering"
                        ),
                        ctx.source_of(Input.PROBES),
                        targets=internet.get("targets"),
                    )
                )
        if not (router_down or probes_down):
            return []
        if router_down:
            confidence = Confidence.CONFIRMED
        else:
            confidence = Confidence.PROBABLE  # the router says a link is up, but nothing answers
        names = [lk.name for lk in ctx.wan_links() if lk.state is not LinkState.DISABLED]
        return [
            Candidate(
                rule_id=self.id,
                key=self.id,
                confidence=confidence,
                facts={
                    "links": names,
                    "router_says_down": bool(router_down),
                    "probes_say_down": bool(probes_down),
                },
                evidence=evidence,
                services=INTERNET,
                guests_affected=True,
                action=Action.CONTACT,
            )
        ]


class FailoverToBackup(Rule):
    id = "failover_to_backup"
    title = "Running on the backup internet connection"
    severity = Severity.WARNING
    requires = (Input.WAN,)
    min_duration = timedelta(seconds=30)
    explains = ("primary_link_degraded",)
    systems = ("peplink",)
    purpose = (
        "The main (highest-priority) WAN link is not usable and another link carries the traffic."
    )
    samples = (
        Sample(
            Confidence.CONFIRMED,
            {
                "primary": "Starlink",
                "backup": "Cellular",
                "backup_is_cellular": True,
                "primary_state": "disconnected",
            },
        ),
    )

    def evaluate(self, ctx: EvalContext) -> list[Candidate]:
        links = ctx.wan_links()
        primary = _primary(links)
        in_use = [lk for lk in links if lk.in_use]
        if (
            primary is None
            or not in_use
            or primary.in_use
            or (_usable(primary) and primary in in_use)
        ):
            return []
        if _usable(primary):
            return []  # primary looks fine; traffic elsewhere is a policy choice, not a failover
        backup = in_use[0]
        return [
            Candidate(
                rule_id=self.id,
                key=f"{self.id}:{primary.source_id}:{primary.link_id}",
                confidence=Confidence.CONFIRMED,
                facts={
                    "primary": primary.name,
                    "backup": backup.name,
                    "backup_is_cellular": backup.wan_type is WanType.CELLULAR,
                    "primary_state": primary.state.value,
                },
                evidence=[
                    ctx.ev(
                        f"{primary.name} (priority {primary.priority}) is {primary.state.value}",
                        primary.source_id,
                        primary.observed_at,
                    ),
                    ctx.ev(
                        f"Traffic is on {backup.name} (priority {backup.priority})",
                        backup.source_id,
                        backup.observed_at,
                    ),
                    *[
                        ctx.ev(e.message, e.source_id, e.observed_at, **e.data)
                        for e in ctx.events_since(["failover"], timedelta(hours=6))
                    ][-3:],
                ],
                devices=(primary.device_key,),
                services=INTERNET,
                guests_affected=True,
                action=Action.NONE,
            )
        ]


class PrimaryLinkDegraded(Rule):
    id = "primary_link_degraded"
    title = "Internet slow or dropping out"
    severity = Severity.WARNING
    requires = (Input.WAN, Input.PROBES)
    optional = (Input.DISH,)
    min_duration = timedelta(seconds=120)
    clear_duration = timedelta(seconds=300)
    systems = ("peplink", "probes")
    purpose = "The link in use loses packets or responds slowly, measured by Insight's own checks."
    samples = (
        Sample(
            Confidence.INSUFFICIENT,
            {
                "link": "Starlink",
                "is_starlink": True,
                "dish_data": False,
                "loss_pct": 12.0,
                "rtt_ms": 950.0,
                "http_slow": True,
            },
        ),
        Sample(
            Confidence.INSUFFICIENT,
            {
                "link": "Starlink",
                "is_starlink": True,
                "dish_data": True,
                "loss_pct": 7.0,
                "rtt_ms": 700.0,
                "http_slow": False,
            },
        ),
    )

    def evaluate(self, ctx: EvalContext) -> list[Candidate]:
        in_use = ctx.in_use()
        if len(in_use) != 1:
            return []
        link = in_use[0]
        internet = ctx.probe("internet")
        http = ctx.probe("http")
        loss = float(internet.get("loss_pct") or 0.0)
        rtt = internet.get("rtt_ms")
        limit_loss = float(ctx.config["threshold_degraded_loss_pct"])
        limit_rtt = float(ctx.config["threshold_degraded_latency_ms"])
        degraded = (
            loss >= limit_loss or (rtt is not None and rtt >= limit_rtt) or bool(http.get("slow"))
        )
        if not degraded or not internet.get("reachable", True):
            return []
        starlink = ctx.starlink()
        is_starlink = (
            starlink is not None
            and starlink.link_id == link.link_id
            and starlink.source_id == link.source_id
        )
        return [
            Candidate(
                rule_id=self.id,
                key=f"{self.id}:{link.source_id}:{link.link_id}",
                confidence=Confidence.INSUFFICIENT,  # degradation is measured; its cause is not
                facts={
                    "link": link.name,
                    "is_starlink": is_starlink,
                    "dish_data": ctx.available(Input.DISH),
                    "loss_pct": round(loss, 1),
                    "rtt_ms": round(float(rtt), 0) if rtt is not None else None,
                    "http_slow": bool(http.get("slow")),
                },
                evidence=[
                    ctx.ev(
                        f"Insight's checks through {link.name}: {loss:.1f}% loss"
                        + (f", {float(rtt):.0f} ms round trip" if rtt is not None else ""),
                        ctx.source_of(Input.PROBES),
                        wan_in_use=internet.get("wan_in_use"),
                    ),
                    *(
                        [
                            ctx.ev(
                                f"Web page load took {http.get('ms'):.0f} ms against a usual {http.get('baseline_ms'):.0f} ms",
                                ctx.source_of(Input.PROBES),
                            )
                        ]
                        if http.get("slow") and http.get("ms") and http.get("baseline_ms")
                        else []
                    ),
                ],
                devices=(link.device_key,),
                services=INTERNET,
                guests_affected=True,
                action=Action.NONE,
            )
        ]


class AllPathsDegraded(Rule):
    id = "all_paths_degraded"
    title = "Every internet connection is struggling"
    severity = Severity.WARNING
    requires = (Input.WAN,)
    min_duration = timedelta(seconds=120)
    clear_duration = timedelta(seconds=300)
    explains = ("primary_link_degraded",)
    systems = ("peplink",)
    purpose = "Two or more connected WAN links all show high latency or loss at the same time."
    samples = (Sample(Confidence.PROBABLE, {"links": ["Starlink", "Cellular"]}),)

    def evaluate(self, ctx: EvalContext) -> list[Candidate]:
        limit_loss = float(ctx.config["threshold_degraded_loss_pct"])
        limit_rtt = float(ctx.config["threshold_degraded_latency_ms"])
        connected = [lk for lk in ctx.wan_links() if lk.state is LinkState.CONNECTED]
        if len(connected) < 2:
            return []

        def bad(lk: WanLink) -> bool:
            return (lk.latency_ms is not None and lk.latency_ms >= limit_rtt) or (
                lk.loss_pct is not None and lk.loss_pct >= limit_loss
            )

        if not all(bad(lk) for lk in connected):
            return []
        return [
            Candidate(
                rule_id=self.id,
                key=self.id,
                confidence=Confidence.PROBABLE,
                facts={"links": [lk.name for lk in connected]},
                evidence=[
                    ctx.ev(
                        f"{lk.name}: "
                        + ", ".join(
                            x
                            for x in (
                                f"{lk.latency_ms:.0f} ms latency"
                                if lk.latency_ms is not None
                                else "",
                                f"{lk.loss_pct:.1f}% loss" if lk.loss_pct is not None else "",
                            )
                            if x
                        ),
                        lk.source_id,
                        lk.observed_at,
                    )
                    for lk in connected
                ],
                devices=tuple(sorted({lk.device_key for lk in connected})),
                services=INTERNET,
                guests_affected=True,
                action=Action.CONTACT,
            )
        ]


class DnsFailure(Rule):
    id = "dns_failure"
    title = "Websites can't be found, though the internet connection works"
    severity = Severity.WARNING
    requires = (Input.PROBES,)
    min_duration = timedelta(seconds=90)
    systems = ("probes",)
    purpose = "Name lookups through the yacht's DNS server fail while a public resolver or IP connectivity works."
    samples = (Sample(Confidence.PROBABLE, {"public_ok": True, "ip_ok": True}),)

    def evaluate(self, ctx: EvalContext) -> list[Candidate]:
        dns = ctx.probe("dns")
        internet = ctx.probe("internet")
        local = dns.get("local") or {}
        public = dns.get("public") or {}
        ip_ok = bool(internet.get("reachable")) and not internet.get("all_targets_failed")
        if local.get("ok", True) or not (public.get("ok") or ip_ok):
            return []
        return [
            Candidate(
                rule_id=self.id,
                key=self.id,
                confidence=Confidence.PROBABLE,
                facts={"public_ok": bool(public.get("ok")), "ip_ok": ip_ok},
                evidence=[
                    ctx.ev(
                        "Lookups through the yacht's DNS server failed",
                        ctx.source_of(Input.PROBES),
                        names=dns.get("names"),
                    ),
                    ctx.ev(
                        f"Lookups through the public resolver {public.get('resolver', '')} "
                        + ("succeeded" if public.get("ok") else "also failed"),
                        ctx.source_of(Input.PROBES),
                    ),
                    ctx.ev(
                        "Internet reachability by IP address "
                        + ("works" if ip_ok else "is failing"),
                        ctx.source_of(Input.PROBES),
                        wan_in_use=internet.get("wan_in_use"),
                    ),
                ],
                services=INTERNET,
                guests_affected=True,
                action=Action.CONTACT,
            )
        ]


class WeakCellularSignal(Rule):
    id = "weak_cellular_signal"
    title = "Weak mobile signal on the connection in use"
    severity = Severity.WARNING
    requires = (Input.WAN,)
    min_duration = timedelta(seconds=120)
    clear_duration = timedelta(seconds=300)
    systems = ("peplink",)
    purpose = (
        "A cellular WAN link carrying traffic reports weak signal (RSRP or SINR below thresholds)."
    )
    samples = (Sample(Confidence.CONFIRMED, {"link": "Cellular", "rsrp": -118.0, "sinr": -2.0}),)

    def evaluate(self, ctx: EvalContext) -> list[Candidate]:
        rsrp_limit = float(ctx.config["threshold_weak_rsrp_dbm"])
        sinr_limit = float(ctx.config["threshold_weak_sinr_db"])
        found = []
        for link in ctx.in_use():
            if link.wan_type is not WanType.CELLULAR:
                continue
            rsrp, sinr = link.signal.get("rsrp"), link.signal.get("sinr")
            weak = (rsrp is not None and rsrp <= rsrp_limit) or (
                sinr is not None and sinr <= sinr_limit
            )
            if not weak:
                continue
            found.append(
                Candidate(
                    rule_id=self.id,
                    key=f"{self.id}:{link.source_id}:{link.link_id}",
                    confidence=Confidence.CONFIRMED,
                    facts={"link": link.name, "rsrp": rsrp, "sinr": sinr},
                    evidence=[
                        ctx.ev(
                            f"{link.name} signal: RSRP {rsrp} dBm, SINR {sinr} dB (carrier {link.carrier or 'unknown'})",
                            link.source_id,
                            link.observed_at,
                        )
                    ],
                    devices=(link.device_key,),
                    services=INTERNET,
                    guests_affected=True,
                    action=Action.NONE,
                )
            )
        return found
