"""Guided setup of integration sources: test the connection, explain failures plainly, save."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from insight.collection import registry
from insight.collection.adapter import AuthFailed, CollectionError, ParseFailed, Unreachable
from insight.sources import SourceConfig, SourceStore, new_source_id
from insight.timeutil import utcnow


@dataclass
class SetupResult:
    ok: bool
    message: str
    source: SourceConfig | None = None


def explain_failure(
    source: SourceConfig, label: str, error: BaseException, timeout_s: float
) -> str:
    """A plain-words explanation of why a connection test failed, naming the source."""
    name = source.name or label
    if isinstance(error, AuthFailed):
        return (
            f"{name} rejected the credentials Insight used. Check the username, password or API key, "
            "and that the account is allowed to read."
        )
    if isinstance(error, ParseFailed):
        return (
            f"{name} answered at {source.address}, but not in a way Insight understands. "
            f"Check that this address is the {label}."
        )
    if isinstance(error, Unreachable):
        return (
            f"Insight could not reach {name} at {source.address}. Check the address and that the "
            f"device is switched on and connected. ({error})"
        )
    if isinstance(error, TimeoutError):
        return f"{name} at {source.address} did not answer within {timeout_s:.0f} seconds."
    if isinstance(error, CollectionError):
        return f"Insight could not collect from {name}: {error.message}"
    return f"Insight could not set up {name}: {type(error).__name__}."


async def test_source(source: SourceConfig) -> SetupResult:
    """Run one read-only collection against the source, without saving anything."""
    try:
        adapter = registry.build(source)
    except (KeyError, ValueError) as exc:
        return SetupResult(False, f"Insight can't set up a source of that type: {exc}")
    label = adapter.info.label
    try:
        result = await asyncio.wait_for(
            adapter.test_connection(utcnow()), timeout=adapter.timeout_s
        )
    except (CollectionError, TimeoutError) as exc:
        return SetupResult(False, explain_failure(source, label, exc, adapter.timeout_s))
    except Exception as exc:  # adapters must never crash setup
        return SetupResult(False, explain_failure(source, label, exc, adapter.timeout_s))
    finally:
        await adapter.close()
    if not result.ok:
        return SetupResult(False, result.message)
    return SetupResult(True, result.message, source)


async def add_source(
    store: SourceStore,
    *,
    kind: str,
    name: str,
    address: str,
    credentials: dict[str, Any],
    options: dict[str, Any] | None = None,
    interval_s: float | None = None,
    source_id: str | None = None,
) -> SetupResult:
    """Test a new or changed source and save it only if the connection works."""
    info = registry.adapter_class(kind).info
    source = SourceConfig(
        id=source_id or new_source_id(kind),
        kind=kind,
        name=name.strip() or info.label,
        address=address.strip(),
        reliability=info.reliability,
        credentials={k: v for k, v in credentials.items() if v not in (None, "")},
        options=options or {},
        interval_s=interval_s,
    )
    if source_id is not None:
        existing = store.get(source_id)
        if existing is not None:
            # Blank credential fields keep what is stored (they are never displayed).
            source.credentials = {**existing.credentials, **source.credentials}
    result = await test_source(source)
    if result.ok:
        store.save(source)
    return result
