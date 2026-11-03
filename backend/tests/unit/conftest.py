"""Inputs shared by the unit tests, each built once per session and never changed by a test."""

from __future__ import annotations

import pytest
from pydantic_settings import SettingsConfigDict

from app.core.config import Settings
from app.db import freshness


def pytest_sessionstart(session: pytest.Session) -> None:
    """Stop before collecting when the rows were generated from another schema.

    Rows from an older schema would let a test pass against tables that no longer exist. Comparing
    the manifest's hash reads files only; it opens no database.
    """
    del session
    problem = freshness.problem()
    if problem is not None:
        pytest.exit(problem, returncode=1)


# Long enough and unpublished, so nothing generates or writes a replacement secret.
UNIT_SECRET = "unit-test-installation-secret-" + "s" * 24


class UnitSettings(Settings):
    """The application's settings without a `.env` file, so every machine sees the same values."""

    model_config = SettingsConfigDict(env_file=None)


@pytest.fixture(scope="session")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """A fixed, strong secret in a directory of its own."""
    return UnitSettings(data_dir=tmp_path_factory.mktemp("data"), secret_key=UNIT_SECRET)
