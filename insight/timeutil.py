"""Time helpers. Everything is stored in UTC; display uses the configured ship's time zone."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return ensure_utc(value).isoformat()


def from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return ensure_utc(datetime.fromisoformat(value))


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("naive datetimes are not allowed; use UTC-aware datetimes")
    return value.astimezone(UTC)


def ship_zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def format_ship_time(value: datetime, zone_name: str | None, fmt: str = "%d %b %Y %H:%M") -> str:
    """Format a UTC timestamp in ship's time, with the zone abbreviation."""
    local = ensure_utc(value).astimezone(ship_zone(zone_name))
    return f"{local.strftime(fmt)} {local.tzname()}"
