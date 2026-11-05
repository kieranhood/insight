"""Insight's own connectivity tests, run from the yacht's network.

Device reachability, internet reachability, DNS (yacht resolver and an independent
public one), HTTP access, and whether the Starlink dish's status port answers. Results
are labelled with the WAN link in use when measured, because a device on the LAN only
ever goes out through the link the router is currently using.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from insight.collection.adapter import Adapter, AdapterInfo
from insight.config_store import ConfigStore
from insight.inventory import Inventory
from insight.model import Metric, Reliability, Snapshot
from insight.sources import SourceConfig
from insight.state import StateStore

PROBES_SOURCE_ID = "insight-probes"


@dataclass(frozen=True)
class PingResult:
    address: str
    ok: bool
    rtt_ms: float | None
    loss_pct: float


Pinger = Callable[[list[str], int], Awaitable[dict[str, PingResult]]]
Resolver = Callable[[str, str | None], Awaitable[float | None]]  # name, nameserver -> ms, or None
Fetcher = Callable[[str], Awaitable[tuple[int, float] | None]]  # url -> (status, ms), or None
Connector = Callable[[str, int], Awaitable[bool]]


async def icmp_ping(addresses: list[str], count: int) -> dict[str, PingResult]:
    from icmplib import async_multiping
    from icmplib.exceptions import SocketPermissionError

    if not addresses:
        return {}
    try:
        hosts = await async_multiping(
            addresses, count=count, interval=0.2, timeout=1, privileged=True
        )
    except SocketPermissionError:
        hosts = await async_multiping(
            addresses, count=count, interval=0.2, timeout=1, privileged=False
        )
    return {
        h.address: PingResult(
            h.address, h.is_alive, h.avg_rtt if h.is_alive else None, h.packet_loss * 100.0
        )
        for h in hosts
    }


async def dns_resolve(name: str, nameserver: str | None) -> float | None:
    import dns.asyncresolver
    import dns.exception

    resolver = dns.asyncresolver.Resolver(configure=nameserver is None)
    if nameserver:
        resolver.nameservers = [nameserver]
    resolver.lifetime = 3.0
    start = time.perf_counter()
    try:
        await resolver.resolve(name, "A")
    except (dns.exception.DNSException, OSError):
        return None
    return (time.perf_counter() - start) * 1000.0


async def http_fetch(url: str) -> tuple[int, float] | None:
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            response = await client.get(url)
    except httpx.HTTPError:
        return None
    return response.status_code, (time.perf_counter() - start) * 1000.0


async def tcp_connect(host: str, port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=3)
    except (OSError, TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


class ProbesAdapter(Adapter):
    info = AdapterInfo(
        kind="probes",
        label="Insight's own checks",
        reliability=Reliability.RELIABLE,
        default_interval_s=30,
    )

    def __init__(
        self,
        source: SourceConfig,
        *,
        inventory: Inventory,
        config: ConfigStore,
        state: StateStore,
        pinger: Pinger = icmp_ping,
        resolver: Resolver = dns_resolve,
        fetcher: Fetcher = http_fetch,
        connector: Connector = tcp_connect,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(source)
        self.inventory = inventory
        self.config = config
        self.state = state
        self.pinger = pinger
        self.resolver = resolver
        self.fetcher = fetcher
        self.connector = connector
        self.clock = clock
        self._device_failures: dict[str, int] = {}
        self._internet_failures = 0
        self._last_run: dict[str, float] = {}
        self._dns: dict[str, Any] | None = None
        self._http: dict[str, Any] | None = None
        self._http_history: deque[float] = deque(maxlen=20)

    @property
    def interval_s(self) -> float:
        return float(self.config.get("probe_device_interval_s"))

    @property
    def timeout_s(self) -> float:
        return 25.0

    def _due(self, name: str, interval: float) -> bool:
        if self.clock() - self._last_run.get(name, -1e18) >= interval:
            self._last_run[name] = self.clock()
            return True
        return False

    def wan_in_use(self) -> str | None:
        names = sorted(link.name for link in self.state.wan_links() if link.in_use)
        return ", ".join(names) if names else None

    async def collect(self, now: datetime) -> Snapshot:
        cfg = self.config.all()
        threshold = int(cfg["probe_failure_threshold"])
        snap = self.new_snapshot(now)
        wan = self.wan_in_use()

        def metric(subject: str, name: str, value: float, unit: str) -> None:
            snap.metrics.append(
                Metric(
                    source_id=self.source.id,
                    observed_at=now,
                    reliability=Reliability.RELIABLE,
                    subject=subject,
                    name=name,
                    value=value,
                    unit=unit,
                )
            )

        targets = self.inventory.probe_targets()
        internet_targets = [str(t) for t in cfg["probe_internet_targets"]]
        results = await self.pinger(sorted(set(targets.values()) | set(internet_targets)), 3)

        devices: dict[str, dict[str, Any]] = {}
        for key, ip in targets.items():
            result = results.get(ip)
            ok = bool(result and result.ok)
            failures = 0 if ok else self._device_failures.get(key, 0) + 1
            self._device_failures[key] = failures
            devices[key] = {
                "ip": ip,
                "reachable": ok or failures < threshold,
                "last_check_ok": ok,
                "consecutive_failures": failures,
                "rtt_ms": result.rtt_ms if result else None,
                "loss_pct": result.loss_pct if result else 100.0,
            }
            if result and result.rtt_ms is not None:
                metric(f"probe:device:{key}", "rtt_ms", result.rtt_ms, "ms")
            metric(f"probe:device:{key}", "loss_pct", result.loss_pct if result else 100.0, "%")
        snap.facts["probe.device"] = devices

        per_target = {t: results.get(t) for t in internet_targets}
        ok_targets = [r for r in per_target.values() if r and r.ok]
        self._internet_failures = 0 if ok_targets else self._internet_failures + 1
        losses = [r.loss_pct if r else 100.0 for r in per_target.values()]
        rtts = [r.rtt_ms for r in ok_targets if r.rtt_ms is not None]
        loss = sum(losses) / len(losses) if losses else 100.0
        rtt = statistics.median(rtts) if rtts else None
        snap.facts["probe.internet"] = {
            "reachable": bool(ok_targets) or self._internet_failures < threshold,
            "all_targets_failed": not ok_targets,
            "consecutive_failures": self._internet_failures,
            "rtt_ms": rtt,
            "loss_pct": loss,
            "targets": {
                t: {"ok": bool(r and r.ok), "rtt_ms": r.rtt_ms if r else None}
                for t, r in per_target.items()
            },
            "wan_in_use": wan,
        }
        if rtt is not None:
            metric("probe:internet", "rtt_ms", rtt, "ms")
        metric("probe:internet", "loss_pct", loss, "%")

        if self._due("dns", float(cfg["probe_dns_interval_s"])) or self._dns is None:
            names = [str(n) for n in cfg["probe_dns_names"]]
            public = str(cfg["probe_dns_public_resolver"])
            local = await asyncio.gather(*(self.resolver(n, None) for n in names))
            remote = await asyncio.gather(*(self.resolver(n, public) for n in names))
            local_ok = [ms for ms in local if ms is not None]
            remote_ok = [ms for ms in remote if ms is not None]
            self._dns = {
                "local": {"ok": bool(local_ok), "ms": min(local_ok) if local_ok else None},
                "public": {
                    "ok": bool(remote_ok),
                    "ms": min(remote_ok) if remote_ok else None,
                    "resolver": public,
                },
                "names": names,
                "wan_in_use": wan,
                "measured_at": now.isoformat(),
            }
            if local_ok:
                metric("probe:dns", "local_ms", min(local_ok), "ms")
            if remote_ok:
                metric("probe:dns", "public_ms", min(remote_ok), "ms")
        snap.facts["probe.dns"] = self._dns

        if self._due("http", float(cfg["probe_http_interval_s"])) or self._http is None:
            urls = [str(u) for u in cfg["probe_http_urls"]]
            fetched = await asyncio.gather(*(self.fetcher(u) for u in urls))
            http_ok: list[tuple[int, float]] = [f for f in fetched if f is not None and f[0] < 500]
            best = min((ms for _, ms in http_ok), default=None)
            baseline = (
                statistics.median(self._http_history) if len(self._http_history) >= 5 else None
            )
            if best is not None:
                self._http_history.append(best)
                metric("probe:http", "response_ms", best, "ms")
            self._http = {
                "ok": bool(http_ok),
                "ms": best,
                "baseline_ms": baseline,
                "slow": bool(
                    best is not None
                    and baseline is not None
                    and best > max(3 * baseline, baseline + 1000)
                ),
                "wan_in_use": wan,
            }
        snap.facts["probe.http"] = self._http

        address = str(cfg.get("starlink_dish_address") or "192.168.100.1:9200")
        host, _, port = address.rpartition(":")
        dish_ok = await self.connector(host or address, int(port or 9200))
        snap.facts["probe.dish"] = {"address": address, "reachable": dish_ok}
        snap.facts["probe.wan_in_use"] = wan
        return snap


def probes_source() -> SourceConfig:
    return SourceConfig(
        id=PROBES_SOURCE_ID,
        kind="probes",
        name="Insight's own checks",
        address="local",
        reliability=Reliability.RELIABLE,
    )
