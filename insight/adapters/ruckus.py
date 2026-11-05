"""Ruckus Unleashed adapters.

- `ruckus-snmp` (reliable): totals from the master AP over SNMP.
- `ruckus-web` (optional): per-AP, Wi-Fi network and client detail via the Unleashed web
  interface (aioruckus), restricted to a read-only allow-list, with secrets redacted.
- A syslog receiver turns Unleashed AP join, leave and reboot messages into events.

See docs/integrations/ruckus-unleashed.md.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from insight.adapters.snmp import SnmpClient, SnmpTarget
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
    AccessPoint,
    Client,
    Device,
    DeviceCategory,
    Event,
    Metric,
    OnlineState,
    Reliability,
    Snapshot,
    WifiNetwork,
    device_key,
    normalise_mac,
)
from insight.timeutil import utcnow

log = logging.getLogger(__name__)

SYS = "1.3.6.1.4.1.25053.1.15.1.1.1"
OID_NAME = f"{SYS}.1.1.0"
OID_IP = f"{SYS}.1.2.0"
OID_MAC = f"{SYS}.1.3.0"
OID_UPTIME = f"{SYS}.1.8.0"
OID_MODEL = f"{SYS}.1.9.0"
OID_SERIAL = f"{SYS}.1.15.0"
OID_FIRMWARE = f"{SYS}.1.18.0"
OID_NUM_AP = f"{SYS}.15.1.0"
OID_NUM_STA = f"{SYS}.15.2.0"
OID_NUM_REG_AP = f"{SYS}.15.15.0"
OID_ALL_STA = f"{SYS}.15.30.0"
SNMP_OIDS = (
    OID_NAME,
    OID_IP,
    OID_MAC,
    OID_UPTIME,
    OID_MODEL,
    OID_SERIAL,
    OID_FIRMWARE,
    OID_NUM_AP,
    OID_NUM_STA,
    OID_NUM_REG_AP,
    OID_ALL_STA,
)


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_snmp(values: dict[str, Any], *, source_id: str, now: datetime, host: str) -> Snapshot:
    if _int(values.get(OID_NUM_AP)) is None:
        raise ParseFailed(
            "the access point did not return Unleashed system statistics (is it the master?)"
        )
    mac = normalise_mac(values.get(OID_MAC))
    key = device_key(mac=mac, serial=values.get(OID_SERIAL), source_id=source_id, native_id=host)
    uptime = _int(values.get(OID_UPTIME))
    snap = Snapshot(source_id=source_id, collected_at=now, reliability=Reliability.RELIABLE)
    snap.devices.append(
        Device(
            source_id=source_id,
            observed_at=now,
            reliability=Reliability.RELIABLE,
            key=key,
            name=values.get(OID_NAME),
            manufacturer="Ruckus",
            model=str(values.get(OID_MODEL) or "").upper() or None,
            category=DeviceCategory.ACCESS_POINT,
            ip=values.get(OID_IP) or host,
            mac=mac,
            firmware=values.get(OID_FIRMWARE),
            serial=values.get(OID_SERIAL),
            online=OnlineState.ONLINE,
            uptime_s=uptime / 100.0 if uptime is not None else None,
            details={"unleashed_master": True},
        )
    )
    known = _int(values.get(OID_NUM_AP)) or 0
    registered = _int(values.get(OID_NUM_REG_AP))
    clients = _int(values.get(OID_ALL_STA))
    if clients is None:
        clients = _int(values.get(OID_NUM_STA))
    snap.facts["wifi.totals"] = {
        "ap_known": known,
        "ap_registered": registered if registered is not None else known,
        "clients": clients,
    }

    def metric(name: str, value: float) -> Metric:
        return Metric(
            source_id=source_id,
            observed_at=now,
            reliability=Reliability.RELIABLE,
            subject="wifi:ruckus",
            name=name,
            value=value,
        )

    snap.metrics.append(metric("ap_known", float(known)))
    if registered is not None:
        snap.metrics.append(metric("ap_registered", float(registered)))
    if clients is not None:
        snap.metrics.append(metric("clients", float(clients)))
    return snap


@register
class RuckusSnmpAdapter(Adapter):
    info = AdapterInfo(
        kind="ruckus-snmp",
        label="Ruckus Unleashed (SNMP)",
        reliability=Reliability.RELIABLE,
        default_interval_s=60,
        address_label="Unleashed management address",
        address_help="Use the Unleashed management IP: the master role can move between access points.",
        credentials=(CredentialField("community", "SNMP read-only community"),),
        setup_steps=(
            "In Unleashed, enable read-only SNMP (Admin & Services, System, Network Management).",
        ),
    )

    def __init__(self, source: Any, client: SnmpClient | None = None) -> None:
        super().__init__(source)
        self.host = source.address.split("://")[-1].split(":")[0]
        self._client = client or SnmpClient(
            SnmpTarget(host=self.host, community=str(source.credentials.get("community", "")))
        )

    async def collect(self, now: datetime) -> Snapshot:
        values = await self._client.get(*SNMP_OIDS)
        return parse_snmp(values, source_id=self.source.id, now=now, host=self.host)

    async def close(self) -> None:
        self._client.close()


# -- syslog --------------------------------------------------------------------------------
MAC_RE = r"(?P<ap_mac>(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2})"
AP_RE = r"AP\[(?P<ap_name>[^\]]*?)@" + MAC_RE + r"\]"
AP_JOINED = re.compile(
    r"eventd_to_syslog\(\):" + AP_RE + r" joins with uptime \[(?P<uptime_s>\d*)\] s"
    r"(?: and last disconnected reason \[(?P<reason>[^\]]*)\])?"
)
AP_DISCONNECTED = re.compile(r"eventd_to_syslog\(\):Lost contact with " + AP_RE)
AP_REBOOTED = re.compile(
    r"eventd_to_syslog\(\):"
    + AP_RE
    + r" (?P<boot>warm|cold) boot successfully,\s*last reboot reason \[(?P<reason>[^\]]*)\]"
)
PRI_RE = re.compile(r"^<\d{1,3}>")


@dataclass(frozen=True)
class SyslogMessage:
    kind: str  # ap_joined, ap_disconnected, ap_rebooted, raw_syslog
    text: str
    ap_mac: str | None = None
    ap_name: str | None = None
    reason: str | None = None


def parse_syslog_line(line: str) -> SyslogMessage:
    text = PRI_RE.sub("", line.strip())
    for kind, pattern in (
        ("ap_joined", AP_JOINED),
        ("ap_disconnected", AP_DISCONNECTED),
        ("ap_rebooted", AP_REBOOTED),
    ):
        match = pattern.search(text)
        if match:
            groups = match.groupdict()
            return SyslogMessage(
                kind=kind,
                text=text,
                ap_mac=normalise_mac(groups.get("ap_mac")),
                ap_name=groups.get("ap_name") or None,
                reason=groups.get("reason"),
            )
    return SyslogMessage(kind="raw_syslog", text=text)


SYSLOG_SOURCE_ID = "ruckus-syslog"

_MESSAGES = {
    "ap_joined": "{name} joined the Wi-Fi system",
    "ap_disconnected": "Unleashed lost contact with {name}",
    "ap_rebooted": "{name} restarted",
}


def syslog_event(message: SyslogMessage, sender: str, now: datetime | None = None) -> Event:
    now = now or utcnow()
    if message.kind == "raw_syslog" or message.ap_mac is None:
        return Event(
            source_id=SYSLOG_SOURCE_ID,
            observed_at=now,
            reliability=Reliability.RELIABLE,
            kind="raw_syslog",
            subject=f"syslog:{sender}",
            message=message.text[:500],
            data={"sender": sender},
        )
    key = device_key(mac=message.ap_mac)
    name = message.ap_name or message.ap_mac
    data: dict[str, Any] = {"sender": sender, "raw": message.text[:500]}
    if message.reason:
        data["reason"] = message.reason
    return Event(
        source_id=SYSLOG_SOURCE_ID,
        observed_at=now,
        reliability=Reliability.RELIABLE,
        kind=message.kind,
        subject=f"device:{key}",
        message=_MESSAGES[message.kind].format(name=name),
        devices=(key,),
        data=data,
    )


class SyslogReceiver(asyncio.DatagramProtocol):
    """UDP syslog listener. Every datagram becomes an event; nothing is ever sent back."""

    def __init__(
        self,
        on_event: Callable[[Event], None],
        allowed_senders: Callable[[], set[str]] | None = None,
    ) -> None:
        self.on_event = on_event
        self.allowed_senders = allowed_senders

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        sender = str(addr[0])
        if self.allowed_senders is not None:
            allowed = self.allowed_senders()
            if allowed and sender not in allowed:
                return
        for line in data.decode("utf-8", errors="replace").splitlines():
            if line.strip():
                self.on_event(syslog_event(parse_syslog_line(line), sender))


async def start_syslog(
    host: str,
    port: int,
    on_event: Callable[[Event], None],
    allowed_senders: Callable[[], set[str]] | None = None,
) -> asyncio.DatagramTransport:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: SyslogReceiver(on_event, allowed_senders), local_addr=(host, port)
    )
    return transport


# -- web interface (optional) ------------------------------------------------------------
READ_ONLY_METHODS = frozenset(
    {"get_system_info", "get_aps", "get_ap_stats", "get_active_clients", "get_wlans"}
)
_SECRET_KEYS = frozenset(
    {"wpa-passphrase", "passphrase", "psk", "dpsk", "x-passphrase", "password"}
)


class ReadOnlyApi:
    """Wraps the aioruckus API so only allow-listed read methods can be called."""

    def __init__(self, api: Any) -> None:
        self._api = api

    def __getattr__(self, name: str) -> Any:
        if name not in READ_ONLY_METHODS:
            raise PermissionError(f"{name} is not on Insight's read-only allow-list")
        return getattr(self._api, name)


def _strip_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_secrets(v) for k, v in value.items() if k.lower() not in _SECRET_KEYS}
    if isinstance(value, list):
        return [_strip_secrets(v) for v in value]
    return value


def _band(radio_type: str | None) -> str | None:
    if not radio_type:
        return None
    rt = radio_type.lower()
    if "11a" in rt and "11ac" not in rt:
        return "5GHz"
    if rt in ("11na", "11ac", "11ax-5g") or "5g" in rt:
        return "5GHz"
    if "6g" in rt:
        return "6GHz"
    if rt in ("11ng", "11g", "11b", "11n", "11ax-2.4g") or "2.4" in rt or "ng" in rt:
        return "2.4GHz"
    return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_aps(
    aps: list[dict[str, Any]], *, source_id: str, now: datetime
) -> tuple[list[Device], list[AccessPoint], list[Metric]]:
    rel = Reliability.OPTIONAL
    devices: list[Device] = []
    points: list[AccessPoint] = []
    metrics: list[Metric] = []
    for raw in _strip_secrets(aps):
        mac = normalise_mac(raw.get("mac"))
        if not mac:
            continue
        key = device_key(mac=mac)
        state = str(raw.get("state", "")).lower()
        online = (
            OnlineState.ONLINE
            if state.startswith("connected")
            else OnlineState.OFFLINE
            if state
            else OnlineState.UNKNOWN
        )
        devices.append(
            Device(
                source_id=source_id,
                observed_at=now,
                reliability=rel,
                key=key,
                name=raw.get("devname") or raw.get("name"),
                manufacturer="Ruckus",
                model=str(raw.get("model") or "").upper() or None,
                category=DeviceCategory.ACCESS_POINT,
                ip=raw.get("ip") or None,
                mac=mac,
                firmware=raw.get("firmware-version") or raw.get("version"),
                serial=raw.get("serial-number") or raw.get("serial"),
                online=online,
                uptime_s=_float(raw.get("uptime")),
                details={"description": raw.get("description")} if raw.get("description") else {},
            )
        )
        channels: dict[str, int] = {}
        util: dict[str, float] = {}
        for radio in raw.get("radio") or []:
            band = _band(radio.get("radio-type"))
            if band is None:
                continue
            if radio.get("channel") not in (None, ""):
                channels[band] = int(radio["channel"])
            busy = _float(radio.get("airtime-busy"))
            if busy is None:
                busy = _float(radio.get("airtime-total"))
            if busy is not None and online is OnlineState.ONLINE:
                util[band] = busy
                metrics.append(
                    Metric(
                        source_id=source_id,
                        observed_at=now,
                        reliability=rel,
                        subject=f"device:{key}",
                        name=f"channel_util_{band}",
                        value=busy,
                        unit="%",
                    )
                )
        clients = raw.get("num-sta")
        points.append(
            AccessPoint(
                source_id=source_id,
                observed_at=now,
                reliability=rel,
                device_key=key,
                name=raw.get("devname"),
                online=online,
                client_count=int(clients) if clients not in (None, "") else None,
                channels=channels,
                channel_utilisation_pct=util,
            )
        )
        if clients not in (None, ""):
            metrics.append(
                Metric(
                    source_id=source_id,
                    observed_at=now,
                    reliability=rel,
                    subject=f"device:{key}",
                    name="clients",
                    value=float(clients),
                )
            )
    return devices, points, metrics


def parse_wlans(wlans: list[dict[str, Any]], *, source_id: str, now: datetime) -> list[WifiNetwork]:
    return [
        WifiNetwork(
            source_id=source_id,
            observed_at=now,
            reliability=Reliability.OPTIONAL,
            network_id=str(raw.get("id") or raw.get("name")),
            ssid=str(raw.get("ssid") or raw.get("name")),
            enabled=str(raw.get("enable-type", "0")) == "0",
        )
        for raw in _strip_secrets(wlans)
        if raw.get("ssid") or raw.get("name")
    ]


def parse_clients(clients: list[dict[str, Any]], *, source_id: str, now: datetime) -> list[Client]:
    result: list[Client] = []
    for raw in _strip_secrets(clients):
        mac = normalise_mac(raw.get("mac"))
        if not mac:
            continue
        ap = normalise_mac(raw.get("ap"))
        result.append(
            Client(
                source_id=source_id,
                observed_at=now,
                reliability=Reliability.OPTIONAL,
                mac=mac,
                ip=raw.get("ip") or None,
                hostname=raw.get("hostname") or None,
                ap_key=device_key(mac=ap) if ap else None,
                ssid=raw.get("ssid") or raw.get("wlan"),
                band=_band(raw.get("radio-type")),
                signal_dbm=_float(raw.get("received-signal-strength")),
                wired=False,
            )
        )
    return result


SessionFactory = Callable[[Any], Any]


def _default_session(source: Any) -> Any:
    from aioruckus.ajaxsession import AjaxSession

    return AjaxSession.async_create(
        source.address.split("://")[-1].rstrip("/"),
        str(source.credentials.get("username", "")),
        str(source.credentials.get("password", "")),
        redact_secrets=True,
    )


@register
class RuckusWebAdapter(Adapter):
    info = AdapterInfo(
        kind="ruckus-web",
        label="Ruckus Unleashed (web interface, optional)",
        reliability=Reliability.OPTIONAL,
        default_interval_s=120,
        address_label="Unleashed management address",
        credentials=(
            CredentialField("username", "Unleashed username", secret=False),
            CredentialField("password", "Password"),
        ),
        setup_steps=(
            "This uses Unleashed's unofficial web interface. It can stop working after a firmware update;"
            " Insight then carries on with SNMP, syslog and its own checks.",
        ),
    )

    def __init__(self, source: Any, session_factory: SessionFactory | None = None) -> None:
        super().__init__(source)
        self._factory = session_factory or _default_session
        self._wlans: list[WifiNetwork] = []
        self._wlans_at = 0.0

    async def collect(self, now: datetime) -> Snapshot:
        import time

        try:
            session = self._factory(self.source)
            async with session as opened:
                api = ReadOnlyApi(opened.api)
                aps = await api.get_aps()
                stats = {normalise_mac(s.get("mac")): s for s in await api.get_ap_stats() or []}
                clients = await api.get_active_clients()
                if time.monotonic() - self._wlans_at >= 900 or not self._wlans:
                    self._wlans = parse_wlans(
                        list(await api.get_wlans()), source_id=self.source.id, now=now
                    )
                    self._wlans_at = time.monotonic()
        except (AuthFailed, ParseFailed, Unreachable):
            raise
        except Exception as exc:
            name = type(exc).__name__
            if "Authentication" in name or "Auth" in name:
                raise AuthFailed("Unleashed rejected the username or password") from exc
            if "Connection" in name or isinstance(exc, OSError | TimeoutError):
                raise Unreachable(f"could not reach Unleashed ({name})") from exc
            raise ParseFailed(f"unexpected data from the Unleashed web interface ({name})") from exc
        merged = []
        for ap in aps:
            mac = normalise_mac(ap.get("mac"))
            merged.append({**ap, **(stats.get(mac) or {})})
        devices, points, metrics = parse_aps(merged, source_id=self.source.id, now=now)
        snap = self.new_snapshot(now)
        snap.devices = devices
        snap.access_points = points
        snap.metrics = metrics
        snap.wifi_networks = [dataclasses.replace(w, observed_at=now) for w in self._wlans]
        snap.clients = parse_clients(list(clients), source_id=self.source.id, now=now)
        return snap
