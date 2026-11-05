from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx

from insight.adapters.unifi import (
    UnifiControllerAdapter,
    mac_table_neighbours,
    parse_classic_clients,
    parse_classic_devices,
    parse_official_switch,
    parse_switch_walk,
)
from insight.model import OnlineState, Reliability, device_key
from insight.sources import SourceConfig
from insight.timeutil import utcnow
from insight.topology import Topology

FIX = Path(__file__).parent / "fixtures" / "unifi"
RUCKUS = "00:24:82:3c:4d:5e"
BRIDGE = "d8:b3:70:1a:2b:01"
CREW = "d8:b3:70:1a:2b:02"


def load(name: str) -> Any:
    return json.loads((FIX / name).read_text())


def test_official_detail_ports_without_watts() -> None:
    dev, ports = parse_official_switch(
        load("official-v1-device-detail-usw24poe.constructed.json"),
        source_id="u",
        now=utcnow(),
        reliability=Reliability.RELIABLE,
    )
    assert (
        dev.key == f"mac:{BRIDGE}" and dev.online is OnlineState.ONLINE and dev.firmware == "7.1.26"
    )
    p12 = next(p for p in ports if p.port_id == "12")
    assert (
        p12.link_up is True
        and p12.poe_enabled is True
        and p12.poe_power_w is None
        and p12.neighbour_mac is None
    )


def test_classic_ports_poe_lldp_and_uplinks() -> None:
    switches = {
        s.name: s for s in parse_classic_devices(load("classic-stat_device.constructed.json"))
    }
    bridge = switches["SW-Bridge"]
    assert bridge.ports["12"].poe_power_w == 7.12
    assert (
        bridge.ports["12"].neighbour_mac == RUCKUS
        and bridge.ports["12"].neighbour_name == "RuckusAP-Saloon"
    )
    assert bridge.ports["25"].is_uplink and bridge.ports["25"].neighbour_mac == "10:56:ca:10:20:30"
    assert bridge.poe_budget_w == 95
    crew = switches["SW-Crew"]
    assert crew.ports["8"].is_uplink and crew.ports["8"].neighbour_mac == BRIDGE


def test_classic_device_level_lldp_shape() -> None:
    sw = parse_classic_devices(load("classic-stat_device-lldp-device-level.constructed.json"))[0]
    # This shape has no port_table, so it yields no ports; neighbours come with port_table only.
    assert sw.mac == BRIDGE


def test_real_world_samples_parse() -> None:
    for name in (
        "classic-stat_device-us16p150.aiounifi.json",
        "classic-stat_device-us24p250.unpoller.json",
    ):
        switches = parse_classic_devices([load(name)])
        assert switches and switches[0].ports, name


def test_mac_table_fallback() -> None:
    neighbours = mac_table_neighbours(
        parse_classic_clients(load("classic-stat_sta.constructed.json"))
    )
    assert neighbours[(BRIDGE, "12")][0] == RUCKUS


def test_snmp_walk_parsing() -> None:
    fx = load("snmp-walk-usw-pro.constructed.json")
    dev, ports = parse_switch_walk(
        fx["system"], fx["walk"], source_id="s", now=utcnow(), mac=BRIDGE, host="10.10.0.11"
    )
    assert dev.name == "SW-Bridge" and dev.key == f"mac:{BRIDGE}" and dev.uptime_s == 1728000
    by_id = {p.port_id: p for p in ports}
    assert set(by_id) == {"1", "12", "25"}  # vlan1 ignored
    assert by_id["1"].link_up is False and by_id["12"].link_up is True
    assert by_id["12"].rx_errors == 3 and by_id["12"].neighbour_mac == RUCKUS


# -- full adapter -------------------------------------------------------------------
class Controller:
    def __init__(self, *, official: bool = True, classic_broken: bool = False) -> None:
        self.official = official
        self.classic_broken = classic_broken
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/login":
            ok = json.loads(request.content).get("password") == "pw"
            return httpx.Response(
                200 if ok else 400, json={"meta": {"rc": "ok" if ok else "error"}}
            )
        if path.startswith("/proxy/network/integration/v1"):
            if not self.official:
                return httpx.Response(404)
            if request.headers.get("x-api-key") != "key":
                return httpx.Response(401)
            rest = path.removeprefix("/proxy/network/integration/v1")
            if rest == "/info":
                return httpx.Response(200, json=load("official-v1-info.official-example.json"))
            if rest == "/sites":
                return httpx.Response(200, json=load("official-v1-sites.constructed.json"))
            if rest.endswith("/devices"):
                return httpx.Response(200, json=load("official-v1-devices.constructed.json"))
            if rest.endswith("5f1c0a0e-3b7d-4c3e-9a51-0d8e2c6f1a01"):
                return httpx.Response(
                    200, json=load("official-v1-device-detail-usw24poe.constructed.json")
                )
            if rest.endswith("5f1c0a0e-3b7d-4c3e-9a51-0d8e2c6f1a02"):
                crew = copy.deepcopy(load("official-v1-device-detail-usw24poe.constructed.json"))
                crew.update(
                    id="5f1c0a0e-3b7d-4c3e-9a51-0d8e2c6f1a02",
                    macAddress=CREW,
                    name="SW-Crew",
                    state="OFFLINE",
                )
                return httpx.Response(200, json=crew)
        if path.endswith("/stat/device"):
            if self.classic_broken:
                return httpx.Response(200, text="<html>not json</html>")
            return httpx.Response(200, json=load("classic-stat_device.constructed.json"))
        if path.endswith("/stat/sta"):
            return httpx.Response(200, json=load("classic-stat_sta.constructed.json"))
        return httpx.Response(404)


def adapter(
    ctrl: Controller, address: str = "https://10.10.0.20", creds: dict[str, str] | None = None
) -> UnifiControllerAdapter:
    source = SourceConfig(
        id="unifi",
        kind="unifi",
        name="UniFi controller",
        address=address,
        reliability=Reliability.RELIABLE,
        credentials=creds if creds is not None else {"api_key": "key"},
    )
    return UnifiControllerAdapter(source, transport=httpx.MockTransport(ctrl))


async def test_official_plus_classic() -> None:
    ctrl = Controller()
    a = adapter(ctrl)
    snap = await a.collect(utcnow())
    assert snap.reliability is Reliability.RELIABLE
    assert snap.facts["unifi.mode"] == "official" and snap.facts["unifi.poe_data"] is True
    devices = {d.name: d for d in snap.devices}
    assert devices["SW-Crew"].online is OnlineState.OFFLINE
    assert devices["SW-Bridge"].reliability is Reliability.RELIABLE
    p12 = next(p for p in snap.ports if p.device_key == f"mac:{BRIDGE}" and p.port_id == "12")
    assert p12.reliability is Reliability.RELIABLE and p12.link_up is True
    assert p12.poe_power_w == 7.12 and p12.neighbour_mac == RUCKUS
    assert all(r.method == "GET" for r in ctrl.requests)
    # 8.3: the topology links the Ruckus AP to its UniFi switch port.
    att = Topology.build(snap.ports).parent(device_key(mac=RUCKUS))
    assert att is not None and att.parent_key == f"mac:{BRIDGE}" and att.port_id == "12"
    await a.close()


async def test_classic_failure_keeps_official_and_last_known_neighbour() -> None:
    ctrl = Controller()
    a = adapter(ctrl)
    await a.collect(utcnow())
    ctrl.classic_broken = True
    snap = await a.collect(utcnow())
    assert "classic" in snap.facts["optional_errors"]
    assert snap.facts["unifi.poe_data"] is False
    p12 = next(p for p in snap.ports if p.device_key == f"mac:{BRIDGE}" and p.port_id == "12")
    assert p12.link_up is True and p12.poe_power_w is None
    assert p12.neighbour_mac == RUCKUS  # remembered attachment
    await a.close()


async def test_controller_without_official_api_is_optional() -> None:
    ctrl = Controller(official=False)
    a = adapter(ctrl)
    snap = await a.collect(utcnow())
    assert snap.reliability is Reliability.OPTIONAL and snap.facts["unifi.mode"] == "classic"
    assert {d.name for d in snap.devices} == {"SW-Bridge", "SW-Crew"}
    await a.close()


async def test_legacy_controller_login() -> None:
    ctrl = Controller(official=False)
    a = adapter(
        ctrl, address="https://10.10.0.20:8443", creds={"username": "insight", "password": "pw"}
    )
    snap = await a.collect(utcnow())
    assert snap.devices and snap.reliability is Reliability.OPTIONAL
    assert [r.method for r in ctrl.requests if r.method != "GET"] == ["POST"]  # only the login
    await a.close()
