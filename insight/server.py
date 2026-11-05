"""Process wiring: builds the Runtime and runs the web server and background services."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import urllib.request

import uvicorn

from insight.runtime import Runtime
from insight.settings import Settings
from insight.web.app import create_app

log = logging.getLogger("insight")


async def _run(settings: Settings) -> None:
    runtime = Runtime(settings)
    app = create_app(runtime)
    config = uvicorn.Config(
        app,
        host=settings.bind_host,
        port=settings.https_port,
        log_level="info",
        proxy_headers=False,
        server_header=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


def serve() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(_run(Settings.from_env()))


def healthcheck() -> int:
    """Used by the container HEALTHCHECK. Talks only to this host."""
    settings = Settings.from_env()
    for scheme in ("https", "http"):
        url = f"{scheme}://127.0.0.1:{settings.https_port}/healthz"
        context = ssl.create_default_context()
        # Local loopback check of our own self-signed certificate.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(url, timeout=5, context=context) as response:  # noqa: S310
                body = json.loads(response.read())
                return 0 if body.get("status") == "ok" else 1
        except urllib.error.HTTPError:
            return 1
        except OSError:
            continue
    return 1
