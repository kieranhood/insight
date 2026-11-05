"""Engineer-only control of the simulated yacht (demonstrations and testing on shore)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response

from insight.adapters.simulator import SCENARIOS, SimulatorHub
from insight.web.render import render
from insight.web.security import require_engineer, runtime_of, verify_csrf

router = APIRouter(dependencies=[Depends(require_engineer), Depends(verify_csrf)])


def _hub_names(request: Request) -> list[str]:
    sources = runtime_of(request).sources.list()
    return sorted({str(s.options.get("hub", "default")) for s in sources if s.kind == "simulator"})


@router.get("/engineer/simulator")
async def simulator_page(request: Request) -> Response:
    hubs = _hub_names(request)
    hub = SimulatorHub.get(hubs[0]) if hubs else None
    return render(
        request,
        "engineer/simulator.html",
        {"scenarios": list(SCENARIOS.values()), "hub": hub, "configured": bool(hubs)},
    )


@router.post("/engineer/simulator/load")
async def load(request: Request, scenario: Annotated[str, Form()]) -> Response:
    if scenario in SCENARIOS:
        for name in _hub_names(request):
            SimulatorHub.get(name).load(scenario)
    return RedirectResponse("/engineer/simulator", status_code=303)


@router.post("/engineer/simulator/step")
async def step(request: Request, all_steps: Annotated[str, Form()] = "") -> Response:
    for name in _hub_names(request):
        hub = SimulatorHub.get(name)
        while hub.step() and all_steps:
            pass
    return RedirectResponse("/engineer/simulator", status_code=303)
