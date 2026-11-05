"""Peplink router adapter (documented local Router API, read-only API client).

Documented endpoints are reliable. Undocumented endpoints (system info, WAN latency,
traffic) are optional: their failure never stops the documented data. Only endpoints on
the allow-list are ever requested, SIM and APN secrets are never copied out of
responses, and once the router rejects the credentials no further attempt is made
until an engineer updates them (the router locks out after repeated failures).
See docs/integrations/peplink.md.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

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
    LinkState,
    Metric,
    OnlineState,
    Reliability,
    Snapshot,
    WanLink,
    WanType,
    device_key,
)

log = logging.getLogger(__name__)

DOCUMENTED = frozenset(
    {
        "info.firmware",
        "status.wan.connection",
        "status.wan.connection.allowance",
        "status.client",
        "status.lan.profile",
    }
)
UNDOCUMENTED = frozenset({"status.system.info", "status.wan.latency", "status.traffic"})
ALLOWED = DOCUMENTED | UNDOCUMENTED

# How often each endpoint is read (seconds). The WAN status is read every cycle.
CADENCE: dict[str, float] = {
    "status.wan.connection": 0,
    "status.traffic": 30,
    "status.wan.latency": 60,
    "status.wan.connection.allowance": 300,
    "status.client": 300,
    "status.lan.profile": 300,
    "status.system.info": 3600,
    "info.firmware": 3600,
}

_TYPES = {
    "ethernet": WanType.ETHERNET,
    "cellular": WanType.CELLULAR,
    "gobi": WanType.CELLULAR,
    "wifi": WanType.WIFI,
}


class EndpointRefused(RuntimeError):
    pass


def wan_state(raw: dict[str, Any]) -> tuple[LinkState, bool | None]:
    """Map a WAN entry to (state, health check passing). The API has no state enum."""
    led = str(raw.get("statusLed", "")).lower()
    message = str(raw.get("message", "")).lower()
    if not raw.get("enable", True) or led in ("gray", "empty") or "disabled" in message:
        return LinkState.DISABLED, None
    if "standby" in message:
        return LinkState.STANDBY, None
    if led == "green":
        return LinkState.CONNECTED, True
    if led == "red":
        return LinkState.DISCONNECTED, False
    return LinkState.DISCONNECTED, None  # yellow/flash: connecting


def _ordered(resp: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    order = resp.get("order") or [k for k in resp if k != "order"]
    return [(str(i), resp[str(i)]) for i in order if isinstance(resp.get(str(i)), dict)]


def _cellular(raw: dict[str, Any]) -> tuple[dict[str, float], str | None, str | None]:
    """Signal, carrier and network type. Only these fields are read: SIM identifiers,
    IMEI and APN credentials in the same structure are never copied."""
    cell = raw.get("cellular")
    if not isinstance(cell, dict):
        return {}, None, None
    band: dict[str, Any] | None = None
    rat = cell.get("rat")
    if isinstance(rat, list) and rat and isinstance(rat[0], dict):
        bands = rat[0].get("band") or []
        band = bands[0] if bands else None
    elif isinstance(cell.get("band"), list) and cell["band"]:
        band = cell["band"][0]
    signal: dict[str, float] = {}
    if isinstance(band, dict) and isinstance(band.get("signal"), dict):
        for name in ("rsrp", "rsrq", "sinr", "rssi"):
            value = band["signal"].get(name)
            if isinstance(value, int | float):
                signal[name] = float(value)
    if isinstance(cell.get("signalLevel"), int | float):
        signal["level"] = float(cell["signalLevel"])
    carrier = cell.get("carrier", {}).get("name") if isinstance(cell.get("carrier"), dict) else None
    network = cell.get("dataTechnology") or cell.get("mobileType") or cell.get("network")
    return signal, carrier, network


def parse_wan_links(
    resp: dict[str, Any], *, source_id: str, now: datetime, router_key: str
) -> list[WanLink]:
    links: list[WanLink] = []
    for link_id, raw in _ordered(resp):
        state, health = wan_state(raw)
        signal, carrier, network = _cellular(raw)
        priority = raw.get("priority")
        links.append(
            WanLink(
                source_id=source_id,
                observed_at=now,
                reliability=Reliability.RELIABLE,
                link_id=link_id,
                name=str(raw.get("name") or f"WAN {link_id}"),
                device_key=router_key,
                wan_type=_TYPES.get(str(raw.get("virtualType") or raw.get("type")), WanType.OTHER),
                state=state,
                priority=int(priority) if isinstance(priority, int | float) else None,
                health_ok=health,
                signal=signal,
                carrier=carrier,
                network_type=network,
            )
        )
    return links


def derive_in_use(links: list[WanLink], traffic: dict[str, float] | None = None) -> set[str]:
    """Links carrying traffic: from live throughput when available, else the connected
    links at the best (lowest) priority."""
    connected = [link for link in links if link.state is LinkState.CONNECTED]
    if traffic:
        busy = {lid for lid, kbps in traffic.items() if kbps > 1.0}
        busy &= {link.link_id for link in connected}
        if busy:
            return busy
    with_priority = [link for link in connected if link.priority is not None]
    if not with_priority:
        return {link.link_id for link in connected}
    best = min(link.priority for link in with_priority if link.priority is not None)
    return {link.link_id for link in with_priority if link.priority == best}


def parse_allowance(resp: dict[str, Any]) -> dict[str, int]:
    """Usage in bytes per WAN, where the bandwidth allowance monitor is on."""
    usage: dict[str, int] = {}
    for link_id, raw in _ordered(resp):
        entries = (
            [raw]
            if "usage" in raw or ("enable" in raw and "order" not in raw)
            else [v for _, v in _ordered(raw)]
        )
        total = 0
        found = False
        for entry in entries:
            if entry.get("enable") and isinstance(entry.get("usage"), int | float):
                unit = str(entry.get("unit", "MB")).upper()
                scale = {"KB": 1_000, "MB": 1_000_000, "GB": 1_000_000_000}.get(unit, 1_000_000)
                total += int(entry["usage"] * scale)
                found = True
        if found:
            usage[link_id] = total
    return usage


def parse_latency(resp: dict[str, Any]) -> dict[str, float]:
    latest: dict[str, float] = {}
    for link_id, raw in _ordered(resp):
        data = (raw.get("latency") or {}).get("data")
        if isinstance(data, list):
            values = [v for v in data if isinstance(v, int | float)]
            if values:
                latest[link_id] = float(values[-1])
    return latest


def parse_traffic(resp: dict[str, Any]) -> dict[str, float]:
    bandwidth = resp.get("bandwidth") or {}
    result: dict[str, float] = {}
    for key, raw in bandwidth.items():
        if isinstance(raw, dict) and isinstance(raw.get("overall"), dict):
            overall = raw["overall"]
            result[str(key)] = float(overall.get("download", 0) or 0) + float(
                overall.get("upload", 0) or 0
            )
    return result


def parse_firmware(resp: dict[str, Any]) -> str | None:
    for _, raw in _ordered(resp):
        if raw.get("inUse"):
            return str(raw.get("version"))
    return None


def parse_clients(resp: dict[str, Any], *, source_id: str, now: datetime) -> list[Client]:
    clients: list[Client] = []
    for raw in resp.get("list", []):
        if not isinstance(raw, dict) or not raw.get("mac"):
            continue
        clients.append(
            Client(
                source_id=source_id,
                observed_at=now,
                reliability=Reliability.RELIABLE,
                mac=str(raw["mac"]).lower(),
                ip=raw.get("ip"),
                hostname=raw.get("name"),
                wired=(raw.get("connectionType") == "ethernet")
                if raw.get("connectionType")
                else None,
            )
        )
    return clients


def parse_lan_subnets(resp: dict[str, Any]) -> list[str]:
    import ipaddress

    subnets: list[str] = []
    for _, raw in _ordered(resp):
        try:
            net = ipaddress.ip_network(f"{raw['ip']}/{raw['mask']}", strict=False)
        except (KeyError, ValueError):
            continue
        subnets.append(str(net))
    return subnets


@register
class PeplinkAdapter(Adapter):
    info = AdapterInfo(
        kind="peplink",
        label="Peplink router",
        reliability=Reliability.RELIABLE,
        default_interval_s=15,
        address_label="Router address",
        address_help="The router's LAN address, for example https://192.168.50.1",
        credentials=(
            CredentialField("client_id", "API client ID", secret=False),
            CredentialField("client_secret", "API client secret"),
        ),
        setup_steps=(
            "On the router, create an API client with read-only scope (see docs/integrations/peplink.md).",
            "Enter the router's LAN address and the client ID and secret here.",
        ),
    )

    def __init__(self, source: Any, transport: httpx.AsyncBaseTransport | None = None) -> None:
        super().__init__(source)
        address = source.address if "://" in source.address else f"https://{source.address}"
        self.base_url = address.rstrip("/")
        self.host = urlparse(self.base_url).hostname
        verify = bool(source.options.get("verify_tls", False))
        self._client = httpx.AsyncClient(
            base_url=self.base_url, verify=verify, transport=transport, timeout=10
        )
        self._token: str | None = None
        self._token_expires = 0.0
        self._rejected_credentials: str | None = None
        self._last_fetch: dict[str, float] = {}
        self._cache: dict[str, dict[str, Any]] = {}

    def _credential_fingerprint(self) -> str:
        blob = json.dumps(self.source.credentials, sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()

    async def close(self) -> None:
        await self._client.aclose()

    # -- HTTP ------------------------------------------------------------------------
    async def _grant_token(self) -> None:
        if self._rejected_credentials == self._credential_fingerprint():
            raise AuthFailed("the router rejected these credentials; update them to try again")
        creds = self.source.credentials
        body = {
            "clientId": creds.get("client_id", ""),
            "clientSecret": creds.get("client_secret", ""),
            "scope": "api.read-only",
        }
        try:
            response = await self._client.post("/api/auth.token.grant", json=body)
            payload = self._json(response)
            if payload.get("stat") != "ok":
                # Some firmware only accepts form encoding for the grant.
                form = {k: v for k, v in body.items() if k != "scope"}
                response = await self._client.post("/api/auth.token.grant", data=form)
                payload = self._json(response)
        except httpx.HTTPError as exc:
            raise Unreachable(_safe_error(exc)) from exc
        if payload.get("stat") != "ok" or not payload.get("response", {}).get("accessToken"):
            self._rejected_credentials = self._credential_fingerprint()
            raise AuthFailed("the router rejected the API client ID or secret")
        token_info = payload["response"]
        self._token = str(token_info["accessToken"])
        expires_in = float(token_info.get("expiresIn", 3600))
        self._token_expires = time.monotonic() + max(60.0, expires_in - 3600)

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ParseFailed(
                f"the router returned non-JSON (HTTP {response.status_code})"
            ) from exc
        if not isinstance(payload, dict):
            raise ParseFailed("unexpected response shape")
        return payload

    async def _get(self, name: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        if name not in ALLOWED:
            raise EndpointRefused(f"endpoint {name} is not on Insight's read-only allow-list")
        for attempt in range(2):
            if self._token is None or time.monotonic() >= self._token_expires:
                await self._grant_token()
            query = {"accessToken": self._token or "", **(params or {})}
            try:
                response = await self._client.get(f"/api/{name}", params=query)
            except httpx.HTTPError as exc:
                raise Unreachable(_safe_error(exc)) from exc
            payload: dict[str, Any] = {"code": 401}
            if response.status_code not in (401, 403):
                payload = self._json(response)
            if payload.get("code") == 401 or response.status_code in (401, 403):
                self._token = None  # token expired or revoked: grant once more
                if attempt == 0:
                    continue
                raise AuthFailed("the router refused Insight's access token")
            if payload.get("stat") != "ok" or not isinstance(payload.get("response"), dict):
                raise ParseFailed(f"{name}: {payload.get('message', 'unexpected response')}")
            response_body: dict[str, Any] = payload["response"]
            return response_body
        raise AuthFailed("the router refused Insight's access token")

    async def _maybe(
        self, name: str, errors: dict[str, str], params: dict[str, str] | None = None
    ) -> dict[str, Any] | None:
        """Fetch an endpoint on its cadence, keeping the last good copy. Undocumented
        endpoints may fail without failing the collection."""
        due = time.monotonic() - self._last_fetch.get(name, -1e9) >= CADENCE.get(name, 0)
        if due:
            try:
                self._cache[name] = await self._get(name, params)
                self._last_fetch[name] = time.monotonic()
            except (ParseFailed, Unreachable) as exc:
                if name == "status.wan.connection":
                    raise
                errors[name] = exc.message
                if name in UNDOCUMENTED:
                    self._cache.pop(name, None)
        return self._cache.get(name)

    # -- collection --------------------------------------------------------------------
    async def collect(self, now: datetime) -> Snapshot:
        snap = self.new_snapshot(now)
        errors: dict[str, str] = {}
        wan = await self._maybe("status.wan.connection", errors)
        if wan is None:
            raise ParseFailed("no WAN status returned")
        system = await self._maybe("status.system.info", errors)
        firmware_resp = await self._maybe("info.firmware", errors)
        device_info = (system or {}).get("device", {}) if isinstance(system, dict) else {}
        serial = device_info.get("serialNumber") if isinstance(device_info, dict) else None
        router_key = device_key(serial=serial, source_id=self.source.id, native_id="router")
        firmware = (
            parse_firmware(firmware_resp) if firmware_resp else device_info.get("firmwareVersion")
        )
        uptime = (
            (system or {}).get("uptime", {}).get("second") if isinstance(system, dict) else None
        )
        snap.devices.append(
            Device(
                source_id=self.source.id,
                observed_at=now,
                reliability=Reliability.RELIABLE,
                key=router_key,
                name=device_info.get("name") or "Peplink router",
                manufacturer=device_info.get("company") or "Peplink",
                model=device_info.get("model"),
                category=DeviceCategory.ROUTER,
                ip=self.host,
                firmware=firmware,
                serial=serial,
                online=OnlineState.ONLINE,
                uptime_s=float(uptime) if isinstance(uptime, int | float) else None,
            )
        )
        links = parse_wan_links(wan, source_id=self.source.id, now=now, router_key=router_key)
        traffic_resp = await self._maybe("status.traffic", errors)
        traffic = parse_traffic(traffic_resp) if traffic_resp else None
        in_use = derive_in_use(links, traffic)
        latency_resp = await self._maybe("status.wan.latency", errors)
        latency = parse_latency(latency_resp) if latency_resp else {}
        allowance_resp = await self._maybe("status.wan.connection.allowance", errors)
        usage = parse_allowance(allowance_resp) if allowance_resp else {}
        final: list[WanLink] = []
        for link in links:
            lat = latency.get(link.link_id) if link.state is LinkState.CONNECTED else None
            updated = dataclasses.replace(
                link,
                in_use=link.link_id in in_use,
                latency_ms=lat,
                usage_bytes=usage.get(link.link_id),
            )
            final.append(updated)
            subject = f"wan:{self.source.id}:{link.link_id}"
            if lat is not None:
                snap.metrics.append(
                    self._metric(now, subject, "latency_ms", lat, "ms", Reliability.OPTIONAL)
                )
            for name, value in link.signal.items():
                snap.metrics.append(self._metric(now, subject, f"signal_{name}", value, "dB"))
            if link.link_id in usage:
                snap.metrics.append(
                    self._metric(now, subject, "usage_bytes", float(usage[link.link_id]), "B")
                )
            if traffic and link.link_id in traffic:
                snap.metrics.append(
                    self._metric(
                        now,
                        subject,
                        "throughput_kbps",
                        traffic[link.link_id],
                        "kbps",
                        Reliability.OPTIONAL,
                    )
                )
        snap.wan_links = final
        clients = await self._maybe("status.client", errors)
        if clients:
            snap.clients = parse_clients(clients, source_id=self.source.id, now=now)
        lan = await self._maybe("status.lan.profile", errors)
        if lan:
            snap.facts["lan_subnets"] = parse_lan_subnets(lan)
        if errors:
            snap.facts["optional_errors"] = errors
        return snap

    def _metric(
        self,
        now: datetime,
        subject: str,
        name: str,
        value: float,
        unit: str,
        rel: Reliability = Reliability.RELIABLE,
    ) -> Metric:
        return Metric(
            source_id=self.source.id,
            observed_at=now,
            reliability=rel,
            subject=subject,
            name=name,
            value=value,
            unit=unit,
        )


def _safe_error(exc: httpx.HTTPError) -> str:
    """Describe an HTTP error without the URL, which can carry the access token."""
    return type(exc).__name__.replace("Error", " error").strip() or "connection error"
