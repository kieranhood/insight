"""Discovery: suggests equipment; an engineer confirms it (design D10).

Three layers:
- source-derived (passive): equipment in the client and address lists sources already return;
- announcements (passive): mDNS and SSDP announcements heard on the network;
- active sweep: only when an engineer starts a run, only on selected subnets.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from insight.discovery.fingerprint import Identification, identify
from insight.inventory import Inventory
from insight.model import DeviceCategory, Event, Reliability, Snapshot, device_key, normalise_mac
from insight.oui import is_locally_administered, vendor_for
from insight.storage.db import Database
from insight.storage.writer import Writer
from insight.timeutil import from_iso, to_iso, utcnow

DISCOVERY_SOURCE_ID = "insight-discovery"


@dataclass
class Discovered:
    key: str
    mac: str | None
    ip: str | None
    name: str | None
    how: list[str]
    observations: dict[str, Any]
    likely_type: str | None
    confidence: str
    evidence: list[str]
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    label: str = field(default="")

    @property
    def display(self) -> str:
        return self.name or self.ip or self.mac or self.key


def discovery_key(mac: str | None, ip: str | None) -> str:
    normalised = normalise_mac(mac)
    if normalised:
        return f"mac:{normalised}"
    if ip:
        return f"ip:{ip}"
    raise ValueError("a discovered device needs a MAC or IP address")


def _row(row: sqlite3.Row) -> Discovered:
    return Discovered(
        key=row["key"],
        mac=row["mac"],
        ip=row["ip"],
        name=row["name"],
        how=json.loads(row["how"]),
        observations=json.loads(row["observations"]),
        likely_type=row["likely_type"],
        confidence=row["confidence"],
        evidence=json.loads(row["evidence"]),
        status=row["status"],
        first_seen_at=from_iso(row["first_seen_at"]) or utcnow(),
        last_seen_at=from_iso(row["last_seen_at"]) or utcnow(),
    )


class DiscoveryStore:
    def __init__(self, db: Database, writer: Writer, inventory: Inventory) -> None:
        self.db = db
        self.writer = writer
        self.inventory = inventory

    def all(self, status: str | None = None) -> list[Discovered]:
        with self.db.read() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM discovered WHERE status=? ORDER BY last_seen_at DESC", (status,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM discovered ORDER BY last_seen_at DESC"
                ).fetchall()
        items = [_row(r) for r in rows]
        for item in items:
            item.label = identify_label(item)
        return items

    def get(self, key: str) -> Discovered | None:
        with self.db.read() as conn:
            row = conn.execute("SELECT * FROM discovered WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        item = _row(row)
        item.label = identify_label(item)
        return item

    def in_inventory(self, mac: str | None, ip: str | None) -> bool:
        devices = self.inventory.devices()
        normalised = normalise_mac(mac)
        if normalised and device_key(mac=normalised) in devices:
            return True
        return bool(ip) and any(d.ip == ip for d in devices.values())

    def record(
        self,
        *,
        mac: str | None,
        ip: str | None,
        name: str | None,
        how: str,
        observations: dict[str, Any],
        now: datetime | None = None,
    ) -> tuple[Discovered | None, bool]:
        """Record an observation. Returns (entry, is_new). Inventory devices are not recorded."""
        now = now or utcnow()
        if self.in_inventory(mac, ip):
            return None, False
        key = discovery_key(mac, ip)
        existing = self.get(key)
        if existing is None and ip and not mac:
            # An active sweep sees IPs; merge with an entry already known by MAC for that IP.
            match = next((d for d in self.all() if d.ip == ip), None)
            if match is not None:
                existing, key = match, match.key
        merged_obs = dict(existing.observations) if existing else {}
        for k, v in observations.items():
            if isinstance(v, list) and isinstance(merged_obs.get(k), list):
                merged_obs[k] = sorted(set(merged_obs[k]) | set(v))
            elif v not in (None, "", [], {}):
                merged_obs[k] = v
        mac = mac or (existing.mac if existing else None)
        ip = ip or (existing.ip if existing else None)
        if mac and "oui_vendor" not in merged_obs:
            vendor = vendor_for(mac)
            if vendor:
                merged_obs["oui_vendor"] = vendor
        if ip:
            merged_obs["ip"] = ip
        result: Identification = identify(merged_obs)
        how_list = sorted(set((existing.how if existing else []) + [how]))
        status = existing.status if existing else "new"
        values = (
            key,
            normalise_mac(mac),
            ip,
            name or (existing.name if existing else None),
            json.dumps(how_list),
            json.dumps(merged_obs, default=str),
            result.type_id,
            result.confidence,
            json.dumps(result.evidence),
            status,
            to_iso(existing.first_seen_at if existing else now),
            to_iso(now),
        )
        self.writer.call_sync(
            lambda c: c.execute(
                "INSERT INTO discovered(key, mac, ip, name, how, observations, likely_type, confidence, evidence,"
                " status, first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(key) DO UPDATE SET mac=excluded.mac, ip=excluded.ip, name=excluded.name,"
                " how=excluded.how, observations=excluded.observations, likely_type=excluded.likely_type,"
                " confidence=excluded.confidence, evidence=excluded.evidence, last_seen_at=excluded.last_seen_at",
                values,
            )
        )
        return self.get(key), existing is None

    def set_status(self, key: str, status: str) -> None:
        if status not in ("new", "accepted", "dismissed"):
            raise ValueError(status)
        self.writer.call_sync(
            lambda c: c.execute("UPDATE discovered SET status=? WHERE key=?", (status, key))
        )

    def dismiss(self, key: str) -> None:
        self.set_status(key, "dismissed")

    def restore(self, key: str) -> None:
        self.set_status(key, "new")

    def accept(
        self, key: str, *, name: str, category: DeviceCategory, location: str | None = None
    ) -> str:
        item = self.get(key)
        if item is None:
            raise KeyError(key)
        if not item.ip:
            raise ValueError("Insight needs an IP address to monitor this device.")
        device = self.inventory.add_manual(
            name, item.ip, category=category, location=location, mac=item.mac
        )
        self.set_status(key, "accepted")
        return device.key

    def new_items(self) -> list[Discovered]:
        return [d for d in self.all("new") if not self.in_inventory(d.mac, d.ip)]

    # -- passive, source-derived ----------------------------------------------------------
    def observe_snapshot(self, snapshot: Snapshot) -> list[Event]:
        """Record equipment seen in a source's client list. Returns new-device events."""
        events: list[Event] = []
        for client in snapshot.clients:
            if client.wired is False or is_locally_administered(client.mac):
                continue  # Wi-Fi phones and laptops are not equipment
            entry, is_new = self.record(
                mac=client.mac,
                ip=client.ip,
                name=client.hostname,
                how=f"listed by {snapshot.source_id}",
                observations={},
                now=snapshot.collected_at,
            )
            if entry is not None and is_new and entry.status == "new":
                events.append(new_device_event(entry, snapshot.collected_at, snapshot.source_id))
        return events

    def observe_announcement(
        self, *, ip: str, name: str | None, services: list[str], server: str | None = None
    ) -> Event | None:
        observations: dict[str, Any] = {"announced_services": services}
        if server:
            observations["ssdp_server"] = server
        entry, is_new = self.record(
            mac=None, ip=ip, name=name, how="announced itself", observations=observations
        )
        if entry is not None and is_new and entry.status == "new":
            return new_device_event(entry, utcnow(), DISCOVERY_SOURCE_ID)
        return None


def identify_label(item: Discovered) -> str:
    from insight.discovery.fingerprint import type_label

    if item.confidence == "unidentified" or not item.likely_type:
        return "Unidentified"
    prefix = "Likely" if item.confidence == "likely" else "Possibly"
    return f"{prefix} a {type_label(item.likely_type)}"


def new_device_event(entry: Discovered, at: datetime, source_id: str) -> Event:
    return Event(
        source_id=source_id,
        observed_at=at,
        reliability=Reliability.RELIABLE,
        kind="new_device_discovered",
        subject=f"discovered:{entry.key}",
        message=f"New device seen on the network: {entry.display}",
        data={"key": entry.key, "ip": entry.ip, "mac": entry.mac},
    )
