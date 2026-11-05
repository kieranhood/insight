"""The active discovery sweep: engineer-started, limited to selected subnets, non-intrusive.

Checks are reachability, TCP connects to a fixed list of management ports, and reading the
page title, redirect target and TLS certificate subject that a device serves publicly. No
sign-in, no credentials, no SNMP, nothing that changes a device.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import ssl
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from insight.timeutil import utcnow

MANAGEMENT_PORTS = (22, 80, 443, 8080, 8443, 8822, 9200, 11443)
WEB_PORTS = (443, 8443, 11443, 80)
MAX_ADDRESSES = 1024  # a /22
RATE_PER_SECOND = 20.0
PORTS_IN_FLIGHT = 4


class SweepError(ValueError):
    pass


@dataclass
class SweepPlan:
    addresses: list[str]
    selected: list[str]
    excluded: list[str]


def plan(selected: list[str], excluded: list[str]) -> SweepPlan:
    """The addresses a run may contact: selected subnets minus excluded ones, at most a /22."""
    if not selected:
        raise SweepError("Select at least one subnet to scan.")
    nets = []
    for text in selected:
        try:
            nets.append(ipaddress.ip_network(text, strict=False))
        except ValueError as exc:
            raise SweepError(f"{text} is not a valid subnet.") from exc
    blocked = []
    for text in excluded:
        try:
            blocked.append(ipaddress.ip_network(text, strict=False))
        except ValueError as exc:
            raise SweepError(f"{text} is not a valid subnet.") from exc
    addresses: list[str] = []
    for net in nets:
        hosts = list(net.hosts()) if net.num_addresses > 2 else list(net)
        for host in hosts:
            if any(host in b for b in blocked):
                continue
            addresses.append(str(host))
            if len(addresses) > MAX_ADDRESSES:
                raise SweepError(
                    "A discovery run can cover at most 1,024 addresses (a /22). Select a smaller range."
                )
    return SweepPlan(
        sorted(set(addresses), key=ipaddress.ip_address), list(selected), list(excluded)
    )


Connector = Callable[[str, int], Awaitable[bool]]
WebReader = Callable[[str, int], Awaitable[dict[str, Any]]]


async def tcp_open(host: str, port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=1.0)
    except (OSError, TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


async def read_public_page(host: str, port: int) -> dict[str, Any]:
    """GET / with no credentials, no cookies and no redirects followed; read the TLS subject."""
    scheme = "http" if port == 80 else "https"
    result: dict[str, Any] = {}
    if scheme == "https":
        subject = await _tls_subject(host, port)
        if subject:
            result["tls_subject"] = subject
    try:
        async with httpx.AsyncClient(verify=False, follow_redirects=False, timeout=3) as client:  # noqa: S501 - read-only public page of a device on the yacht LAN
            response = await client.get(f"{scheme}://{host}:{port}/")
    except httpx.HTTPError:
        return result
    result["http_status"] = response.status_code
    if "location" in response.headers:
        result["http_location"] = response.headers["location"]
    text = response.text[:20000]
    match = _TITLE.search(text)
    if match:
        result["http_title"] = " ".join(match.group(1).split())[:120]
    for marker in ("init_company_name",):
        if marker in text:
            result["http_body_snippet"] = marker
    return result


async def _tls_subject(host: str, port: int) -> str | None:
    from cryptography import x509

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=context), timeout=3
        )
    except (OSError, TimeoutError, ssl.SSLError):
        return None
    try:
        ssl_obj = writer.get_extra_info("ssl_object")
        der = ssl_obj.getpeercert(binary_form=True) if ssl_obj else None
        return x509.load_der_x509_certificate(der).subject.rfc4514_string() if der else None
    except ValueError:
        return None
    finally:
        writer.close()


@dataclass
class SweepRun:
    started_by: str
    plan: SweepPlan
    started_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None
    scanned: int = 0
    found: list[dict[str, Any]] = field(default_factory=list)
    cancelled: bool = False
    task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self.finished_at is None

    @property
    def progress(self) -> str:
        return f"{self.scanned} of {len(self.plan.addresses)} addresses"


async def sweep(
    run: SweepRun,
    on_found: Callable[[str, dict[str, Any]], None],
    *,
    connect: Connector = tcp_open,
    read_page: WebReader = read_public_page,
    rate: float = RATE_PER_SECOND,
    ports: tuple[int, ...] = MANAGEMENT_PORTS,
) -> None:
    """Probe each planned address in turn, starting at most `rate` addresses per second."""
    host_slots = asyncio.Semaphore(16)
    pending: set[asyncio.Task[None]] = set()

    async def probe(host: str) -> None:
        async with host_slots:
            port_slots = asyncio.Semaphore(PORTS_IN_FLIGHT)

            async def check(port: int) -> int | None:
                async with port_slots:
                    return port if await connect(host, port) else None

            results = await asyncio.gather(*(check(p) for p in ports))
            open_ports = sorted(p for p in results if p is not None)
            if open_ports:
                observations: dict[str, Any] = {"open_ports": open_ports}
                for web in WEB_PORTS:
                    if web in open_ports:
                        observations.update(await read_page(host, web))
                        break
                run.found.append({"ip": host, **observations})
                on_found(host, observations)
            run.scanned += 1

    interval = 1.0 / rate
    next_start = time.monotonic()
    try:
        for host in run.plan.addresses:
            if run.cancelled:
                break
            delay = next_start - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            next_start = max(next_start + interval, time.monotonic())
            task = asyncio.create_task(probe(host))
            pending.add(task)
            task.add_done_callback(pending.discard)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    finally:
        for task in pending:
            task.cancel()
        run.finished_at = utcnow()
