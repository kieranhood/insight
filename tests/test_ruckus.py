from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path
from typing import Any

import pytest

from insight.adapters.ruckus import (
    ReadOnlyApi,
    RuckusWebAdapter,
    parse_aps,
    parse_clients,
    parse_snmp,
    parse_syslog_line,
    parse_wlans,
    start_syslog,
    syslog_event,
)
from insight.collection.adapter import ParseFailed
from insight.inventory import Inventory
from insight.model import DeviceCategory, Event, OnlineState, Reliability
from insight.runtime import Runtime
from insight.sources import SourceConfig
from insight.timeutil import utcnow
from tests.factories import port, snap

FIX = Path(__file__).parent / "fixtures" / "ruckus"


def load(name: str) -> Any:
    return json.loads((FIX / name).read_text())


# 9.1 ------------------------------------------------------------------------------------
def test_snmp_totals_and_master() -> None:
    s = parse_snmp(load("snmp_master.json"), source_id="r", now=utcnow(), host="10.10.20.11")
    assert s.facts["wifi.totals"] == {"ap_known": 8, "ap_registered": 7, "clients": 23}
    master = s.devices[0]
    assert (
        master.name == "Unleashed-Yacht"
        and master.model == "R750"
        and master.mac == "2c:c5:d3:aa:bb:01"
    )
    assert master.details["unleashed_master"] is True


def test_snmp_real_world_capture_parses() -> None:
    s = parse_snmp(load("snmp_master_librenms_r650.json"), source_id="r", now=utcnow(), host="x")
    assert s.facts["wifi.totals"]["ap_known"] >= 1


def test_snmp_non_master_rejected() -> None:
    with pytest.raises(ParseFailed, match="master"):
        parse_snmp({"1.3.6.1.2.1.1.5.0": "member"}, source_id="r", now=utcnow(), host="x")


# 9.2 ------------------------------------------------------------------------------------
def test_syslog_samples() -> None:
    lines = (FIX / "syslog_samples.txt").read_text().splitlines()
    kinds = [parse_syslog_line(line).kind for line in lines]
    assert kinds == [
        "ap_joined",
        "ap_joined",
        "ap_rebooted",
        "raw_syslog",  # radio on
        "raw_syslog",  # unrelated daemon line
        "raw_syslog",  # heartbeats lost is deliberately not a leave
        "ap_disconnected",
        "ap_joined",
        "ap_rebooted",
    ]
    lost = parse_syslog_line(lines[6])
    assert lost.ap_mac == "2c:c5:d3:aa:bb:08" and lost.ap_name == "Bridge-Deck"
    event = syslog_event(lost, "10.10.20.11")
    assert event.kind == "ap_disconnected" and event.devices == ("mac:2c:c5:d3:aa:bb:08",)
    assert "Bridge-Deck" in event.message


def test_unrecognised_line_is_raw_event_only() -> None:
    event = syslog_event(
        parse_syslog_line("<134>Apr 15 10:24:20 Ruckus1 rfmd[461]: Netlink - RTM_DELLINK"),
        "10.0.0.5",
    )
    assert event.kind == "raw_syslog" and event.devices == ()
    assert event.message.startswith("Apr 15")


async def test_udp_receiver() -> None:
    received: list[Event] = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        port_no = s.getsockname()[1]
    transport = await start_syslog("127.0.0.1", port_no, received.append)
    line = (FIX / "syslog_samples.txt").read_text().splitlines()[6]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(f"<134>{line}".encode(), ("127.0.0.1", port_no))
    for _ in range(50):
        if received:
            break
        await asyncio.sleep(0.02)
    transport.close()
    assert [e.kind for e in received] == ["ap_disconnected"]


async def test_receiver_ignores_unknown_senders() -> None:
    received: list[Event] = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        port_no = s.getsockname()[1]
    transport = await start_syslog("127.0.0.1", port_no, received.append, lambda: {"10.10.20.11"})
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(b"hello", ("127.0.0.1", port_no))
    await asyncio.sleep(0.1)
    transport.close()
    assert received == []


# 9.3 ------------------------------------------------------------------------------------
def test_parse_aps_wlans_clients() -> None:
    now = utcnow()
    devices, points, metrics = parse_aps(load("aioruckus_aps.json"), source_id="w", now=now)
    assert len(devices) == 8 and all(d.reliability is Reliability.OPTIONAL for d in devices)
    by_name = {p.name: p for p in points}
    assert by_name["Sun-Deck"].online is OnlineState.OFFLINE
    salon = by_name["Main-Salon"]
    assert salon.online is OnlineState.ONLINE and salon.client_count == 9
    assert salon.channels == {"2.4GHz": 6, "5GHz": 36}
    assert salon.channel_utilisation_pct["2.4GHz"] == 31.0
    assert any(m.name == "channel_util_5GHz" for m in metrics)
    wlans = parse_wlans(load("aioruckus_wlans.json"), source_id="w", now=now)
    assert sorted(w.ssid for w in wlans) == ["Crew", "Guest"]
    clients = parse_clients(load("aioruckus_clients.json"), source_id="w", now=now)
    guest = next(c for c in clients if c.hostname == "Guest-iPhone")
    assert guest.ssid == "Guest" and guest.band == "5GHz" and guest.signal_dbm == -44.0
    assert guest.ap_key == "mac:2c:c5:d3:aa:bb:01"


def test_secrets_are_dropped() -> None:
    clients = parse_clients(
        [{"mac": "aa:bb:cc:00:00:01", "wpa-passphrase": "hunter2"}], source_id="w", now=utcnow()
    )
    assert "hunter2" not in repr(clients)


def test_read_only_wrapper_refuses_writes() -> None:
    class Api:
        async def do_restart_ap(self) -> None: ...
        async def get_aps(self) -> list[Any]:
            return []

    api = ReadOnlyApi(Api())
    assert api.get_aps
    with pytest.raises(PermissionError):
        api.do_restart_ap  # noqa: B018


class FakeSession:
    def __init__(self, broken: bool = False) -> None:
        self.broken = broken
        self.api = self

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_aps(self) -> list[dict[str, Any]]:
        if self.broken:
            raise KeyError("ap-list")  # what a changed interface tends to look like
        return load("aioruckus_aps.json")

    async def get_ap_stats(self) -> list[dict[str, Any]]:
        return []

    async def get_active_clients(self) -> list[dict[str, Any]]:
        return load("aioruckus_clients.json")

    async def get_wlans(self) -> list[dict[str, Any]]:
        return load("aioruckus_wlans.json")


def web_source() -> SourceConfig:
    return SourceConfig(
        id="ruckus-web",
        kind="ruckus-web",
        name="Ruckus web",
        address="10.10.20.11",
        reliability=Reliability.OPTIONAL,
        credentials={"username": "insight", "password": "pw"},
    )


async def test_web_adapter_collects() -> None:
    adapter = RuckusWebAdapter(web_source(), session_factory=lambda s: FakeSession())
    snapshot = await adapter.collect(utcnow())
    assert snapshot.reliability is Reliability.OPTIONAL
    assert (
        len(snapshot.access_points) == 8 and len(snapshot.wifi_networks) == 2 and snapshot.clients
    )


async def test_web_parse_failure_leaves_snmp_and_syslog_intact(runtime: Runtime) -> None:
    from insight.collection.adapter import Adapter, AdapterInfo

    class Snmp(Adapter):
        info = AdapterInfo(
            kind="ruckus-snmp-test",
            label="x",
            reliability=Reliability.RELIABLE,
            default_interval_s=60,
        )

        async def collect(self, now):  # type: ignore[no-untyped-def]
            return parse_snmp(
                load("snmp_master.json"), source_id=self.source.id, now=now, host="10.10.20.11"
            )

    web = RuckusWebAdapter(web_source(), session_factory=lambda s: FakeSession(broken=True))
    snmp = Snmp(
        SourceConfig(
            id="ruckus-snmp",
            kind="ruckus-snmp",
            name="Ruckus SNMP",
            address="x",
            reliability=Reliability.RELIABLE,
        )
    )
    runtime.scheduler.add(web)
    runtime.scheduler.add(snmp)
    web_result = await runtime.scheduler.run_once(web)
    snmp_result = await runtime.scheduler.run_once(snmp)
    assert web_result.snapshot is None and web_result.events[0].kind == "monitoring_failure"
    assert snmp_result.snapshot is not None and runtime.state.is_fresh("ruckus-snmp")
    runtime.on_pushed_event(
        syslog_event(
            parse_syslog_line((FIX / "syslog_samples.txt").read_text().splitlines()[0]),
            "10.10.20.11",
        )
    )
    assert runtime.recent_events[-1].kind == "ap_joined"


# 9.4 ------------------------------------------------------------------------------------
async def test_aps_from_optional_source(runtime: Runtime) -> None:
    snapshot = await RuckusWebAdapter(
        web_source(), session_factory=lambda s: FakeSession()
    ).collect(utcnow())
    runtime.inventory.sync(snapshot)
    aps = [
        d for d in runtime.inventory.devices().values() if d.category is DeviceCategory.ACCESS_POINT
    ]
    assert len(aps) == 8 and {d.name for d in aps} >= {"Main-Salon", "Sun-Deck"}


def test_aps_from_switch_neighbours_when_optional_disabled(runtime: Runtime) -> None:
    inv: Inventory = runtime.inventory
    inv.sync(
        snap(
            "unifi",
            ports=[
                port(
                    "unifi",
                    "d8:b3:70:1a:2b:01",
                    "12",
                    neighbour_mac="2c:c5:d3:aa:bb:02",
                    neighbour_name="Owner-Deck",
                )
            ],
        )
    )
    item = inv.get("mac:2c:c5:d3:aa:bb:02")
    assert (
        item is not None
        and item.category is DeviceCategory.ACCESS_POINT
        and item.manufacturer == "Ruckus"
    )
    assert item.name == "Owner-Deck"
