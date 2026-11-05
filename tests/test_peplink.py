from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from insight.adapters.peplink import (
    EndpointRefused,
    PeplinkAdapter,
    derive_in_use,
    parse_allowance,
    parse_latency,
    parse_wan_links,
)
from insight.collection.adapter import AuthFailed
from insight.model import LinkState, Reliability, WanType
from insight.sources import SourceConfig
from insight.state import StateStore
from insight.timeutil import utcnow

FIX = Path(__file__).parent / "fixtures" / "peplink"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIX / name).read_text())


def resp(name: str) -> dict[str, Any]:
    return load(name)["response"]


def links(name: str = "status_wan_connection.json") -> list:
    return parse_wan_links(resp(name), source_id="pep", now=utcnow(), router_key="serial:X")


def test_wan_links_states_types_priorities() -> None:
    by_name = {link.name: link for link in links()}
    assert (
        by_name["Starlink"].state is LinkState.CONNECTED and by_name["Starlink"].health_ok is True
    )
    assert by_name["Starlink"].priority == 1 and by_name["Starlink"].wan_type is WanType.ETHERNET
    assert by_name["Cellular"].state is LinkState.STANDBY and by_name["Cellular"].priority == 2
    assert by_name["Cellular"].wan_type is WanType.CELLULAR
    assert by_name["Wi-Fi WAN"].state is LinkState.DISABLED


def test_cellular_signal_and_carrier_without_secrets() -> None:
    cell = next(link for link in links() if link.name == "Cellular")
    assert cell.signal["rsrp"] == -98.0 and cell.signal["sinr"] == 12.0
    assert cell.carrier == "Vodafone ES"
    assert cell.network_type == "LTE-A"
    dumped = json.dumps(dataclasses.asdict(cell), default=str)
    for secret in ("imsi", "iccid", "imei", "apn", "000000000000000"):
        assert secret not in dumped.lower()


def test_link_in_use_derived_from_priority() -> None:
    assert derive_in_use(links()) == {"1"}
    failover = links("status_wan_connection_failover.json")
    assert {link.name for link in failover if link.link_id in derive_in_use(failover)} == {
        "Cellular"
    }


def test_link_in_use_confirmed_by_traffic() -> None:
    ls = links()
    assert derive_in_use(ls, {"1": 0.0, "2": 0.0}) == {"1"}  # no traffic: fall back to priority


def test_allowance_and_latency() -> None:
    assert parse_allowance(resp("status_wan_connection_allowance.json")) == {"2": 38_912_000_000}
    latency = parse_latency(resp("status_wan_latency.json"))
    assert "1" in latency and latency["1"] > 0


# -- full adapter against a mock router -------------------------------------------------
ROUTES = {
    "/api/info.firmware": "info_firmware.json",
    "/api/status.system.info": "status_system_info.json",
    "/api/status.wan.connection": "status_wan_connection.json",
    "/api/status.wan.connection.allowance": "status_wan_connection_allowance.json",
    "/api/status.wan.latency": "status_wan_latency.json",
    "/api/status.traffic": "status_traffic.json",
    "/api/status.client": "status_client.json",
    "/api/status.lan.profile": "status_lan_profile.json",
}


class Router:
    def __init__(self, *, secret: str = "s3cret", broken: set[str] | None = None) -> None:
        self.secret = secret
        self.broken = broken or set()
        self.requests: list[httpx.Request] = []
        self.wan_fixture = "status_wan_connection.json"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/auth.token.grant":
            body = (
                json.loads(request.content or b"{}")
                if request.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            if body.get("clientSecret") == self.secret:
                return httpx.Response(200, json=load("auth_token_grant.json"))
            return httpx.Response(200, json=load("error_unauthorized.json"))
        if (
            request.url.params.get("accessToken")
            != load("auth_token_grant.json")["response"]["accessToken"]
        ):
            return httpx.Response(200, json=load("error_unauthorized.json"))
        if path in self.broken:
            return httpx.Response(200, text="<html>changed</html>")
        name = self.wan_fixture if path == "/api/status.wan.connection" else ROUTES.get(path)
        if name is None:
            return httpx.Response(404, json={"stat": "fail", "code": 404})
        return httpx.Response(200, json=load(name))


def adapter(router: Router, secret: str = "s3cret") -> PeplinkAdapter:
    source = SourceConfig(
        id="pep",
        kind="peplink",
        name="Peplink router",
        address="https://192.168.50.1",
        reliability=Reliability.RELIABLE,
        credentials={"client_id": "insight", "client_secret": secret},
    )
    return PeplinkAdapter(source, transport=httpx.MockTransport(router))


async def test_full_collection() -> None:
    router = Router()
    a = adapter(router)
    snap = await a.collect(utcnow())
    device = snap.devices[0]
    assert (device.model, device.firmware, device.serial) == (
        "Pepwave MAX BR1 Pro 5G",
        "8.5.4 build 5808",
        "1111-2222-3333",
    )
    assert device.key == "serial:1111-2222-3333"
    assert {link.name: link.in_use for link in snap.wan_links} == {
        "Starlink": True,
        "Cellular": False,
        "Wi-Fi WAN": False,
    }
    starlink = next(link for link in snap.wan_links if link.name == "Starlink")
    assert starlink.latency_ms is not None
    assert len(snap.clients) >= 4
    assert "192.168.20.0/24" in snap.facts["lan_subnets"]
    assert "optional_errors" not in snap.facts
    everything = json.dumps(dataclasses.asdict(snap), default=str).lower()
    for secret in ("iccid", "imsi", "imei", "airtelwap"):
        assert secret not in everything
    # Every request was to an allow-listed endpoint (or the token grant), and only GET for reads.
    for request in router.requests:
        assert request.url.path == "/api/auth.token.grant" or request.method == "GET"
    await a.close()


async def test_token_reused_between_cycles() -> None:
    router = Router()
    a = adapter(router)
    await a.collect(utcnow())
    await a.collect(utcnow())
    grants = [r for r in router.requests if r.url.path == "/api/auth.token.grant"]
    assert len(grants) == 1
    await a.close()


async def test_undocumented_failure_keeps_documented_data() -> None:
    router = Router(
        broken={"/api/status.system.info", "/api/status.wan.latency", "/api/status.traffic"}
    )
    a = adapter(router)
    snap = await a.collect(utcnow())
    assert {"status.system.info", "status.wan.latency", "status.traffic"} <= set(
        snap.facts["optional_errors"]
    )
    assert snap.devices[0].firmware == "8.5.4 build 5808"  # from documented info.firmware
    assert snap.devices[0].model is None
    assert all(link.latency_ms is None for link in snap.wan_links)
    assert {link.name for link in snap.wan_links if link.in_use} == {"Starlink"}
    await a.close()


async def test_rejected_credentials_are_not_retried() -> None:
    router = Router()
    a = adapter(router, secret="wrong")
    with pytest.raises(AuthFailed):
        await a.collect(utcnow())
    count = len(router.requests)
    with pytest.raises(AuthFailed, match="update them"):
        await a.collect(utcnow())
    assert len(router.requests) == count  # no further attempt against the router
    # Updating the credentials allows a new attempt.
    a.source.credentials["client_secret"] = "s3cret"
    snap = await a.collect(utcnow())
    assert snap.wan_links
    await a.close()


async def test_command_endpoints_refused() -> None:
    a = adapter(Router())
    for name in ("cmd.wifi.scan", "cmd.config.download", "config.pepvpn.profile"):
        with pytest.raises(EndpointRefused):
            await a._get(name)
    await a.close()


# 7.2 ---------------------------------------------------------------------------------
async def test_failover_event_from_fixture_pair() -> None:
    router = Router()
    a = adapter(router)
    state = StateStore()
    state.configure_source(
        "pep",
        name="Peplink router",
        kind="peplink",
        reliability=Reliability.RELIABLE,
        interval_s=15,
    )
    state.apply(await a.collect(utcnow()))
    router.wan_fixture = "status_wan_connection_failover.json"
    events = state.apply(await a.collect(utcnow()))
    failovers = [e for e in events if e.kind == "failover"]
    assert len(failovers) == 1
    assert failovers[0].data == {"previous": ["Starlink"], "current": ["Cellular"]}
    assert "Starlink" in failovers[0].message and "Cellular" in failovers[0].message
    await a.close()
