"""The current-state store.

Holds the latest snapshot from each source and how fresh it is, merges devices that
several sources report, and compares successive snapshots to emit events.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from insight.model import (
    AccessPoint,
    Client,
    Device,
    DeviceCategory,
    Event,
    Metric,
    OnlineState,
    Port,
    Reliability,
    Snapshot,
    WanLink,
    WifiNetwork,
)
from insight.timeutil import utcnow


class SourceState(StrEnum):
    NEVER = "never"  # configured but never collected
    OK = "ok"
    FAILED = "failed"


class FailureKind(StrEnum):
    UNREACHABLE = "unreachable"
    AUTH = "authentication"
    PARSE = "unparseable"
    TIMEOUT = "timeout"


@dataclass
class SourceStatus:
    source_id: str
    name: str
    kind: str
    reliability: Reliability
    interval_s: float
    state: SourceState = SourceState.NEVER
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    failure_kind: FailureKind | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    failing_since: datetime | None = None


@dataclass
class MergedDevice:
    """A device as seen across all sources that report it."""

    key: str
    source_ids: list[str]
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
    observed_at: datetime | None = None
    fresh: bool = False
    details: dict[str, Any] = field(default_factory=dict)


_MERGE_FIELDS = ("name", "manufacturer", "model", "ip", "mac", "firmware", "serial", "uptime_s")


class StateStore:
    def __init__(self, stale_factor: float = 3.0) -> None:
        self.stale_factor = stale_factor
        self.sources: dict[str, SourceStatus] = {}
        self.snapshots: dict[str, Snapshot] = {}

    # -- source lifecycle ---------------------------------------------------------
    def configure_source(
        self,
        source_id: str,
        *,
        name: str,
        kind: str,
        reliability: Reliability,
        interval_s: float,
    ) -> SourceStatus:
        status = self.sources.get(source_id)
        if status is None:
            status = SourceStatus(source_id, name, kind, reliability, interval_s)
            self.sources[source_id] = status
        else:
            status.name, status.kind = name, kind
            status.reliability, status.interval_s = reliability, interval_s
        return status

    def remove_source(self, source_id: str) -> None:
        self.sources.pop(source_id, None)
        self.snapshots.pop(source_id, None)

    def is_fresh(self, source_id: str, now: datetime | None = None) -> bool:
        status = self.sources.get(source_id)
        if status is None or status.state is not SourceState.OK or status.last_success_at is None:
            return False
        now = now or utcnow()
        return now - status.last_success_at <= timedelta(
            seconds=status.interval_s * self.stale_factor
        )

    def apply(self, snapshot: Snapshot) -> list[Event]:
        """Record a successful collection and return the events it implies."""
        status = self.sources.get(snapshot.source_id)
        if status is None:
            raise KeyError(f"unknown source {snapshot.source_id}")
        events: list[Event] = []
        if status.state is SourceState.FAILED:
            events.append(
                self._source_event(
                    status,
                    snapshot.collected_at,
                    "monitoring_recovered",
                    f"Monitoring of {status.name} recovered",
                    {"was_failing_since": status.failing_since},
                )
            )
        previous = self.snapshots.get(snapshot.source_id)
        if previous is not None:
            events.extend(diff_snapshots(previous, snapshot))
        self.snapshots[snapshot.source_id] = snapshot
        events.extend(snapshot.events)
        status.state = SourceState.OK
        status.last_success_at = snapshot.collected_at
        status.last_attempt_at = snapshot.collected_at
        status.failure_kind = None
        status.failing_since = None
        return events

    def record_failure(
        self, source_id: str, kind: FailureKind, message: str, at: datetime | None = None
    ) -> list[Event]:
        """Record a failed collection. Emits an event only when the source starts failing."""
        status = self.sources[source_id]
        at = at or utcnow()
        events: list[Event] = []
        changed = status.state is not SourceState.FAILED or status.failure_kind is not kind
        if status.state is not SourceState.FAILED:
            status.failing_since = at
        status.state = SourceState.FAILED
        status.failure_kind = kind
        status.last_error = message
        status.last_error_at = at
        status.last_attempt_at = at
        if changed:
            events.append(
                self._source_event(
                    status,
                    at,
                    "monitoring_failure",
                    f"Insight cannot collect from {status.name} ({kind.value}): {message}",
                    {"failure_kind": kind.value},
                )
            )
        return events

    @staticmethod
    def _source_event(
        status: SourceStatus, at: datetime, kind: str, message: str, data: dict[str, Any]
    ) -> Event:
        return Event(
            source_id=status.source_id,
            observed_at=at,
            reliability=status.reliability,
            kind=kind,
            subject=f"source:{status.source_id}",
            message=message,
            data=data,
        )

    # -- merged views ----------------------------------------------------------------
    def _ordered_snapshots(self) -> list[Snapshot]:
        # Reliable sources win merges over optional ones; fresher wins within a class.
        return sorted(
            self.snapshots.values(),
            key=lambda s: (s.reliability is not Reliability.RELIABLE, -s.collected_at.timestamp()),
        )

    def devices(self, now: datetime | None = None) -> dict[str, MergedDevice]:
        now = now or utcnow()
        merged: dict[str, MergedDevice] = {}
        for snap in self._ordered_snapshots():
            fresh = self.is_fresh(snap.source_id, now)
            for dev in snap.devices:
                target = merged.get(dev.key)
                if target is None:
                    target = MergedDevice(key=dev.key, source_ids=[], category=dev.category)
                    merged[dev.key] = target
                _merge_into(target, dev, fresh)
        return merged

    def device(self, key: str) -> MergedDevice | None:
        return self.devices().get(key)

    def _collect(self, attr: str, *, fresh_only: bool = False) -> list[Any]:
        items: list[Any] = []
        for snap in self._ordered_snapshots():
            if fresh_only and not self.is_fresh(snap.source_id):
                continue
            items.extend(getattr(snap, attr))
        return items

    def ports(self, device_key: str | None = None) -> list[Port]:
        ports: list[Port] = self._collect("ports")
        return [p for p in ports if device_key is None or p.device_key == device_key]

    def wan_links(self) -> list[WanLink]:
        links: list[WanLink] = self._collect("wan_links")
        return links

    def access_points(self) -> dict[str, AccessPoint]:
        aps: dict[str, AccessPoint] = {}
        for ap in self._collect("access_points"):
            aps.setdefault(ap.device_key, ap)
        return aps

    def wifi_networks(self) -> list[WifiNetwork]:
        nets: list[WifiNetwork] = self._collect("wifi_networks")
        return nets

    def clients(self) -> list[Client]:
        clients: list[Client] = self._collect("clients")
        return clients

    def latest_metrics(self) -> dict[tuple[str, str], Metric]:
        latest: dict[tuple[str, str], Metric] = {}
        for metric in self._collect("metrics"):
            key = (metric.subject, metric.name)
            current = latest.get(key)
            if current is None or metric.observed_at > current.observed_at:
                latest[key] = metric
        return latest

    def facts(self, source_id: str) -> dict[str, Any]:
        snap = self.snapshots.get(source_id)
        return dict(snap.facts) if snap else {}

    def sources_of_kind(self, *kinds: str) -> list[SourceStatus]:
        return [s for s in self.sources.values() if s.kind in kinds]


def _merge_into(target: MergedDevice, dev: Device, fresh: bool) -> None:
    if dev.source_id not in target.source_ids:
        target.source_ids.append(dev.source_id)
    for name in _MERGE_FIELDS:
        if getattr(target, name) is None and getattr(dev, name) is not None:
            setattr(target, name, getattr(dev, name))
    if target.category is DeviceCategory.OTHER:
        target.category = dev.category
    # Online state comes from the first fresh source that knows it.
    if dev.online is not OnlineState.UNKNOWN and fresh and not target.fresh:
        target.online = dev.online
    if fresh:
        target.fresh = True
    if target.observed_at is None or dev.observed_at > target.observed_at:
        target.observed_at = dev.observed_at
    for k, v in dev.details.items():
        target.details.setdefault(k, v)


def diff_snapshots(old: Snapshot, new: Snapshot) -> list[Event]:
    """Events implied by the change between two snapshots from the same source."""
    events: list[Event] = []
    at, src, rel = new.collected_at, new.source_id, new.reliability

    def event(kind: str, subject: str, message: str, devices: tuple[str, ...], **data: Any) -> None:
        events.append(
            Event(
                source_id=src,
                observed_at=at,
                reliability=rel,
                kind=kind,
                subject=subject,
                message=message,
                devices=devices,
                data=data,
            )
        )

    old_devices = {d.key: d for d in old.devices}
    for dev in new.devices:
        before = old_devices.get(dev.key)
        if before is None or before.online == dev.online:
            continue
        label = dev.name or dev.key
        if dev.online is OnlineState.OFFLINE:
            event("device_offline", f"device:{dev.key}", f"{label} went offline", (dev.key,))
        elif dev.online is OnlineState.ONLINE and before.online is OnlineState.OFFLINE:
            event("device_online", f"device:{dev.key}", f"{label} came back online", (dev.key,))

    old_ports = {(p.device_key, p.port_id): p for p in old.ports}
    for port in new.ports:
        before_port = old_ports.get((port.device_key, port.port_id))
        if before_port is None:
            continue
        subject = f"port:{port.device_key}:{port.port_id}"
        label = port.name or f"port {port.port_id}"
        devs = (port.device_key,) + ((f"mac:{port.neighbour_mac}",) if port.neighbour_mac else ())
        if before_port.link_up is True and port.link_up is False:
            event("port_down", subject, f"{label} lost link", devs, port=port.port_id)
        elif before_port.link_up is False and port.link_up is True:
            event("port_up", subject, f"{label} link restored", devs, port=port.port_id)
        was, now_w = before_port.poe_power_w, port.poe_power_w
        if was is not None and now_w is not None:
            if was > 0 and now_w == 0:
                event(
                    "poe_lost",
                    subject,
                    f"{label} stopped supplying PoE power ({was:.1f} W -> 0 W)",
                    devs,
                    port=port.port_id,
                    before_w=was,
                )
            elif was == 0 and now_w > 0:
                event(
                    "poe_restored",
                    subject,
                    f"{label} PoE power restored ({now_w:.1f} W)",
                    devs,
                    port=port.port_id,
                )

    old_links = {link.link_id: link for link in old.wan_links}
    for link in new.wan_links:
        before_link = old_links.get(link.link_id)
        if before_link is not None and before_link.state != link.state:
            event(
                "wan_state_change",
                f"wan:{src}:{link.link_id}",
                f"{link.name} changed from {before_link.state.value} to {link.state.value}",
                (link.device_key,),
                link=link.name,
                before=before_link.state.value,
                after=link.state.value,
            )
    old_in_use = sorted(link.name for link in old.wan_links if link.in_use)
    new_in_use = sorted(link.name for link in new.wan_links if link.in_use)
    if old.wan_links and new.wan_links and old_in_use != new_in_use:
        before_txt = ", ".join(old_in_use) or "no link"
        after_txt = ", ".join(new_in_use) or "no link"
        device_keys = tuple(sorted({link.device_key for link in new.wan_links}))
        event(
            "failover",
            f"wan:{src}",
            f"Internet traffic moved from {before_txt} to {after_txt}",
            device_keys,
            previous=old_in_use,
            current=new_in_use,
        )

    old_aps = {ap.device_key: ap for ap in old.access_points}
    for ap in new.access_points:
        before_ap = old_aps.get(ap.device_key)
        if before_ap is None or before_ap.online == ap.online:
            continue
        label = ap.name or ap.device_key
        if ap.online is OnlineState.OFFLINE:
            event(
                "ap_offline", f"device:{ap.device_key}", f"{label} disconnected", (ap.device_key,)
            )
        elif ap.online is OnlineState.ONLINE and before_ap.online is OnlineState.OFFLINE:
            event("ap_online", f"device:{ap.device_key}", f"{label} reconnected", (ap.device_key,))
    return events


def replace_observed(item: Any, **changes: Any) -> Any:
    """Small helper for tests and the simulator: copy a frozen model object with changes."""
    return dataclasses.replace(item, **changes)
