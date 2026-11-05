"""End-to-end check of a real Insight container against the simulator.

    python scripts/e2e.py --image insight:dev [--upgrade-image insight:next] [--offline]

Starts a fresh container with a new data volume, creates the first engineer account,
adds simulator sources for every role, plays every scenario and checks findings,
statuses, timeline events and crew wording. Then restarts the container and (optionally)
replaces it with another image on the same volume, checking that data survives.

With --offline the container runs on an internal Docker network with no route to the
internet: it must start, serve its whole interface and keep diagnosing.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from insight.diagnostics import Confidence
from insight.diagnostics.lint import lint_crew_text

PASSWORD = "e2e engineer password"
ROLES = ["peplink", "unifi", "ruckus-snmp", "ruckus-web", "starlink", "probes"]
EXPECT = {
    "failover": "failover_to_backup",
    "internet_down": "internet_unavailable",
    "primary_degraded": "primary_link_degraded",
    "all_paths_degraded": "all_paths_degraded",
    "dns_failure": "dns_failure",
    "dish_obstruction": "starlink_obstructed",
    "dish_alert": "starlink_dish_alert",
    "weak_cellular": "weak_cellular_signal",
    "ap_poe_loss": "ap_lost_poe",
    "ap_offline": "ap_offline",
    "switch_offline": "switch_offline",
    "wifi_congestion": "wifi_congestion",
    "controller_outage": "monitoring_source_unavailable",
    "ruckus_web_broken": "monitoring_source_unavailable",
    "intermittent_ap": "ap_offline",
    "new_device": None,
    "baseline": None,
}
ENV = {
    "INSIGHT_DURATION_SCALE": "0.05",
    "INSIGHT_EVAL_INTERVAL": "2",
    "INSIGHT_LISTEN_ANNOUNCEMENTS": "0",
}


def sh(*args: str, check: bool = True) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


class Insight:
    def __init__(self, image: str, offline: bool, volume: str, network: str | None) -> None:
        self.image, self.offline, self.volume, self.network = image, offline, volume, network
        self.name = f"insight-e2e-{uuid.uuid4().hex[:6]}"
        self.https_port = 18443
        self.base = ""
        self.client: httpx.Client | None = None

    def start(self) -> None:
        env = [f"--env={k}={v}" for k, v in ENV.items()]
        net = [f"--network={self.network}"] if self.offline else ["--network=host"]
        ports = [
            "--env=INSIGHT_HTTPS_PORT=18443",
            "--env=INSIGHT_HTTP_PORT=18080",
            "--env=INSIGHT_SYSLOG_PORT=15514",
        ]
        sh(
            "docker",
            "run",
            "-d",
            f"--name={self.name}",
            "--cap-drop=ALL",
            "--cap-add=NET_RAW",
            "--cap-add=NET_BIND_SERVICE",
            f"--volume={self.volume}:/data",
            *net,
            *env,
            *ports,
            self.image,
        )
        host = "127.0.0.1"
        if self.offline:
            host = sh(
                "docker",
                "inspect",
                "-f",
                "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                self.name,
            )
        self.base = f"https://{host}:{self.https_port}"
        self.client = httpx.Client(
            base_url=self.base, verify=False, timeout=20, follow_redirects=False, trust_env=False
        )
        for _ in range(120):
            try:
                if self.client.get("/healthz").status_code in (200, 503):
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise RuntimeError(
            "container did not start: " + sh("docker", "logs", self.name, check=False)[-2000:]
        )

    def stop(self) -> None:
        sh("docker", "rm", "-f", self.name, check=False)
        if self.client:
            self.client.close()

    @property
    def c(self) -> httpx.Client:
        assert self.client is not None
        return self.client

    def csrf(self, path: str) -> str:
        match = re.search(r'name="csrf_token" value="([^"]+)"', self.c.get(path).text)
        assert match, f"no CSRF token on {path}"
        return match.group(1)

    def first_run(self) -> None:
        token = self.csrf("/first-run")
        r = self.c.post(
            "/first-run",
            data={
                "username": "eng",
                "password": PASSWORD,
                "confirm": PASSWORD,
                "csrf_token": token,
            },
        )
        assert r.status_code == 303, r.text[:500]

    def sign_in(self) -> None:
        self.c.cookies.clear()
        token = self.csrf("/signin")
        r = self.c.post(
            "/signin", data={"username": "eng", "password": PASSWORD, "csrf_token": token}
        )
        assert r.status_code == 303, "sign-in failed"

    def add_sim_sources(self) -> None:
        for role in ROLES:
            token = self.csrf("/engineer/sources/new?kind=simulator")
            r = self.c.post(
                "/engineer/sources",
                data={
                    "csrf_token": token,
                    "kind": "simulator",
                    "name": f"Simulated {role}",
                    "address": role,
                    "interval_s": "2",
                },
            )
            assert r.status_code == 303, r.text[:500]

    def scenario(self, name: str, steps_individually: bool = False) -> None:
        token = self.csrf("/engineer/simulator")
        self.c.post("/engineer/simulator/load", data={"csrf_token": token, "scenario": name})
        time.sleep(8)
        if steps_individually:
            for _ in range(8):
                self.c.post("/engineer/simulator/step", data={"csrf_token": token})
                time.sleep(7)
        else:
            self.c.post("/engineer/simulator/step", data={"csrf_token": token, "all_steps": "1"})

    def findings(self, status: str = "open") -> list[dict[str, Any]]:
        data: list[dict[str, Any]] = self.c.get(f"/api/engineer/findings?status={status}").json()
        return data

    def wait_for(self, rule_id: str, timeout: float = 60) -> dict[str, Any]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for f in self.findings():
                if f["rule_id"] == rule_id:
                    return f
            time.sleep(1)
        raise AssertionError(
            f"finding {rule_id} did not open; open: {[f['rule_id'] for f in self.findings()]}"
        )


def check_assets(insight: Insight) -> None:
    """Every asset a page references is served locally."""
    for path in ["/", "/engineer", "/engineer/wan", "/engineer/inventory", "/signin"]:
        html = insight.c.get(path).text
        assert not re.search(r"""(?:src|href)\s*=\s*["'](?:https?:)?//""", html), (
            f"external reference on {path}"
        )
        for asset in set(re.findall(r"""(?:src|href)="(/static/[^"]+)\"""", html)):
            assert insight.c.get(asset).status_code == 200, asset


def run(args: argparse.Namespace) -> None:
    volume = f"insight-e2e-{uuid.uuid4().hex[:6]}"
    network = None
    if args.offline:
        network = f"insight-offline-{uuid.uuid4().hex[:6]}"
        sh("docker", "network", "create", "--internal", network)
    insight = Insight(args.image, args.offline, volume, network)
    try:
        insight.start()
        print(f"started {insight.image} at {insight.base}")
        if args.offline:
            probe = sh(
                "docker",
                "exec",
                insight.name,
                "python",
                "-c",
                "import socket; s=socket.socket(); s.settimeout(3)\n"
                "try:\n s.connect(('1.1.1.1', 443)); print('ONLINE')\nexcept OSError: print('OFFLINE')",
                check=False,
            )
            assert "OFFLINE" in probe, f"container can reach the internet: {probe}"
            print("confirmed: no route to the internet")
        assert insight.c.get("/").headers["location"] == "/first-run"
        insight.first_run()
        insight.add_sim_sources()
        time.sleep(6)
        token = insight.csrf("/engineer/settings")
        insight.c.post(
            "/engineer/settings/services",
            data={"csrf_token": token, "ssid_guest_wifi": "Guest", "ssid_crew_wifi": "Crew"},
        )
        check_assets(insight)
        print("first run, sources and local assets OK")
        scenarios = (
            list(EXPECT)
            if not args.quick
            else ["failover", "ap_poe_loss", "controller_outage", "dns_failure"]
        )
        for name in scenarios:
            insight.scenario(name, steps_individually=(name == "intermittent_ap"))
            expected = EXPECT[name]
            if expected:
                finding = insight.wait_for(expected)
                print(f"  {name:20s} -> {finding['rule_id']} ({finding['confidence']})")
            else:
                time.sleep(6)
                print(f"  {name:20s} -> (no finding expected)")
        for f in insight.findings("all"):
            problems = lint_crew_text(f["crew_text"], Confidence(f["confidence"]))
            assert not problems, (f["rule_id"], problems)
        health = insight.c.get("/api/engineer/health").json()
        assert set(health["services"]) == {"internet", "guest_wifi", "crew_wifi"}
        assert "UNKNOWN" not in health["services"].values(), health
        timeline = insight.c.get("/engineer/timeline?hours=24").text
        assert "finding_opened" in timeline and "failover" in timeline
        if "new_device" in scenarios:
            assert "new_device_discovered" in timeline
        dashboard = insight.c.get("/").text
        assert "Yacht systems" in dashboard
        before = {f["id"] for f in insight.findings("all")}
        print(
            f"scenarios OK: {len(before)} findings recorded; health {json.dumps(health['services'])}"
        )

        sh("docker", "restart", insight.name)
        insight.start_wait = True  # type: ignore[attr-defined]
        for _ in range(120):
            try:
                if insight.c.get("/healthz").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        insight.sign_in()
        after = {f["id"] for f in insight.findings("all")}
        assert before <= after, "findings lost across restart"
        print("restart OK: accounts, sources and findings kept")

        if args.upgrade_image:
            sh("docker", "rm", "-f", insight.name)
            insight.image = args.upgrade_image
            insight.start()
            insight.sign_in()
            upgraded = {f["id"] for f in insight.findings("all")}
            assert before <= upgraded, "findings lost across upgrade"
            assert len(insight.c.get("/api/engineer/sources").json()) == len(ROLES)
            print(f"upgrade to {args.upgrade_image} OK: data intact")
        print("E2E PASSED")
    finally:
        insight.stop()
        sh("docker", "volume", "rm", "-f", volume, check=False)
        if network:
            sh("docker", "network", "rm", network, check=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="insight:dev")
    parser.add_argument("--upgrade-image")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--quick", action="store_true", help="a few scenarios only")
    run(parser.parse_args())
