"""Starlink dish rules. Both need the optional dish source; without it they do not fire."""

from __future__ import annotations

from datetime import timedelta

from insight.diagnostics import Action, Candidate, Confidence, Input, Rule, Sample, Severity
from insight.diagnostics.context import EvalContext
from insight.inventory import Service

# Alerts the dish reports, in plain words. Unknown alerts fall back to a generic text.
ALERTS: dict[str, tuple[str, Severity, str]] = {
    "thermal_throttle": (
        "The Starlink dish is too hot and has slowed itself down",
        Severity.WARNING,
        "heat",
    ),
    "thermal_shutdown": (
        "The Starlink dish has shut down because it is too hot",
        Severity.CRITICAL,
        "heat",
    ),
    "motors_stuck": ("The Starlink dish reports a motor problem", Severity.WARNING, "hardware"),
    "mast_not_near_vertical": (
        "The Starlink dish is not mounted level",
        Severity.WARNING,
        "mounting",
    ),
    "unexpected_location": (
        "Starlink reports the dish is somewhere it doesn't expect",
        Severity.WARNING,
        "service",
    ),
    "slow_ethernet_speeds": (
        "The cable to the Starlink dish is running slower than it should",
        Severity.WARNING,
        "cabling",
    ),
    "power_supply_thermal_throttle": (
        "The Starlink power supply is too hot and has slowed the dish down",
        Severity.WARNING,
        "heat",
    ),
    "is_heating": (
        "The Starlink dish is heating itself to melt snow or ice",
        Severity.INFO,
        "weather",
    ),
    "water_detected": ("The Starlink dish reports water inside", Severity.CRITICAL, "hardware"),
}


class StarlinkObstructed(Rule):
    id = "starlink_obstructed"
    title = "Starlink dish's view of the sky is blocked"
    severity = Severity.WARNING
    requires = (Input.WAN,)
    optional = (Input.DISH,)
    optional_essential = True
    min_duration = timedelta(seconds=60)
    clear_duration = timedelta(seconds=300)
    explains = ("primary_link_degraded",)
    systems = ("starlink",)
    purpose = "The dish reports obstruction (currently obstructed or a significant obstructed fraction) with obstruction outages."
    samples = (
        Sample(Confidence.CONFIRMED, {"fraction_pct": 18.0, "outages": 2, "currently": True}),
        Sample(Confidence.PROBABLE, {"fraction_pct": 6.0, "outages": 0, "currently": False}),
    )

    def evaluate(self, ctx: EvalContext) -> list[Candidate]:
        dish = ctx.facts(Input.DISH, "dish")
        if not isinstance(dish, dict):
            return []
        fraction = float(dish.get("obstruction_fraction") or 0.0)
        currently = bool(dish.get("currently_obstructed"))
        obstruction_outages = [
            o for o in dish.get("outages") or [] if str(o.get("cause")) == "OBSTRUCTED"
        ]
        if not currently and fraction < float(ctx.config["threshold_obstruction_fraction"]):
            return []
        confidence = (
            Confidence.CONFIRMED if currently and obstruction_outages else Confidence.PROBABLE
        )
        source = ctx.source_of(Input.DISH)
        return [
            Candidate(
                rule_id=self.id,
                key=self.id,
                confidence=confidence,
                facts={
                    "fraction_pct": round(fraction * 100, 1),
                    "outages": len(obstruction_outages),
                    "currently": currently,
                },
                evidence=[
                    ctx.ev(
                        f"Dish reports {fraction * 100:.1f}% of its view obstructed",
                        source,
                        fraction=fraction,
                    ),
                    ctx.ev(
                        "Dish reports it is obstructed right now"
                        if currently
                        else "Dish is not obstructed at this moment",
                        source,
                    ),
                    *[
                        ctx.ev(
                            f"Outage caused by obstruction lasting {o.get('duration_s') or 0:.0f} s",
                            source,
                            **o,
                        )
                        for o in obstruction_outages[-5:]
                    ],
                ],
                services=(Service.INTERNET.value,),
                guests_affected=True,
                action=Action.NONE,
            )
        ]


class StarlinkDishAlert(Rule):
    id = "starlink_dish_alert"
    title = "Starlink dish alert"
    severity = Severity.WARNING
    optional = (Input.DISH,)
    optional_essential = True
    min_duration = timedelta(seconds=30)
    clear_duration = timedelta(seconds=300)
    systems = ("starlink",)
    purpose = (
        "The dish reports an active alert (for example overheating, motors, mounting or water)."
    )
    samples = (
        Sample(
            Confidence.CONFIRMED,
            {
                "alert": "thermal_throttle",
                "headline": ALERTS["thermal_throttle"][0],
                "category": "heat",
            },
        ),
        Sample(
            Confidence.CONFIRMED,
            {
                "alert": "novel_alert",
                "headline": "The Starlink dish reports a problem",
                "category": "other",
            },
        ),
    )

    def evaluate(self, ctx: EvalContext) -> list[Candidate]:
        dish = ctx.facts(Input.DISH, "dish")
        if not isinstance(dish, dict):
            return []
        source = ctx.source_of(Input.DISH)
        found = []
        for alert in dish.get("alerts") or []:
            headline, severity, category = ALERTS.get(
                alert, ("The Starlink dish reports a problem", Severity.WARNING, "other")
            )
            found.append(
                Candidate(
                    rule_id=self.id,
                    key=f"{self.id}:{alert}",
                    confidence=Confidence.CONFIRMED,
                    facts={"alert": alert, "headline": headline, "category": category},
                    evidence=[ctx.ev(f"Dish alert active: {alert}", source, alert=alert)],
                    severity=severity,
                    services=(Service.INTERNET.value,),
                    guests_affected=severity is not Severity.INFO,
                    action=Action.CHECK
                    if category in ("mounting", "cabling")
                    else Action.NONE
                    if category == "weather"
                    else Action.CONTACT,
                )
            )
        return found
