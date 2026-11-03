"""Inputs shared by the unit tests, each built once per session and never changed by a test."""

from __future__ import annotations

import pytest

from app.core.config import Settings

# Long enough and unpublished, so nothing generates or writes a replacement secret.
UNIT_SECRET = "unit-test-installation-secret-" + "s" * 24


@pytest.fixture(scope="session")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """A fixed, strong secret; `.env` is ignored so every machine sees the same values."""
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_dir=tmp_path_factory.mktemp("data"),
        secret_key=UNIT_SECRET,
    )
