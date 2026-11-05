"""Read-only SNMP helper (GET and WALK only; SET is never used)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from insight.collection.adapter import AuthFailed, Unreachable


@dataclass(frozen=True)
class SnmpTarget:
    host: str
    port: int = 161
    community: str | None = None  # v2c
    v3_user: str | None = None
    v3_auth_key: str | None = None
    v3_priv_key: str | None = None
    timeout: float = 3.0
    retries: int = 1


def _value(raw: Any) -> Any:
    """Convert a pysnmp value to a plain Python value."""
    name = type(raw).__name__
    if name in (
        "Integer",
        "Integer32",
        "Unsigned32",
        "Gauge32",
        "Counter32",
        "Counter64",
        "TimeTicks",
    ):
        return int(raw)
    if name == "OctetString":
        data = bytes(raw)
        try:
            text = data.decode()
            if text.isprintable():
                return text
        except UnicodeDecodeError:
            pass
        if len(data) == 6:
            return ":".join(f"{b:02x}" for b in data)
        return data.hex()
    if name == "IpAddress":
        return ".".join(str(b) for b in bytes(raw))
    if name in ("NoSuchObject", "NoSuchInstance", "EndOfMibView"):
        return None
    return str(raw)


class SnmpClient:
    def __init__(self, target: SnmpTarget) -> None:
        from pysnmp.hlapi.v3arch.asyncio import (
            CommunityData,
            ContextData,
            SnmpEngine,
            UsmUserData,
            usmAesCfb128Protocol,
            usmHMACSHAAuthProtocol,
        )

        self.target = target
        self._engine = SnmpEngine()
        self._context = ContextData()
        if target.v3_user:
            self._auth: Any = UsmUserData(
                target.v3_user,
                authKey=target.v3_auth_key,
                privKey=target.v3_priv_key,
                authProtocol=usmHMACSHAAuthProtocol,
                privProtocol=usmAesCfb128Protocol,
            )
        else:
            self._auth = CommunityData(target.community or "", mpModel=1)  # noqa: S508 - v2c where the device offers no v3
        self._transport: Any = None

    async def _transport_target(self) -> Any:
        from pysnmp.hlapi.v3arch.asyncio import UdpTransportTarget

        if self._transport is None:
            self._transport = await UdpTransportTarget.create(
                (self.target.host, self.target.port),
                timeout=self.target.timeout,
                retries=self.target.retries,
            )
        return self._transport

    @staticmethod
    def _check(error_indication: Any, error_status: Any) -> None:
        if error_indication:
            text = str(error_indication)
            if (
                "unknownUserName" in text
                or "wrongDigest" in text
                or "authorization" in text.lower()
            ):
                raise AuthFailed(f"SNMP authentication failed: {text}")
            raise Unreachable(f"no SNMP response ({text})")
        if error_status and int(error_status) != 0:
            raise Unreachable(f"SNMP error {error_status.prettyPrint()}")

    async def get(self, *oids: str) -> dict[str, Any]:
        from pysnmp.hlapi.v3arch.asyncio import ObjectIdentity, ObjectType, get_cmd

        transport = await self._transport_target()
        ei, es, _, binds = await get_cmd(
            self._engine,
            self._auth,
            transport,
            self._context,
            *(ObjectType(ObjectIdentity(o)) for o in oids),
        )
        self._check(ei, es)
        return {str(name): _value(val) for name, val in binds}

    async def walk(self, oid: str, max_rows: int = 5000) -> dict[str, Any]:
        from pysnmp.hlapi.v3arch.asyncio import ObjectIdentity, ObjectType, bulk_walk_cmd

        transport = await self._transport_target()
        result: dict[str, Any] = {}
        async for ei, es, _, binds in bulk_walk_cmd(
            self._engine,
            self._auth,
            transport,
            self._context,
            0,
            25,
            ObjectType(ObjectIdentity(oid)),
            lexicographicMode=False,
        ):
            self._check(ei, es)
            for name, val in binds:
                result[str(name)] = _value(val)
            if len(result) >= max_rows:
                break
        return result

    def close(self) -> None:
        self._engine.close_dispatcher()


def column(walk: dict[str, Any], base: str) -> dict[str, Any]:
    """Rows of one table column: index suffix -> value."""
    prefix = base.rstrip(".") + "."
    return {oid[len(prefix) :]: value for oid, value in walk.items() if oid.startswith(prefix)}
