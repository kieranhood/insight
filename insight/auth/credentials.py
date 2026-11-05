"""Encryption at rest for device credentials (API keys, passwords, SNMP communities).

The key lives in its own file on the data volume (mode 0600). This protects
credentials in database exports and backups; under the managed-appliance model only
50N has root on the host, and full-disk encryption protects the volume at rest.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

MASK = "********"


class CredentialError(RuntimeError):
    pass


class CredentialVault:
    def __init__(self, key_path: Path) -> None:
        self.key_path = key_path
        self._fernet = Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        if self.key_path.exists():
            return self.key_path.read_bytes().strip()
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
        return key

    def encrypt(self, credentials: dict[str, Any]) -> bytes:
        return self._fernet.encrypt(json.dumps(credentials).encode())

    def decrypt(self, blob: bytes | None) -> dict[str, Any]:
        if not blob:
            return {}
        try:
            value: dict[str, Any] = json.loads(self._fernet.decrypt(blob))
        except InvalidToken as exc:
            raise CredentialError("stored credentials cannot be decrypted with this key") from exc
        return value


def masked(credentials: dict[str, Any]) -> dict[str, str]:
    """What the interface may show: which credential fields are set, never their values."""
    return {name: (MASK if value else "") for name, value in credentials.items()}
