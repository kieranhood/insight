"""Everything a rule may look at, in vendor-neutral terms."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from insight.diagnostics import Evidence, Input
from insight.inventory import Inventory, InventoryDevice, Service
from insight.model import AccessPoint, Event, Port, Reliability, WanLink
from insight.state import SourceState, SourceStatus, StateStore
from insight.topology import Topology

# Which source kinds can satisfy each input.
INPUT_KINDS: dict[Input, tuple[str, ...]] = {
    Input.WAN: ("peplink",),
    Input.PROBES: ("probes",),
    Input.SWITCHES: ("unifi", "unifi-snmp"),
    Input.POE: ("unifi",),
    Input.WIFI_TOTALS: ("ruckus-snmp",),
    Input.WIFI_DETAIL: ("ruckus-web",),
    Input.DISH: ("starlink",),
}

# Simulator roles map onto the same inputs.
SIM_ROLE_KINDS = {
    "peplink": "peplink",
    "unifi": "unifi",
    "ruckus-snmp": "ruckus-snmp",
    "ruckus-web": "ruckus-web",
    "starlink": "starlink",
    "probes": "probes",
}

SYSTEM_NAMES = {
    "peplink": "Peplink router",
    "unifi": "UniFi switching",
    "unifi-snmp": "UniFi switching",
    "ruckus-snmp": "Ruckus Wi-Fi",
    "ruckus-web": "Ruckus Wi-Fi",
    "starlink": "Starlink",
    "probes": "Insight's own checks",
}


@dataclass
class EvalContext:
    now: datetime
    state: StateStore
    inventory: Inventory
    config: dict[str, Any]
    recent_events: list[Event] = field(default_factory=list)
    source_kinds: dict[str, str] = field(default_factory=dict)  # source_id -> effective kind
    disk: dict[str, Any] = field(default_factory=dict)
    _topology: Topology | None = None
    _devices: dict[str, InventoryDevice] | None = None

    # -- sources and inputs -----------------------------------------------------------
    def kind_of(self, source_id: str) -> str:
        return self.source_kinds.get(source_id) or (
            self.state.sources[source_id].kind if source_id in self.state.sources else ""
        )

    def sources_for(self, inp: Input) -> list[SourceStatus]:
        kinds = INPUT_KINDS[inp]
        return [s for sid, s in self.state.sources.items() if self.kind_of(sid) in kinds]

    def available(self, inp: Input) -> bool:
        sources = self.sources_for(inp)
        if inp is Input.POE:
            return any(
                self.state.is_fresh(s.source_id, self.now)
                and self.state.facts(s.source_id).get("unifi.poe_data", True)
                for s in sources
            )
        return any(self.state.is_fresh(s.source_id, self.now) for s in sources)

    def configured(self, inp: Input) -> bool:
        return bool(self.sources_for(inp))

    def failed_sources(self, inp: Input) -> list[SourceStatus]:
        return [
            s
            for s in self.sources_for(inp)
            if s.state is SourceState.FAILED or not self.state.is_fresh(s.source_id, self.now)
        ]

    def facts(self, inp: Input, key: str) -> Any:
        """A fact from the freshest available source for an input."""
        for status in self.sources_for(inp):
            if self.state.is_fresh(status.source_id, self.now):
                value = self.state.facts(status.source_id).get(key)
                if value is not None:
                    return value
        return None

    def source_of(self, inp: Input) -> str | None:
        for status in self.sources_for(inp):
            if self.state.is_fresh(status.source_id, self.now):
                return status.source_id
        return None

    # -- convenient views -------------------------------------------------------------------
    def wan_links(self) -> list[WanLink]:
        return [
            link for link in self.state.wan_links() if self.state.is_fresh(link.source_id, self.now)
        ]

    def starlink(self) -> WanLink | None:
        marked = self.config.get("starlink_wan")
        links = self.wan_links()
        if marked:
            return next(
                (
                    lk
                    for lk in links
                    if lk.source_id == marked.get("source_id")
                    and lk.link_id == marked.get("link_id")
                ),
                None,
            )
        return next((lk for lk in links if "starlink" in lk.name.lower()), None)

    def in_use(self) -> list[WanLink]:
        return [link for link in self.wan_links() if link.in_use]

    def ports(self) -> list[Port]:
        return [p for p in self.state.ports() if self.state.is_fresh(p.source_id, self.now)]

    def access_points(self) -> dict[str, AccessPoint]:
        return {
            k: ap
            for k, ap in self.state.access_points().items()
            if self.state.is_fresh(ap.source_id, self.now)
        }

    def topology(self) -> Topology:
        if self._topology is None:
            self._topology = Topology.build(
                self.state.topology_ports(), self.inventory.topology_overrides()
            )
        return self._topology

    def devices(self) -> dict[str, InventoryDevice]:
        if self._devices is None:
            self._devices = self.inventory.devices()
        return self._devices

    def device_name(self, key: str) -> str:
        device = self.devices().get(key)
        if device is not None:
            return device.label
        merged = self.state.devices(self.now).get(key)
        return (merged.name if merged else None) or key.split(":", 1)[-1]

    def location(self, key: str) -> str | None:
        device = self.devices().get(key)
        return device.location if device else None

    def where(self, key: str) -> str:
        """Plain-English place for crew text: the tagged location, never an address."""
        return self.location(key) or "one area of the yacht (its location hasn't been set yet)"

    def probe(self, name: str) -> dict[str, Any]:
        value = self.facts(Input.PROBES, f"probe.{name}")
        return value if isinstance(value, dict) else {}

    def device_reachable(self, key: str) -> bool | None:
        info = self.probe("device").get(key)
        return None if info is None else bool(info.get("reachable"))

    def events_since(self, kinds: Iterable[str], window: timedelta) -> list[Event]:
        kind_set = set(kinds)
        cutoff = self.now - window
        return [e for e in self.recent_events if e.kind in kind_set and e.observed_at >= cutoff]

    # -- services ----------------------------------------------------------------------------
    def services_for_device(self, key: str) -> tuple[str, ...]:
        mappings = self.inventory.mappings()
        result: set[str] = set()
        ap = self.state.access_points().get(key)
        for service, refs in mappings.items():
            if key in refs["device"]:
                result.add(service.value)
            if ap is not None and refs["ssid"] & set(ap.ssids):
                result.add(service.value)
        return tuple(sorted(result))

    def wifi_services_for_aps(self, keys: Iterable[str]) -> tuple[str, ...]:
        result: set[str] = set()
        for key in keys:
            result.update(self.services_for_device(key))
        return tuple(sorted(result))

    @staticmethod
    def guests(services: Iterable[str]) -> bool:
        return Service.GUEST_WIFI.value in set(services) or Service.INTERNET.value in set(services)

    # -- evidence helpers --------------------------------------------------------------------
    def ev(
        self,
        description: str,
        source_id: str | None,
        observed_at: datetime | None = None,
        **data: Any,
    ) -> Evidence:
        return Evidence(description, source_id, observed_at or self.now, data)

    def reliability_of(self, source_id: str) -> Reliability | None:
        status = self.state.sources.get(source_id)
        return status.reliability if status else None
