"""The equipment inventory: devices from sources, manual devices, tags and services."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from insight.model import Device, DeviceCategory, Event, Reliability, Snapshot, device_key
from insight.state import StateStore
from insight.storage.db import Database
from insight.storage.writer import Writer
from insight.timeutil import from_iso, to_iso, utcnow


class Service(StrEnum):
    INTERNET = "internet"
    GUEST_WIFI = "guest_wifi"
    CREW_WIFI = "crew_wifi"

    @property
    def label(self) -> str:
        return {"internet": "Internet", "guest_wifi": "Guest Wi-Fi", "crew_wifi": "Crew Wi-Fi"}[
            self.value
        ]


@dataclass
class InventoryDevice:
    key: str
    name: str | None
    display_name: str | None
    manufacturer: str | None
    model: str | None
    category: DeviceCategory
    ip: str | None
    mac: str | None
    firmware: str | None
    serial: str | None
    source_ids: list[str]
    location: str | None
    manual: bool
    reported: bool
    first_seen_at: datetime
    last_seen_at: datetime
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """The everyday name: the engineer's display name, else the source's name, else the address."""
        return self.display_name or self.name or self.ip or self.mac or self.key

    @property
    def monitoring_status(self) -> str:
        if self.manual:
            return "probes only"
        return "reported" if self.reported else "no longer reported by its source"


_DETAIL_FIELDS = ("name", "manufacturer", "model", "category", "ip", "mac", "firmware", "serial")


def _row_to_device(row: sqlite3.Row) -> InventoryDevice:
    return InventoryDevice(
        key=row["key"],
        name=row["name"],
        display_name=row["display_name"],
        manufacturer=row["manufacturer"],
        model=row["model"],
        category=DeviceCategory(row["category"]),
        ip=row["ip"],
        mac=row["mac"],
        firmware=row["firmware"],
        serial=row["serial"],
        source_ids=json.loads(row["source_ids"]),
        location=row["location"],
        manual=bool(row["manual"]),
        reported=bool(row["reported"]),
        first_seen_at=from_iso(row["first_seen_at"]) or utcnow(),
        last_seen_at=from_iso(row["last_seen_at"]) or utcnow(),
        details=json.loads(row["details"]),
    )


class Inventory:
    def __init__(self, db: Database, writer: Writer) -> None:
        self.db = db
        self.writer = writer
        self._cache: dict[str, InventoryDevice] | None = None

    # -- reads -------------------------------------------------------------------
    def devices(self) -> dict[str, InventoryDevice]:
        if self._cache is None:
            with self.db.read() as conn:
                rows = conn.execute("SELECT * FROM devices").fetchall()
            self._cache = {r["key"]: _row_to_device(r) for r in rows}
        return dict(self._cache)

    def get(self, key: str) -> InventoryDevice | None:
        return self.devices().get(key)

    def find_by_ip(self, ip: str) -> InventoryDevice | None:
        return next((d for d in self.devices().values() if d.ip == ip), None)

    def find_by_mac(self, mac: str) -> InventoryDevice | None:
        key = device_key(mac=mac, native_id="-")
        return self.devices().get(key)

    def probe_targets(self) -> dict[str, str]:
        """Every inventory device with an IP address, for reachability checks: key -> IP."""
        return {d.key: d.ip for d in self.devices().values() if d.ip}

    def _invalidate(self) -> None:
        self._cache = None

    # -- population from sources ---------------------------------------------------
    def sync(self, snapshot: Snapshot) -> list[Event]:
        """Bring the inventory in line with one successful snapshot. Returns inventory events."""
        reported = {d.key: d for d in snapshot.devices}
        # Neighbours seen on switch ports are equipment too, even when no source reports them.
        for port in snapshot.ports:
            if port.neighbour_mac:
                key = device_key(mac=port.neighbour_mac, native_id=port.neighbour_mac)
                if key not in reported:
                    reported[key] = Device(
                        source_id=snapshot.source_id,
                        observed_at=port.observed_at,
                        reliability=port.reliability,
                        key=key,
                        name=port.neighbour_name,
                        mac=port.neighbour_mac,
                        details={"seen_as": "switch port neighbour"},
                    )
        current = self.devices()
        now = snapshot.collected_at
        events: list[Event] = []
        upserts: list[tuple[InventoryDevice, bool]] = []
        for key, dev in reported.items():
            existing = current.get(key)
            if existing is None:
                item = InventoryDevice(
                    key=key,
                    name=dev.name,
                    display_name=None,
                    manufacturer=dev.manufacturer,
                    model=dev.model,
                    category=dev.category,
                    ip=dev.ip,
                    mac=dev.mac,
                    firmware=dev.firmware,
                    serial=dev.serial,
                    source_ids=[snapshot.source_id],
                    location=None,
                    manual=False,
                    reported=True,
                    first_seen_at=now,
                    last_seen_at=now,
                    details=dict(dev.details),
                )
                upserts.append((item, True))
                events.append(
                    self._event(
                        snapshot, "device_added", item, f"{item.label} added to the inventory"
                    )
                )
                continue
            changed = False
            # Reliable sources win; optional sources only fill gaps.
            authoritative = snapshot.reliability is Reliability.RELIABLE or existing.source_ids == [
                snapshot.source_id
            ]
            for name in _DETAIL_FIELDS:
                new = getattr(dev, name)
                if new in (None, DeviceCategory.OTHER):
                    continue
                old = getattr(existing, name)
                if old != new and (authoritative or old in (None, DeviceCategory.OTHER)):
                    setattr(existing, name, new)
                    changed = True
            if snapshot.source_id not in existing.source_ids:
                existing.source_ids.append(snapshot.source_id)
                changed = True
            if not existing.reported and not existing.manual:
                existing.reported = True
                changed = True
                events.append(
                    self._event(
                        snapshot,
                        "device_reported_again",
                        existing,
                        f"{existing.label} is reported again",
                    )
                )
            existing.last_seen_at = now
            for k, v in dev.details.items():
                if existing.details.get(k) != v:
                    existing.details[k] = v
                    changed = True
            upserts.append((existing, changed))
        for key, existing in current.items():
            if key in reported or snapshot.source_id not in existing.source_ids:
                continue
            existing.source_ids.remove(snapshot.source_id)
            if not existing.source_ids and not existing.manual and existing.reported:
                existing.reported = False
                events.append(
                    self._event(
                        snapshot,
                        "device_no_longer_reported",
                        existing,
                        f"{existing.label} is no longer reported by its source",
                    )
                )
            upserts.append((existing, True))
        self._write(upserts, now)
        return events

    @staticmethod
    def _event(snapshot: Snapshot, kind: str, item: InventoryDevice, message: str) -> Event:
        return Event(
            source_id=snapshot.source_id,
            observed_at=snapshot.collected_at,
            reliability=snapshot.reliability,
            kind=kind,
            subject=f"device:{item.key}",
            message=message,
            devices=(item.key,),
        )

    def _write(self, upserts: list[tuple[InventoryDevice, bool]], now: datetime) -> None:
        changed = [d for d, c in upserts if c]
        touched = [d.key for d, c in upserts if not c]
        if not changed and not touched:
            return

        def write(conn: sqlite3.Connection) -> None:
            for d in changed:
                conn.execute(
                    "INSERT INTO devices(key, name, display_name, manufacturer, model, category, ip, mac, firmware,"
                    " serial, source_ids, location, manual, reported, first_seen_at, last_seen_at, details)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET"
                    " name=excluded.name, manufacturer=excluded.manufacturer, model=excluded.model,"
                    " category=excluded.category, ip=excluded.ip, mac=excluded.mac, firmware=excluded.firmware,"
                    " serial=excluded.serial, source_ids=excluded.source_ids, reported=excluded.reported,"
                    " last_seen_at=excluded.last_seen_at, details=excluded.details",
                    (
                        d.key,
                        d.name,
                        d.display_name,
                        d.manufacturer,
                        d.model,
                        d.category.value,
                        d.ip,
                        d.mac,
                        d.firmware,
                        d.serial,
                        json.dumps(d.source_ids),
                        d.location,
                        int(d.manual),
                        int(d.reported),
                        to_iso(d.first_seen_at),
                        to_iso(d.last_seen_at),
                        json.dumps(d.details, default=str),
                    ),
                )
            if touched:
                conn.executemany(
                    "UPDATE devices SET last_seen_at=? WHERE key=?",
                    [(to_iso(now), k) for k in touched],
                )

        self.writer.call_sync(write)
        self._invalidate()

    # -- engineer actions ----------------------------------------------------------
    def add_manual(
        self,
        name: str,
        ip: str,
        category: DeviceCategory = DeviceCategory.OTHER,
        location: str | None = None,
        mac: str | None = None,
    ) -> InventoryDevice:
        if not name.strip() or not ip.strip():
            raise ValueError("A manual device needs a name and an IP address.")
        key = device_key(mac=mac, source_id="manual", native_id=uuid.uuid4().hex[:10])
        now = utcnow()
        item = InventoryDevice(
            key=key,
            name=name.strip(),
            display_name=None,
            manufacturer=None,
            model=None,
            category=category,
            ip=ip.strip(),
            mac=mac,
            firmware=None,
            serial=None,
            source_ids=[],
            location=location,
            manual=True,
            reported=True,
            first_seen_at=now,
            last_seen_at=now,
        )
        self._write([(item, True)], now)
        self.writer.call_sync(
            lambda c: c.execute("UPDATE devices SET location=? WHERE key=?", (location, key))
        )
        self._invalidate()
        return item

    def remove(self, key: str) -> None:
        self.writer.call_sync(lambda c: c.execute("DELETE FROM devices WHERE key=?", (key,)))
        self.writer.call_sync(
            lambda c: c.execute(
                "DELETE FROM service_mappings WHERE kind='device' AND ref=?", (key,)
            )
        )
        self._invalidate()

    def set_tags(
        self, key: str, *, location: str | None = None, display_name: str | None = None
    ) -> None:
        def write(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE devices SET location=?, display_name=? WHERE key=?",
                ((location or "").strip() or None, (display_name or "").strip() or None, key),
            )

        self.writer.call_sync(write)
        self._invalidate()

    # -- services ----------------------------------------------------------------------
    def mappings(self) -> dict[Service, dict[str, set[str]]]:
        result: dict[Service, dict[str, set[str]]] = {
            s: {"device": set(), "wan": set(), "ssid": set()} for s in Service
        }
        with self.db.read() as conn:
            for row in conn.execute("SELECT service, kind, ref FROM service_mappings"):
                result[Service(row["service"])][row["kind"]].add(row["ref"])
        return result

    def map(self, service: Service, kind: str, ref: str) -> None:
        if kind not in ("device", "wan", "ssid"):
            raise ValueError(kind)
        self.writer.call_sync(
            lambda c: c.execute(
                "INSERT OR IGNORE INTO service_mappings(service, kind, ref) VALUES (?, ?, ?)",
                (service.value, kind, ref),
            )
        )

    def unmap(self, service: Service, kind: str, ref: str) -> None:
        self.writer.call_sync(
            lambda c: c.execute(
                "DELETE FROM service_mappings WHERE service=? AND kind=? AND ref=?",
                (service.value, kind, ref),
            )
        )

    def unmapped_ssids(self, state: StateStore) -> list[str]:
        mapped = {ssid for m in self.mappings().values() for ssid in m["ssid"]}
        seen = {n.ssid for n in state.wifi_networks()}
        return sorted(seen - mapped)

    def service_is_set_up(self, service: Service) -> bool:
        return any(self.mappings()[service].values())

    # -- topology overrides ------------------------------------------------------------
    def topology_overrides(self) -> dict[str, tuple[str, str | None]]:
        with self.db.read() as conn:
            rows = conn.execute(
                "SELECT device_key, parent_key, port_id FROM topology_overrides"
            ).fetchall()
        return {r["device_key"]: (r["parent_key"], r["port_id"]) for r in rows}

    def set_topology_override(
        self, device: str, parent: str | None, port_id: str | None = None
    ) -> None:
        if parent is None:
            self.writer.call_sync(
                lambda c: c.execute("DELETE FROM topology_overrides WHERE device_key=?", (device,))
            )
            return
        self.writer.call_sync(
            lambda c: c.execute(
                "INSERT INTO topology_overrides(device_key, parent_key, port_id) VALUES (?, ?, ?)"
                " ON CONFLICT(device_key) DO UPDATE SET parent_key=excluded.parent_key, port_id=excluded.port_id",
                (device, parent, port_id),
            )
        )
