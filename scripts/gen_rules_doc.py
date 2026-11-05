"""Regenerate docs/rules.md from the rule catalogue: python scripts/gen_rules_doc.py"""

from __future__ import annotations

from pathlib import Path

from insight.config_store import DEFAULTS
from insight.diagnostics.engine import render
from insight.diagnostics.rules import all_rules

CONFIDENCE_LOGIC = {
    "internet_unavailable": "**Confirmed** when the router reports every enabled WAN link down or failing its health check. **Probable** when only Insight's checks fail while the router still shows a link up (the cause may be beyond the router).",
    "failover_to_backup": "**Confirmed**: the router reports the highest-priority link unusable and a lower-priority link in use.",
    "primary_link_degraded": "**Insufficient information**: degradation is measured on the link in use, but no source evidences why. If the dish reports obstruction, the obstruction finding replaces this one.",
    "all_paths_degraded": "**Probable**: every connected link shows high latency or loss; several explanations remain possible.",
    "dns_failure": '**Probable** ("suspected"): lookups through the yacht\'s resolver fail while a public resolver or IP connectivity works.',
    "starlink_obstructed": "**Confirmed** when the dish reports it is obstructed now and has recent outages caused by obstruction; otherwise **probable**. Does not fire without dish data.",
    "starlink_dish_alert": "**Confirmed**: the dish reports the alert. Severity depends on the alert (thermal shutdown and water are critical). Does not fire without dish data.",
    "weak_cellular_signal": "**Confirmed**: the router reports the signal of the cellular link in use.",
    "ap_offline": "**Confirmed** when the Wi-Fi system reports the access point disconnected (web interface, or an Unleashed lost-contact message). **Probable** when only Insight's reachability checks fail.",
    "ap_lost_poe": "**Confirmed** when current PoE power data for the access point's port shows 0 W or link down. **Probable** when PoE data is unavailable but the port (known from LLDP or an engineer's record) is down and the access point does not answer.",
    "switch_offline": "**Confirmed** when the controller reports the switch offline; **probable** when only Insight's checks fail. Lists everything behind the switch, using remembered cabling.",
    "wifi_congestion": "**Probable**: high channel utilisation or client count suggests local congestion. Does not fire without the optional Ruckus web data.",
    "monitoring_source_unavailable": "**Monitoring failure**: Insight cannot collect from the source. Equipment it covers is not reported faulty on that basis. Optional sources are information severity.",
    "low_disk_space": "**Confirmed**: measured free space is below the threshold.",
}

THRESHOLDS = {
    "primary_link_degraded": ["threshold_degraded_loss_pct", "threshold_degraded_latency_ms"],
    "all_paths_degraded": ["threshold_degraded_loss_pct", "threshold_degraded_latency_ms"],
    "starlink_obstructed": ["threshold_obstruction_fraction"],
    "weak_cellular_signal": ["threshold_weak_rsrp_dbm", "threshold_weak_sinr_db"],
    "wifi_congestion": ["threshold_channel_util_pct", "threshold_ap_clients"],
    "ap_offline": ["probe_failure_threshold"],
    "internet_unavailable": ["probe_failure_threshold"],
    "low_disk_space": ["low_disk_free_mb"],
}


def main() -> None:
    out = [
        "# Diagnostic rules",
        "",
        "Generated from the rule catalogue by `scripts/gen_rules_doc.py`; do not edit by hand.",
        "",
        "Every finding has a confidence: **confirmed** (evidence directly shows it), **probable** (evidence points to it, other causes possible), **insufficient information** (something is wrong, cause unknown) or **monitoring failure** (Insight cannot see the system). Crew wording is checked automatically: no addresses, port numbers or technical terms, and hedged wording unless confirmed. Thresholds are settings an engineer can change.",
        "",
    ]
    for rule in all_rules():
        out += [f"## `{rule.id}`: {rule.title}", "", rule.purpose, ""]
        out.append(f"- **Severity:** {rule.severity.value}")
        needs = ", ".join(i.value for i in rule.requires) or "none"
        optional = ", ".join(i.value for i in rule.optional) or "none"
        out.append(
            f"- **Needs:** {needs}. **Optional:** {optional}"
            + (" (essential: the rule does not fire without it)" if rule.optional_essential else "")
        )
        out.append(
            f"- **Opens after:** {int(rule.min_duration.total_seconds())} s; **resolves after clear for:** {int(rule.clear_duration.total_seconds())} s"
        )
        if rule.explains:
            out.append(f"- **Absorbs:** {', '.join(f'`{e}`' for e in rule.explains)}")
        if rule.id in THRESHOLDS:
            out.append(
                "- **Thresholds:** "
                + ", ".join(f"`{k}` = {DEFAULTS[k]}" for k in THRESHOLDS[rule.id])
            )
        out.append(f"- **Confidence:** {CONFIDENCE_LOGIC[rule.id]}")
        out.append("")
        for sample in rule.samples:
            rendered = render(rule, sample.confidence, sample.facts)
            out += [
                f"**Example ({sample.confidence.value})**: *{rendered.title}*",
                "",
                f"> Crew: {rendered.crew}",
                ">",
                f"> Engineer: {rendered.summary}",
                "",
            ]
    Path("docs/rules.md").write_text("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
