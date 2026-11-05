from __future__ import annotations

from typing import Any

import pytest

from insight.model import Reliability
from insight.probes import IcmpNotPermitted, PingResult, ProbesAdapter, icmp_ping, probes_source
from insight.runtime import Runtime
from insight.timeutil import utcnow
from tests.factories import snap, wan


class Net:
    """A fake network for the probes."""

    def __init__(self) -> None:
        self.down: set[str] = set()
        self.dns_local_ok = True
        self.dns_public_ok = True
        self.http_ms = 150.0
        self.http_ok = True
        self.dish_ok = True
        self.now = 0.0

    async def ping(self, addresses: list[str], count: int) -> dict[str, PingResult]:
        return {
            a: PingResult(
                a,
                a not in self.down,
                None if a in self.down else 1.5,
                100.0 if a in self.down else 0.0,
            )
            for a in addresses
        }

    async def resolve(self, name: str, nameserver: str | None) -> float | None:
        ok = self.dns_public_ok if nameserver else self.dns_local_ok
        return 20.0 if ok else None

    async def fetch(self, url: str) -> tuple[int, float] | None:
        return (204, self.http_ms) if self.http_ok else None

    async def connect(self, host: str, port: int) -> bool:
        return self.dish_ok

    def clock(self) -> float:
        return self.now


def make(runtime: Runtime, net: Net) -> ProbesAdapter:
    return ProbesAdapter(
        probes_source(),
        inventory=runtime.inventory,
        config=runtime.config,
        state=runtime.state,
        pinger=net.ping,
        resolver=net.resolve,
        fetcher=net.fetch,
        connector=net.connect,
        clock=net.clock,
    )


async def collect(adapter: ProbesAdapter, net: Net, advance: float = 30.0) -> dict[str, Any]:
    net.now += advance
    return (await adapter.collect(utcnow())).facts


# 11.1 -------------------------------------------------------------------------------------
async def test_one_lost_check_is_not_unreachable(runtime: Runtime) -> None:
    item = runtime.inventory.add_manual("Bridge PC", "10.20.9.5")
    net = Net()
    probes = make(runtime, net)
    assert (await collect(probes, net))["probe.device"][item.key]["reachable"] is True
    net.down.add("10.20.9.5")
    facts = await collect(probes, net)
    assert facts["probe.device"][item.key]["reachable"] is True  # one miss
    net.down.clear()
    assert (await collect(probes, net))["probe.device"][item.key]["consecutive_failures"] == 0


async def test_consecutive_failures_mark_unreachable(runtime: Runtime) -> None:
    item = runtime.inventory.add_manual("Bridge PC", "10.20.9.5")
    net = Net()
    net.down.add("10.20.9.5")
    probes = make(runtime, net)
    results = [
        (await collect(probes, net))["probe.device"][item.key]["reachable"] for _ in range(3)
    ]
    assert results == [True, True, False]


# 11.2 -------------------------------------------------------------------------------------
async def test_one_internet_target_down_is_not_internet_down(runtime: Runtime) -> None:
    net = Net()
    net.down.add("8.8.8.8")
    probes = make(runtime, net)
    for _ in range(4):
        facts = await collect(probes, net)
    assert facts["probe.internet"]["reachable"] is True
    assert facts["probe.internet"]["targets"]["8.8.8.8"]["ok"] is False


async def test_all_targets_down(runtime: Runtime) -> None:
    net = Net()
    net.down.update({"1.1.1.1", "8.8.8.8", "9.9.9.9"})
    probes = make(runtime, net)
    seen = [(await collect(probes, net))["probe.internet"]["reachable"] for _ in range(3)]
    assert seen == [True, True, False]


# 11.3 -------------------------------------------------------------------------------------
async def test_local_dns_failing_public_ok(runtime: Runtime) -> None:
    net = Net()
    net.dns_local_ok = False
    facts = await collect(make(runtime, net), net)
    assert facts["probe.dns"]["local"]["ok"] is False and facts["probe.dns"]["public"]["ok"] is True
    assert facts["probe.internet"]["reachable"] is True


# 11.4 -------------------------------------------------------------------------------------
async def test_http_slowdown_against_baseline(runtime: Runtime) -> None:
    net = Net()
    probes = make(runtime, net)
    for _ in range(6):
        facts = await collect(probes, net, advance=130)
    assert facts["probe.http"]["slow"] is False and facts["probe.http"]["baseline_ms"] == 150.0
    net.http_ms = 3500.0
    facts = await collect(probes, net, advance=130)
    assert facts["probe.http"]["slow"] is True


async def test_results_labelled_with_wan_in_use(runtime: Runtime) -> None:
    runtime.state.configure_source(
        "pep", name="Peplink", kind="peplink", reliability=Reliability.RELIABLE, interval_s=15
    )
    runtime.state.apply(
        snap(
            "pep",
            wan_links=[
                wan("pep", "1", "Starlink", in_use=False),
                wan("pep", "2", "Cellular", in_use=True),
            ],
        )
    )
    net = Net()
    facts = await collect(make(runtime, net), net)
    assert facts["probe.wan_in_use"] == "Cellular"
    assert (
        facts["probe.internet"]["wan_in_use"] == "Cellular"
        and facts["probe.dns"]["wan_in_use"] == "Cellular"
    )


async def test_defaults_and_editable_settings(runtime: Runtime) -> None:
    assert runtime.config.get("probe_internet_targets") == ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
    runtime.config.set("probe_internet_targets", ["208.67.222.222"])
    runtime.config.set("probe_failure_threshold", 1)
    net = Net()
    net.down.add("208.67.222.222")
    facts = await collect(make(runtime, net), net)
    assert list(facts["probe.internet"]["targets"]) == ["208.67.222.222"]
    assert facts["probe.internet"]["reachable"] is False


async def test_dish_port_check(runtime: Runtime) -> None:
    net = Net()
    net.dish_ok = False
    facts = await collect(make(runtime, net), net)
    assert facts["probe.dish"] == {"address": "192.168.100.1:9200", "reachable": False}


async def test_probes_always_configured(runtime: Runtime) -> None:
    runtime.load_sources()
    assert "insight-probes" in runtime.scheduler.adapters


async def test_real_icmp_to_loopback() -> None:
    try:
        results = await icmp_ping(["127.0.0.1"], 1)
    except IcmpNotPermitted:
        pytest.skip("this OS does not allow ICMP sockets for the test user")
    assert results["127.0.0.1"].ok


async def test_icmp_denied_becomes_clear_monitoring_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import icmplib
    from icmplib.exceptions import SocketPermissionError

    async def denied(*args: object, **kwargs: object) -> None:
        raise SocketPermissionError(False)

    monkeypatch.setattr(icmplib, "async_multiping", denied)
    with pytest.raises(IcmpNotPermitted, match="NET_RAW"):
        await icmp_ping(["127.0.0.1"], 1)
