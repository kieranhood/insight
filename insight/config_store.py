"""Yacht configuration stored in the database (settings an engineer can change)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from insight.storage.db import Database
from insight.storage.writer import Writer

DEFAULTS: dict[str, Any] = {
    "ship_timezone": "UTC",
    "retention_detail_days": 30,
    "retention_summary_days": 365,
    "session_idle_minutes_crew": 12 * 60,
    "session_idle_minutes_engineer": 2 * 60,
    "probe_internet_targets": ["1.1.1.1", "8.8.8.8", "9.9.9.9"],
    "probe_dns_names": ["www.google.com", "www.cloudflare.com"],
    "probe_dns_public_resolver": "1.1.1.1",
    "probe_http_urls": [
        "http://connectivitycheck.gstatic.com/generate_204",
        "http://www.msftconnecttest.com/connecttest.txt",
    ],
    "probe_device_interval_s": 30,
    "probe_internet_interval_s": 30,
    "probe_dns_interval_s": 60,
    "probe_http_interval_s": 120,
    "probe_failure_threshold": 3,
    "discovery_selected_subnets": [],
    "discovery_excluded_subnets": [],
    "low_disk_free_mb": 1024,
    "starlink_dish_address": "192.168.100.1:9200",
    "starlink_wan": None,
    "threshold_degraded_loss_pct": 5.0,
    "threshold_degraded_latency_ms": 600.0,
    "threshold_obstruction_fraction": 0.05,
    "threshold_weak_rsrp_dbm": -110.0,
    "threshold_weak_sinr_db": 0.0,
    "threshold_channel_util_pct": 80.0,
    "threshold_ap_clients": 40,
}


class ConfigStore:
    def __init__(self, db: Database, writer: Writer) -> None:
        self.db = db
        self.writer = writer

    def get(self, key: str) -> Any:
        with self.db.read() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row is None:
            return DEFAULTS.get(key)
        return json.loads(row["value"])

    def all(self) -> dict[str, Any]:
        values = dict(DEFAULTS)
        with self.db.read() as conn:
            for row in conn.execute("SELECT key, value FROM settings"):
                values[row["key"]] = json.loads(row["value"])
        return values

    def set(self, key: str, value: Any) -> None:
        payload = json.dumps(value)

        def write(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, payload),
            )

        self.writer.call_sync(write)
