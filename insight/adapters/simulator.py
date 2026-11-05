"""A simulated yacht for development, demonstration and tests.

A SimulatorHub holds one simulated yacht ("world"). Simulator sources each play one
role (Peplink, UniFi, Ruckus SNMP, Ruckus web, Starlink dish, probes) and report the
world through the normal pipeline, exactly as real adapters would. Scenarios script
changes to the world step by step.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from insight.collection.adapter import Adapter, AdapterInfo, ConnectionTest, Unreachable
from insight.collection.registry import register
from insight.model import (
    AccessPoint,
    Client,
    Device,
    DeviceCategory,
    Event,
    LinkState,
    Metric,
    OnlineState,
    Port,
    Reliability,
    Snapshot,
    WanLink,
    WanType,
    WifiNetwork,
    device_key,
)

ROUTER_MAC = "00:1a:dd:c0:ff:ee"
CORE_MAC = "f0:9f:c2:00:00:01"
SW_MAIN_MAC = "f0:9f:c2:00:00:10"
SW_LOWER_MAC = "f0:9f:c2:00:00:20"
DISH_KEY = "serial:UT01000000-SIM00001"


@dataclass
class SimWan:
    link_id: str
    name: str
    wan_type: WanType
    priority: int
    state: LinkState = LinkState.CONNECTED
    health_ok: bool = True
    latency_ms: float = 45.0
    loss_pct: float = 0.0
    signal: dict[str, float] = field(default_factory=dict)
    carrier: str | None = None
    usage_bytes: int = 0


@dataclass
class SimPort:
    port_id: str
    link_up: bool = True
    poe_w: float | None = None
    neighbour_mac: str | None = None
    neighbour_name: str | None = None
    uplink: bool = False


@dataclass
class SimSwitch:
    mac: str
    name: str
    ip: str
    model: str
    online: bool = True
    ports: dict[str, SimPort] = field(default_factory=dict)


@dataclass
class SimAp:
    mac: str
    name: str
    ip: str
    model: str = "R650"
    online: bool = True
    clients: int = 6
    util: dict[str, float] = field(default_factory=lambda: {"2.4GHz": 25.0, "5GHz": 18.0})
    ssids: tuple[str, ...] = ("Guest", "Crew")


@dataclass
class SimDish:
    reachable: bool = True
    online: bool = True
    obstruction_fraction: float = 0.002
    currently_obstructed: bool = False
    alerts: list[str] = field(default_factory=list)
    outages: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 42.0
    drop_rate: float = 0.0


@dataclass
class SimProbes:
    internet_ok: bool = True
    internet_loss_pct: float = 0.0
    internet_rtt_ms: float = 48.0
    dns_local_ok: bool = True
    dns_public_ok: bool = True
    http_ok: bool = True
    http_ms: float = 180.0


@dataclass
class World:
    wans: list[SimWan]
    switches: list[SimSwitch]
    aps: list[SimAp]
    dish: SimDish
    probes: SimProbes
    lan_clients: list[dict[str, str]]
    down_roles: set[str] = field(default_factory=set)

    def ap_reachable(self, ap: SimAp) -> bool:
        if not ap.online:
            return False
        for sw in self.switches:
            for port in sw.ports.values():
                if port.neighbour_mac == ap.mac:
                    return sw.online and port.link_up and (port.poe_w is None or port.poe_w > 0)
        return True

    def in_use(self) -> list[SimWan]:
        usable = [w for w in self.wans if w.state is LinkState.CONNECTED and w.health_ok]
        if not usable:
            return []
        best = min(w.priority for w in usable)
        return [w for w in usable if w.priority == best]


AP_LOCATIONS = [
    ("24:79:2a:00:00:01", "AP-SALOON", "10.20.1.41", SW_MAIN_MAC, "1"),
    ("24:79:2a:00:00:02", "AP-DINING", "10.20.1.42", SW_MAIN_MAC, "2"),
    ("24:79:2a:00:00:03", "AP-SUNDECK", "10.20.1.43", SW_MAIN_MAC, "3"),
    ("24:79:2a:00:00:04", "AP-CAB4", "10.20.1.44", SW_LOWER_MAC, "1"),
    ("24:79:2a:00:00:05", "AP-CAB6", "10.20.1.45", SW_LOWER_MAC, "2"),
    ("24:79:2a:00:00:06", "AP-CREWMESS", "10.20.1.46", SW_LOWER_MAC, "3"),
]


def baseline_world() -> World:
    main = SimSwitch(SW_MAIN_MAC, "SW-MAIN-01", "10.20.0.11", "USW-Pro-24-PoE")
    lower = SimSwitch(SW_LOWER_MAC, "SW-LD-01", "10.20.0.12", "USW-Pro-24-PoE")
    core = SimSwitch(CORE_MAC, "SW-CORE", "10.20.0.10", "USW-Pro-Aggregation")
    core.ports = {
        "1": SimPort("1", neighbour_mac=ROUTER_MAC, neighbour_name="Peplink", uplink=True),
        "2": SimPort("2", neighbour_mac=SW_MAIN_MAC, neighbour_name="SW-MAIN-01"),
        "3": SimPort("3", neighbour_mac=SW_LOWER_MAC, neighbour_name="SW-LD-01"),
    }
    for sw in (main, lower):
        sw.ports["25"] = SimPort(
            "25", neighbour_mac=CORE_MAC, neighbour_name="SW-CORE", uplink=True
        )
    aps = []
    for mac, name, ip, sw_mac, port_id in AP_LOCATIONS:
        aps.append(SimAp(mac, name, ip))
        sw = main if sw_mac == SW_MAIN_MAC else lower
        sw.ports[port_id] = SimPort(port_id, poe_w=7.4, neighbour_mac=mac, neighbour_name=name)
    lower.ports["8"] = SimPort("8", link_up=False, poe_w=0.0)
    return World(
        wans=[
            SimWan("1", "Starlink", WanType.ETHERNET, 1, latency_ms=42.0),
            SimWan(
                "2",
                "Cellular",
                WanType.CELLULAR,
                2,
                latency_ms=68.0,
                signal={"rsrp": -88.0, "sinr": 14.0},
                carrier="Vodafone",
            ),
        ],
        switches=[core, main, lower],
        aps=aps,
        dish=SimDish(),
        probes=SimProbes(),
        lan_clients=[
            {"mac": "3c:22:fb:11:22:33", "ip": "10.20.5.20", "name": "Captain-iPad"},
            {"mac": "00:0e:58:aa:bb:01", "ip": "10.20.3.10", "name": "SONOS-Saloon"},
        ],
    )


Step = Callable[[World], None]


def _failover(w: World) -> None:
    w.wans[0].state = LinkState.DISCONNECTED
    w.wans[0].health_ok = False
    w.dish.online = False
    w.dish.outages.append({"cause": "NO_SCHEDULE", "duration_s": 300})
    w.probes.internet_rtt_ms = 75.0


def _internet_down(w: World) -> None:
    for wan in w.wans:
        wan.state = LinkState.DISCONNECTED
        wan.health_ok = False
    w.dish.online = False
    w.probes.internet_ok = False
    w.probes.internet_loss_pct = 100.0
    w.probes.dns_public_ok = False
    w.probes.dns_local_ok = False
    w.probes.http_ok = False


def _primary_degraded(w: World) -> None:
    w.wans[0].latency_ms = 900.0
    w.wans[0].loss_pct = 12.0
    w.probes.internet_rtt_ms = 950.0
    w.probes.internet_loss_pct = 12.0
    w.probes.http_ms = 4200.0


def _all_paths_degraded(w: World) -> None:
    _primary_degraded(w)
    w.wans[1].latency_ms = 700.0
    w.wans[1].loss_pct = 9.0


def _dns_failure(w: World) -> None:
    w.probes.dns_local_ok = False


def _dish_obstruction(w: World) -> None:
    w.dish.obstruction_fraction = 0.18
    w.dish.currently_obstructed = True
    w.dish.outages = [
        {"cause": "OBSTRUCTED", "duration_s": 9},
        {"cause": "OBSTRUCTED", "duration_s": 14},
    ]
    w.wans[0].loss_pct = 6.0
    w.wans[0].latency_ms = 160.0
    w.probes.internet_loss_pct = 6.0
    w.probes.http_ms = 1500.0


def _dish_alert(w: World) -> None:
    w.dish.alerts = ["thermal_throttle"]


def _weak_cellular(w: World) -> None:
    _failover(w)
    w.wans[1].signal = {"rsrp": -118.0, "sinr": -2.0}


def _port_for(w: World, ap_mac: str) -> SimPort:
    for sw in w.switches:
        for port in sw.ports.values():
            if port.neighbour_mac == ap_mac:
                return port
    raise KeyError(ap_mac)


def _ap_poe_loss(w: World) -> None:
    port = _port_for(w, "24:79:2a:00:00:04")
    port.poe_w = 0.0
    port.link_up = False


def _ap_offline(w: World) -> None:
    w.aps[0].online = False  # AP-SALOON stops answering, its port still has power and link


def _switch_offline(w: World) -> None:
    lower = next(s for s in w.switches if s.mac == SW_LOWER_MAC)
    lower.online = False
    core = next(s for s in w.switches if s.mac == CORE_MAC)
    core.ports["3"].link_up = False


def _wifi_congestion(w: World) -> None:
    w.aps[0].util = {"2.4GHz": 92.0, "5GHz": 81.0}
    w.aps[0].clients = 48


def _controller_outage(w: World) -> None:
    w.down_roles.add("unifi")


def _ruckus_web_broken(w: World) -> None:
    w.down_roles.add("ruckus-web")


def _new_device(w: World) -> None:
    w.lan_clients.append({"mac": "b8:27:eb:12:34:56", "ip": "10.20.5.77", "name": "raspberrypi"})


def _flap(w: World) -> None:
    w.aps[1].online = not w.aps[1].online


@dataclass(frozen=True)
class Scenario:
    name: str
    title: str
    steps: tuple[Step, ...]
    expect_events: tuple[str, ...] = ()


SCENARIOS: dict[str, Scenario] = {
    s.name: s
    for s in [
        Scenario("baseline", "Everything healthy", ()),
        Scenario("failover", "Starlink fails, cellular takes over", (_failover,), ("failover",)),
        Scenario(
            "internet_down", "All internet links down", (_internet_down,), ("wan_state_change",)
        ),
        Scenario("primary_degraded", "Starlink slow and lossy", (_primary_degraded,)),
        Scenario("all_paths_degraded", "Every internet path degraded", (_all_paths_degraded,)),
        Scenario("dns_failure", "Yacht DNS fails, IP works", (_dns_failure,)),
        Scenario("dish_obstruction", "Dish obstructed", (_dish_obstruction,)),
        Scenario("dish_alert", "Dish thermal throttling", (_dish_alert,), ("dish_alert",)),
        Scenario("weak_cellular", "On cellular with weak signal", (_weak_cellular,), ("failover",)),
        Scenario("ap_poe_loss", "Cabin 4 AP loses PoE", (_ap_poe_loss,), ("poe_lost", "port_down")),
        Scenario("ap_offline", "Saloon AP stops responding", (_ap_offline,), ("ap_offline",)),
        Scenario(
            "switch_offline", "Lower deck switch offline", (_switch_offline,), ("device_offline",)
        ),
        Scenario("wifi_congestion", "Saloon Wi-Fi congested", (_wifi_congestion,)),
        Scenario(
            "controller_outage",
            "UniFi controller unreachable",
            (_controller_outage,),
            ("monitoring_failure",),
        ),
        Scenario(
            "ruckus_web_broken",
            "Ruckus web interface changed",
            (_ruckus_web_broken,),
            ("monitoring_failure",),
        ),
        Scenario("new_device", "Unknown device joins the network", (_new_device,)),
        Scenario(
            "intermittent_ap", "Dining AP keeps dropping", (_flap,) * 8, ("ap_offline", "ap_online")
        ),
    ]
}


class SimulatorHub:
    """One simulated yacht, shared by all simulator sources with the same hub name."""

    _hubs: ClassVar[dict[str, SimulatorHub]] = {}

    def __init__(self) -> None:
        self.world = baseline_world()
        self.scenario = SCENARIOS["baseline"]
        self.step_index = 0

    @classmethod
    def get(cls, name: str = "default") -> SimulatorHub:
        hub = cls._hubs.get(name)
        if hub is None:
            hub = cls._hubs[name] = SimulatorHub()
        return hub

    @classmethod
    def reset_all(cls) -> None:
        cls._hubs.clear()

    def load(self, scenario: str) -> None:
        self.world = baseline_world()
        self.scenario = SCENARIOS[scenario]
        self.step_index = 0

    def step(self) -> bool:
        """Apply the next scenario step. Returns False when the scenario is finished."""
        if self.step_index >= len(self.scenario.steps):
            return False
        self.scenario.steps[self.step_index](self.world)
        self.step_index += 1
        return True

    def snapshot_world(self) -> World:
        return copy.deepcopy(self.world)


ROLES: dict[str, Reliability] = {
    "peplink": Reliability.RELIABLE,
    "unifi": Reliability.RELIABLE,
    "ruckus-snmp": Reliability.RELIABLE,
    "ruckus-web": Reliability.OPTIONAL,
    "starlink": Reliability.OPTIONAL,
    "probes": Reliability.RELIABLE,
}


@register
class SimulatorAdapter(Adapter):
    info = AdapterInfo(
        kind="simulator",
        label="Simulator (demo and testing)",
        reliability=Reliability.RELIABLE,
        default_interval_s=15,
        address_label="Role",
        address_help="One of: " + ", ".join(ROLES),
    )

    def __init__(self, source: Any) -> None:
        super().__init__(source)
        self.role = str(source.options.get("role") or source.address)
        if self.role not in ROLES:
            raise ValueError(f"unknown simulator role {self.role!r}")
        self.hub = SimulatorHub.get(str(source.options.get("hub", "default")))
        self._previous_alerts: set[str] = set()

    @property
    def reliability(self) -> Reliability:
        return ROLES[self.role]

    async def test_connection(self, now: datetime) -> ConnectionTest:
        return ConnectionTest(True, f"Simulator role {self.role} ready.")

    async def collect(self, now: datetime) -> Snapshot:
        world = self.hub.snapshot_world()
        if self.role in world.down_roles:
            raise Unreachable("simulated outage: no response")
        snap = self.new_snapshot(now)
        getattr(self, "_" + self.role.replace("-", "_"))(world, snap, now)
        return snap

    # -- helpers -------------------------------------------------------------------
    def _common(self, now: datetime) -> dict[str, Any]:
        return {"source_id": self.source.id, "observed_at": now, "reliability": self.reliability}

    def _peplink(self, w: World, snap: Snapshot, now: datetime) -> None:
        c = self._common(now)
        router = device_key(mac=ROUTER_MAC)
        snap.devices.append(
            Device(
                key=router,
                name="Peplink MAX HD4",
                manufacturer="Peplink",
                model="MAX HD4 MBX",
                category=DeviceCategory.ROUTER,
                ip="10.20.0.1",
                mac=ROUTER_MAC,
                firmware="8.5.2",
                serial="1111-2222-3333",
                online=OnlineState.ONLINE,
                **c,
            )
        )
        in_use = {x.link_id for x in w.in_use()}
        for wan in w.wans:
            snap.wan_links.append(
                WanLink(
                    link_id=wan.link_id,
                    name=wan.name,
                    device_key=router,
                    wan_type=wan.wan_type,
                    state=wan.state,
                    priority=wan.priority,
                    in_use=wan.link_id in in_use,
                    health_ok=wan.health_ok,
                    latency_ms=wan.latency_ms if wan.state is LinkState.CONNECTED else None,
                    loss_pct=wan.loss_pct if wan.state is LinkState.CONNECTED else None,
                    signal=dict(wan.signal),
                    carrier=wan.carrier,
                    network_type="LTE" if wan.wan_type is WanType.CELLULAR else None,
                    usage_bytes=wan.usage_bytes,
                    **c,
                )
            )
            subject = f"wan:{self.source.id}:{wan.link_id}"
            if wan.state is LinkState.CONNECTED:
                snap.metrics.append(
                    Metric(subject=subject, name="latency_ms", value=wan.latency_ms, unit="ms", **c)
                )
                snap.metrics.append(
                    Metric(subject=subject, name="loss_pct", value=wan.loss_pct, unit="%", **c)
                )
            for name, value in wan.signal.items():
                snap.metrics.append(
                    Metric(subject=subject, name=f"signal_{name}", value=value, unit="dB", **c)
                )
        snap.clients.extend(
            Client(mac=lc["mac"], ip=lc["ip"], hostname=lc["name"], wired=None, **c)
            for lc in w.lan_clients
        )
        snap.facts["lan_subnets"] = ["10.20.0.0/22"]

    def _unifi(self, w: World, snap: Snapshot, now: datetime) -> None:
        c = self._common(now)
        for sw in w.switches:
            key = device_key(mac=sw.mac)
            snap.devices.append(
                Device(
                    key=key,
                    name=sw.name,
                    manufacturer="Ubiquiti",
                    model=sw.model,
                    category=DeviceCategory.SWITCH,
                    ip=sw.ip,
                    mac=sw.mac,
                    firmware="7.1.26",
                    online=OnlineState.ONLINE if sw.online else OnlineState.OFFLINE,
                    **c,
                )
            )
            if not sw.online:
                continue
            for port in sw.ports.values():
                snap.ports.append(
                    Port(
                        device_key=key,
                        port_id=port.port_id,
                        name=f"Port {port.port_id}",
                        link_up=port.link_up,
                        speed_mbps=1000.0 if port.link_up else None,
                        poe_capable=port.poe_w is not None,
                        poe_enabled=port.poe_w is not None,
                        poe_power_w=port.poe_w,
                        is_uplink=port.uplink,
                        neighbour_mac=port.neighbour_mac if port.link_up else None,
                        neighbour_name=port.neighbour_name if port.link_up else None,
                        rx_errors=0,
                        tx_errors=0,
                        **c,
                    )
                )
                if port.poe_w is not None:
                    snap.metrics.append(
                        Metric(
                            subject=f"port:{key}:{port.port_id}",
                            name="poe_power_w",
                            value=port.poe_w,
                            unit="W",
                            **c,
                        )
                    )

    def _ruckus_snmp(self, w: World, snap: Snapshot, now: datetime) -> None:
        c = self._common(now)
        master = w.aps[0]
        snap.devices.append(
            Device(
                key=device_key(mac=master.mac),
                name=master.name,
                manufacturer="Ruckus",
                model=master.model,
                category=DeviceCategory.ACCESS_POINT,
                ip=master.ip,
                mac=master.mac,
                firmware="200.15.6.212",
                online=OnlineState.ONLINE if w.ap_reachable(master) else OnlineState.UNKNOWN,
                details={"unleashed_master": True},
                **c,
            )
        )
        registered = [ap for ap in w.aps if w.ap_reachable(ap)]
        snap.facts["wifi.totals"] = {
            "ap_known": len(w.aps),
            "ap_registered": len(registered),
            "clients": sum(ap.clients for ap in registered),
        }
        snap.metrics.append(
            Metric(subject="wifi:ruckus", name="ap_registered", value=len(registered), **c)
        )
        snap.metrics.append(
            Metric(
                subject="wifi:ruckus",
                name="clients",
                value=sum(ap.clients for ap in registered),
                **c,
            )
        )

    def _ruckus_web(self, w: World, snap: Snapshot, now: datetime) -> None:
        c = self._common(now)
        for ssid in ("Guest", "Crew"):
            snap.wifi_networks.append(
                WifiNetwork(network_id=ssid.lower(), ssid=ssid, enabled=True, **c)
            )
        for ap in w.aps:
            key = device_key(mac=ap.mac)
            online = w.ap_reachable(ap)
            snap.devices.append(
                Device(
                    key=key,
                    name=ap.name,
                    manufacturer="Ruckus",
                    model=ap.model,
                    category=DeviceCategory.ACCESS_POINT,
                    ip=ap.ip,
                    mac=ap.mac,
                    firmware="200.15.6.212",
                    online=OnlineState.ONLINE if online else OnlineState.OFFLINE,
                    **c,
                )
            )
            snap.access_points.append(
                AccessPoint(
                    device_key=key,
                    name=ap.name,
                    online=OnlineState.ONLINE if online else OnlineState.OFFLINE,
                    client_count=ap.clients if online else 0,
                    channels={"2.4GHz": 6, "5GHz": 44},
                    channel_utilisation_pct=dict(ap.util) if online else {},
                    ssids=ap.ssids,
                    **c,
                )
            )
            if online:
                for band, pct in ap.util.items():
                    snap.metrics.append(
                        Metric(
                            subject=f"device:{key}",
                            name=f"channel_util_{band}",
                            value=pct,
                            unit="%",
                            **c,
                        )
                    )
                for i in range(min(ap.clients, 3)):
                    snap.clients.append(
                        Client(
                            mac=f"aa:bb:cc:{ap.mac[-5:-3]}:{ap.mac[-2:]}:{i:02x}",
                            ap_key=key,
                            ssid=ap.ssids[i % len(ap.ssids)],
                            band="5GHz",
                            signal_dbm=-58.0 - i * 6,
                            wired=False,
                            **c,
                        )
                    )

    def _starlink(self, w: World, snap: Snapshot, now: datetime) -> None:
        c = self._common(now)
        d = w.dish
        if not d.reachable:
            raise Unreachable("dish not responding on 192.168.100.1:9200")
        snap.devices.append(
            Device(
                key=DISH_KEY,
                name="Starlink dish",
                manufacturer="SpaceX",
                model="rev4_prod1 (Flat High Performance)",
                category=DeviceCategory.SATELLITE_TERMINAL,
                ip="192.168.100.1",
                firmware="2026.10.09.mr1",
                serial="UT01000000-SIM00001",
                online=OnlineState.ONLINE if d.online else OnlineState.OFFLINE,
                **c,
            )
        )
        snap.facts["dish"] = {
            "online": d.online,
            "obstruction_fraction": d.obstruction_fraction,
            "currently_obstructed": d.currently_obstructed,
            "alerts": list(d.alerts),
            "outages": list(d.outages),
            "latency_ms": d.latency_ms if d.online else None,
            "drop_rate": d.drop_rate,
            "stowed": False,
        }
        subject = f"dish:{self.source.id}"
        snap.metrics.append(
            Metric(subject=subject, name="obstruction_fraction", value=d.obstruction_fraction, **c)
        )
        if d.online:
            snap.metrics.append(
                Metric(subject=subject, name="latency_ms", value=d.latency_ms, unit="ms", **c)
            )
        current = set(d.alerts)
        for alert in sorted(current - self._previous_alerts):
            snap.events.append(
                Event(
                    kind="dish_alert",
                    subject=f"device:{DISH_KEY}",
                    message=f"Starlink dish reported alert: {alert}",
                    devices=(DISH_KEY,),
                    data={"alert": alert},
                    **c,
                )
            )
        self._previous_alerts = current

    def _probes(self, w: World, snap: Snapshot, now: datetime) -> None:
        c = self._common(now)
        p = w.probes
        devices: dict[str, dict[str, Any]] = {}
        for ap in w.aps:
            ok = w.ap_reachable(ap)
            devices[device_key(mac=ap.mac)] = {
                "reachable": ok,
                "rtt_ms": 1.2 if ok else None,
                "loss_pct": 0.0 if ok else 100.0,
            }
        for sw in w.switches:
            ok = sw.online
            devices[device_key(mac=sw.mac)] = {
                "reachable": ok,
                "rtt_ms": 0.8 if ok else None,
                "loss_pct": 0.0 if ok else 100.0,
            }
        devices[device_key(mac=ROUTER_MAC)] = {"reachable": True, "rtt_ms": 0.6, "loss_pct": 0.0}
        devices[DISH_KEY] = {
            "reachable": w.dish.reachable,
            "rtt_ms": 2.0 if w.dish.reachable else None,
            "loss_pct": 0.0 if w.dish.reachable else 100.0,
        }
        in_use = w.in_use()
        snap.facts["probe.device"] = devices
        snap.facts["probe.internet"] = {
            "reachable": p.internet_ok,
            "rtt_ms": p.internet_rtt_ms if p.internet_ok else None,
            "loss_pct": p.internet_loss_pct,
            "targets": {t: {"ok": p.internet_ok} for t in ("1.1.1.1", "8.8.8.8", "9.9.9.9")},
        }
        snap.facts["probe.dns"] = {
            "local": {"ok": p.dns_local_ok, "ms": 22.0 if p.dns_local_ok else None},
            "public": {"ok": p.dns_public_ok, "ms": 48.0 if p.dns_public_ok else None},
        }
        snap.facts["probe.http"] = {
            "ok": p.http_ok,
            "ms": p.http_ms if p.http_ok else None,
            "baseline_ms": 180.0,
        }
        snap.facts["probe.wan_in_use"] = in_use[0].name if in_use else None
        if p.internet_ok:
            snap.metrics.append(
                Metric(
                    subject="probe:internet", name="rtt_ms", value=p.internet_rtt_ms, unit="ms", **c
                )
            )
        snap.metrics.append(
            Metric(
                subject="probe:internet", name="loss_pct", value=p.internet_loss_pct, unit="%", **c
            )
        )
        if p.http_ok:
            snap.metrics.append(
                Metric(subject="probe:http", name="response_ms", value=p.http_ms, unit="ms", **c)
            )
