"""The adapter interface every integration implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from insight.model import Reliability, Snapshot
from insight.sources import SourceConfig
from insight.state import FailureKind


class CollectionError(Exception):
    """A collection attempt failed. `kind` says how, for monitoring-failure reporting."""

    kind: FailureKind = FailureKind.UNREACHABLE

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class Unreachable(CollectionError):
    kind = FailureKind.UNREACHABLE


class AuthFailed(CollectionError):
    kind = FailureKind.AUTH


class ParseFailed(CollectionError):
    kind = FailureKind.PARSE


@dataclass(frozen=True)
class CredentialField:
    name: str
    label: str
    secret: bool = True
    required: bool = True
    help: str = ""


@dataclass(frozen=True)
class AdapterInfo:
    """Describes an adapter for guided setup."""

    kind: str
    label: str
    reliability: Reliability
    default_interval_s: float
    address_label: str = "Address"
    address_help: str = ""
    credentials: tuple[CredentialField, ...] = ()
    options_help: str = ""
    setup_steps: tuple[str, ...] = ()


@dataclass
class ConnectionTest:
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class Adapter(ABC):
    info: ClassVar[AdapterInfo]

    def __init__(self, source: SourceConfig) -> None:
        self.source = source

    @property
    def reliability(self) -> Reliability:
        return self.info.reliability

    @property
    def interval_s(self) -> float:
        return self.source.interval_s or self.info.default_interval_s

    @property
    def timeout_s(self) -> float:
        return float(
            self.source.options.get("timeout_s", min(20.0, max(5.0, self.interval_s * 0.8)))
        )

    @abstractmethod
    async def collect(self, now: datetime) -> Snapshot:
        """Read the source once. Raise CollectionError subclasses on failure; never write."""

    async def test_connection(self, now: datetime) -> ConnectionTest:
        snapshot = await self.collect(now)
        return ConnectionTest(
            True,
            f"Connected to {self.source.name}.",
            {"devices": len(snapshot.devices)},
        )

    async def close(self) -> None:  # noqa: B027 - optional hook
        """Release connections."""

    def new_snapshot(self, now: datetime) -> Snapshot:
        return Snapshot(source_id=self.source.id, collected_at=now, reliability=self.reliability)

    def describe_error(self, error: CollectionError) -> str:
        return f"{self.source.name}: {error.message}"
