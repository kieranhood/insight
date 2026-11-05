from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from insight.adapters.starlink import (
    READ_ONLY_REQUESTS,
    ReflectionClient,
    RequestRefused,
    StarlinkDishAdapter,
    check_request,
    parse_history_outages,
    parse_status,
    starlink_link,
)
from insight.collection.adapter import ParseFailed
from insight.model import OnlineState, Reliability
from insight.sources import SourceConfig
from insight.state import StateStore
from insight.timeutil import utcnow
from tests.factories import snap, wan

FIX = Path(__file__).parent / "fixtures" / "starlink"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIX / name).read_text())


# 10.1 -------------------------------------------------------------------------------------
def test_marked_link_attributed_to_starlink() -> None:
    state = StateStore()
    state.configure_source(
        "pep", name="Peplink", kind="peplink", reliability=Reliability.RELIABLE, interval_s=15
    )
    state.apply(
        snap(
            "pep",
            wan_links=[wan("pep", "1", "WAN 1", health_ok=False), wan("pep", "2", "Cellular")],
        )
    )
    link = starlink_link(state, {"source_id": "pep", "link_id": "1"})
    assert link is not None and link.name == "WAN 1" and link.health_ok is False
    assert starlink_link(state, {"source_id": "pep", "link_id": "9"}) is None


def test_unmarked_link_guessed_by_name() -> None:
    state = StateStore()
    state.configure_source(
        "pep", name="Peplink", kind="peplink", reliability=Reliability.RELIABLE, interval_s=15
    )
    state.apply(snap("pep", wan_links=[wan("pep", "1", "Starlink"), wan("pep", "2", "Cellular")]))
    link = starlink_link(state, None)
    assert link is not None and link.link_id == "1"


# 10.2 -------------------------------------------------------------------------------------
def test_parse_ok_status() -> None:
    facts = parse_status(load("get_status_ok.json"))
    assert facts["online"] is True and facts["alerts"] == [] and facts["latency_ms"] is not None
    assert facts["software_version"]


def test_parse_obstructed_status() -> None:
    facts = parse_status(load("get_status_obstructed.json"))
    assert facts["online"] is False and facts["current_outage_cause"] == "OBSTRUCTED"
    assert facts["currently_obstructed"] is True and facts["obstruction_fraction"] == pytest.approx(
        0.087
    )


def test_parse_thermal_alert() -> None:
    assert parse_status(load("get_status_thermal_alert.json"))["alerts"] == ["thermal_throttle"]


def test_parse_history_outages() -> None:
    outages = parse_history_outages(load("get_history_obstruction_outages.json"))
    assert [o["cause"] for o in outages].count("OBSTRUCTED") == 3
    assert outages[1]["switched"] is True and outages[1]["duration_s"] == pytest.approx(7.8)


def test_malformed_response_is_a_parse_failure() -> None:
    with pytest.raises(ParseFailed):
        parse_status({"apiVersion": "43", "somethingElse": {}})


def test_allow_list() -> None:
    assert READ_ONLY_REQUESTS == {"get_status", "get_history", "get_device_info"}
    for forbidden in (
        "reboot",
        "dish_stow",
        "dish_set_config",
        "factory_reset",
        "dish_clear_obstruction_map",
    ):
        with pytest.raises(RequestRefused):
            check_request(forbidden)


def test_no_write_request_names_in_adapter_source() -> None:
    source = (
        (Path(__file__).parents[1] / "insight" / "adapters" / "starlink.py").read_text().lower()
    )
    for name in (
        "reboot",
        "dish_stow",
        "dish_set_",
        "_clear_",
        "factory_reset",
        "set_stow",
        "set_sleep",
    ):
        assert name not in source, name


def dish_source(address: str = "192.168.100.1:9200") -> SourceConfig:
    return SourceConfig(
        id="dish",
        kind="starlink",
        name="Starlink dish",
        address=address,
        reliability=Reliability.OPTIONAL,
    )


async def test_adapter_with_injected_call_and_alert_event() -> None:
    responses = {
        "get_status": load("get_status_thermal_alert.json"),
        "get_history": load("get_history_obstruction_outages.json"),
    }
    sent: list[str] = []

    async def call(kind: str) -> dict[str, Any]:
        sent.append(kind)
        return responses[kind]

    adapter = StarlinkDishAdapter(dish_source(), call=call)
    first = await adapter.collect(utcnow())
    assert first.reliability is Reliability.OPTIONAL
    assert [e.kind for e in first.events] == ["dish_alert"]
    assert first.facts["dish"]["outages"] and first.devices[0].online is OnlineState.ONLINE
    second = await adapter.collect(utcnow())
    assert second.events == []  # same alert, no new event
    assert set(sent) <= READ_ONLY_REQUESTS


async def test_dish_address_configurable_for_peplink_proxy() -> None:
    adapter = StarlinkDishAdapter(dish_source("192.168.50.1:9201"), call=lambda kind: None)  # type: ignore[arg-type,return-value]
    assert adapter.address == "192.168.50.1:9201"
    assert (
        StarlinkDishAdapter(dish_source("192.168.100.1"), call=lambda k: None).address
        == "192.168.100.1:9200"
    )  # type: ignore[arg-type,return-value]


async def test_reflection_client_against_fake_dish() -> None:
    from tests.fake_dish import start_fake_dish

    server, port, received = await start_fake_dish()
    client = ReflectionClient(f"127.0.0.1:{port}")
    try:
        response = await client("get_status")
        assert response["dishGetStatus"]["deviceInfo"]["id"] == "ut0000-fake"
        assert response["dishGetStatus"]["popPingLatencyMs"] == pytest.approx(41.5)
        with pytest.raises(RequestRefused):
            await client("dish_stow")
        assert received == ["get_status"]  # the stow request never left Insight
    finally:
        await client.close()
        await server.stop(None)
