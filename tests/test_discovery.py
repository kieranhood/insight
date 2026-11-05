from __future__ import annotations

import asyncio
import itertools
import time
from typing import Any

import dns.message
import dns.rdataclass
import dns.rdatatype
import dns.rrset
import pytest
from fastapi.testclient import TestClient

from insight.adapters.simulator import ROLES, SimulatorAdapter, SimulatorHub
from insight.discovery.fingerprint import identify
from insight.discovery.listeners import parse_mdns, parse_ssdp
from insight.discovery.sweep import SweepError, SweepRun, plan, sweep
from insight.model import Client, DeviceCategory, Reliability
from insight.runtime import Runtime
from insight.sources import SourceConfig
from insight.timeutil import utcnow
from tests.conftest import page_csrf
from tests.factories import dev, snap


def client(mac: str, ip: str, name: str, wired: bool | None = True) -> Client:
    return Client(
        source_id="pep",
        observed_at=utcnow(),
        reliability=Reliability.RELIABLE,
        mac=mac,
        ip=ip,
        hostname=name,
        wired=wired,
    )


# 12.1 ---------------------------------------------------------------------------------------
def test_source_client_not_in_inventory_is_discovered(runtime: Runtime) -> None:
    runtime.inventory.sync(
        snap("unifi", devices=[dev("unifi", "f0:9f:c2:00:00:10", ip="10.10.0.11")])
    )
    events = runtime.discovery.observe_snapshot(
        snap(
            "pep",
            clients=[
                client("f8:bc:12:4a:9e:21", "10.10.0.50", "BRIDGE-NAV-PC"),
                client("f0:9f:c2:00:00:10", "10.10.0.11", "switch"),
            ],
        )
    )
    found = runtime.discovery.new_items()
    assert [d.name for d in found] == ["BRIDGE-NAV-PC"]  # the inventory switch is not listed
    assert [e.kind for e in events] == ["new_device_discovered"]


def test_wifi_and_randomised_clients_ignored(runtime: Runtime) -> None:
    runtime.discovery.observe_snapshot(
        snap(
            "w",
            clients=[
                client("da:a1:19:00:00:01", "10.10.30.1", "phone", wired=None),
                client("3c:22:fb:00:00:01", "10.10.30.2", "laptop", wired=False),
            ],
        )
    )
    assert runtime.discovery.new_items() == []


# 12.2 ---------------------------------------------------------------------------------------
def test_mdns_announcement_parsed() -> None:
    msg = dns.message.Message()
    msg.flags |= 0x8400  # response, authoritative
    msg.answer.append(
        dns.rrset.from_text(
            "_sonos._tcp.local.", 120, "IN", "PTR", "Sonos-Saloon._sonos._tcp.local."
        )
    )
    msg.additional.append(dns.rrset.from_text("Sonos-Saloon.local.", 120, "IN", "A", "10.10.20.31"))
    ann = parse_mdns(msg.to_wire(), "10.10.20.31")
    assert ann is not None and "_sonos._tcp" in ann.services and ann.name == "Sonos-Saloon"


def test_ssdp_notify_parsed() -> None:
    packet = (
        b"NOTIFY * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nNT: urn:schemas-upnp-org:device:ZonePlayer:1\r\n"
        b"NTS: ssdp:alive\r\nSERVER: Linux UPnP/1.0 Sonos/79.1\r\nUSN: uuid:RINCON_1::urn\r\n\r\n"
    )
    ann = parse_ssdp(packet, "10.10.20.31")
    assert (
        ann is not None
        and ann.services == ["urn:schemas-upnp-org:device:ZonePlayer:1"]
        and "Sonos" in (ann.server or "")
    )
    assert parse_ssdp(packet.replace(b"ssdp:alive", b"ssdp:byebye"), "x") is None
    assert parse_mdns(b"garbage", "x") is None


def test_announcement_recorded(runtime: Runtime) -> None:
    event = runtime.discovery.observe_announcement(
        ip="10.10.20.31", name="Sonos-Saloon", services=["_sonos._tcp"]
    )
    assert event is not None and event.kind == "new_device_discovered"
    item = runtime.discovery.new_items()[0]
    assert (
        item.observations["announced_services"] == ["_sonos._tcp"]
        and "announced itself" in item.how
    )


# 12.3 ---------------------------------------------------------------------------------------
def test_plan_selected_minus_excluded_and_cap() -> None:
    p = plan(["10.10.0.0/29"], ["10.10.0.4/30"])
    assert p.addresses == ["10.10.0.1", "10.10.0.2", "10.10.0.3"]
    with pytest.raises(SweepError, match="at least one"):
        plan([], [])
    with pytest.raises(SweepError, match="1,024"):
        plan(["10.0.0.0/21"], [])
    assert len(plan(["10.0.0.0/22"], []).addresses) == 1022


class FakeNet:
    def __init__(self, open_ports: dict[str, set[int]]) -> None:
        self.open_ports = open_ports
        self.contacted: list[tuple[str, int]] = []
        self.started: dict[str, float] = {}
        self.page_reads: list[tuple[str, int]] = []

    async def connect(self, host: str, port: int) -> bool:
        self.started.setdefault(host, time.monotonic())
        self.contacted.append((host, port))
        return port in self.open_ports.get(host, set())

    async def read_page(self, host: str, port: int) -> dict[str, Any]:
        self.page_reads.append((host, port))
        return {"tls_subject": "CN=captive-portal.peplink.com"} if host == "10.10.0.1" else {}


async def test_sweep_contacts_only_planned_and_respects_rate() -> None:
    net = FakeNet({"10.10.0.1": {443, 80}})
    run = SweepRun(started_by="eng", plan=plan(["10.10.0.0/28"], ["10.10.0.8/29"]))
    found: list[tuple[str, dict[str, Any]]] = []
    start = time.monotonic()
    await sweep(
        run,
        lambda ip, obs: found.append((ip, obs)),
        connect=net.connect,
        read_page=net.read_page,
        rate=20,
    )
    elapsed = time.monotonic() - start
    hosts = {h for h, _ in net.contacted}
    assert hosts == {
        f"10.10.0.{i}" for i in range(1, 8)
    }  # .8-.15 excluded, nothing outside the subnet
    assert elapsed >= (len(hosts) - 1) / 20 * 0.9
    starts = sorted(net.started.values())
    assert all(b - a >= 0.04 for a, b in itertools.pairwise(starts))
    assert found == [
        ("10.10.0.1", {"open_ports": [80, 443], "tls_subject": "CN=captive-portal.peplink.com"})
    ]
    assert net.page_reads == [("10.10.0.1", 443)]
    assert run.finished_at is not None and run.scanned == 7


async def test_sweep_cancellation() -> None:
    net = FakeNet({})
    run = SweepRun(started_by="eng", plan=plan(["10.10.0.0/24"], []))

    async def cancel_soon() -> None:
        await asyncio.sleep(0.2)
        run.cancelled = True

    await asyncio.gather(
        sweep(run, lambda ip, obs: None, connect=net.connect, read_page=net.read_page, rate=20),
        cancel_soon(),
    )
    assert len({h for h, _ in net.contacted}) < 20


async def test_page_reads_carry_no_credentials() -> None:
    import httpx

    from insight.discovery import sweep as sweep_mod

    seen: list[httpx.Request] = []
    real = httpx.AsyncClient

    def fake_client(**kwargs: Any) -> httpx.AsyncClient:
        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(302, headers={"location": "/admin/login.jsp"})

        return real(
            transport=httpx.MockTransport(handler),
            **{k: v for k, v in kwargs.items() if k != "verify"},
        )

    async def no_tls(host: str, port: int) -> None:
        return None

    original_client, original_tls = sweep_mod.httpx.AsyncClient, sweep_mod._tls_subject
    sweep_mod.httpx.AsyncClient, sweep_mod._tls_subject = fake_client, no_tls  # type: ignore[assignment,misc]
    try:
        result = await sweep_mod.read_public_page("10.10.20.11", 443)
    finally:
        sweep_mod.httpx.AsyncClient, sweep_mod._tls_subject = original_client, original_tls  # type: ignore[misc]
    assert result["http_location"] == "/admin/login.jsp"
    for request in seen:
        assert (
            request.method == "GET"
            and "authorization" not in request.headers
            and not request.url.query
        )
        assert "cookie" not in request.headers


# 12.4 ---------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("observations", "expected"),
    [
        (
            {
                "oui_vendor": "Peplink",
                "tls_subject": "CN=captive-portal.peplink.com",
                "open_ports": [443],
            },
            "peplink",
        ),
        ({"oui_vendor": "Ubiquiti", "open_ports": [443, 8080], "http_title": "UniFi OS"}, "unifi"),
        (
            {
                "ip": "10.10.20.11",
                "oui_vendor": "Ruckus",
                "http_location": "/admin/login.jsp",
                "open_ports": [80, 443],
            },
            "ruckus-master",
        ),
        ({"ip": "192.168.100.1", "open_ports": [9200]}, "starlink"),
    ],
)
def test_four_source_types_likely(observations: dict[str, Any], expected: str) -> None:
    result = identify(observations)
    assert (result.type_id, result.confidence) == (expected, "likely")
    assert result.evidence


def test_unmatched_is_unidentified_and_weak_is_possible() -> None:
    assert identify({"open_ports": [22]}).confidence == "unidentified"
    assert identify({"oui_vendor": "Peplink"}).confidence == "possible"


# 12.5 ---------------------------------------------------------------------------------------
def seed(runtime: Runtime) -> str:
    runtime.discovery.record(
        mac="a8:c0:ea:10:20:30",
        ip="10.10.0.1",
        name="router",
        how="found by a discovery run",
        observations={"tls_subject": "CN=captive-portal.peplink.com", "open_ports": [443]},
    )
    runtime.discovery.record(
        mac="f8:bc:12:4a:9e:21",
        ip="10.10.0.50",
        name="BRIDGE-NAV-PC",
        how="listed by pep",
        observations={},
    )
    return "mac:f8:bc:12:4a:9e:21"


def test_review_page_accept_dismiss_restore(runtime: Runtime, engineer: TestClient) -> None:
    key = seed(runtime)
    page = engineer.get("/engineer/discovery")
    assert (
        page.status_code == 200
        and "BRIDGE-NAV-PC" in page.text
        and "Likely a Peplink router" in page.text
    )
    assert "/engineer/sources/new?kind=peplink&amp;address=https%3A%2F%2F10.10.0.1" in page.text
    token = page_csrf(engineer, "/engineer/discovery")
    response = engineer.post(
        f"/engineer/discovery/{key}/accept",
        data={"csrf_token": token, "name": "Nav PC", "category": "other"},
    )
    assert response.status_code == 303
    accepted = runtime.inventory.find_by_mac("f8:bc:12:4a:9e:21")
    assert accepted is not None and accepted.manual and accepted.ip == "10.10.0.50"
    assert key not in {d.key for d in runtime.discovery.new_items()}
    engineer.post("/engineer/discovery/mac:a8:c0:ea:10:20:30/dismiss", data={"csrf_token": token})
    assert runtime.discovery.get("mac:a8:c0:ea:10:20:30").status == "dismissed"  # type: ignore[union-attr]
    # Seen again by a later run: still dismissed, not new.
    runtime.discovery.record(
        mac="a8:c0:ea:10:20:30",
        ip="10.10.0.1",
        name=None,
        how="found by a discovery run",
        observations={},
    )
    assert runtime.discovery.new_items() == []
    engineer.post("/engineer/discovery/mac:a8:c0:ea:10:20:30/restore", data={"csrf_token": token})
    assert [d.key for d in runtime.discovery.new_items()] == ["mac:a8:c0:ea:10:20:30"]


def test_subnet_settings_and_run_start(runtime: Runtime, engineer: TestClient) -> None:
    token = page_csrf(engineer, "/engineer/discovery")
    assert (
        engineer.post("/engineer/discovery/run", data={"csrf_token": token}).status_code == 400
    )  # nothing selected
    bad = engineer.post(
        "/engineer/discovery/subnets", data={"csrf_token": token, "selected": "10.0.0.0/16"}
    )
    assert bad.status_code == 400 and "1,024" in bad.text
    engineer.post(
        "/engineer/discovery/subnets",
        data={"csrf_token": token, "selected": "127.0.0.0/30", "excluded": "10.10.30.0/24"},
    )
    assert runtime.config.get("discovery_selected_subnets") == ["127.0.0.0/30"]


async def test_run_recorded_in_timeline_with_starter(runtime: Runtime) -> None:
    runtime.config.set("discovery_selected_subnets", ["127.0.0.0/30"])
    run = await runtime.start_discovery_run("kate")
    assert run.task is not None
    await run.task
    kinds = [e.kind for e in runtime.recent_events]
    assert kinds[:1] == ["discovery_run_started"] and "discovery_run_finished" in kinds
    assert runtime.recent_events[0].data["started_by"] == "kate"


# 12.6 ---------------------------------------------------------------------------------------
async def test_new_device_notice_from_simulator(runtime: Runtime) -> None:
    SimulatorHub.reset_all()
    hub = SimulatorHub.get("nd")
    hub.load("new_device")
    pep = SimulatorAdapter(
        SourceConfig(
            id="sim-peplink",
            kind="simulator",
            name="p",
            address="peplink",
            reliability=ROLES["peplink"],
            options={"role": "peplink", "hub": "nd"},
        )
    )
    runtime.scheduler.add(pep)
    await runtime.scheduler.run_once(pep)
    before = {d.key for d in runtime.discovery.new_items()}
    hub.step()
    result = await runtime.scheduler.run_once(pep)
    new_events = [e for e in result.events if e.kind == "new_device_discovered"]
    assert len(new_events) == 1 and new_events[0].data["mac"] == "b8:27:eb:12:34:56"
    assert {d.key for d in runtime.discovery.new_items()} - before == {"mac:b8:27:eb:12:34:56"}
    assert runtime.inventory.find_by_mac("b8:27:eb:12:34:56") is None  # never adopted automatically
    assert runtime.discovery_run is None  # and never probed actively
    assert DeviceCategory  # keep import
