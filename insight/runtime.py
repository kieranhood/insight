"""The Runtime holds every long-lived component of a running Insight instance."""

from __future__ import annotations

from datetime import datetime

from insight.settings import Settings
from insight.timeutil import utcnow


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.started_at: datetime = utcnow()
        self.last_cycle_at: datetime | None = None
        self.expected_cycle_interval: float = 60.0

    def record_cycle(self, at: datetime | None = None) -> None:
        self.last_cycle_at = at or utcnow()
