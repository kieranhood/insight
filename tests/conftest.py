from __future__ import annotations

from pathlib import Path

import pytest

from insight.runtime import Runtime
from insight.settings import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def runtime(settings: Settings) -> Runtime:
    return Runtime(settings)
