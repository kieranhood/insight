"""Sign-in, sign-out, first-run setup and the about page."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response

from insight.auth.accounts import AccountError, SignInResult
from insight.auth.sessions import COOKIE_NAME
from insight.web.render import render
from insight.web.security import (
    current_session,
    runtime_of,
    set_session_cookie,
    verify_csrf,
)

router = APIRouter()


def _safe_next(target: str | None) -> str:
    """Only allow redirects to local paths."""
    if not target:
        return "/"
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/") or target.startswith("//"):
        return "/"
    return target


@router.get("/signin")
async def signin_page(request: Request, next: str = "/") -> Response:
    if current_session(request) is not None:
        return RedirectResponse(_safe_next(next), status_code=303)
    return render(request, "signin.html", {"next": _safe_next(next)})


@router.post("/signin", dependencies=[Depends(verify_csrf)])
async def signin(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/",
) -> Response:
    runtime = runtime_of(request)
    result, user = runtime.accounts.authenticate(username, password)
    if result is SignInResult.LOCKED:
        return render(
            request,
            "signin.html",
            {
                "error": "Too many failed attempts. This account is locked for a few minutes.",
                "username": username,
                "next": _safe_next(next),
            },
            status_code=429,
        )
    if user is None:
        return render(
            request,
            "signin.html",
            {
                "error": "Username or password is incorrect.",
                "username": username,
                "next": _safe_next(next),
            },
            status_code=401,
        )
    token, _ = runtime.sessions.create(user)
    response = RedirectResponse(_safe_next(next), status_code=303)
    set_session_cookie(response, token)
    return response


@router.post("/signout", dependencies=[Depends(verify_csrf)])
async def signout(request: Request) -> Response:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        runtime_of(request).sessions.revoke(token)
    response = RedirectResponse("/signin", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/first-run")
async def first_run_page(request: Request) -> Response:
    if runtime_of(request).accounts.has_users():
        return RedirectResponse("/signin", status_code=303)
    return render(request, "first_run.html", {})


@router.post("/first-run", dependencies=[Depends(verify_csrf)])
async def first_run(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    confirm: Annotated[str, Form()],
) -> Response:
    runtime = runtime_of(request)
    if runtime.accounts.has_users():
        return RedirectResponse("/signin", status_code=303)
    error = None
    if password != confirm:
        error = "The passwords don't match."
    else:
        try:
            user = runtime.accounts.create_first_engineer(username, password)
        except AccountError as exc:
            error = str(exc)
    if error:
        return render(
            request, "first_run.html", {"error": error, "username": username}, status_code=400
        )
    token, _ = runtime.sessions.create(user)
    response = RedirectResponse("/engineer", status_code=303)
    set_session_cookie(response, token)
    return response


@router.get("/about")
async def about(request: Request) -> Response:
    return render(request, "about.html", {})
