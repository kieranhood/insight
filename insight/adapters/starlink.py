"""Starlink: link attribution (reliable, from the Peplink) and the dish's local status
interface (optional, unofficial gRPC).

The dish's single `Handle` RPC carries both reads and writes, so requests are built in
one place from a fixed read-only allow-list. Message types are resolved at runtime by
gRPC server reflection (by symbol), so Insight ships no copy of SpaceX's definitions.
See docs/integrations/starlink.md.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from insight.collection.adapter import Adapter, AdapterInfo, ParseFailed, Unreachable
from insight.collection.registry import register
from insight.model import (
    Device,
    DeviceCategory,
    Event,
    Metric,
    OnlineState,
    Reliability,
    Snapshot,
    WanLink,
)
from insight.state import StateStore

DEFAULT_DISH_ADDRESS = "192.168.100.1:9200"
SERVICE = "SpaceX.API.Device.Device"

# The only requests Insight ever sends to the dish.
READ_ONLY_REQUESTS = frozenset({"get_status", "get_history", "get_device_info"})


class RequestRefused(RuntimeError):
    pass


def check_request(kind: str) -> str:
    if kind not in READ_ONLY_REQUESTS:
        raise RequestRefused(f"dish request {kind!r} is not on Insight's read-only allow-list")
    return kind


# -- link attribution (reliable) ---------------------------------------------------------
def starlink_link(state: StateStore, marked: dict[str, str] | None) -> WanLink | None:
    """The WAN link the engineer marked as Starlink. Until one is marked, a link named
    "Starlink" is used as a best guess."""
    links = state.wan_links()
    if marked:
        for link in links:
            if link.source_id == marked.get("source_id") and link.link_id == marked.get("link_id"):
                return link
        return None
    return next((link for link in links if "starlink" in link.name.lower()), None)


# -- status parsing ----------------------------------------------------------------------
def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_status(response: dict[str, Any]) -> dict[str, Any]:
    """Map a `dish_get_status` response (protobuf JSON) to Insight's dish facts."""
    status = response.get("dishGetStatus")
    if not isinstance(status, dict):
        raise ParseFailed("the dish answered, but without dish_get_status")
    info = status.get("deviceInfo") or {}
    obstruction = status.get("obstructionStats") or {}
    outage = status.get("outage") if isinstance(status.get("outage"), dict) else None
    alerts = sorted(_snake(k) for k, v in (status.get("alerts") or {}).items() if v is True)
    uptime = _f((status.get("deviceState") or {}).get("uptimeS"))
    return {
        "id": info.get("id"),
        "hardware_version": info.get("hardwareVersion"),
        "software_version": info.get("softwareVersion"),
        "uptime_s": uptime,
        "online": outage is None,
        "current_outage_cause": outage.get("cause") if outage else None,
        "obstruction_fraction": _f(obstruction.get("fractionObstructed")) or 0.0,
        "currently_obstructed": bool(obstruction.get("currentlyObstructed")),
        "latency_ms": _f(status.get("popPingLatencyMs")),
        "drop_rate": _f(status.get("popPingDropRate")) or 0.0,
        "downlink_bps": _f(status.get("downlinkThroughputBps")),
        "uplink_bps": _f(status.get("uplinkThroughputBps")),
        "alerts": alerts,
        "stowed": bool(status.get("stowRequested")),
        "software_update_state": status.get("softwareUpdateState"),
    }


def parse_history_outages(response: dict[str, Any]) -> list[dict[str, Any]]:
    history = response.get("dishGetHistory")
    if not isinstance(history, dict):
        raise ParseFailed("the dish answered, but without dish_get_history")
    outages: list[dict[str, Any]] = []
    for raw in history.get("outages") or []:
        start_ns, duration_ns = _f(raw.get("startTimestampNs")), _f(raw.get("durationNs"))
        outages.append(
            {
                "cause": raw.get("cause", "UNKNOWN"),
                "start_ns": start_ns,
                "duration_s": duration_ns / 1e9 if duration_ns is not None else None,
                "switched": bool(raw.get("didSwitch")),
            }
        )
    return outages


# -- gRPC transport ------------------------------------------------------------------------
DishCall = Callable[[str], Awaitable[dict[str, Any]]]


class ReflectionClient:
    """Calls the dish with message types resolved by server reflection."""

    def __init__(self, address: str, timeout: float = 5.0) -> None:
        self.address = address
        self.timeout = timeout
        self._channel: Any = None
        self._request_cls: Any = None
        self._response_cls: Any = None

    async def _resolve(self) -> None:
        if self._request_cls is not None:
            return
        import grpc
        from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
        from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc

        self._channel = grpc.aio.insecure_channel(self.address)
        stub = reflection_pb2_grpc.ServerReflectionStub(self._channel)
        pool = descriptor_pool.DescriptorPool()
        seen: set[str] = set()

        async def files_for(symbol: str | None = None, filename: str | None = None) -> None:
            # The request fields are a oneof: set exactly one.
            if symbol:
                request = reflection_pb2.ServerReflectionRequest(file_containing_symbol=symbol)
            else:
                request = reflection_pb2.ServerReflectionRequest(file_by_filename=filename or "")
            async for reply in stub.ServerReflectionInfo(iter([request]), timeout=self.timeout):
                for blob in reply.file_descriptor_response.file_descriptor_proto:
                    proto = descriptor_pb2.FileDescriptorProto.FromString(blob)
                    if proto.name in seen:
                        continue
                    seen.add(proto.name)
                    for dep in proto.dependency:
                        if dep not in seen:
                            await files_for(filename=dep)
                    try:
                        pool.Add(proto)
                    except TypeError:
                        pass  # already present

        try:
            await files_for(symbol=SERVICE)
            service = pool.FindServiceByName(SERVICE)
            method = service.FindMethodByName("Handle")
        except Exception as exc:
            raise ParseFailed(
                f"the dish did not describe its status interface ({type(exc).__name__})"
            ) from exc
        self._request_cls = message_factory.GetMessageClass(method.input_type)
        self._response_cls = message_factory.GetMessageClass(method.output_type)

    async def __call__(self, kind: str) -> dict[str, Any]:
        check_request(kind)
        import grpc
        from google.protobuf.json_format import MessageToDict

        try:
            await self._resolve()
            request = self._request_cls()
            getattr(request, kind).SetInParent()  # an empty read request, e.g. get_status {}
            call = self._channel.unary_unary(
                f"/{SERVICE}/Handle",
                request_serializer=lambda m: m.SerializeToString(),
                response_deserializer=self._response_cls.FromString,
            )
            response = await call(request, timeout=self.timeout)
        except grpc.aio.AioRpcError as exc:
            raise Unreachable(f"dish gRPC error {exc.code().name}") from exc
        except OSError as exc:
            raise Unreachable(f"could not reach the dish ({exc})") from exc
        result: dict[str, Any] = MessageToDict(response)
        return result

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close()


@register
class StarlinkDishAdapter(Adapter):
    info = AdapterInfo(
        kind="starlink",
        label="Starlink dish (optional)",
        reliability=Reliability.OPTIONAL,
        default_interval_s=30,
        address_label="Dish address",
        address_help=(
            "Usually 192.168.100.1:9200. If the Peplink proxies the dish, use the Peplink's LAN "
            "address and port 9200 plus the WAN number."
        ),
        setup_steps=(
            "On the Peplink, pair the WAN with Starlink and add an enforced outbound policy rule sending "
            "192.168.100.1 to the Starlink WAN, or enable the Peplink's dish proxy.",
            "This uses the dish's unofficial status interface. It can change after a dish update; Insight "
            "then carries on with the Peplink's view and its own checks.",
        ),
    )

    HISTORY_INTERVAL_S = 300.0

    def __init__(self, source: Any, call: DishCall | None = None) -> None:
        super().__init__(source)
        address = (source.address or DEFAULT_DISH_ADDRESS).split("://")[-1]
        if ":" not in address:
            address = f"{address}:9200"
        self.address = address
        self._client = None if call is not None else ReflectionClient(address)
        self._call: DishCall = call or self._client  # type: ignore[assignment]
        self._history_at = -1e9
        self._outages: list[dict[str, Any]] = []
        self._alerts: set[str] = set()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()

    async def collect(self, now: datetime) -> Snapshot:
        facts = parse_status(await self._call(check_request("get_status")))
        if time.monotonic() - self._history_at >= self.HISTORY_INTERVAL_S:
            try:
                self._outages = parse_history_outages(
                    await self._call(check_request("get_history"))
                )
                self._history_at = time.monotonic()
            except (ParseFailed, Unreachable):
                pass  # history is a bonus on top of status
        facts["outages"] = list(self._outages)
        snap = self.new_snapshot(now)
        rel = Reliability.OPTIONAL
        dish_id = facts.get("id") or "dish"
        key = f"serial:{str(dish_id).upper()}"
        snap.devices.append(
            Device(
                source_id=self.source.id,
                observed_at=now,
                reliability=rel,
                key=key,
                name="Starlink dish",
                manufacturer="SpaceX",
                model=facts.get("hardware_version"),
                category=DeviceCategory.SATELLITE_TERMINAL,
                ip=self.address.split(":")[0],
                firmware=facts.get("software_version"),
                serial=str(dish_id) if facts.get("id") else None,
                online=OnlineState.ONLINE if facts["online"] else OnlineState.OFFLINE,
                uptime_s=facts.get("uptime_s"),
            )
        )
        snap.facts["dish"] = facts
        subject = f"dish:{self.source.id}"

        def metric(name: str, value: float | None, unit: str = "") -> None:
            if value is not None:
                snap.metrics.append(
                    Metric(
                        source_id=self.source.id,
                        observed_at=now,
                        reliability=rel,
                        subject=subject,
                        name=name,
                        value=value,
                        unit=unit,
                    )
                )

        metric("obstruction_fraction", facts["obstruction_fraction"])
        metric("latency_ms", facts["latency_ms"], "ms")
        metric("drop_rate", facts["drop_rate"])
        metric("downlink_bps", facts["downlink_bps"], "bps")
        current = set(facts["alerts"])
        for alert in sorted(current - self._alerts):
            # The dish gives no alert time, so the time is when Insight first saw it.
            snap.events.append(
                Event(
                    source_id=self.source.id,
                    observed_at=now,
                    reliability=rel,
                    kind="dish_alert",
                    subject=f"device:{key}",
                    message=f"Starlink dish reported alert: {alert.replace('_', ' ')}",
                    devices=(key,),
                    data={"alert": alert},
                )
            )
        self._alerts = current
        return snap
