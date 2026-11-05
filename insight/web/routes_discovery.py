"""Engineer discovery screens: subnets, runs, and reviewing what was found."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response

from insight.auth.accounts import User
from insight.discovery.fingerprint import type_info
from insight.discovery.sweep import SweepError, plan
from insight.model import DeviceCategory
from insight.web.render import render
from insight.web.security import require_engineer, runtime_of, verify_csrf

router = APIRouter(dependencies=[Depends(require_engineer), Depends(verify_csrf)])


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.replace(",", "\n").splitlines() if line.strip()]


def _setup_link(likely_type: str | None, confidence: str, ip: str | None) -> str | None:
    if not likely_type or confidence == "unidentified" or not ip:
        return None
    info = type_info(likely_type)
    kind, template = info.get("source_kind"), info.get("address_template")
    if not kind or not template:
        return None
    return "/engineer/sources/new?" + urlencode({"kind": kind, "address": template.format(ip=ip)})


def _page(request: Request, **extra: object) -> Response:
    runtime = runtime_of(request)
    discovery = runtime.discovery
    new = discovery.new_items()
    suggested = []
    for status in runtime.state.sources.values():
        suggested.extend(runtime.state.facts(status.source_id).get("lan_subnets", []))
    context = {
        "new": new,
        "dismissed": discovery.all("dismissed"),
        "setups": {d.key: _setup_link(d.likely_type, d.confidence, d.ip) for d in new},
        "selected": runtime.config.get("discovery_selected_subnets"),
        "excluded": runtime.config.get("discovery_excluded_subnets"),
        "suggested": sorted(set(suggested)),
        "run": runtime.discovery_run,
        "categories": list(DeviceCategory),
        **extra,
    }
    return render(
        request, "engineer/discovery.html", context, status_code=400 if "error" in extra else 200
    )


@router.get("/engineer/discovery")
async def discovery_page(request: Request) -> Response:
    return _page(request)


@router.post("/engineer/discovery/subnets")
async def save_subnets(
    request: Request, selected: Annotated[str, Form()] = "", excluded: Annotated[str, Form()] = ""
) -> Response:
    runtime = runtime_of(request)
    chosen, never = _lines(selected), _lines(excluded)
    if chosen:
        try:
            plan(chosen, never)
        except SweepError as exc:
            return _page(request, error=str(exc))
    runtime.config.set("discovery_selected_subnets", chosen)
    runtime.config.set("discovery_excluded_subnets", never)
    return RedirectResponse("/engineer/discovery", status_code=303)


@router.post("/engineer/discovery/run")
async def start_run(request: Request, user: User = Depends(require_engineer)) -> Response:  # noqa: B008
    try:
        await runtime_of(request).start_discovery_run(user.username)
    except SweepError as exc:
        return _page(request, error=str(exc))
    return RedirectResponse("/engineer/discovery", status_code=303)


@router.post("/engineer/discovery/cancel")
async def cancel_run(request: Request) -> Response:
    runtime_of(request).cancel_discovery_run()
    return RedirectResponse("/engineer/discovery", status_code=303)


@router.post("/engineer/discovery/{key}/accept")
async def accept(
    request: Request,
    key: str,
    name: Annotated[str, Form()],
    category: Annotated[str, Form()] = "other",
) -> Response:
    try:
        device_key = runtime_of(request).discovery.accept(
            key, name=name, category=DeviceCategory(category)
        )
    except (KeyError, ValueError) as exc:
        return _page(request, error=str(exc))
    return RedirectResponse(f"/engineer/inventory/{quote(device_key, safe='')}", status_code=303)


@router.post("/engineer/discovery/{key}/dismiss")
async def dismiss(request: Request, key: str) -> Response:
    runtime_of(request).discovery.dismiss(key)
    return RedirectResponse("/engineer/discovery", status_code=303)


@router.post("/engineer/discovery/{key}/restore")
async def restore(request: Request, key: str) -> Response:
    runtime_of(request).discovery.restore(key)
    return RedirectResponse("/engineer/discovery", status_code=303)
