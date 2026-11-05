"""Run Insight over plain HTTP on localhost in a background thread, for browser tests."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import uvicorn

from insight.runtime import Runtime
from insight.web.app import create_app


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def serve(runtime: Runtime) -> Iterator[str]:
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(runtime), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=asyncio.run, args=(server.serve(),), daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    try:
        yield f"http://localhost:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
