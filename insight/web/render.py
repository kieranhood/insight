"""Template rendering with the context every page needs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from insight import __version__, branding
from insight.timeutil import format_ship_time
from insight.web.security import (
    current_session,
    presession_token,
    runtime_of,
    set_presession_cookie,
)

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.trim_blocks = True
templates.env.lstrip_blocks = True


def _ship_time_filter(value: datetime | None, fmt: str = "%d %b %H:%M") -> str:
    if value is None:
        return "never"
    return format_ship_time(value, templates.env.globals.get("ship_timezone", "UTC"), fmt)  # type: ignore[arg-type]


templates.env.filters["shiptime"] = _ship_time_filter


def render(
    request: Request, name: str, context: dict[str, Any], status_code: int = 200
) -> HTMLResponse:
    session = current_session(request)
    runtime = runtime_of(request)
    templates.env.globals["ship_timezone"] = runtime.config.get("ship_timezone")
    presession = None if session else presession_token(request)
    base: dict[str, Any] = {
        "user": session.user if session else None,
        "csrf_token": session.csrf_token if session else presession,
        "version": __version__,
        "branding": branding,
        "path": request.url.path,
    }
    base.update(context)
    response = templates.TemplateResponse(request, name, base, status_code=status_code)
    if presession is not None:
        set_presession_cookie(response, presession)
    return response
