"""Engineer console routes. Every route here requires the engineer role."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from insight.web.render import render
from insight.web.security import require_engineer, runtime_of, verify_csrf

router = APIRouter(dependencies=[Depends(require_engineer), Depends(verify_csrf)])


@router.get("/engineer")
async def home(request: Request) -> Response:
    return render(request, "engineer/home.html", {})


@router.get("/api/engineer/sources")
async def api_sources(request: Request) -> JSONResponse:
    sources = runtime_of(request).sources.list()
    return JSONResponse([s.public() for s in sources])


@router.get("/api/engineer/sources/{source_id}")
async def api_source(request: Request, source_id: str) -> JSONResponse:
    source = runtime_of(request).sources.get(source_id)
    if source is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(source.public())


@router.post("/engineer/settings/certificate")
async def upload_certificate(request: Request) -> Response:
    from insight.auth.tls import CertificateError, install_certificate

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
    return render(
        request,
        "engineer/certificate.html",
        {"message": "Certificate installed. New connections use it now."},
    )


@router.get("/engineer/settings/certificate")
async def certificate_page(request: Request) -> Response:
    from insight.auth.tls import cert_paths, certificate_summary

    cert_path, _ = cert_paths(runtime_of(request).settings.data_dir)
    summary = certificate_summary(cert_path) if cert_path.exists() else None
    return render(request, "engineer/certificate.html", {"cert": summary})
