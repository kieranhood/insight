"""UniFi switch adapters: the UniFi Network controller, and SNMP on the switches.

Controller data from the official Network API is reliable. Data that only the older,
undocumented ("classic") API provides is optional: PoE power and budget, LLDP
neighbours, port counters, uplink port and client port. On controllers without the
official API, everything from the controller is optional. Only GET requests are sent
(plus the login POST for legacy controllers). See docs/integrations/unifi.md.
"""

from __future__ import annotations

import dataclasses
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from insight.adapters.snmp import SnmpClient, SnmpTarget, column
from insight.collection.adapter import (
    Adapter,
    AdapterInfo,
    AuthFailed,
    CredentialField,
    ParseFailed,
    Unreachable,
)
from insight.collection.registry import register
from insight.model import (
    Client,
    Device,
    DeviceCategory,
    Metric,
    OnlineState,
    Port,
    Reliability,
    Snapshot,
    device_key,
    normalise_mac,
)

OFFICIAL_PREFIX = "/proxy/network/integration/v1"


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# -- official API parsing ------------------------------------------------------------
def parse_official_switch(
    detail: dict[str, Any], *, source_id: str, now: datetime, reliability: Reliability
) -> tuple[Device, list[Port]]:
    mac = normalise_mac(detail.get("macAddress"))
    key = device_key(mac=mac, source_id=source_id, native_id=str(detail.get("id")))
    state = str(detail.get("state", "")).upper()
    online = (
        OnlineState.ONLINE
        if state == "ONLINE"
        else OnlineState.OFFLINE
        if state in ("OFFLINE", "DISCONNECTED")
        else OnlineState.UNKNOWN
    )
    device = Device(
        source_id=source_id,
        observed_at=now,
        reliability=reliability,
        key=key,
        name=detail.get("name"),
        manufacturer="Ubiquiti",
        model=detail.get("model"),
        category=DeviceCategory.SWITCH,
        ip=detail.get("ipAddress"),
        mac=mac,
        firmware=detail.get("firmwareVersion"),
        online=online,
        details={"unifi_id": detail.get("id")},
    )
    ports: list[Port] = []
    interfaces = detail.get("interfaces")
    for raw in interfaces.get("ports", []) if isinstance(interfaces, dict) else []:
        poe = raw.get("poe") if isinstance(raw.get("poe"), dict) else None
        link = str(raw.get("state", "")).upper()
        ports.append(
            Port(
                source_id=source_id,
                observed_at=now,
                reliability=reliability,
                device_key=key,
                port_id=str(raw.get("idx")),
                name=f"Port {raw.get('idx')}",
                link_up=True if link == "UP" else False if link == "DOWN" else None,
                speed_mbps=_float(raw.get("speedMbps")),
                poe_capable=poe is not None,
                poe_enabled=bool(poe.get("enabled")) if poe else None,
            )
        )
    return device, ports


# -- classic API parsing -------------------------------------------------------------
@dataclasses.dataclass
class ClassicPort:
    port_id: str
    name: str | None
    link_up: bool | None
    speed_mbps: float | None
    poe_capable: bool
    poe_enabled: bool | None
    poe_power_w: float | None
    is_uplink: bool
    neighbour_mac: str | None
    neighbour_name: str | None
    rx_bytes: int | None
    tx_bytes: int | None
    rx_errors: int | None
    tx_errors: int | None


@dataclasses.dataclass
class ClassicSwitch:
    mac: str
    name: str | None
    model: str | None
    ip: str | None
    firmware: str | None
    serial: str | None
    online: OnlineState
    uptime_s: float | None
    poe_budget_w: float | None
    ports: dict[str, ClassicPort]


def parse_classic_devices(payload: dict[str, Any] | list[Any]) -> list[ClassicSwitch]:
    rows = payload.get("data", []) if isinstance(payload, dict) else payload
    switches: list[ClassicSwitch] = []
    for raw in rows if isinstance(rows, list) else []:
        if not isinstance(raw, dict) or raw.get("type") not in ("usw", None) or not raw.get("mac"):
            continue
        if raw.get("type") is None and "port_table" not in raw:
            continue
        mac = normalise_mac(raw["mac"]) or str(raw["mac"])
        device_lldp: dict[str, tuple[str | None, str | None]] = {}
        for entry in raw.get("lldp_table") or []:
            if isinstance(entry, dict) and entry.get("local_port_idx") is not None:
                device_lldp[str(entry["local_port_idx"])] = (
                    normalise_mac(entry.get("chassis_id")),
                    entry.get("system_name"),
                )
        uplink: dict[str, Any] = raw["uplink"] if isinstance(raw.get("uplink"), dict) else {}
        uplink_port = str(uplink.get("port_idx")) if uplink.get("port_idx") is not None else None
        ports: dict[str, ClassicPort] = {}
        for p in raw.get("port_table") or []:
            pid = str(p.get("port_idx"))
            n_mac, n_name = None, None
            lldp = p.get("lldp_table") or []
            if lldp and isinstance(lldp[0], dict):
                n_mac = normalise_mac(lldp[0].get("lldp_chassis_id"))
                n_name = lldp[0].get("lldp_system_name")
            elif pid in device_lldp:
                n_mac, n_name = device_lldp[pid]
            is_uplink = bool(p.get("is_uplink")) or pid == uplink_port
            if is_uplink and not n_mac and uplink.get("uplink_mac"):
                n_mac = normalise_mac(uplink.get("uplink_mac"))
                n_name = uplink.get("uplink_device_name")
            ports[pid] = ClassicPort(
                port_id=pid,
                name=p.get("name"),
                link_up=bool(p["up"]) if "up" in p else None,
                speed_mbps=_float(p.get("speed")) or None,
                poe_capable=bool(p.get("port_poe")),
                poe_enabled=p.get("poe_enable"),
                poe_power_w=_float(p.get("poe_power")) if p.get("port_poe") else None,
                is_uplink=is_uplink,
                neighbour_mac=n_mac,
                neighbour_name=n_name,
                rx_bytes=p.get("rx_bytes"),
                tx_bytes=p.get("tx_bytes"),
                rx_errors=p.get("rx_errors"),
                tx_errors=p.get("tx_errors"),
            )
        state = raw.get("state")
        switches.append(
            ClassicSwitch(
                mac=mac,
                name=raw.get("name"),
                model=raw.get("model"),
                ip=raw.get("ip"),
                firmware=raw.get("version"),
                serial=raw.get("serial"),
                online=OnlineState.ONLINE
                if state == 1
                else OnlineState.OFFLINE
                if state == 0
                else OnlineState.UNKNOWN,
                uptime_s=_float(raw.get("uptime")),
                poe_budget_w=_float(raw.get("total_max_power")),
                ports=ports,
            )
        )
    return switches


def parse_classic_clients(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    rows = payload.get("data", []) if isinstance(payload, dict) else payload
    return (
        [r for r in rows if isinstance(r, dict) and r.get("mac")] if isinstance(rows, list) else []
    )


def mac_table_neighbours(
    clients: list[dict[str, Any]],
) -> dict[tuple[str, str], tuple[str, str | None]]:
    """(switch MAC, port) -> (client MAC, name) for ports with exactly one wired client."""
    seen: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for c in clients:
        if c.get("is_wired") and c.get("sw_mac") and c.get("sw_port") is not None:
            sw = normalise_mac(c["sw_mac"]) or str(c["sw_mac"])
            seen.setdefault((sw, str(c["sw_port"])), []).append(c)
    result: dict[tuple[str, str], tuple[str, str | None]] = {}
    for key, entries in seen.items():
        if len(entries) == 1:
            entry = entries[0]
            mac = normalise_mac(entry["mac"])
            if mac:
                result[key] = (mac, entry.get("name") or entry.get("hostname"))
    return result


@register
class UnifiControllerAdapter(Adapter):
    info = AdapterInfo(
        kind="unifi",
        label="UniFi Network controller",
        reliability=Reliability.RELIABLE,
        default_interval_s=60,
        address_label="Controller address",
        address_help="For example https://192.168.50.20 (UniFi OS) or https://192.168.50.20:8443 (legacy).",
        credentials=(
            CredentialField("api_key", "API key (UniFi OS)", required=False),
            CredentialField(
                "username", "View Only username (legacy controllers)", secret=False, required=False
            ),
            CredentialField("password", "Password (legacy controllers)", required=False),
        ),
        setup_steps=(
            "On UniFi OS, create an API key in the Network app under Integrations.",
            "On a legacy controller, create a View Only administrator.",
        ),
    )

    def __init__(self, source: Any, transport: httpx.AsyncBaseTransport | None = None) -> None:
        super().__init__(source)
        address = source.address if "://" in source.address else f"https://{source.address}"
        self.base_url = address.rstrip("/")
        self.site = str(source.options.get("site", "default"))
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            verify=bool(source.options.get("verify_tls", False)),
            transport=transport,
            timeout=15,
        )
        self._mode: str | None = None  # "official" (UniFi OS with API) or "classic"
        self._site_id: str | None = None
        self._logged_in = False
        self._known_neighbours: dict[tuple[str, str], tuple[str, str | None]] = {}
        self._last: dict[str, float] = {}
        self._client_cache: list[dict[str, Any]] = []

    @property
    def reliability(self) -> Reliability:
        return Reliability.OPTIONAL if self._mode == "classic" else Reliability.RELIABLE

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def _headers(self) -> dict[str, str]:
        key = self.source.credentials.get("api_key")
        return (
            {"X-API-KEY": str(key), "Accept": "application/json"}
            if key
            else {"Accept": "application/json"}
        )

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = await self._client.get(path, params=params, headers=self._headers)
        except httpx.HTTPError as exc:
            raise Unreachable(type(exc).__name__) from exc
        if response.status_code in (401, 403):
            raise AuthFailed(f"the controller refused access (HTTP {response.status_code})")
        if response.status_code == 404:
            raise FileNotFoundError(path)
        if response.status_code >= 400:
            raise ParseFailed(f"HTTP {response.status_code} from {path}")
        try:
            return response.json()
        except ValueError as exc:
            raise ParseFailed(f"non-JSON response from {path}") from exc

    def _classic_base(self) -> str:
        legacy = self._is_legacy()
        return f"/api/s/{self.site}" if legacy else f"/proxy/network/api/s/{self.site}"

    def _is_legacy(self) -> bool:
        return urlparse(self.base_url).port == 8443 and not self.source.credentials.get("api_key")

    async def _legacy_login(self) -> None:
        if self._logged_in:
            return
        creds = self.source.credentials
        try:
            response = await self._client.post(
                "/api/login",
                json={"username": creds.get("username", ""), "password": creds.get("password", "")},
            )
        except httpx.HTTPError as exc:
            raise Unreachable(type(exc).__name__) from exc
        if response.status_code != 200:
            raise AuthFailed("the controller rejected the username or password")
        self._logged_in = True

    async def _detect_mode(self) -> None:
        if self._mode is not None:
            return
        if not self.source.credentials.get("api_key"):
            self._mode = "classic"
            return
        try:
            await self._get(f"{OFFICIAL_PREFIX}/info")
            sites = await self._get(f"{OFFICIAL_PREFIX}/sites")
            for site in sites.get("data", []):
                if site.get("internalReference") == self.site or self._site_id is None:
                    self._site_id = site.get("id")
            self._mode = "official"
        except FileNotFoundError:
            self._mode = "classic"  # Network 8.x or older: no official API

    async def _official_paged(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await self._get(path, {"offset": offset, "limit": 200})
            data = page.get("data", []) if isinstance(page, dict) else []
            items.extend(d for d in data if isinstance(d, dict))
            total = page.get("totalCount", len(items)) if isinstance(page, dict) else len(items)
            offset += len(data)
            if not data or offset >= total or offset > 5000:
                return items

    async def collect(self, now: datetime) -> Snapshot:
        await self._detect_mode()
        snap = self.new_snapshot(now)
        errors: dict[str, str] = {}
        devices: dict[str, Device] = {}
        ports: dict[tuple[str, str], Port] = {}
        mac_to_key: dict[str, str] = {}
        if self._mode == "official":
            base = f"{OFFICIAL_PREFIX}/sites/{self._site_id}"
            for summary in await self._official_paged(f"{base}/devices"):
                if "switching" not in (summary.get("features") or []):
                    continue
                detail = await self._get(f"{base}/devices/{summary['id']}")
                device, sw_ports = parse_official_switch(
                    detail, source_id=self.source.id, now=now, reliability=Reliability.RELIABLE
                )
                devices[device.key] = device
                if device.mac:
                    mac_to_key[device.mac] = device.key
                for p in sw_ports:
                    ports[(device.key, p.port_id)] = p
        # Classic data: everything on legacy controllers, the optional extras otherwise.
        classic: list[ClassicSwitch] = []
        try:
            if self._is_legacy():
                await self._legacy_login()
            classic = parse_classic_devices(await self._get(f"{self._classic_base()}/stat/device"))
            if time.monotonic() - self._last.get("sta", -1e9) >= 300:
                self._client_cache = parse_classic_clients(
                    await self._get(f"{self._classic_base()}/stat/sta")
                )
                self._last["sta"] = time.monotonic()
        except (ParseFailed, Unreachable, FileNotFoundError, AuthFailed) as exc:
            if self._mode == "classic":
                if isinstance(exc, FileNotFoundError):
                    raise ParseFailed(
                        "the controller did not answer the expected API paths"
                    ) from exc
                raise
            errors["classic"] = getattr(exc, "message", str(exc))
        fallback = mac_table_neighbours(self._client_cache) if classic else {}
        for sw in classic:
            key = mac_to_key.get(sw.mac) or device_key(mac=sw.mac, native_id=sw.mac)
            base_device = devices.get(key)
            if base_device is None:
                base_device = Device(
                    source_id=self.source.id,
                    observed_at=now,
                    reliability=Reliability.OPTIONAL,
                    key=key,
                    name=sw.name,
                    manufacturer="Ubiquiti",
                    model=sw.model,
                    category=DeviceCategory.SWITCH,
                    ip=sw.ip,
                    mac=sw.mac,
                    firmware=sw.firmware,
                    online=sw.online,
                )
            devices[key] = dataclasses.replace(
                base_device,
                serial=base_device.serial or sw.serial,
                uptime_s=base_device.uptime_s or sw.uptime_s,
                details={**base_device.details, "poe_budget_w": sw.poe_budget_w},
            )
            if sw.poe_budget_w is not None:
                snap.metrics.append(
                    self._metric(now, f"device:{key}", "poe_budget_w", sw.poe_budget_w, "W")
                )
            for pid, cp in sw.ports.items():
                n_mac, n_name = cp.neighbour_mac, cp.neighbour_name
                if not n_mac and (sw.mac, pid) in fallback:
                    n_mac, n_name = fallback[(sw.mac, pid)]
                if n_mac:
                    self._known_neighbours[(key, pid)] = (n_mac, n_name)
                existing = ports.get((key, pid))
                merged = Port(
                    source_id=self.source.id,
                    observed_at=now,
                    reliability=existing.reliability if existing else Reliability.OPTIONAL,
                    device_key=key,
                    port_id=pid,
                    name=cp.name or (existing.name if existing else None),
                    link_up=existing.link_up
                    if existing and existing.link_up is not None
                    else cp.link_up,
                    speed_mbps=(existing.speed_mbps if existing else None) or cp.speed_mbps,
                    poe_capable=cp.poe_capable or bool(existing and existing.poe_capable),
                    poe_enabled=existing.poe_enabled
                    if existing and existing.poe_enabled is not None
                    else cp.poe_enabled,
                    poe_power_w=cp.poe_power_w,
                    is_uplink=cp.is_uplink,
                    neighbour_mac=n_mac,
                    neighbour_name=n_name,
                    rx_bytes=cp.rx_bytes,
                    tx_bytes=cp.tx_bytes,
                    rx_errors=cp.rx_errors,
                    tx_errors=cp.tx_errors,
                )
                ports[(key, pid)] = merged
                if cp.poe_power_w is not None:
                    snap.metrics.append(
                        self._metric(now, f"port:{key}:{pid}", "poe_power_w", cp.poe_power_w, "W")
                    )
                if cp.rx_errors is not None:
                    snap.metrics.append(
                        self._metric(
                            now,
                            f"port:{key}:{pid}",
                            "errors",
                            float(cp.rx_errors + (cp.tx_errors or 0)),
                            "",
                        )
                    )
        if not classic:
            # Keep the last known attachments: cabling rarely changes, and it lets
            # diagnosis still link an AP to its port while the optional data is missing.
            for (key, pid), port in list(ports.items()):
                if not port.neighbour_mac and (key, pid) in self._known_neighbours:
                    mac, name = self._known_neighbours[(key, pid)]
                    ports[(key, pid)] = dataclasses.replace(
                        port, neighbour_mac=mac, neighbour_name=name
                    )
        snap.devices = list(devices.values())
        snap.ports = list(ports.values())
        snap.clients = [
            Client(
                source_id=self.source.id,
                observed_at=now,
                reliability=Reliability.OPTIONAL,
                mac=normalise_mac(c["mac"]) or c["mac"],
                ip=c.get("ip"),
                hostname=c.get("name") or c.get("hostname"),
                wired=c.get("is_wired"),
            )
            for c in self._client_cache
        ]
        snap.facts["unifi.mode"] = self._mode
        snap.facts["unifi.poe_data"] = bool(classic)
        if errors:
            snap.facts["optional_errors"] = errors
        snap.reliability = self.reliability
        return snap

    def _metric(self, now: datetime, subject: str, name: str, value: float, unit: str) -> Metric:
        return Metric(
            source_id=self.source.id,
            observed_at=now,
            reliability=Reliability.OPTIONAL,
            subject=subject,
            name=name,
            value=value,
            unit=unit,
        )


# -- SNMP --------------------------------------------------------------------------------
IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
IF_HIGH_SPEED = "1.3.6.1.2.1.31.1.1.1.15"
IF_HC_IN = "1.3.6.1.2.1.31.1.1.1.6"
IF_HC_OUT = "1.3.6.1.2.1.31.1.1.1.10"
IF_OPER = "1.3.6.1.2.1.2.2.1.8"
IF_IN_ERR = "1.3.6.1.2.1.2.2.1.14"
IF_OUT_ERR = "1.3.6.1.2.1.2.2.1.20"
SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
LLDP_REM_CHASSIS = "1.0.8802.1.1.2.1.4.1.1.5"
LLDP_REM_SYSNAME = "1.0.8802.1.1.2.1.4.1.1.9"
IF_MIB_ROOT = "1.3.6.1.2.1.2.2.1"
IFX_MIB_ROOT = "1.3.6.1.2.1.31.1.1.1"
LLDP_REM_ROOT = "1.0.8802.1.1.2.1.4.1.1"


def parse_switch_walk(
    system: dict[str, Any],
    walk: dict[str, Any],
    *,
    source_id: str,
    now: datetime,
    mac: str | None,
    host: str,
) -> tuple[Device, list[Port]]:
    key = device_key(mac=mac, source_id=source_id, native_id=host)
    device = Device(
        source_id=source_id,
        observed_at=now,
        reliability=Reliability.RELIABLE,
        key=key,
        name=system.get(SYS_NAME),
        manufacturer="Ubiquiti",
        model=str(system.get(SYS_DESCR) or "") or None,
        category=DeviceCategory.SWITCH,
        ip=host,
        mac=mac,
        online=OnlineState.ONLINE,
        uptime_s=(system[SYS_UPTIME] / 100.0) if isinstance(system.get(SYS_UPTIME), int) else None,
    )
    names = column(walk, IF_NAME)
    oper = column(walk, IF_OPER)
    speed = column(walk, IF_HIGH_SPEED)
    rx, tx = column(walk, IF_HC_IN), column(walk, IF_HC_OUT)
    rx_err, tx_err = column(walk, IF_IN_ERR), column(walk, IF_OUT_ERR)
    chassis, sysnames = column(walk, LLDP_REM_CHASSIS), column(walk, LLDP_REM_SYSNAME)
    neighbours: dict[str, tuple[str | None, str | None]] = {}
    for index, value in chassis.items():
        # lldpRemTable index: timeMark.localPortNum.remIndex
        parts = index.split(".")
        if len(parts) >= 2:
            neighbours[parts[1]] = (normalise_mac(str(value)), sysnames.get(index))
    ports: list[Port] = []
    for index, name in names.items():
        label = str(name)
        if not label.lower().startswith(("port", "eth", "ge", "0/")) and not label.isdigit():
            continue  # skip VLAN, loopback and CPU interfaces
        port_id = "".join(ch for ch in label if ch.isdigit()) or index
        n_mac, n_name = neighbours.get(port_id, (None, None))
        status = oper.get(index)
        ports.append(
            Port(
                source_id=source_id,
                observed_at=now,
                reliability=Reliability.RELIABLE,
                device_key=key,
                port_id=port_id,
                name=label,
                link_up=True if status == 1 else False if status == 2 else None,
                speed_mbps=float(speed[index]) if speed.get(index) else None,
                neighbour_mac=n_mac,
                neighbour_name=n_name,
                rx_bytes=rx.get(index),
                tx_bytes=tx.get(index),
                rx_errors=rx_err.get(index),
                tx_errors=tx_err.get(index),
            )
        )
    return device, ports


@register
class UnifiSnmpAdapter(Adapter):
    info = AdapterInfo(
        kind="unifi-snmp",
        label="UniFi switch (SNMP)",
        reliability=Reliability.RELIABLE,
        default_interval_s=60,
        address_label="Switch address",
        credentials=(CredentialField("community", "SNMP read-only community"),),
        options_help="Optionally set the switch MAC address so SNMP data merges with controller data.",
        setup_steps=(
            "Enable SNMP for the site in the UniFi Network app (Settings, System, SNMP).",
        ),
    )

    def __init__(self, source: Any, client: SnmpClient | None = None) -> None:
        super().__init__(source)
        self.host = source.address.split("://")[-1].split(":")[0]
        self._client = client or SnmpClient(
            SnmpTarget(host=self.host, community=str(source.credentials.get("community", "")))
        )

    async def collect(self, now: datetime) -> Snapshot:
        system = await self._client.get(SYS_NAME, SYS_DESCR, SYS_UPTIME)
        walk: dict[str, Any] = {}
        for root in (IF_MIB_ROOT, IFX_MIB_ROOT):
            walk.update(await self._client.walk(root))
        try:
            walk.update(await self._client.walk(LLDP_REM_ROOT))
        except Unreachable:
            pass  # LLDP-MIB is not supported on every model
        if not column(walk, IF_NAME):
            raise ParseFailed("the switch returned no interface table")
        device, ports = parse_switch_walk(
            system,
            walk,
            source_id=self.source.id,
            now=now,
            mac=self.source.options.get("mac"),
            host=self.host,
        )
        snap = self.new_snapshot(now)
        snap.devices.append(device)
        snap.ports.extend(ports)
        return snap

    async def close(self) -> None:
        self._client.close()
