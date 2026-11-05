"""The diagnostic engine: rules turn observations into findings that say what is wrong,
how sure Insight is, why, and what to check next."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from insight.diagnostics.context import EvalContext


class Severity(StrEnum):
    INFO = "information"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {"information": 0, "warning": 1, "critical": 2}[self.value]


class Confidence(StrEnum):
    CONFIRMED = "confirmed"
    PROBABLE = "probable"
    INSUFFICIENT = "insufficient information"
    MONITORING_FAILURE = "monitoring failure"


class Action(StrEnum):
    NONE = "none"  # nothing needs to be done on board
    CHECK = "check"  # a specific simple check can be made on board
    CONTACT = "contact"  # contact the ETO or 50N support


class Input(StrEnum):
    """Logical inputs a rule can need. Each is satisfied by fresh data from some source."""

    WAN = "wan"  # router WAN links (Peplink)
    PROBES = "probes"  # Insight's own checks
    SWITCHES = "switches"  # switch and port state (UniFi)
    POE = "poe"  # per-port PoE power (UniFi classic API, optional)
    WIFI_TOTALS = "wifi_totals"  # Ruckus SNMP totals
    WIFI_DETAIL = "wifi_detail"  # per-AP detail (Ruckus web interface, optional)
    DISH = "dish"  # Starlink dish status (optional)


@dataclass(frozen=True)
class Evidence:
    description: str
    source_id: str | None
    observed_at: datetime | None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Candidate:
    """A rule's claim that a problem exists now."""

    rule_id: str
    key: str  # identifies "the same problem" across evaluations
    confidence: Confidence
    facts: dict[str, Any]
    evidence: list[Evidence]
    severity: Severity | None = None
    systems: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    devices: tuple[str, ...] = ()
    guests_affected: bool = False
    action: Action = Action.CONTACT


@dataclass(frozen=True)
class Sample:
    """An example rendering of a rule, used for wording checks and documentation."""

    confidence: Confidence
    facts: dict[str, Any]


class Rule:
    id: ClassVar[str]
    title: ClassVar[str]
    severity: ClassVar[Severity]
    requires: ClassVar[tuple[Input, ...]] = ()
    optional: ClassVar[tuple[Input, ...]] = ()
    optional_essential: ClassVar[bool] = False  # skip the rule when optional inputs are missing
    min_duration: ClassVar[timedelta] = timedelta(seconds=60)
    clear_duration: ClassVar[timedelta] = timedelta(seconds=120)
    explains: ClassVar[tuple[str, ...]] = ()  # symptom rules this rule absorbs
    systems: ClassVar[tuple[str, ...]] = ()
    purpose: ClassVar[str] = ""
    samples: ClassVar[tuple[Sample, ...]] = ()

    def evaluate(self, ctx: EvalContext) -> list[Candidate]:
        raise NotImplementedError
