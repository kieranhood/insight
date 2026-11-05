from __future__ import annotations

from urllib.parse import quote

from fastapi.testclient import TestClient

from insight import __version__
from insight.inventory import Service
from insight.runtime import Runtime
from tests.conftest import page_csrf
from tests.sim import Sim


async def scenario(runtime: Runtime, name: str) -> Sim:
    sim = Sim(runtime, name)
    await sim.play(cycles_per_step=12)
    runtime.writer.flush_sync()
    return sim


# 18.1 --------------------------------------------------------------------------------------
async def test_finding_detail_with_evidence(runtime: Runtime, engineer: TestClient) -> None:
    await scenario(runtime, "ap_poe_loss")
    finding = next(f for f in runtime.findings.open() if f.rule_id == "ap_lost_poe")
    listing = engineer.get("/engineer/findings").text
    assert f"/engineer/findings/{finding.id}" in listing
    html = engineer.get(f"/engineer/findings/{finding.id}").text
    for text in (
        "ap_lost_poe",
        "confirmed",
        "Evidence",
        "SW-LD-01 port 1",
        "PoE 0.0 W",
        "Suggested checks",
        "Likely causes",
        "What crew see",
    ):
        assert text in html, text
    assert "Simulated unifi" in html  # evidence names its source
    assert engineer.get("/engineer/findings?status=resolved").status_code == 200
    assert engineer.get("/engineer/findings/99999").status_code == 404


# 18.2 --------------------------------------------------------------------------------------
async def test_inventory_search_and_device_detail(runtime: Runtime, engineer: TestClient) -> None:
    await scenario(runtime, "baseline")
    html = engineer.get("/engineer/inventory?q=10.20.0.12").text
    assert "SW-LD-01" in html and "SW-MAIN-01" not in html
    by_category = engineer.get("/engineer/inventory?category=access_point").text
    assert "AP-SALOON" in by_category and "SW-LD-01" not in by_category
    key = "mac:f0:9f:c2:00:00:20"
    detail = engineer.get(f"/engineer/inventory/{quote(key, safe='')}").text
    assert "Ports" in detail and "7.4 W" in detail and "AP-CAB4" in detail
    assert "Behind this device" in detail
    assert "data-chart=" in detail and "poe" in detail


async def test_device_tags_and_attachment(runtime: Runtime, engineer: TestClient) -> None:
    await scenario(runtime, "baseline")
    key = "mac:24:79:2a:00:00:02"
    token = page_csrf(engineer, "/engineer/inventory")
    engineer.post(
        f"/engineer/inventory/{quote(key, safe='')}/tags",
        data={"csrf_token": token, "location": "Main deck, dining", "display_name": "Dining AP"},
    )
    item = runtime.inventory.get(key)
    assert item is not None and item.location == "Main deck, dining" and item.label == "Dining AP"
    engineer.post(
        f"/engineer/inventory/{quote(key, safe='')}/attachment",
        data={"csrf_token": token, "switch": "mac:f0:9f:c2:00:00:10", "port": "9"},
    )
    assert runtime.inventory.topology_overrides()[key] == ("mac:f0:9f:c2:00:00:10", "9")


# 18.3 --------------------------------------------------------------------------------------
async def test_wan_view_and_timeline(runtime: Runtime, engineer: TestClient) -> None:
    await scenario(runtime, "failover")
    wan = engineer.get("/engineer/wan").text
    assert wan.find("Starlink") < wan.find("Cellular")  # side by side, by priority
    assert "IN USE" in wan and "disconnected" in wan and "RSRP" in wan
    assert "Internet traffic moved from Starlink to Cellular" in wan
    timeline = engineer.get("/engineer/timeline?hours=24&kind=failover").text
    assert "Internet traffic moved from Starlink to Cellular" in timeline
    assert '<span class="tag">finding_opened</span>' not in timeline
    by_service = engineer.get("/engineer/timeline?hours=24&service=internet").text
    assert "status_change" in by_service


# 18.4 --------------------------------------------------------------------------------------
async def test_sources_view_with_failing_optional_source(
    runtime: Runtime, engineer: TestClient
) -> None:
    await scenario(runtime, "ruckus_web_broken")
    html = engineer.get("/engineer/sources").text
    row = html[html.find("Simulated ruckus-web") :][:1200]
    assert "optional" in row and "FAILING" in row and "simulated outage" in row
    assert __version__ in engineer.get("/engineer").text


# 18.5 --------------------------------------------------------------------------------------
async def test_settings_save_and_take_effect(runtime: Runtime, engineer: TestClient) -> None:
    await scenario(runtime, "baseline")
    token = page_csrf(engineer, "/engineer/settings")
    r = engineer.post(
        "/engineer/settings/general",
        data={
            "csrf_token": token,
            "ship_timezone": "Europe/Monaco",
            "retention_detail_days": "45",
            "retention_summary_days": "400",
        },
    )
    assert r.status_code == 303
    assert (
        runtime.config.get("ship_timezone") == "Europe/Monaco"
        and runtime.config.get("retention_detail_days") == 45
    )
    assert "CET" in engineer.get("/engineer").text or "CEST" in engineer.get("/engineer").text
    engineer.post(
        "/engineer/settings/probes",
        data={
            "csrf_token": token,
            "internet_targets": "1.1.1.1\n9.9.9.9",
            "dns_names": "example.com",
            "dns_public_resolver": "9.9.9.9",
            "http_urls": "http://example.com/",
            "device_interval": "45",
            "failure_threshold": "4",
            "dish_address": "192.168.50.1:9201",
        },
    )
    assert runtime.config.get("probe_internet_targets") == ["1.1.1.1", "9.9.9.9"]
    assert runtime.config.get("starlink_dish_address") == "192.168.50.1:9201"
    engineer.post(
        "/engineer/settings/services",
        data={"csrf_token": token, "ssid_guest_wifi": ["Guest", "Crew"]},
    )
    assert runtime.inventory.mappings()[Service.GUEST_WIFI]["ssid"] == {"Guest", "Crew"}
    assert runtime.inventory.mappings()[Service.CREW_WIFI]["ssid"] == set()
    engineer.post(
        "/engineer/settings/starlink", data={"csrf_token": token, "link": "sim-peplink|1"}
    )
    assert runtime.config.get("starlink_wan") == {"source_id": "sim-peplink", "link_id": "1"}
    engineer.post(
        "/engineer/settings/users",
        data={
            "csrf_token": token,
            "username": "deckhand",
            "password": "a long enough password",
            "role": "crew",
        },
    )
    assert any(u.username == "deckhand" for u in runtime.accounts.list())
    bad = engineer.post(
        "/engineer/settings/general",
        data={
            "csrf_token": token,
            "ship_timezone": "Mars/Base",
            "retention_detail_days": "30",
            "retention_summary_days": "365",
        },
    )
    assert "error=" in bad.headers["location"]


async def test_add_source_through_ui(runtime: Runtime, engineer: TestClient) -> None:
    form = engineer.get("/engineer/sources/new?kind=simulator&address=peplink").text
    assert "Simulator" in form
    token = page_csrf(engineer, "/engineer/sources/new?kind=simulator")
    r = engineer.post(
        "/engineer/sources",
        data={
            "csrf_token": token,
            "kind": "simulator",
            "name": "Demo router",
            "address": "peplink",
        },
    )
    assert r.status_code == 303
    saved = [s for s in runtime.sources.list() if s.name == "Demo router"]
    assert saved and saved[0].id in runtime.scheduler.adapters
    failing = engineer.post(
        "/engineer/sources",
        data={
            "csrf_token": token,
            "kind": "peplink",
            "name": "Router",
            "address": "https://127.0.0.1:1",
            "cred_client_id": "x",
            "cred_client_secret": "y",
        },
    )
    assert failing.status_code == 400 and "could not reach Router" in failing.text


# 18.6 --------------------------------------------------------------------------------------
async def test_pages_stay_small_for_slow_links(runtime: Runtime, engineer: TestClient) -> None:
    await scenario(runtime, "ap_poe_loss")
    for path in [
        "/engineer",
        "/engineer/findings",
        "/engineer/timeline?hours=168",
        "/engineer/wan",
        "/engineer/inventory",
        "/",
    ]:
        size = len(engineer.get(path).content)
        assert size < 200_000, (path, size)
    readings = engineer.get(
        "/api/engineer/readings?subject=probe:internet&name=rtt_ms&range=1h"
    ).json()
    assert readings["x"] and len(readings["x"]) <= 600
