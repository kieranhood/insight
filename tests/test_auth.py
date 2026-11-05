from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from insight.auth.accounts import Role, SignInResult
from insight.runtime import Runtime
from insight.timeutil import utcnow
from tests.conftest import PASSWORD, all_routes, csrf_from, page_csrf, sign_in


# 4.1 ------------------------------------------------------------------------------
def test_first_run_blocks_every_other_page(client: TestClient) -> None:
    for path in ["/", "/engineer", "/signin", "/about", "/engineer/sources"]:
        response = client.get(path)
        assert response.status_code == 303 and response.headers["location"] == "/first-run", path
    assert client.get("/first-run").status_code == 200
    assert client.get("/healthz").status_code == 200


def test_no_default_credentials(runtime: Runtime) -> None:
    assert not runtime.accounts.has_users()
    for username in ["admin", "engineer", "insight", "root", "50n"]:
        for password in ["admin", "password", "insight", "50nsystems", ""]:
            assert runtime.accounts.authenticate(username, password)[0] is SignInResult.INVALID


def test_first_run_creates_engineer_and_signs_in(client: TestClient, runtime: Runtime) -> None:
    token = csrf_from(client.get("/first-run").text)
    response = client.post(
        "/first-run",
        data={"username": "kate", "password": PASSWORD, "confirm": PASSWORD, "csrf_token": token},
    )
    assert response.status_code == 303 and response.headers["location"] == "/engineer"
    assert client.get("/engineer").status_code == 200
    assert runtime.accounts.list()[0].role is Role.ENGINEER
    # First run cannot be repeated.
    assert client.get("/first-run").headers["location"] == "/signin"


def test_stored_hashes_are_not_plain_text(runtime: Runtime) -> None:
    runtime.accounts.create("eng", PASSWORD, Role.ENGINEER)
    with runtime.db.read() as conn:
        stored = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    assert PASSWORD not in stored
    assert stored.startswith("$argon2id$")
    raw = runtime.db.path.read_bytes()
    assert PASSWORD.encode() not in raw


# 4.2 ------------------------------------------------------------------------------
def test_expired_session_redirects_to_sign_in(runtime: Runtime, engineer: TestClient) -> None:
    assert engineer.get("/").status_code == 200
    old = (utcnow() - timedelta(hours=3)).isoformat()
    runtime.writer.call_sync(lambda c: c.execute("UPDATE sessions SET last_seen_at=?", (old,)))
    response = engineer.get("/")
    assert response.status_code == 303 and response.headers["location"].startswith("/signin")


def test_crew_idle_timeout_is_longer_than_engineer(runtime: Runtime, crew: TestClient) -> None:
    three_hours = (utcnow() - timedelta(hours=3)).isoformat()
    runtime.writer.call_sync(
        lambda c: c.execute("UPDATE sessions SET last_seen_at=?", (three_hours,))
    )
    assert crew.get("/").status_code == 200


def test_post_without_csrf_rejected(engineer: TestClient) -> None:
    assert engineer.post("/signout").status_code == 403
    assert engineer.post("/signout", data={"csrf_token": "wrong"}).status_code == 403
    assert engineer.get("/").status_code == 200  # still signed in


def test_sign_out(engineer: TestClient) -> None:
    response = engineer.post("/signout", data={"csrf_token": page_csrf(engineer)})
    assert response.status_code == 303
    assert engineer.get("/").status_code == 303


def test_session_cookie_flags(runtime: Runtime, client: TestClient) -> None:
    runtime.accounts.create("eng", PASSWORD, Role.ENGINEER)
    page = client.get("/signin")
    response = client.post(
        "/signin",
        data={"username": "eng", "password": PASSWORD, "csrf_token": csrf_from(page.text)},
    )
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie


def test_open_redirect_blocked(runtime: Runtime, client: TestClient) -> None:
    runtime.accounts.create("eng", PASSWORD, Role.ENGINEER)
    page = client.get("/signin")
    response = client.post(
        "/signin",
        data={
            "username": "eng",
            "password": PASSWORD,
            "next": "https://evil.example/",
            "csrf_token": csrf_from(page.text),
        },
    )
    assert response.headers["location"] == "/"


# 4.3 ------------------------------------------------------------------------------
def test_every_engineer_route_refused_for_crew(crew: TestClient) -> None:
    engineer_routes = [
        (path, method)
        for path, methods in all_routes(crew.app)
        if path.startswith(("/engineer", "/api/engineer"))
        for method in methods
    ]
    assert engineer_routes, "expected engineer routes to exist"
    token = page_csrf(crew)
    for path, method in engineer_routes:
        concrete = path.replace("{", "").replace("}", "")
        response = crew.request(method, concrete, data={"csrf_token": token})
        assert response.status_code == 403, (method, path, response.status_code)
        assert "credentials" not in response.text and "address" not in response.text


def test_crew_sees_no_engineer_link(crew: TestClient) -> None:
    assert 'href="/engineer"' not in crew.get("/").text


# 4.4 ------------------------------------------------------------------------------
def test_sixth_attempt_refused_even_with_correct_password(
    runtime: Runtime, client: TestClient
) -> None:
    runtime.accounts.create("eng", PASSWORD, Role.ENGINEER)
    for _ in range(5):
        page = client.get("/signin")
        client.post(
            "/signin",
            data={
                "username": "eng",
                "password": "wrong password",
                "csrf_token": csrf_from(page.text),
            },
        )
    page = client.get("/signin")
    response = client.post(
        "/signin",
        data={"username": "eng", "password": PASSWORD, "csrf_token": csrf_from(page.text)},
    )
    assert response.status_code == 429
    assert "locked" in response.text


def test_lock_expires(runtime: Runtime) -> None:
    runtime.accounts.create("eng", PASSWORD, Role.ENGINEER)
    now = utcnow()
    for _ in range(5):
        runtime.accounts.authenticate("eng", "nope", now)
    assert (
        runtime.accounts.authenticate("eng", PASSWORD, now + timedelta(minutes=5))[0]
        is SignInResult.LOCKED
    )
    assert (
        runtime.accounts.authenticate("eng", PASSWORD, now + timedelta(minutes=16))[0]
        is SignInResult.OK
    )


def test_failures_outside_window_do_not_lock(runtime: Runtime) -> None:
    runtime.accounts.create("eng", PASSWORD, Role.ENGINEER)
    now = utcnow()
    for i in range(5):
        runtime.accounts.authenticate("eng", "nope", now + timedelta(minutes=3 * i))
    assert (
        runtime.accounts.authenticate("eng", PASSWORD, now + timedelta(minutes=13))[0]
        is SignInResult.OK
    )


def test_licence_notice_on_signin_and_about(runtime: Runtime, client: TestClient) -> None:
    runtime.accounts.create("eng", PASSWORD, Role.ENGINEER)
    assert "proprietary software of 50N Systems" in client.get("/signin").text
    sign_in(client, "eng")
    assert "proprietary software of 50N Systems" in client.get("/about").text
