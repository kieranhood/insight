"""Identify discovered equipment from observations, using the signature table (data)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

SIGNATURES_PATH = Path(__file__).with_name("signatures.json")


@dataclass(frozen=True)
class Identification:
    type_id: str | None
    confidence: str  # likely, possible, unidentified
    evidence: list[str] = field(default_factory=list)


@cache
def load_table(path: Path = SIGNATURES_PATH) -> dict[str, Any]:
    table: dict[str, Any] = json.loads(path.read_text())
    return table


def type_label(type_id: str) -> str:
    return str(load_table()["types"].get(type_id, {}).get("label", type_id))


def type_info(type_id: str) -> dict[str, Any]:
    info: dict[str, Any] = load_table()["types"].get(type_id, {})
    return info


def _matches(sig: dict[str, Any], obs: dict[str, Any]) -> bool:
    title = str(obs.get("http_title") or "")
    body = str(obs.get("http_body_snippet") or "")
    location = str(obs.get("http_location") or "")
    tls = str(obs.get("tls_subject") or "")
    ports = set(obs.get("open_ports") or [])
    checks: list[bool] = []
    if "oui_vendor" in sig:
        checks.append(obs.get("oui_vendor") == sig["oui_vendor"])
    if "tls_subject_contains" in sig:
        checks.append(sig["tls_subject_contains"].lower() in tls.lower())
    if "http_title_contains" in sig:
        checks.append(sig["http_title_contains"].lower() in title.lower())
    if "http_title_contains_any" in sig:
        checks.append(any(t.lower() in title.lower() for t in sig["http_title_contains_any"]))
    if "http_body_contains" in sig:
        checks.append(sig["http_body_contains"] in body)
    if "http_location_endswith" in sig:
        ok = location.endswith(sig["http_location_endswith"])
        if ok and sig.get("http_location_same_host"):
            ip = str(obs.get("ip") or "")
            ok = "://" not in location or (bool(ip) and f"//{ip}" in location)
        checks.append(ok)
    if "port_open" in sig:
        checks.append(int(sig["port_open"]) in ports)
    if "ip_equals" in sig:
        checks.append(obs.get("ip") == sig["ip_equals"])
    return bool(checks) and all(checks)


def identify(observations: dict[str, Any]) -> Identification:
    """One strong match, or two medium ones, is 'likely'; one medium is 'possible'."""
    table = load_table()
    scores: dict[str, tuple[int, int, list[str]]] = {}
    for sig in table["signatures"]:
        if _matches(sig, observations):
            strong, medium, evidence = scores.get(sig["type"], (0, 0, []))
            if sig["strength"] == "strong":
                strong += 1
            else:
                medium += 1
            scores[sig["type"]] = (strong, medium, [*evidence, sig["what"]])
    best: tuple[int, str, Identification] | None = None
    for type_id, (strong, medium, evidence) in scores.items():
        if strong >= 1 or medium >= 2:
            ident = Identification(type_id, "likely", evidence)
        elif medium == 1:
            ident = Identification(type_id, "possible", evidence)
        else:
            continue
        rank = strong * 10 + medium
        if best is None or rank > best[0]:
            best = (rank, type_id, ident)
    if best is None:
        return Identification(None, "unidentified", [])
    return best[2]
