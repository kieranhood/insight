"""Plain-HTTP listener whose only job is redirecting browsers to HTTPS."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route


def create_redirect_app(https_port: int) -> Starlette:
    async def redirect(request: Request) -> Response:
        host = (request.headers.get("host") or "insight").split(":")[0]
        port = "" if https_port == 443 else f":{https_port}"
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(f"https://{host}{port}{request.url.path}{query}", status_code=308)

    methods = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    return Starlette(routes=[Route("/{path:path}", redirect, methods=methods)])
