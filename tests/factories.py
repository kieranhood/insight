"""Small builders for model objects used across tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from insight.model import (
    AccessPoint,
    Device,
    DeviceCategory,
    LinkState,
    OnlineState,
    Port,
    Reliability,
    Snapshot,
    WanLink,
    WanType,
    device_key,
)
from insight.timeutil import utcnow

R = Reliability.RELIABLE
O = Reliability.OPTIONAL  # noqa: E741


def snap(source: str, at: datetime | None = None, rel: Reliability = R, **items: Any) -> Snapshot:
    return Snapshot(source_id=source, collected_at=at or utcnow(), reliability=rel, **items)


def dev(
    source: str, mac: str, at: datetime | None = None, rel: Reliability = R, **kw: Any
) -> Device:
    kw.setdefault("category", DeviceCategory.OTHER)
    kw.setdefault("online", OnlineState.ONLINE)
    return Device(
        source_id=source,
        observed_at=at or utcnow(),
        reliability=rel,
        key=device_key(mac=mac),
        mac=mac,
        **kw,
    )


def port(source: str, switch_mac: str, port_id: str, at: datetime | None = None, **kw: Any) -> Port:
    return Port(
        source_id=source,
        observed_at=at or utcnow(),
        reliability=R,
        device_key=device_key(mac=switch_mac),
        port_id=port_id,
        **kw,
    )


def wan(source: str, link_id: str, name: str, at: datetime | None = None, **kw: Any) -> WanLink:
    kw.setdefault("state", LinkState.CONNECTED)
    kw.setdefault("wan_type", WanType.ETHERNET)
    return WanLink(
        source_id=source,
        observed_at=at or utcnow(),
        reliability=R,
        link_id=link_id,
        name=name,
        device_key=device_key(mac="00:1a:dd:00:00:01"),
        **kw,
    )


def ap(
    source: str, mac: str, at: datetime | None = None, rel: Reliability = O, **kw: Any
) -> AccessPoint:
    kw.setdefault("online", OnlineState.ONLINE)
    return AccessPoint(
        source_id=source,
        observed_at=at or utcnow(),
        reliability=rel,
        device_key=device_key(mac=mac),
        **kw,
    )
