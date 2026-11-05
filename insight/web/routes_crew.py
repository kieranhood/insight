"""Crew dashboard routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from insight.auth.accounts import User
from insight.web.render import render
from insight.web.security import require_user

router = APIRouter()


@router.get("/")
async def dashboard(request: Request, user: User = Depends(require_user)) -> Response:  # noqa: B008
    return render(request, "crew/dashboard.html", {})
