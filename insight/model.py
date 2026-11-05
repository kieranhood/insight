"""The common, vendor-neutral data model.

Adapters translate vendor data into these types. Diagnostics, health status and the
views only ever see these types, never vendor-specific structures.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class Reliability(StrEnum):
    RELIABLE = "reliable"  # official or standard interface
    OPTIONAL = "optional"  # unofficial interface that may change without notice


class DeviceCategory(StrEnum):
    ROUTER = "router"
    SWITCH = "switch"
    ACCESS_POINT = "access_point"
    NETWORK_CONTROLLER = "network_controller"
    SATELLITE_TERMINAL = "satellite_terminal"
    OTHER = "other"


class OnlineState(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class LinkState(StrEnum):
    CONNECTED = "connected"
    STANDBY = "standby"
    DISCONNECTED = "disconnected"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


class WanType(StrEnum):
    ETHERNET = "ethernet"
    CELLULAR = "cellular"
    WIFI = "wifi"
    OTHER = "other"


_MAC_RE = re.compile(r"^[0-9a-f]{12}$")


def normalise_mac(value: str | None) -> str | None:
    """Return a MAC address as lower-case colon-separated, or None if it is not a MAC."""
    if not value:
        return None
    digits = re.sub(r"[^0-9a-fA-F]", "", value).lower()
    if not _MAC_RE.match(digits):
        return None
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def device_key(
    *, mac: str | None = None, serial: str | None = None, source_id: str = "", native_id: str = ""
) -> str:
    """Stable identity for a device: MAC address first, then serial number, then source-local id."""
    normalised = normalise_mac(mac)
    if normalised:
        return f"mac:{normalised}"
    if serial:
        return f"serial:{serial.strip().upper()}"
    if not native_id:
        raise ValueError("a device needs a MAC address, serial number or native id")
    return f"src:{source_id}:{native_id}"


@dataclass(frozen=True, kw_only=True)
class Observed:
    """Base for everything an adapter reports: who reported it, when, and how reliable it is."""

    source_id: str
    observed_at: datetime
    reliability: Reliability

    def __post_init__(self) -> None:
        if not isinstance(self.observed_at, datetime):
            raise TypeError("observed_at must be a datetime")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware (UTC)")
        if not self.source_id:
            raise ValueError("source_id is required")


@dataclass(frozen=True, kw_only=True)
class Device(Observed):
    key: str
    name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    category: DeviceCategory = DeviceCategory.OTHER
    ip: str | None = None
    mac: str | None = None
    firmware: str | None = None
    serial: str | None = None
    online: OnlineState = OnlineState.UNKNOWN
    uptime_s: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class Port(Observed):
    device_key: str
    port_id: str
    name: str | None = None
    link_up: bool | None = None
    speed_mbps: float | None = None
    poe_capable: bool | None = None
    poe_enabled: bool | None = None
    poe_power_w: float | None = None
    is_uplink: bool = False
    neighbour_mac: str | None = None
    neighbour_name: str | None = None
    rx_bytes: int | None = None
    tx_bytes: int | None = None
    rx_errors: int | None = None
    tx_errors: int | None = None


@dataclass(frozen=True, kw_only=True)
class WanLink(Observed):
    link_id: str
    name: str
    device_key: str
    wan_type: WanType = WanType.OTHER
    state: LinkState = LinkState.UNKNOWN
    priority: int | None = None
    in_use: bool | None = None
    health_ok: bool | None = None
    latency_ms: float | None = None
    loss_pct: float | None = None
    signal: dict[str, float] = field(default_factory=dict)
    carrier: str | None = None
    network_type: str | None = None
    usage_bytes: int | None = None


@dataclass(frozen=True, kw_only=True)
class WifiNetwork(Observed):
    network_id: str
    ssid: str
    enabled: bool | None = None


@dataclass(frozen=True, kw_only=True)
class AccessPoint(Observed):
    device_key: str
    name: str | None = None
    online: OnlineState = OnlineState.UNKNOWN
    client_count: int | None = None
    channels: dict[str, int] = field(default_factory=dict)  # band -> channel
    channel_utilisation_pct: dict[str, float] = field(default_factory=dict)  # band -> %
    ssids: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class Client(Observed):
    mac: str
    ip: str | None = None
    hostname: str | None = None
    ap_key: str | None = None
    ssid: str | None = None
    band: str | None = None
    signal_dbm: float | None = None
    wired: bool | None = None


@dataclass(frozen=True, kw_only=True)
class Metric(Observed):
    subject: str  # e.g. "wan:<source>:<link_id>", "device:<key>", "probe:internet"
    name: str  # e.g. "latency_ms"
    value: float
    unit: str = ""


@dataclass(frozen=True, kw_only=True)
class Event(Observed):
    kind: str  # e.g. "failover", "port_down", "ap_disconnected", "raw_syslog"
    subject: str
    message: str
    devices: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True)
class Snapshot:
    """Everything one source reported in one collection cycle."""

    source_id: str
    collected_at: datetime
    reliability: Reliability
    devices: list[Device] = field(default_factory=list)
    ports: list[Port] = field(default_factory=list)
    wan_links: list[WanLink] = field(default_factory=list)
    wifi_networks: list[WifiNetwork] = field(default_factory=list)
    access_points: list[AccessPoint] = field(default_factory=list)
    clients: list[Client] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.collected_at.tzinfo is None:
            raise ValueError("collected_at must be timezone-aware (UTC)")
