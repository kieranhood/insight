"""The initial rule catalogue."""

from __future__ import annotations

from insight.diagnostics import Rule
from insight.diagnostics.rules.internet import (
    AllPathsDegraded,
    DnsFailure,
    FailoverToBackup,
    InternetUnavailable,
    PrimaryLinkDegraded,
    WeakCellularSignal,
)
from insight.diagnostics.rules.starlink import StarlinkDishAlert, StarlinkObstructed
from insight.diagnostics.rules.system import LowDiskSpace, MonitoringSourceUnavailable
from insight.diagnostics.rules.wifi import ApLostPoe, ApOffline, SwitchOffline, WifiCongestion

RULE_CLASSES: list[type[Rule]] = [
    InternetUnavailable,
    FailoverToBackup,
    PrimaryLinkDegraded,
    AllPathsDegraded,
    DnsFailure,
    StarlinkObstructed,
    StarlinkDishAlert,
    WeakCellularSignal,
    ApOffline,
    ApLostPoe,
    SwitchOffline,
    WifiCongestion,
    MonitoringSourceUnavailable,
    LowDiskSpace,
]


def all_rules() -> list[Rule]:
    return [cls() for cls in RULE_CLASSES]
