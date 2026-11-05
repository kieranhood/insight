"""Crew dashboard routes: plain-English status for the captain and crew."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse

from insight.auth.accounts import User
from insight.diagnostics import Action
from insight.timeutil import utcnow
from insight.web.render import render
from insight.web.security import require_user, runtime_of

router = APIRouter()

ACTIONS = {
    Action.NONE: ("none", "Nothing needs to be done on board."),
    Action.CHECK: ("check", "A simple check can be made on board: ask the ETO."),
    Action.CONTACT: ("contact", "Contact the ETO or 50N support."),
}
STALE_AFTER = timedelta(minutes=3)


def board_context(request: Request) -> dict[str, Any]:
    runtime = runtime_of(request)
    now = utcnow()
    report = runtime.last_report or runtime.health(now)
    open_findings = runtime.findings.open()
    issues = [f for f in open_findings if f.rule_id != "monitoring_source_unavailable"]
    monitoring = [f for f in open_findings if f.rule_id == "monitoring_source_unavailable"]
    last = runtime.last_evaluated_at
    stale = last is None or now - last > STALE_AFTER
    return {
        "report": report,
        "issues": issues,
        "monitoring": monitoring,
        "resolved": runtime.findings.resolved_since(timedelta(hours=24), now),
        "actions": ACTIONS,
        "last_updated": last,
        "stale": stale,
    }


@router.get("/")
async def dashboard(request: Request, user: User = Depends(require_user)) -> Response:  # noqa: B008
    return render(request, "crew/dashboard.html", board_context(request))


@router.get("/partials/board")
async def board(request: Request, user: User = Depends(require_user)) -> Response:  # noqa: B008
    return render(request, "crew/_board.html", board_context(request))


@router.get("/events/stream")
async def stream(request: Request, user: User = Depends(require_user)) -> StreamingResponse:  # noqa: B008
    runtime = runtime_of(request)

    async def events() -> AsyncIterator[bytes]:
        seen = runtime.version
        idle = 0.0
        yield b"retry: 10000\n\n"
        while True:
            if await request.is_disconnected():
                return
            if runtime.version != seen:
                seen = runtime.version
                idle = 0.0
                yield b"event: refresh\ndata: {}\n\n"
            elif idle >= 20:
                idle = 0.0
                yield b": keep-alive\n\n"
            await asyncio.sleep(2)
            idle += 2

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
    )
