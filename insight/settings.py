"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


@dataclass(frozen=True)
class Settings:
    """Process-level settings. Yacht configuration lives in the database, not here."""

    data_dir: Path
    bind_host: str = "0.0.0.0"  # noqa: S104 - Insight serves the yacht LAN
    https_port: int = 443
    http_port: int = 80
    syslog_port: int = 514
    stall_factor: int = 3
    listen_announcements: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            data_dir=Path(os.environ.get("INSIGHT_DATA_DIR", "/data")),
            bind_host=os.environ.get("INSIGHT_BIND_HOST", "0.0.0.0"),  # noqa: S104
            https_port=_int("INSIGHT_HTTPS_PORT", 443),
            http_port=_int("INSIGHT_HTTP_PORT", 80),
            syslog_port=_int("INSIGHT_SYSLOG_PORT", 514),
            stall_factor=_int("INSIGHT_STALL_FACTOR", 3),
            listen_announcements=os.environ.get("INSIGHT_LISTEN_ANNOUNCEMENTS", "1") != "0",
        )
