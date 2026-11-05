"""Checks on crew-facing wording: no jargon, and honest about uncertainty."""

from __future__ import annotations

import re

from insight.diagnostics import Confidence

_PATTERNS = {
    "IP address": re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),
    "MAC address": re.compile(r"\b[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}\b"),
    "port number": re.compile(r"\bport\s*\d+\b", re.I),
}
PROTOCOL_WORDS = (
    "DNS",
    "DHCP",
    "HTTP",
    "HTTPS",
    "TCP",
    "UDP",
    "ICMP",
    "SNMP",
    "LLDP",
    "PoE",
    "WAN",
    "LAN",
    "SSID",
    "VLAN",
    "RSRP",
    "SINR",
    "gRPC",
    "API",
    "syslog",
)
HEDGES = (
    "may",
    "might",
    "probably",
    "appears",
    "seems",
    "likely",
    "possibly",
    "can't yet tell",
    "could",
)
MONITORING_PHRASES = ("can't currently", "cannot currently")


def lint_crew_text(text: str, confidence: Confidence) -> list[str]:
    """Problems with a crew explanation. An empty list means it passes."""
    problems = [f"contains a {name}" for name, pattern in _PATTERNS.items() if pattern.search(text)]
    for word in PROTOCOL_WORDS:
        if re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", text):
            problems.append(f"uses the technical term {word!r}")
    lowered = text.lower()
    if confidence is Confidence.MONITORING_FAILURE:
        if not any(p in lowered for p in MONITORING_PHRASES):
            problems.append(
                "a monitoring failure must say Insight can't currently check, not that something is broken"
            )
    elif confidence is not Confidence.CONFIRMED and not any(
        re.search(rf"\b{re.escape(h)}\b", lowered) for h in HEDGES
    ):
        problems.append(
            f"a {confidence.value} finding must use hedged wording (for example 'may' or 'probably')"
        )
    return problems
