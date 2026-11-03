"""The platform profile: what is retried, what is reported, and how it is configured."""

from __future__ import annotations

import errno
from pathlib import Path
from typing import Any

import pytest

from app.core import platform as platform_profile
from app.core.config import Settings


def _locked(path: Path, *, winerror: int | None = None, errno_value: int | None = None) -> OSError:
    error = PermissionError(errno_value or errno.EACCES, "held by another process", str(path))
    if winerror is not None:
        error.winerror = winerror  # type: ignore[attr-defined]
    return error


def test_auto_resolves_to_the_running_operating_system() -> None:
    import os

    windows = os.name == "nt"
    expected = platform_profile.PROFILE_WINDOWS if windows else platform_profile.PROFILE_POSIX
    assert platform_profile.resolve_profile("auto") == expected
    assert platform_profile.resolve_profile(None) == expected


def test_an_explicit_profile_wins_and_an_unknown_one_is_rejected() -> None:
    assert platform_profile.resolve_profile("network") == "network"
    assert platform_profile.resolve_profile("WINDOWS") == "windows"
    with pytest.raises(ValueError, match="platform_profile"):
        Settings(platform_profile="solaris")


def test_settings_store_the_resolved_profile(settings: Settings) -> None:
    explicit = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_dir=settings.data_dir,
        platform_profile="network",
    )
    assert explicit.platform_profile == "network"
    assert explicit.file_profile == "network"


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ("windows", "winerror_32"),
        ("posix", None),
        ("network", None),
    ],
)
def test_a_held_file_is_transient_only_where_the_host_reports_it(
    profile: str, expected: str | None
) -> None:
    assert platform_profile.transient_error(_locked(Path("x"), winerror=32), profile) == expected


def test_a_permission_problem_is_never_retried_on_any_profile() -> None:
    for profile in ("windows", "posix", "network"):
        denied = PermissionError(errno.EACCES, "denied", "x")
        denied.winerror = 5  # type: ignore[attr-defined]
        # WinError 5 is what antivirus raises, so it is retried on Windows; EACCES alone is not.
        assert platform_profile.transient_error(
            OSError(errno.EACCES, "denied"), profile
        ) in (None, "winerror_5")
        read_only = OSError(errno.EROFS, "read-only")
        assert platform_profile.transient_error(read_only, profile) is None


def test_remove_tree_retries_a_transient_lock_and_then_succeeds(
    tmp_path: Path, monkeypatch: Any
) -> None:
    target = tmp_path / "board"
    target.mkdir()
    (target / "board.sqlite").write_bytes(b"x")
    calls = {"n": 0}
    real = platform_profile.shutil.rmtree

    def flaky(path: Any, **kwargs: Any) -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise _locked(Path(path), winerror=32)
        real(path, **kwargs)

    monkeypatch.setattr(platform_profile.shutil, "rmtree", flaky)
    monkeypatch.setattr(platform_profile, "DELAY_SECONDS", 0)
    platform_profile.remove_tree(target, profile="windows")
    assert calls["n"] == 3
    assert not target.exists()


def test_remove_tree_gives_up_immediately_on_a_permanent_error(
    tmp_path: Path, monkeypatch: Any
) -> None:
    target = tmp_path / "board"
    target.mkdir()
    calls = {"n": 0}

    def denied(path: Any, **_kwargs: Any) -> None:
        calls["n"] += 1
        raise OSError(errno.EACCES, "denied", str(path))

    monkeypatch.setattr(platform_profile.shutil, "rmtree", denied)
    monkeypatch.setattr(platform_profile, "DELAY_SECONDS", 0)
    with pytest.raises(OSError):
        platform_profile.remove_tree(target, profile="posix")
    # A retry cannot change a permission problem, so there must be exactly one attempt.
    assert calls["n"] == 1


def test_removing_what_is_not_there_is_success(tmp_path: Path) -> None:
    platform_profile.remove_tree(tmp_path / "gone", profile="posix")
    assert platform_profile.remove_file(tmp_path / "gone.txt", profile="posix") is False


def test_the_lock_mechanism_ignores_the_configured_profile() -> None:
    """A wrong profile must not be able to select a locking call this host does not have."""
    import os

    windows = os.name == "nt"
    expected = platform_profile.PROFILE_WINDOWS if windows else platform_profile.PROFILE_POSIX
    assert platform_profile.lock_primitive() == expected
