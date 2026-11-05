"""Authentication, role enforcement and CSRF protection for the web interface."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING
from urllib.parse import quote

from fastapi import Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from insight.auth.accounts import User
from insight.auth.sessions import COOKIE_NAME, Session, csrf_matches

if TYPE_CHECKING:
    from insight.runtime import Runtime

PRESESSION_COOKIE = "insight_presession"
CSRF_FIELD = "csrf_token"
CSRF_HEADER = "x-csrf-token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Paths available before the first engineer account exists, or without signing in.
PUBLIC_PREFIXES = ("/static/", "/healthz", "/signin", "/first-run", "/about")


class NotSignedIn(Exception):
    pass


class Forbidden(Exception):
    pass


class CsrfFailed(Exception):
    pass


def runtime_of(request: Request) -> Runtime:
    runtime: Runtime = request.app.state.runtime
    return runtime


def current_session(request: Request) -> Session | None:
    if "insight_session" not in request.scope.setdefault("state", {}):
        token = request.cookies.get(COOKIE_NAME)
        request.state.insight_session = runtime_of(request).sessions.validate(token)
    session: Session | None = request.state.insight_session
    return session


def require_session(request: Request) -> Session:
    session = current_session(request)
    if session is None:
        raise NotSignedIn()
    return session


def require_user(session: Session = Depends(require_session)) -> User:  # noqa: B008
    return session.user


def require_engineer(session: Session = Depends(require_session)) -> User:  # noqa: B008
    if not session.user.is_engineer:
        raise Forbidden()
    return session.user


async def verify_csrf(request: Request) -> None:
    """Every state-changing request must carry the CSRF token for its session (or pre-session)."""
    if request.method not in UNSAFE_METHODS:
        return
    supplied = request.headers.get(CSRF_HEADER)
    if supplied is None:
        content_type = request.headers.get("content-type", "")
        if "form" in content_type:
            form = await request.form()
            value = form.get(CSRF_FIELD)
            supplied = value if isinstance(value, str) else None
    session = current_session(request)
    if session is not None:
        expected = session.csrf_token
    else:
        expected = request.cookies.get(PRESESSION_COOKIE, "")
    if not expected or not csrf_matches(expected, supplied):
        raise CsrfFailed()


def presession_token(request: Request) -> str:
    return request.cookies.get(PRESESSION_COOKIE) or secrets.token_urlsafe(32)


def set_presession_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        PRESESSION_COOKIE, token, httponly=True, secure=True, samesite="strict", max_age=3600
    )


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE_NAME, token, httponly=True, secure=True, samesite="strict")


def is_api(request: Request) -> bool:
    return request.url.path.startswith("/api/")


async def not_signed_in_handler(request: Request, exc: Exception) -> Response:
    if is_api(request):
        return JSONResponse({"error": "sign-in required"}, status_code=401)
    target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"/signin?next={quote(target)}", status_code=303)


async def forbidden_handler(request: Request, exc: Exception) -> Response:
    if is_api(request):
        return JSONResponse({"error": "engineer role required"}, status_code=403)
    from insight.web.render import render

    return render(request, "errors/forbidden.html", {}, status_code=403)


async def csrf_failed_handler(request: Request, exc: Exception) -> Response:
    if is_api(request):
        return JSONResponse({"error": "invalid or missing CSRF token"}, status_code=403)
    from insight.web.render import render

    return render(request, "errors/csrf.html", {}, status_code=403)


class FirstRunMiddleware(BaseHTTPMiddleware):
    """Until an engineer account exists, every page except first-run setup is unavailable."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        runtime = runtime_of(request)
        if (
            not path.startswith(("/static/", "/healthz", "/first-run"))
            and not runtime.accounts.has_users()
        ):
            if path.startswith("/api/"):
                return JSONResponse({"error": "Insight has not been set up yet"}, status_code=503)
            return RedirectResponse("/first-run", status_code=303)
        return await call_next(request)
