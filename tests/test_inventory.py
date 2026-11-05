from __future__ import annotations

from datetime import datetime, timedelta

from insight.collection.adapter import Adapter, AdapterInfo, AuthFailed, ParseFailed, Unreachable
from insight.collection.registry import register
from insight.inventory import Inventory, Service
from insight.model import DeviceCategory, Reliability, Snapshot, WifiNetwork
from insight.runtime import Runtime
from insight.setup import add_source
from insight.state import StateStore
from insight.timeutil import utcnow
from tests.factories import dev, port, snap

SW = "f0:9f:c2:00:00:10"
AP = "24:79:2a:00:00:01"


@register
class SetupFake(Adapter):
    info = AdapterInfo(
        kind="setup-fake",
        label="Peplink router",
        reliability=Reliability.RELIABLE,
        default_interval_s=30,
    )

    async def collect(self, now: datetime) -> Snapshot:
        behaviour = self.source.options.get("behaviour", "ok")
        if behaviour == "auth":
            raise AuthFailed("HTTP 401")
        if behaviour == "unreachable":
            raise Unreachable("connection refused")
        if behaviour == "parse":
            raise ParseFailed("not JSON")
        return self.new_snapshot(now)


# 6.1 -----------------------------------------------------------------------------
async def test_setup_success_saves_source(runtime: Runtime) -> None:
    result = await add_source(
        runtime.sources,
        kind="setup-fake",
        name="Bridge router",
        address="https://10.0.0.1",
        credentials={"key": "k"},
    )
    assert result.ok
    saved = runtime.sources.list()
    assert [s.name for s in saved] == ["Bridge router"]
    assert saved[0].reliability is Reliability.RELIABLE


async def test_setup_bad_credentials_explained_and_not_saved(runtime: Runtime) -> None:
    result = await add_source(
        runtime.sources,
        kind="setup-fake",
        name="Bridge router",
        address="https://10.0.0.1",
        credentials={"key": "wrong"},
        options={"behaviour": "auth"},
    )
    assert not result.ok
    assert "Bridge router rejected the credentials" in result.message
    assert runtime.sources.list() == []


async def test_setup_unreachable_explained(runtime: Runtime) -> None:
    result = await add_source(
        runtime.sources,
        kind="setup-fake",
        name="Bridge router",
        address="https://10.9.9.9",
        credentials={},
        options={"behaviour": "unreachable"},
    )
    assert not result.ok
    assert "could not reach Bridge router at https://10.9.9.9" in result.message


async def test_setup_wrong_device_explained(runtime: Runtime) -> None:
    result = await add_source(
        runtime.sources,
        kind="setup-fake",
        name="",
        address="https://10.0.0.7",
        credentials={},
        options={"behaviour": "parse"},
    )
    assert (
        not result.ok
        and "Peplink router" in result.message
        and "Insight understands" in result.message
    )


# 6.2 -----------------------------------------------------------------------------
def test_new_device_added_with_event(runtime: Runtime) -> None:
    inv = runtime.inventory
    events = inv.sync(
        snap("unifi", devices=[dev("unifi", SW, name="SW-LD-01", category=DeviceCategory.SWITCH)])
    )
    assert [e.kind for e in events] == ["device_added"]
    assert inv.get(f"mac:{SW}").name == "SW-LD-01"  # type: ignore[union-attr]


def test_details_update_and_missing_device_marked(runtime: Runtime) -> None:
    inv = runtime.inventory
    inv.sync(snap("unifi", devices=[dev("unifi", SW, firmware="7.1.0")]))
    assert inv.sync(snap("unifi", devices=[dev("unifi", SW, firmware="7.1.26")])) == []
    assert inv.get(f"mac:{SW}").firmware == "7.1.26"  # type: ignore[union-attr]
    events = inv.sync(snap("unifi", devices=[]))
    assert [e.kind for e in events] == ["device_no_longer_reported"]
    item = inv.get(f"mac:{SW}")
    assert item is not None and not item.reported  # kept, not deleted
    assert [e.kind for e in inv.sync(snap("unifi", devices=[dev("unifi", SW)]))] == [
        "device_reported_again"
    ]


def test_port_neighbours_populate_inventory(runtime: Runtime) -> None:
    inv = runtime.inventory
    inv.sync(
        snap("unifi", ports=[port("unifi", SW, "12", neighbour_mac=AP, neighbour_name="AP-SALOON")])
    )
    item = inv.get(f"mac:{AP}")
    assert item is not None and item.name == "AP-SALOON"


def test_optional_source_does_not_override_reliable(runtime: Runtime) -> None:
    inv = runtime.inventory
    inv.sync(snap("unifi", devices=[dev("unifi", AP, name="ap-saloon")]))
    inv.sync(
        snap(
            "ruckus-web",
            rel=Reliability.OPTIONAL,
            devices=[dev("ruckus-web", AP, rel=Reliability.OPTIONAL, name="Saloon", model="R650")],
        )
    )
    item = inv.get(f"mac:{AP}")
    assert item is not None and item.name == "ap-saloon" and item.model == "R650"


# 6.3 -----------------------------------------------------------------------------
def test_manual_device_monitored_by_probes(runtime: Runtime) -> None:
    item = runtime.inventory.add_manual("Bridge PC", "10.20.9.5", location="Bridge")
    assert runtime.inventory.get(item.key).manual  # type: ignore[union-attr]
    assert runtime.inventory.probe_targets()[item.key] == "10.20.9.5"
    assert runtime.inventory.get(item.key).monitoring_status == "probes only"  # type: ignore[union-attr]


# 6.4 -----------------------------------------------------------------------------
def test_tags_survive_firmware_refresh(runtime: Runtime) -> None:
    inv = runtime.inventory
    inv.sync(snap("ruckus", devices=[dev("ruckus", AP, firmware="200.14")]))
    inv.set_tags(f"mac:{AP}", location="Main deck, saloon", display_name="Saloon AP")
    inv.sync(
        snap(
            "ruckus",
            at=utcnow() + timedelta(minutes=1),
            devices=[dev("ruckus", AP, firmware="200.15")],
        )
    )
    item = inv.get(f"mac:{AP}")
    assert item is not None
    assert (item.firmware, item.location, item.label) == (
        "200.15",
        "Main deck, saloon",
        "Saloon AP",
    )


def test_services_and_unmapped_ssids(runtime: Runtime) -> None:
    state = StateStore()
    state.configure_source(
        "ruckus-web", name="r", kind="r", reliability=Reliability.OPTIONAL, interval_s=60
    )
    now = utcnow()
    nets = [
        WifiNetwork(
            source_id="ruckus-web",
            observed_at=now,
            reliability=Reliability.OPTIONAL,
            network_id=n,
            ssid=n,
        )
        for n in ("Guest", "Crew", "Owner")
    ]
    state.apply(snap("ruckus-web", rel=Reliability.OPTIONAL, wifi_networks=nets))
    inv: Inventory = runtime.inventory
    assert not inv.service_is_set_up(Service.GUEST_WIFI)
    inv.map(Service.GUEST_WIFI, "ssid", "Guest")
    inv.map(Service.CREW_WIFI, "ssid", "Crew")
    assert inv.service_is_set_up(Service.GUEST_WIFI)
    assert inv.unmapped_ssids(state) == ["Owner"]
    assert inv.mappings()[Service.GUEST_WIFI]["ssid"] == {"Guest"}
