"""Passive listeners for mDNS and SSDP announcements. They only listen; nothing is sent."""

from __future__ import annotations

import asyncio
import functools
import logging
import socket
import struct
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

MDNS_GROUP, MDNS_PORT = "224.0.0.251", 5353
SSDP_GROUP, SSDP_PORT = "239.255.255.250", 1900


@dataclass(frozen=True)
class Announcement:
    ip: str
    name: str | None
    services: list[str]
    server: str | None = None


def parse_mdns(packet: bytes, sender_ip: str) -> Announcement | None:
    """Service types and instance/host names from an mDNS response or announcement."""
    import dns.exception
    import dns.message
    import dns.rdatatype

    try:
        message = dns.message.from_wire(packet)
    except (dns.exception.DNSException, ValueError):
        return None
    services: set[str] = set()
    names: set[str] = set()
    for rrset in list(message.answer) + list(message.additional):
        owner = rrset.name.to_text().rstrip(".")
        if rrset.rdtype == dns.rdatatype.PTR:
            if (owner.startswith("_") and "._tcp" in owner) or "._udp" in owner:
                services.add(owner.removesuffix(".local"))
            for rd in rrset:
                target = rd.target.to_text().rstrip(".")
                if owner.startswith("_"):
                    names.add(target.split("._")[0])
        elif rrset.rdtype in (dns.rdatatype.A, dns.rdatatype.AAAA) and owner.endswith(".local"):
            names.add(owner.removesuffix(".local"))
    if not services and not names:
        return None
    name = sorted(names, key=len)[0] if names else None
    return Announcement(sender_ip, name, sorted(services))


def parse_ssdp(packet: bytes, sender_ip: str) -> Announcement | None:
    try:
        text = packet.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        return None
    lines = text.split("\r\n") if "\r\n" in text else text.split("\n")
    if not lines or not (lines[0].startswith("NOTIFY") or lines[0].startswith("HTTP/1.1 200")):
        return None
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().upper()] = v.strip()
    if headers.get("NTS", "ssdp:alive") == "ssdp:byebye":
        return None
    service = headers.get("NT") or headers.get("ST")
    return Announcement(sender_ip, None, [service] if service else [], headers.get("SERVER"))


class _Listener(asyncio.DatagramProtocol):
    def __init__(
        self,
        parse: Callable[[bytes, str], Announcement | None],
        on_announcement: Callable[[Announcement], None],
    ) -> None:
        self.parse = parse
        self.on_announcement = on_announcement

    def datagram_received(self, data: bytes, addr: tuple[str | object, int]) -> None:
        announcement = self.parse(data, str(addr[0]))
        if announcement is not None:
            try:
                self.on_announcement(announcement)
            except Exception:
                log.exception("failed to record announcement")


def _same(listener: _Listener) -> _Listener:
    return listener


def _multicast_socket(group: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind(("", port))
    membership = struct.pack("4s4s", socket.inet_aton(group), socket.inet_aton("0.0.0.0"))  # noqa: S104
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
    sock.setblocking(False)
    return sock


async def start_listeners(
    on_announcement: Callable[[Announcement], None],
) -> list[asyncio.BaseTransport]:
    loop = asyncio.get_running_loop()
    transports: list[asyncio.BaseTransport] = []
    for group, port, parser in (
        (MDNS_GROUP, MDNS_PORT, parse_mdns),
        (SSDP_GROUP, SSDP_PORT, parse_ssdp),
    ):
        try:
            sock = _multicast_socket(group, port)
            listener = _Listener(parser, on_announcement)
            transport, _ = await loop.create_datagram_endpoint(
                functools.partial(_same, listener), sock=sock
            )
            transports.append(transport)
        except OSError as exc:
            log.warning("discovery listener on UDP %s not started: %s", port, exc)
    return transports
