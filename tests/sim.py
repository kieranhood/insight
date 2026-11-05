"""A simulated yacht wired through the real pipeline, with a controllable clock."""

from __future__ import annotations

from datetime import datetime, timedelta

from insight.adapters.simulator import ROLES, SimulatorAdapter, SimulatorHub
from insight.collection.scheduler import Scheduler
from insight.inventory import Service
from insight.model import Event, device_key
from insight.runtime import Runtime
from insight.sources import SourceConfig
from insight.timeutil import utcnow

LOCATIONS = {
    "24:79:2a:00:00:01": "Main deck, saloon",
    "24:79:2a:00:00:02": "Main deck, dining room",
    "24:79:2a:00:00:03": "Sun deck",
    "24:79:2a:00:00:04": "Lower deck, guest cabin 4",
    "24:79:2a:00:00:05": "Lower deck, guest cabin 6",
    "24:79:2a:00:00:06": "Lower deck, crew mess",
    "f0:9f:c2:00:00:20": "Lower deck comms cabinet",
}


class Sim:
    def __init__(
        self, runtime: Runtime, scenario: str, roles: dict | None = None, tag: bool = True
    ) -> None:
        self.runtime = runtime
        SimulatorHub.reset_all()
        self.hub = SimulatorHub.get(scenario)
        self.hub.load(scenario)
        self.now: datetime = utcnow()
        self.scheduler = Scheduler(
            runtime.state, hooks=[runtime._on_collection], clock=lambda: self.now
        )
        self.adapters = []
        for role, reliability in (roles or ROLES).items():
            source = SourceConfig(
                id=f"sim-{role}",
                kind="simulator",
                name=f"Simulated {role}",
                address=role,
                reliability=reliability,
                options={"role": role, "hub": scenario},
                interval_s=30,
            )
            runtime.sources.save(source)
            adapter = SimulatorAdapter(source)
            self.scheduler.add(adapter)
            self.adapters.append(adapter)
        self.tag = tag
        self._tagged = False

    async def cycle(self, advance: float = 30.0) -> list[Event]:
        self.now += timedelta(seconds=advance)
        for adapter in self.adapters:
            await self.scheduler.run_once(adapter)
        if self.tag and not self._tagged:
            self._tag()
        return self.runtime.evaluate(self.now)

    def _tag(self) -> None:
        inv = self.runtime.inventory
        for mac, place in LOCATIONS.items():
            if inv.get(device_key(mac=mac)) is not None:
                inv.set_tags(device_key(mac=mac), location=place)
        inv.map(Service.GUEST_WIFI, "ssid", "Guest")
        inv.map(Service.CREW_WIFI, "ssid", "Crew")
        self._tagged = True

    async def settle(self, cycles: int = 8, advance: float = 30.0) -> list[Event]:
        events: list[Event] = []
        for _ in range(cycles):
            events.extend(await self.cycle(advance))
        return events

    async def play(self, cycles_per_step: int = 8) -> list[Event]:
        """Baseline, then each scenario step, letting findings open."""
        events = await self.settle(3)
        while self.hub.step():
            events.extend(await self.settle(cycles_per_step))
        return events

    def open_findings(self) -> dict[str, object]:
        return {f.rule_id: f for f in self.runtime.findings.open()}
