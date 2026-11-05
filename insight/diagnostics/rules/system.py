"""Rules about Insight's own ability to see: monitoring sources and storage."""

from __future__ import annotations

from datetime import timedelta

from insight.diagnostics import Action, Candidate, Confidence, Rule, Sample, Severity
from insight.diagnostics.context import SYSTEM_NAMES, EvalContext
from insight.model import Reliability
from insight.state import SourceState

# What crew lose sight of when each kind of source is unavailable.
WHAT_IT_COVERS = {
    "peplink": "the internet connections",
    "probes": "whether the internet and devices answer",
    "unifi": "the network switches",
    "unifi-snmp": "the network switches",
    "ruckus-snmp": "the Wi-Fi",
    "ruckus-web": "detailed Wi-Fi information for each area",
    "starlink": "detailed Starlink dish information",
}


class MonitoringSourceUnavailable(Rule):
    id = "monitoring_source_unavailable"
    title = "Insight can't currently check part of the system"
    severity = Severity.WARNING
    min_duration = timedelta(seconds=60)
    clear_duration = timedelta(seconds=60)
    systems = ("insight",)
    purpose = "A configured source cannot be reached, rejects Insight's credentials, or returns data Insight can't interpret."
    samples = (
        Sample(
            Confidence.MONITORING_FAILURE,
            {
                "source": "UniFi controller",
                "covers": "the network switches",
                "optional": False,
                "reason": "unreachable",
                "since_s": 300,
            },
        ),
        Sample(
            Confidence.MONITORING_FAILURE,
            {
                "source": "Starlink dish",
                "covers": "detailed Starlink dish information",
                "optional": True,
                "reason": "unparseable",
                "since_s": 3600,
            },
        ),
    )

    def evaluate(self, ctx: EvalContext) -> list[Candidate]:
        found = []
        for source_id, status in ctx.state.sources.items():
            failing = status.state is SourceState.FAILED or (
                status.state is SourceState.OK and not ctx.state.is_fresh(source_id, ctx.now)
            )
            if not failing:
                continue
            kind = ctx.kind_of(source_id)
            optional = status.reliability is Reliability.OPTIONAL
            since = status.failing_since or status.last_success_at or ctx.now
            found.append(
                Candidate(
                    rule_id=self.id,
                    key=f"{self.id}:{source_id}",
                    confidence=Confidence.MONITORING_FAILURE,
                    facts={
                        "source": status.name,
                        "covers": WHAT_IT_COVERS.get(
                            kind, SYSTEM_NAMES.get(kind, "part of the system")
                        ),
                        "optional": optional,
                        "reason": status.failure_kind.value
                        if status.failure_kind
                        else "no recent data",
                        "since_s": max(0.0, (ctx.now - since).total_seconds()),
                    },
                    evidence=[
                        ctx.ev(
                            f"Last error: {status.last_error or 'no data received recently'}",
                            source_id,
                            status.last_error_at,
                        ),
                        ctx.ev(
                            f"Last successful collection: {status.last_success_at.isoformat() if status.last_success_at else 'never'}",
                            source_id,
                        ),
                    ],
                    severity=Severity.INFO if optional else Severity.WARNING,
                    systems=(kind,),
                    action=Action.CONTACT,
                )
            )
        return found


class LowDiskSpace(Rule):
    id = "low_disk_space"
    title = "Insight is running out of storage space"
    severity = Severity.WARNING
    min_duration = timedelta(seconds=0)
    clear_duration = timedelta(seconds=600)
    systems = ("insight",)
    purpose = "Free space for Insight's data has fallen below the safe threshold; the oldest readings are being removed."
    samples = (Sample(Confidence.CONFIRMED, {"free_mb": 412.0, "threshold_mb": 1024.0}),)

    def evaluate(self, ctx: EvalContext) -> list[Candidate]:
        if not ctx.disk.get("low"):
            return []
        return [
            Candidate(
                rule_id=self.id,
                key=self.id,
                confidence=Confidence.CONFIRMED,
                facts={
                    "free_mb": ctx.disk.get("free_mb"),
                    "threshold_mb": ctx.disk.get("threshold_mb"),
                },
                evidence=[
                    ctx.ev(
                        f"{ctx.disk.get('free_mb')} MB free; threshold {ctx.disk.get('threshold_mb')} MB; "
                        f"{ctx.disk.get('pruned_rows', 0)} oldest readings removed",
                        None,
                    )
                ],
                action=Action.CONTACT,
            )
        ]
