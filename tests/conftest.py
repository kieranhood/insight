from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from insight.auth.accounts import Role
from insight.runtime import Runtime
from insight.settings import Settings
from insight.web.app import create_app

PASSWORD = "correct horse battery"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def runtime(settings: Settings) -> Iterator[Runtime]:
    rt = Runtime(settings)
    yield rt
    rt.close()


@pytest.fixture
def client(runtime: Runtime) -> TestClient:
    return TestClient(create_app(runtime), base_url="https://testserver", follow_redirects=False)


def csrf_from(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "no csrf token in page"
    return match.group(1)


def sign_in(client: TestClient, username: str, password: str = PASSWORD) -> TestClient:
    page = client.get("/signin")
    response = client.post(
        "/signin",
        data={"username": username, "password": password, "csrf_token": csrf_from(page.text)},
    )
    assert response.status_code == 303, response.text
    return client


@pytest.fixture
def engineer(runtime: Runtime, client: TestClient) -> TestClient:
    runtime.accounts.create("eng", PASSWORD, Role.ENGINEER)
    return sign_in(client, "eng")


@pytest.fixture
def crew(runtime: Runtime, client: TestClient) -> TestClient:
    if not runtime.accounts.has_engineer():
        runtime.accounts.create("eng", PASSWORD, Role.ENGINEER)
    runtime.accounts.create("crew", PASSWORD, Role.CREW)
    return sign_in(client, "crew")


def all_routes(app: object) -> list[tuple[str, set[str]]]:
    """Flatten routes, including those inside included routers (FastAPI >= 0.16x wraps them)."""
    found: list[tuple[str, set[str]]] = []

    def walk(routes: list[object], prefix: str = "") -> None:
        for route in routes:
            inner = getattr(route, "original_router", None)
            if inner is not None:
                ctx = getattr(route, "include_context", None)
                walk(inner.routes, prefix + (getattr(ctx, "prefix", "") or ""))
            elif hasattr(route, "methods") and hasattr(route, "path"):
                found.append((prefix + route.path, set(route.methods)))  # type: ignore[attr-defined]

    walk(app.router.routes)  # type: ignore[attr-defined]
    return found


def page_csrf(client: TestClient, path: str = "/") -> str:
    return csrf_from(client.get(path).text)
