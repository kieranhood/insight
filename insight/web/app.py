"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from insight import __version__
from insight.runtime import Runtime
from insight.web import (
    health,
    routes_auth,
    routes_crew,
    routes_discovery,
    routes_engineer,
    routes_simulator,
)
from insight.web.security import (
    CsrfFailed,
    FirstRunMiddleware,
    Forbidden,
    NotSignedIn,
    csrf_failed_handler,
    forbidden_handler,
    not_signed_in_handler,
)

STATIC_DIR = Path(__file__).parent / "static"


def create_app(runtime: Runtime) -> FastAPI:
    app = FastAPI(
        title="Insight",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.runtime = runtime
    app.add_middleware(FirstRunMiddleware)
    app.add_exception_handler(NotSignedIn, not_signed_in_handler)
    app.add_exception_handler(Forbidden, forbidden_handler)
    app.add_exception_handler(CsrfFailed, csrf_failed_handler)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(health.router)
    app.include_router(routes_auth.router)
    app.include_router(routes_crew.router)
    app.include_router(routes_engineer.router)
    app.include_router(routes_discovery.router)
    app.include_router(routes_simulator.router)
    return app
