"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from insight import __version__
from insight.runtime import Runtime
from insight.web import health


def create_app(runtime: Runtime) -> FastAPI:
    app = FastAPI(
        title="Insight",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.runtime = runtime
    app.include_router(health.router)
    return app
