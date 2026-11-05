"""Registry of available adapter kinds."""

from __future__ import annotations

from insight.collection.adapter import Adapter, AdapterInfo
from insight.sources import SourceConfig

_ADAPTERS: dict[str, type[Adapter]] = {}


def register(cls: type[Adapter]) -> type[Adapter]:
    _ADAPTERS[cls.info.kind] = cls
    return cls


def adapter_class(kind: str) -> type[Adapter]:
    _load_builtin()
    try:
        return _ADAPTERS[kind]
    except KeyError as exc:
        raise KeyError(f"no adapter for source kind {kind!r}") from exc


def available() -> list[AdapterInfo]:
    _load_builtin()
    return [cls.info for cls in _ADAPTERS.values()]


def build(source: SourceConfig) -> Adapter:
    return adapter_class(source.kind)(source)


def _load_builtin() -> None:
    # Importing the modules registers their adapters.
    import insight.adapters  # noqa: F401
