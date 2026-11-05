from __future__ import annotations

import asyncio
import socket
import ssl
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from cryptography import x509
from fastapi.testclient import TestClient

from insight.auth.accounts import Role
from insight.auth.tls import CertificateError, generate_self_signed, validate_pair
from insight.runtime import Runtime
from insight.server import build_servers
from insight.settings import Settings
from insight.web.redirect import create_redirect_app
from tests.conftest import PASSWORD, csrf_from


def test_plain_http_redirects_to_https() -> None:
    client = TestClient(
        create_redirect_app(443), base_url="http://insight.local", follow_redirects=False
    )
    response = client.get("/engineer?x=1")
    assert response.status_code == 308
    assert response.headers["location"] == "https://insight.local/engineer?x=1"
    other = TestClient(
        create_redirect_app(8443), base_url="http://10.0.0.5", follow_redirects=False
    )
    assert other.get("/").headers["location"] == "https://10.0.0.5:8443/"


def test_mismatched_pair_rejected() -> None:
    cert_a, _ = generate_self_signed("a")
    _, key_b = generate_self_signed("b")
    with pytest.raises(CertificateError):
        validate_pair(cert_a, key_b)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _served_cert(port: int) -> x509.Certificate:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with (
        socket.create_connection(("127.0.0.1", port), timeout=5) as raw,
        context.wrap_socket(raw) as tls,
    ):
        der = tls.getpeercert(binary_form=True)
    assert der is not None
    return x509.load_der_x509_certificate(der)


@pytest.fixture
def live(tmp_path: Path) -> Iterator[tuple[Runtime, int, int]]:
    https_port, http_port = _free_port(), _free_port()
    settings = Settings(
        data_dir=tmp_path / "data",
        bind_host="127.0.0.1",
        https_port=https_port,
        http_port=http_port,
    )
    runtime = Runtime(settings)
    https, http = build_servers(runtime)

    async def serve_both() -> None:
        await asyncio.gather(https.serve(), http.serve())

    thread = threading.Thread(target=asyncio.run, args=(serve_both(),), daemon=True)
    thread.start()
    for _ in range(100):
        if https.started and http.started:
            break
        time.sleep(0.05)
    yield runtime, https_port, http_port
    https.should_exit = http.should_exit = True
    thread.join(timeout=10)
    runtime.close()


def test_served_over_https_and_uploaded_certificate_is_served(
    live: tuple[Runtime, int, int],
) -> None:
    runtime, https_port, http_port = live
    original = _served_cert(https_port)
    assert "50N Systems Insight" in original.subject.rfc4514_string()

    redirect = httpx.get(f"http://127.0.0.1:{http_port}/", follow_redirects=False)
    assert redirect.status_code == 308 and redirect.headers["location"].startswith("https://")

    runtime.accounts.create("eng", PASSWORD, Role.ENGINEER)
    with httpx.Client(base_url=f"https://127.0.0.1:{https_port}", verify=False) as client:
        page = client.get("/signin")
        client.post(
            "/signin",
            data={"username": "eng", "password": PASSWORD, "csrf_token": csrf_from(page.text)},
        )
        token = csrf_from(client.get("/engineer/settings/certificate").text)
        cert_pem, key_pem = generate_self_signed("bridge-insight.yacht")
        response = client.post(
            "/engineer/settings/certificate",
            data={"csrf_token": token},
            files={"certificate": ("cert.pem", cert_pem), "private_key": ("key.pem", key_pem)},
        )
        assert response.status_code == 200, response.text
    replaced = _served_cert(https_port)
    assert "bridge-insight.yacht" in replaced.subject.rfc4514_string()
