from __future__ import annotations

import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from insight.auth.credentials import MASK, CredentialError, CredentialVault
from insight.model import Reliability
from insight.runtime import Runtime
from insight.sources import SourceConfig

SECRET = "pepwave-client-secret-7c1f"


def add_source(runtime: Runtime) -> SourceConfig:
    return runtime.sources.save(
        SourceConfig(
            id="peplink-1",
            kind="peplink",
            name="Peplink router",
            address="https://10.0.0.1",
            reliability=Reliability.RELIABLE,
            credentials={"client_id": "insight", "client_secret": SECRET},
        )
    )


def test_database_holds_no_plain_text_credential(runtime: Runtime) -> None:
    add_source(runtime)
    runtime.writer.flush_sync()
    for path in runtime.settings.data_dir.rglob("insight.db*"):
        assert SECRET.encode() not in path.read_bytes(), path
    assert runtime.sources.get("peplink-1").credentials["client_secret"] == SECRET  # type: ignore[union-attr]


def test_key_file_is_private(runtime: Runtime) -> None:
    key = runtime.settings.data_dir / "secret.key"
    assert stat.S_IMODE(key.stat().st_mode) == 0o600


def test_api_masks_credentials(runtime: Runtime, engineer: TestClient) -> None:
    add_source(runtime)
    body = engineer.get("/api/engineer/sources/peplink-1").json()
    assert body["credentials"] == {"client_id": MASK, "client_secret": MASK}
    assert SECRET not in engineer.get("/api/engineer/sources").text


def test_blank_update_keeps_stored_credential(runtime: Runtime) -> None:
    add_source(runtime)
    runtime.sources.update_credentials("peplink-1", {"client_secret": ""})
    assert runtime.sources.get("peplink-1").credentials["client_secret"] == SECRET  # type: ignore[union-attr]
    runtime.sources.update_credentials("peplink-1", {"client_secret": "new-one"})
    assert runtime.sources.get("peplink-1").credentials["client_secret"] == "new-one"  # type: ignore[union-attr]


def test_wrong_key_cannot_decrypt(tmp_path: Path) -> None:
    blob = CredentialVault(tmp_path / "a.key").encrypt({"x": "y"})
    with pytest.raises(CredentialError):
        CredentialVault(tmp_path / "b.key").decrypt(blob)
