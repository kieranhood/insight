from __future__ import annotations

import re

from fastapi.testclient import TestClient

from insight.runtime import Runtime
from tests.sim import Sim

EXTERNAL = re.compile(r"""(?:src|href|action)\s*=\s*["'](?:https?:)?//""", re.I)


def test_pages_load_no_external_assets(runtime: Runtime, engineer: TestClient) -> None:
    for path in ["/", "/signin", "/about", "/engineer", "/engineer/discovery"]:
        html = engineer.get(path).text
        assert not EXTERNAL.search(html), path
    css = engineer.get("/static/css/insight.css").text
    assert "url(http" not in css and "@import" not in css
    for asset in (
        "/static/js/htmx.min.js",
        "/static/js/uPlot.iife.min.js",
        "/static/js/insight.js",
    ):
        assert engineer.get(asset).status_code == 200


async def test_status_first_then_issues(runtime: Runtime, crew: TestClient) -> None:
    sim = Sim(runtime, "failover")
    await sim.play(cycles_per_step=12)
    html = crew.get("/").text
    overall, services, issues = (
        html.find("Yacht systems"),
        html.find("Guest Wi-Fi"),
        html.find("Active issues"),
    )
    assert -1 < overall < services < issues
    assert "status-DEGRADED" in html
    assert "1 active issue." in html
    assert "Running on the backup internet connection" in html
    assert "main internet connection (Starlink) is unavailable" in html
    assert "Nothing needs to be done on board." in html
    assert "Guests affected" in html


async def test_no_jargon_for_crew(runtime: Runtime, crew: TestClient) -> None:
    sim = Sim(runtime, "ap_poe_loss")
    await sim.play(cycles_per_step=12)
    html = crew.get("/").text
    assert "Lower deck, guest cabin 4" in html
    for jargon in ("10.20.", "24:79:2a", "port 1", "PoE", "SW-LD-01"):
        assert jargon not in html, jargon
    assert "A simple check can be made on board" in html


async def test_monitoring_unavailable_is_not_a_fault(runtime: Runtime, crew: TestClient) -> None:
    sim = Sim(runtime, "baseline")
    await sim.settle(4)
    sim.hub.world.down_roles.update({"ruckus-snmp", "ruckus-web"})
    await sim.settle(10)
    html = crew.get("/").text
    assert "Insight can&#39;t currently check" in html or "Insight can't currently check" in html
    assert "Wi-Fi is down" not in html


async def test_recently_resolved_and_partial(runtime: Runtime, crew: TestClient) -> None:
    sim = Sim(runtime, "failover")
    await sim.play(cycles_per_step=12)
    sim.hub.load("baseline")
    await sim.settle(12)
    html = crew.get("/partials/board").text
    assert "No active issues." in html
    resolved = html[html.find("Resolved in the last 24 hours") :]
    assert "Running on the backup internet connection" in resolved
    assert 'hx-trigger="insight:refresh from:body"' in html


def test_stale_notice_before_any_evaluation(runtime: Runtime, crew: TestClient) -> None:
    html = crew.get("/").text
    assert "may be out of date" in html
    assert "data-live" in html


async def test_live_stream_requires_sign_in(client: TestClient) -> None:
    assert client.get("/events/stream").status_code in (303, 401)
