from __future__ import annotations

from insight.model import device_key
from insight.topology import Topology
from tests.factories import port

CORE = "f0:9f:c2:00:00:01"
SW_LD = "f0:9f:c2:00:00:10"
AP_A = "24:79:2a:00:00:01"
AP_B = "24:79:2a:00:00:02"
AP_C = "24:79:2a:00:00:03"


def fixture_ports() -> list:
    return [
        # SW-LD uplink (port 25) goes to the core switch.
        port("unifi", SW_LD, "25", is_uplink=True, neighbour_mac=CORE),
        port("unifi", CORE, "3", neighbour_mac=SW_LD),
        port("unifi", SW_LD, "1", neighbour_mac=AP_A),
        port("unifi", SW_LD, "2", neighbour_mac=AP_B),
        port("unifi", CORE, "8", neighbour_mac=AP_C),
        port("unifi", SW_LD, "5"),  # nothing attached
    ]


def k(mac: str) -> str:
    return device_key(mac=mac)


def test_downstream_of_switch() -> None:
    topo = Topology.build(fixture_ports())
    assert topo.downstream(k(SW_LD)) == sorted([k(AP_A), k(AP_B)])
    assert topo.downstream(k(CORE)) == sorted([k(SW_LD), k(AP_A), k(AP_B), k(AP_C)])
    att = topo.parent(k(AP_B))
    assert att is not None and att.parent_key == k(SW_LD) and att.port_id == "2"
    assert topo.path_to_root(k(AP_A)) == [k(SW_LD), k(CORE)]


def test_manual_override_wins() -> None:
    topo = Topology.build(fixture_ports(), overrides={k(AP_C): (k(SW_LD), "7")})
    assert k(AP_C) in topo.downstream(k(SW_LD))
    att = topo.parent(k(AP_C))
    assert att is not None and att.manual and att.port_id == "7"


def test_cycle_is_broken() -> None:
    ports = [
        port("unifi", CORE, "1", neighbour_mac=SW_LD),
        port("unifi", SW_LD, "1", neighbour_mac=CORE),
    ]
    topo = Topology.build(ports)
    assert len(topo.downstream(k(CORE))) <= 1
