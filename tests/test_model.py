from __future__ import annotations

from datetime import datetime

import pytest

from insight.model import (
    AccessPoint,
    Client,
    Device,
    DeviceCategory,
    Event,
    Metric,
    Port,
    Reliability,
    Snapshot,
    WanLink,
    WifiNetwork,
    device_key,
    normalise_mac,
)
from insight.timeutil import utcnow

R = Reliability.RELIABLE


def common() -> dict[str, object]:
    return {"source_id": "s1", "observed_at": utcnow(), "reliability": R}


def test_each_type_constructs() -> None:
    key = device_key(mac="AA-BB-CC-DD-EE-FF")
    items = [
        Device(key=key, category=DeviceCategory.SWITCH, **common()),  # type: ignore[arg-type]
        Port(device_key=key, port_id="1", **common()),  # type: ignore[arg-type]
        WanLink(link_id="1", name="Starlink", device_key=key, **common()),  # type: ignore[arg-type]
        WifiNetwork(network_id="g", ssid="Guest", **common()),  # type: ignore[arg-type]
        AccessPoint(device_key=key, **common()),  # type: ignore[arg-type]
        Client(mac="aa:bb:cc:00:00:01", **common()),  # type: ignore[arg-type]
        Metric(subject="device:x", name="latency_ms", value=1.0, **common()),  # type: ignore[arg-type]
        Event(kind="port_down", subject="x", message="m", **common()),  # type: ignore[arg-type]
    ]
    assert all(item.source_id == "s1" for item in items)
    Snapshot(source_id="s1", collected_at=utcnow(), reliability=R)


def test_missing_timestamp_rejected() -> None:
    with pytest.raises(TypeError):
        Device(key="k", source_id="s1", reliability=R)  # type: ignore[call-arg]


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Device(key="k", source_id="s1", reliability=R, observed_at=datetime(2026, 1, 1))


def test_device_key_prefers_mac_then_serial() -> None:
    assert device_key(mac="AABBCCDDEEFF", serial="X1") == "mac:aa:bb:cc:dd:ee:ff"
    assert device_key(mac="not-a-mac", serial="x1") == "serial:X1"
    assert device_key(source_id="s", native_id="7") == "src:s:7"
    with pytest.raises(ValueError):
        device_key()


def test_normalise_mac() -> None:
    assert normalise_mac("00:1A:2b:3c:4d:5e") == "00:1a:2b:3c:4d:5e"
    assert normalise_mac("001a.2b3c.4d5e") == "00:1a:2b:3c:4d:5e"
    assert normalise_mac("bogus") is None
