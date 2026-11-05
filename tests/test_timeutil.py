from __future__ import annotations

from datetime import UTC, datetime

import pytest

from insight.timeutil import ensure_utc, format_ship_time, from_iso, to_iso


def test_ship_time_formatting_in_two_zones() -> None:
    stamp = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    assert format_ship_time(stamp, "Europe/Monaco") == "01 Jul 2026 14:00 CEST"
    assert format_ship_time(stamp, "America/Antigua") == "01 Jul 2026 08:00 AST"


def test_unknown_zone_falls_back_to_utc() -> None:
    stamp = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    assert format_ship_time(stamp, "Not/AZone") == "01 Jul 2026 12:00 UTC"


def test_iso_round_trip_and_naive_rejected() -> None:
    stamp = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    assert from_iso(to_iso(stamp)) == stamp
    with pytest.raises(ValueError):
        ensure_utc(datetime(2026, 7, 1))


def test_ship_timezone_setting_is_stored(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from insight.config_store import ConfigStore
    from insight.storage.db import Database
    from insight.storage.writer import Writer

    db = Database(tmp_path / "i.db")
    db.migrate()
    writer = Writer(db)
    config = ConfigStore(db, writer)
    assert config.get("ship_timezone") == "UTC"
    config.set("ship_timezone", "Europe/Monaco")
    assert config.get("ship_timezone") == "Europe/Monaco"
    stamp = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert format_ship_time(stamp, config.get("ship_timezone")) == "01 Jan 2026 13:00 CET"
    writer.close()
