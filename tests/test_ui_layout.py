from __future__ import annotations

import os
from pathlib import Path

import pytest

from insight.auth.accounts import Role
from insight.runtime import Runtime
from tests.conftest import PASSWORD
from tests.live_server import serve
from tests.sim import Sim

playwright = pytest.importorskip("playwright.async_api")

SHOTS = Path(os.environ.get("INSIGHT_SCREENSHOTS", "/tmp/claude-0/insight-screenshots"))
VIEWPORTS = {"phone": (390, 844), "tablet": (820, 1180), "desktop": (1280, 900)}


async def _sign_in(page: object, base: str, user: str) -> None:
    await page.goto(f"{base}/signin")  # type: ignore[attr-defined]
    await page.fill("input[name=username]", user)  # type: ignore[attr-defined]
    await page.fill("input[name=password]", PASSWORD)  # type: ignore[attr-defined]
    await page.click("button[type=submit]")  # type: ignore[attr-defined]
    await page.wait_for_load_state("networkidle")  # type: ignore[attr-defined]


@pytest.fixture
async def scenario_runtime(runtime: Runtime) -> Runtime:
    runtime.accounts.create("eng", PASSWORD, Role.ENGINEER)
    runtime.accounts.create("crew", PASSWORD, Role.CREW)
    sim = Sim(runtime, "ap_poe_loss")
    await sim.play(cycles_per_step=12)
    sim.hub.load("failover")
    sim.hub.step()
    await sim.settle(6)
    return runtime


async def test_dashboard_layout_at_three_widths(scenario_runtime: Runtime) -> None:
    from playwright.async_api import async_playwright

    SHOTS.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    with serve(scenario_runtime) as base:
        async with async_playwright() as p:
            exe = os.environ.get("INSIGHT_CHROMIUM", "/opt/pw-browsers/chromium")
            browser = await p.chromium.launch(executable_path=exe if Path(exe).is_file() else None)  # noqa: ASYNC240
            for name, (width, height) in VIEWPORTS.items():
                for scheme in ("light", "dark"):
                    context = await browser.new_context(
                        viewport={"width": width, "height": height}, color_scheme=scheme
                    )
                    page = await context.new_page()
                    external: list[str] = []
                    page.on(
                        "request",
                        lambda r, ext=external: (
                            ext.append(r.url) if not r.url.startswith(base) else None
                        ),
                    )
                    await _sign_in(page, base, "crew")
                    overflow = await page.evaluate(
                        "document.documentElement.scrollWidth - window.innerWidth"
                    )
                    assert overflow <= 0, (name, scheme, overflow)
                    assert await page.is_visible("text=Yacht systems")
                    assert await page.is_visible("#issues-title")
                    body_size = await page.evaluate(
                        "parseFloat(getComputedStyle(document.body).fontSize)"
                    )
                    assert body_size >= 16
                    await page.screenshot(
                        path=str(SHOTS / f"crew-{name}-{scheme}.png"), full_page=True
                    )
                    assert external == [], external
                    await context.close()
            await browser.close()
