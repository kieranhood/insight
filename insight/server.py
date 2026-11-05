"""Process wiring: builds the Runtime and runs the web server and background services."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import urllib.request

import uvicorn

from insight.auth.tls import ensure_certificate
from insight.runtime import Runtime
from insight.settings import Settings
from insight.web.app import create_app
from insight.web.redirect import create_redirect_app

log = logging.getLogger("insight")


def build_servers(runtime: Runtime) -> tuple[uvicorn.Server, uvicorn.Server]:
    """The HTTPS server for Insight and the plain-HTTP server that redirects to it."""
    settings = runtime.settings
    cert_path, key_path = ensure_certificate(settings.data_dir)
    https_config = uvicorn.Config(
        create_app(runtime),
        host=settings.bind_host,
        port=settings.https_port,
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
        log_level="info",
        proxy_headers=False,
        server_header=False,
    )
    https = uvicorn.Server(https_config)

    def reload_tls() -> None:
        # New connections use the replacement certificate without a restart.
        if https.config.ssl is not None:
            https.config.ssl.load_cert_chain(str(cert_path), str(key_path))

    runtime.reload_tls = reload_tls
    http_config = uvicorn.Config(
        create_redirect_app(settings.https_port),
        host=settings.bind_host,
        port=settings.http_port,
        log_level="warning",
        server_header=False,
    )
    return https, uvicorn.Server(http_config)


async def run(runtime: Runtime) -> None:
    https, http = build_servers(runtime)
    await runtime.start_background()
    try:
        await asyncio.gather(https.serve(), http.serve())
    finally:
        await runtime.stop_background()
        runtime.close()


async def _run(settings: Settings) -> None:
    await run(Runtime(settings))


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
