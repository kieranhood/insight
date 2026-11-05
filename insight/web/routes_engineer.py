"""Engineer console routes. Every route here requires the engineer role."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any
from urllib.parse import quote
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from insight import __version__
from insight.auth.accounts import AccountError, Role, User
from insight.collection import registry
from insight.diagnostics.context import SYSTEM_NAMES
from insight.inventory import Service
from insight.model import DeviceCategory, Reliability
from insight.setup import add_source
from insight.state import SourceState
from insight.timeutil import utcnow
from insight.web.render import render
from insight.web.security import require_engineer, runtime_of, verify_csrf

router = APIRouter(dependencies=[Depends(require_engineer), Depends(verify_csrf)])

RANGES = {"1h": 1, "6h": 6, "24h": 24, "7d": 168, "30d": 720}


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def _source_rows(request: Request) -> list[dict[str, Any]]:
    runtime = runtime_of(request)
    rows = []
    configs = {s.id: s for s in runtime.sources.list()}
    for source_id, status in runtime.state.sources.items():
        config = configs.get(source_id)
        rows.append(
            {
                "id": source_id,
                "name": status.name,
                "kind": runtime.source_kinds().get(source_id, status.kind),
                "reliability": status.reliability.value,
                "state": status.state.value,
                "fresh": runtime.state.is_fresh(source_id),
                "last_success_at": status.last_success_at,
                "last_error": status.last_error,
                "last_error_at": status.last_error_at,
                "failure_kind": status.failure_kind.value if status.failure_kind else None,
                "optional_errors": runtime.state.facts(source_id).get("optional_errors") or {},
                "address": config.address if config else "built in",
                "enabled": config.enabled if config else True,
                "configurable": config is not None,
            }
        )
    for source_id, config in configs.items():
        if source_id not in runtime.state.sources:
            rows.append(
                {
                    "id": source_id,
                    "name": config.name,
                    "kind": config.kind,
                    "reliability": config.reliability.value,
                    "state": "disabled" if not config.enabled else SourceState.NEVER.value,
                    "fresh": False,
                    "last_success_at": None,
                    "last_error": None,
                    "last_error_at": None,
                    "failure_kind": None,
                    "optional_errors": {},
                    "address": config.address,
                    "enabled": config.enabled,
                    "configurable": True,
                }
            )
    return sorted(rows, key=lambda r: (r["reliability"] != "reliable", r["name"]))


# -- overview ----------------------------------------------------------------------------
@router.get("/engineer")
async def home(request: Request) -> Response:
    runtime = runtime_of(request)
    return render(
        request,
        "engineer/home.html",
        {
            "report": runtime.last_report or runtime.health(),
            "open": runtime.findings.open(),
            "sources": _source_rows(request),
            "version": __version__,
            "disk": runtime.disk_status,
            "last_evaluated_at": runtime.last_evaluated_at,
        },
    )


# -- findings ------------------------------------------------------------------------------
@router.get("/engineer/findings")
async def findings(request: Request, status: str = "open") -> Response:
    store = runtime_of(request).findings
    items = (
        store.open()
        if status == "open"
        else store.query(status=None if status == "all" else status, limit=300)
    )
    return render(request, "engineer/findings.html", {"findings": items, "status": status})


@router.get("/engineer/findings/{finding_id}")
async def finding_detail(request: Request, finding_id: int) -> Response:
    runtime = runtime_of(request)
    finding = runtime.findings.get(finding_id)
    if finding is None:
        return render(request, "engineer/not_found.html", {"what": "That finding"}, status_code=404)
    rule = runtime.engine.rules.get(finding.rule_id)
    names = {k: runtime.eval_context().device_name(k) for k in finding.devices}
    return render(
        request,
        "engineer/finding.html",
        {
            "f": finding,
            "rule": rule,
            "device_names": names,
            "source_names": {s: st.name for s, st in runtime.state.sources.items()},
        },
    )


# -- inventory -------------------------------------------------------------------------------
@router.get("/engineer/inventory")
async def inventory(
    request: Request, q: str = "", category: str = "", monitoring: str = ""
) -> Response:
    runtime = runtime_of(request)
    devices = sorted(
        runtime.inventory.devices().values(), key=lambda d: (d.category.value, d.label.lower())
    )
    needle = q.strip().lower()
    if needle:
        devices = [
            d
            for d in devices
            if any(
                needle in (v or "").lower()
                for v in (d.label, d.name, d.ip, d.mac, d.model, d.location, d.serial)
            )
        ]
    if category:
        devices = [d for d in devices if d.category.value == category]
    if monitoring:
        devices = [d for d in devices if d.monitoring_status == monitoring]
    reach = runtime.eval_context().probe("device")
    return render(
        request,
        "engineer/inventory.html",
        {
            "devices": devices,
            "q": q,
            "category": category,
            "monitoring": monitoring,
            "categories": list(DeviceCategory),
            "reach": reach,
        },
    )


@router.post("/engineer/inventory/manual")
async def add_manual(
    request: Request,
    name: Annotated[str, Form()],
    ip: Annotated[str, Form()],
    category: Annotated[str, Form()] = "other",
    location: Annotated[str, Form()] = "",
) -> Response:
    try:
        item = runtime_of(request).inventory.add_manual(
            name, ip, DeviceCategory(category), location or None
        )
    except ValueError as exc:
        return render(request, "engineer/not_found.html", {"what": str(exc)}, status_code=400)
    return _redirect(f"/engineer/inventory/{quote(item.key, safe='')}")


@router.get("/engineer/inventory/{key}")
async def device_detail(request: Request, key: str, range: str = "24h") -> Response:
    runtime = runtime_of(request)
    device = runtime.inventory.get(key)
    if device is None:
        return render(request, "engineer/not_found.html", {"what": "That device"}, status_code=404)
    ctx = runtime.eval_context()
    ports = sorted(
        runtime.state.ports(key), key=lambda p: int(p.port_id) if p.port_id.isdigit() else 0
    )
    neighbours = {
        p.port_id: runtime.inventory.find_by_mac(p.neighbour_mac) for p in ports if p.neighbour_mac
    }
    subjects = [f"device:{key}", f"probe:device:{key}"] + [f"port:{key}:{p.port_id}" for p in ports]
    series = [s for subject in subjects for s in runtime.history.series_list(subject)]
    topology = ctx.topology()
    attachment = topology.parent(key)
    switches = [
        d for d in runtime.inventory.devices().values() if d.category is DeviceCategory.SWITCH
    ]
    return render(
        request,
        "engineer/device.html",
        {
            "d": device,
            "merged": runtime.state.devices().get(key),
            "ports": ports,
            "neighbours": neighbours,
            "series": series,
            "range": range if range in RANGES else "24h",
            "ranges": list(RANGES),
            "findings": runtime.findings.for_device(key, limit=20),
            "events": runtime.history.timeline(
                device=key, start=utcnow() - timedelta(days=7), limit=50
            ),
            "reach": ctx.probe("device").get(key),
            "attachment": attachment,
            "attachment_name": ctx.device_name(attachment.parent_key) if attachment else None,
            "downstream": [(k, ctx.device_name(k)) for k in topology.downstream(key)],
            "switches": switches,
            "services": [Service(s).label for s in ctx.services_for_device(key)],
            "categories": list(DeviceCategory),
        },
    )


@router.post("/engineer/inventory/{key}/tags")
async def save_tags(
    request: Request,
    key: str,
    location: Annotated[str, Form()] = "",
    display_name: Annotated[str, Form()] = "",
) -> Response:
    runtime_of(request).inventory.set_tags(key, location=location, display_name=display_name)
    return _redirect(f"/engineer/inventory/{quote(key, safe='')}")


@router.post("/engineer/inventory/{key}/attachment")
async def save_attachment(
    request: Request,
    key: str,
    switch: Annotated[str, Form()] = "",
    port: Annotated[str, Form()] = "",
) -> Response:
    runtime_of(request).inventory.set_topology_override(key, switch or None, port or None)
    return _redirect(f"/engineer/inventory/{quote(key, safe='')}")


@router.post("/engineer/inventory/{key}/remove")
async def remove_device(request: Request, key: str) -> Response:
    runtime_of(request).inventory.remove(key)
    return _redirect("/engineer/inventory")


# -- WAN -------------------------------------------------------------------------------------
@router.get("/engineer/wan")
async def wan(request: Request, range: str = "24h") -> Response:
    runtime = runtime_of(request)
    links = sorted(
        runtime.state.wan_links(),
        key=lambda lk: (lk.priority if lk.priority is not None else 99, lk.name),
    )
    starlink = runtime.eval_context().starlink()
    rows = []
    for link in links:
        subject = f"wan:{link.source_id}:{link.link_id}"
        rows.append(
            {
                "link": link,
                "subject": subject,
                "series": runtime.history.series_list(subject),
                "is_starlink": starlink is not None
                and starlink.link_id == link.link_id
                and starlink.source_id == link.source_id,
            }
        )
    probe = runtime.eval_context().probe("internet")
    return render(
        request,
        "engineer/wan.html",
        {
            "rows": rows,
            "probe": probe,
            "range": range if range in RANGES else "24h",
            "ranges": list(RANGES),
            "failovers": runtime.history.timeline(
                kinds=["failover", "wan_state_change"], start=utcnow() - timedelta(days=7), limit=50
            ),
            "dish": next(
                (
                    runtime.state.facts(sid)["dish"]
                    for sid in runtime.state.sources
                    if runtime.state.facts(sid).get("dish")
                ),
                None,
            ),
        },
    )


# -- timeline ----------------------------------------------------------------------------------
@router.get("/engineer/timeline")
async def timeline(
    request: Request,
    hours: int = 24,
    system: str = "",
    device: str = "",
    service: str = "",
    kind: str = "",
) -> Response:
    runtime = runtime_of(request)
    hours = max(1, min(hours, 24 * 365))
    end = utcnow()
    events = runtime.history.timeline(
        start=end - timedelta(hours=hours),
        end=end,
        system=system or None,
        device=device or None,
        service=service or None,
        kinds=[kind] if kind else None,
        limit=500,
    )
    return render(
        request,
        "engineer/timeline.html",
        {
            "events": events,
            "hours": hours,
            "system": system,
            "device": device,
            "service": service,
            "kind": kind,
            "kinds": runtime.history.event_kinds(),
            "systems": sorted({*SYSTEM_NAMES, "ruckus", "insight"}),
            "services": list(Service),
        },
    )


# -- sources -----------------------------------------------------------------------------------
@router.get("/engineer/sources")
async def sources(request: Request) -> Response:
    return render(
        request,
        "engineer/sources.html",
        {"rows": _source_rows(request), "kinds": registry.available()},
    )


def _source_form(request: Request, **context: Any) -> Response:
    kinds = [i for i in registry.available() if i.kind != "probes"]
    return render(
        request,
        "engineer/source_form.html",
        {"kinds": kinds, **context},
        status_code=400 if context.get("error") else 200,
    )


@router.get("/engineer/sources/new")
async def new_source(request: Request, kind: str = "peplink", address: str = "") -> Response:
    try:
        info = registry.adapter_class(kind).info
    except KeyError:
        info = registry.adapter_class("peplink").info
    return _source_form(request, info=info, source=None, address=address, name="", interval="")


@router.get("/engineer/sources/{source_id}")
async def edit_source(request: Request, source_id: str) -> Response:
    source = runtime_of(request).sources.get(source_id)
    if source is None:
        return render(request, "engineer/not_found.html", {"what": "That source"}, status_code=404)
    info = registry.adapter_class(source.kind).info
    return _source_form(
        request,
        info=info,
        source=source.public(),
        address=source.address,
        name=source.name,
        interval=source.interval_s or "",
    )


async def _save_source(request: Request, source_id: str | None) -> Response:
    runtime = runtime_of(request)
    form = await request.form()
    kind = str(form.get("kind", ""))
    try:
        info = registry.adapter_class(kind).info
    except KeyError:
        return _source_form(
            request,
            info=registry.adapter_class("peplink").info,
            source=None,
            error="Choose a source type.",
        )
    credentials = {f.name: str(form.get(f"cred_{f.name}", "")) for f in info.credentials}
    options: dict[str, Any] = {}
    existing = runtime.sources.get(source_id) if source_id else None
    if existing:
        options.update(existing.options)
    if kind == "simulator":
        options["role"] = str(form.get("address", ""))
    interval = str(form.get("interval_s", "")).strip()
    result = await add_source(
        runtime.sources,
        kind=kind,
        name=str(form.get("name", "")),
        address=str(form.get("address", "")),
        credentials=credentials,
        options=options,
        interval_s=float(interval) if interval else None,
        source_id=source_id,
    )
    if not result.ok or result.source is None:
        return _source_form(
            request,
            info=info,
            source=existing.public() if existing else None,
            address=str(form.get("address", "")),
            name=str(form.get("name", "")),
            interval=interval,
            error=result.message,
        )
    await runtime.apply_source(result.source.id)
    return _redirect("/engineer/sources")


@router.post("/engineer/sources")
async def create_source(request: Request) -> Response:
    return await _save_source(request, None)


@router.post("/engineer/sources/{source_id}")
async def update_source(request: Request, source_id: str) -> Response:
    return await _save_source(request, source_id)


@router.post("/engineer/sources/{source_id}/delete")
async def delete_source(request: Request, source_id: str) -> Response:
    runtime = runtime_of(request)
    runtime.sources.delete(source_id)
    await runtime.scheduler.remove(source_id)
    return _redirect("/engineer/sources")


@router.post("/engineer/sources/{source_id}/toggle")
async def toggle_source(request: Request, source_id: str) -> Response:
    runtime = runtime_of(request)
    source = runtime.sources.get(source_id)
    if source is not None:
        source.enabled = not source.enabled
        runtime.sources.save(source)
        await runtime.apply_source(source_id)
    return _redirect("/engineer/sources")


# -- settings -----------------------------------------------------------------------------------
@router.get("/engineer/settings")
async def settings_page(request: Request, saved: str = "", error: str = "") -> Response:
    runtime = runtime_of(request)
    ctx = runtime.eval_context()
    ssids = sorted(
        {n.ssid for n in runtime.state.wifi_networks()}
        | {s for m in runtime.inventory.mappings().values() for s in m["ssid"]}
    )
    return render(
        request,
        "engineer/settings.html",
        {
            "config": runtime.config.all(),
            "mappings": runtime.inventory.mappings(),
            "services": list(Service),
            "ssids": ssids,
            "unmapped": runtime.inventory.unmapped_ssids(runtime.state),
            "links": runtime.state.wan_links(),
            "starlink": ctx.starlink(),
            "users": runtime.accounts.list(),
            "timezones": sorted(available_timezones()),
            "saved": saved,
            "error": error,
        },
    )


def _floats(text: str) -> list[str]:
    return [line.strip() for line in text.replace(",", "\n").splitlines() if line.strip()]


@router.post("/engineer/settings/general")
async def save_general(
    request: Request,
    ship_timezone: Annotated[str, Form()],
    retention_detail_days: Annotated[int, Form()],
    retention_summary_days: Annotated[int, Form()],
) -> Response:
    config = runtime_of(request).config
    if ship_timezone not in available_timezones():
        return _redirect("/engineer/settings?error=Unknown+time+zone")
    if not (1 <= retention_detail_days <= 3650 and 30 <= retention_summary_days <= 3650):
        return _redirect("/engineer/settings?error=Retention+out+of+range")
    config.set("ship_timezone", ship_timezone)
    config.set("retention_detail_days", retention_detail_days)
    config.set("retention_summary_days", retention_summary_days)
    return _redirect("/engineer/settings?saved=general")


@router.post("/engineer/settings/probes")
async def save_probes(
    request: Request,
    internet_targets: Annotated[str, Form()],
    dns_names: Annotated[str, Form()],
    dns_public_resolver: Annotated[str, Form()],
    http_urls: Annotated[str, Form()],
    device_interval: Annotated[int, Form()],
    failure_threshold: Annotated[int, Form()],
    dish_address: Annotated[str, Form()] = "192.168.100.1:9200",
) -> Response:
    config = runtime_of(request).config
    targets, names, urls = _floats(internet_targets), _floats(dns_names), _floats(http_urls)
    if not targets or not names or not urls:
        return _redirect("/engineer/settings?error=Each+probe+list+needs+at+least+one+entry")
    config.set("probe_internet_targets", targets)
    config.set("probe_dns_names", names)
    config.set("probe_dns_public_resolver", dns_public_resolver.strip())
    config.set("probe_http_urls", urls)
    config.set("probe_device_interval_s", max(10, device_interval))
    config.set("probe_internet_interval_s", max(10, device_interval))
    config.set("probe_failure_threshold", max(1, failure_threshold))
    config.set("starlink_dish_address", dish_address.strip() or "192.168.100.1:9200")
    return _redirect("/engineer/settings?saved=probes")


@router.post("/engineer/settings/services")
async def save_services(request: Request) -> Response:
    runtime = runtime_of(request)
    form = await request.form()
    for service in Service:
        if service is Service.INTERNET:
            continue
        chosen = {str(v) for v in form.getlist(f"ssid_{service.value}")}
        current = runtime.inventory.mappings()[service]["ssid"]
        for ssid in current - chosen:
            runtime.inventory.unmap(service, "ssid", ssid)
        for ssid in chosen - current:
            runtime.inventory.map(service, "ssid", ssid)
    return _redirect("/engineer/settings?saved=services")


@router.post("/engineer/settings/starlink")
async def save_starlink(request: Request, link: Annotated[str, Form()] = "") -> Response:
    config = runtime_of(request).config
    if link:
        source_id, _, link_id = link.partition("|")
        config.set("starlink_wan", {"source_id": source_id, "link_id": link_id})
    else:
        config.set("starlink_wan", None)
    return _redirect("/engineer/settings?saved=starlink")


@router.post("/engineer/settings/users")
async def create_user(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    role: Annotated[str, Form()] = "crew",
) -> Response:
    try:
        runtime_of(request).accounts.create(username, password, Role(role))
    except (AccountError, ValueError) as exc:
        return _redirect("/engineer/settings?error=" + quote(str(exc)))
    return _redirect("/engineer/settings?saved=users")


@router.post("/engineer/settings/users/{user_id}/delete")
async def delete_user(
    request: Request, user_id: int, me: User = Depends(require_engineer)
) -> Response:
    runtime = runtime_of(request)
    if user_id == me.id:
        return _redirect("/engineer/settings?error=You+can%27t+delete+your+own+account")
    try:
        runtime.accounts.delete(user_id)
        runtime.sessions.revoke_user(user_id)
    except AccountError as exc:
        return _redirect("/engineer/settings?error=" + quote(str(exc)))
    return _redirect("/engineer/settings?saved=users")


@router.post("/engineer/settings/users/{user_id}/role")
async def change_role(request: Request, user_id: int, role: Annotated[str, Form()]) -> Response:
    runtime = runtime_of(request)
    try:
        runtime.accounts.set_role(user_id, Role(role))
        runtime.sessions.revoke_user(user_id)
    except (AccountError, ValueError) as exc:
        return _redirect("/engineer/settings?error=" + quote(str(exc)))
    return _redirect("/engineer/settings?saved=users")


@router.post("/engineer/settings/users/{user_id}/password")
async def reset_password(
    request: Request, user_id: int, password: Annotated[str, Form()]
) -> Response:
    runtime = runtime_of(request)
    try:
        runtime.accounts.set_password(user_id, password)
        runtime.sessions.revoke_user(user_id)
    except AccountError as exc:
        return _redirect("/engineer/settings?error=" + quote(str(exc)))
    return _redirect("/engineer/settings?saved=users")


# -- certificate ---------------------------------------------------------------------------------
@router.post("/engineer/settings/certificate")
async def upload_certificate(request: Request) -> Response:
    from insight.auth.tls import (
        CertificateError,
        cert_paths,
        certificate_summary,
        install_certificate,
    )

    runtime = runtime_of(request)
    form = await request.form()
    cert, key = form.get("certificate"), form.get("private_key")
    if isinstance(cert, str) or isinstance(key, str) or cert is None or key is None:
        return render(
            request,
            "engineer/certificate.html",
            {"error": "Choose both a certificate file and its private key."},
            status_code=400,
        )
    try:
        install_certificate(runtime.settings.data_dir, await cert.read(), await key.read())
    except CertificateError as exc:
        return render(request, "engineer/certificate.html", {"error": str(exc)}, status_code=400)
    runtime.reload_tls()
    summary = certificate_summary(cert_paths(runtime.settings.data_dir)[0])
    return render(
        request,
        "engineer/certificate.html",
        {"message": "Certificate installed. New connections use it now.", "cert": summary},
    )


@router.get("/engineer/settings/certificate")
async def certificate_page(request: Request) -> Response:
    from insight.auth.tls import cert_paths, certificate_summary

    cert_path, _ = cert_paths(runtime_of(request).settings.data_dir)
    summary = certificate_summary(cert_path) if cert_path.exists() else None
    return render(request, "engineer/certificate.html", {"cert": summary})


# -- API -------------------------------------------------------------------------------------------
@router.get("/api/engineer/sources")
async def api_sources(request: Request) -> JSONResponse:
    sources_list = runtime_of(request).sources.list()
    return JSONResponse([s.public() for s in sources_list])


@router.get("/api/engineer/sources/{source_id}")
async def api_source(request: Request, source_id: str) -> JSONResponse:
    source = runtime_of(request).sources.get(source_id)
    if source is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(source.public())


@router.get("/api/engineer/readings")
async def api_readings(
    request: Request, subject: str, name: str, range: str = "24h"
) -> JSONResponse:
    """Readings for one series over the selected range only (charts load this on demand)."""
    runtime = runtime_of(request)
    hours = RANGES.get(range, 24)
    end = utcnow()
    source_scope = []
    if subject.startswith(("wan:", "dish:")):
        source_scope = [f"source:{subject.split(':')[1]}"]
    points = runtime.history.readings(
        subject, name, end - timedelta(hours=hours), end, gap_scopes=source_scope, max_points=600
    )
    unit = next((u for s, n, u in runtime.history.series_list(subject) if n == name), "")
    return JSONResponse(
        {
            "label": name,
            "unit": unit,
            "x": [int(p.at.timestamp()) for p in points],
            "y": [p.value for p in points],
        }
    )


__all__ = ["Reliability", "router"]
