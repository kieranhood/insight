from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from insight import __version__
from insight.runtime import Runtime
from insight.timeutil import utcnow
from insight.web.app import create_app


def test_healthz_reports_version_and_cycle_only(runtime: Runtime) -> None:
    runtime.record_cycle()
    client = TestClient(create_app(runtime))
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["last_collection_cycle"] is not None
    # No yacht data: only these three keys are ever returned.
    assert set(body) == {"status", "version", "last_collection_cycle"}


def test_healthz_grace_period_before_first_cycle(runtime: Runtime) -> None:
    client = TestClient(create_app(runtime))
    assert client.get("/healthz").status_code == 200


def test_healthz_unhealthy_when_no_cycle_after_grace(runtime: Runtime) -> None:
    runtime.started_at = utcnow() - timedelta(hours=1)
    client = TestClient(create_app(runtime))
    response = client.get("/healthz")
    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"


async def test_stalled_scheduler_reports_unhealthy(runtime: Runtime) -> None:
    import asyncio

    from tests.test_scheduler import Fake, source

    runtime.scheduler.add(Fake(source("fast", interval=0.05)))
    client = TestClient(create_app(runtime))
    await runtime.start_background()
    await asyncio.sleep(0.3)
    assert client.get("/healthz").status_code == 200
    assert runtime.last_cycle_at is not None
    # Stall collection: no cycles complete any more.
    await runtime.scheduler.stop()
    await asyncio.sleep(0.4)
    response = client.get("/healthz")
    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"
    await runtime.stop_background()
