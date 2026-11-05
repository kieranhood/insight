"""Container health endpoint. Reveals no yacht data."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from insight import __version__
from insight.timeutil import to_iso, utcnow

if TYPE_CHECKING:
    from insight.runtime import Runtime

router = APIRouter()


def health_report(runtime: Runtime) -> tuple[bool, dict[str, Any]]:
    """Healthy while the collection scheduler keeps completing cycles."""
    last = runtime.last_cycle_at
    interval = runtime.expected_cycle_interval
    started = runtime.started_at
    now = utcnow()
    limit = timedelta(seconds=interval * runtime.settings.stall_factor)
    if last is None:
        # Allow a grace period after start before the first cycle must have completed.
        healthy = now - started <= limit
    else:
        healthy = now - last <= limit
    body = {
        "status": "ok" if healthy else "unhealthy",
        "version": __version__,
        "last_collection_cycle": to_iso(last),
    }
    return healthy, body


@router.get("/healthz", include_in_schema=False)
async def healthz(request: Request) -> JSONResponse:
    healthy, body = health_report(request.app.state.runtime)
    return JSONResponse(body, status_code=200 if healthy else 503)
