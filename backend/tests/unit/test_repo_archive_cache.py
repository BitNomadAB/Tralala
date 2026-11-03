"""The GitHub archive cache: per repository and commit, bounded, the oldest out first, and never a
reason for a run to fail."""

from __future__ import annotations

import logging

import pytest

from app.services.repo_archive_cache import ArchiveCache, cache_key_valid
from tests.unit.fakes.archives import FakeArchiveFiles
from tests.unit.log_lines import events

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


def test_an_archive_is_kept_per_repository_and_commit() -> None:
    cache = ArchiveCache(FakeArchiveFiles(), max_bytes=1_000)
    cache.put("repo-1", SHA_A, b"one")
    assert (cache.get("repo-1", SHA_A), cache.get("repo-1", SHA_B), cache.get("repo-2", SHA_A)) == (
        b"one",
        None,
        None,
    )


def test_the_oldest_archives_go_first_until_the_cache_fits() -> None:
    files = FakeArchiveFiles()
    cache = ArchiveCache(files, max_bytes=250)
    cache.put("repo-1", SHA_A, b"a" * 100)
    cache.put("repo-2", SHA_B, b"b" * 100)
    cache.put("repo-1", SHA_C, b"c" * 100)
    # 300 bytes over a 250-byte bound: the first archive written is the one that goes.
    assert files.removed == [("repo-1", SHA_A)]
    assert sorted(files.stored) == [("repo-1", SHA_C), ("repo-2", SHA_B)]


def test_the_archive_just_written_stays_even_when_it_is_the_oldest_by_its_time() -> None:
    files = FakeArchiveFiles()
    cache = ArchiveCache(files, max_bytes=150)
    files.stored[("repo-2", SHA_B)] = (b"b" * 100, 50.0)
    cache.put("repo-1", SHA_A, b"a" * 100)
    assert list(files.stored) == [("repo-1", SHA_A)]


def test_an_archive_larger_than_the_cache_or_a_zero_bound_keeps_nothing() -> None:
    files = FakeArchiveFiles()
    ArchiveCache(files, max_bytes=10).put("repo-1", SHA_A, b"x" * 11)
    disabled = ArchiveCache(files, max_bytes=0)
    disabled.put("repo-1", SHA_B, b"x")
    assert (files.stored, disabled.get("repo-1", SHA_B)) == ({}, None)


@pytest.mark.parametrize(
    ("repository_id", "sha"),
    [("../etc", SHA_A), ("repo-1", "../../x"), ("repo-1", "A" * 40), ("", SHA_A)],
)
def test_a_key_that_is_not_an_id_and_a_commit_never_reaches_the_files(
    repository_id: str, sha: str
) -> None:
    files = FakeArchiveFiles()
    cache = ArchiveCache(files, max_bytes=1_000)
    cache.put(repository_id, sha, b"x")
    assert (cache_key_valid(repository_id, sha), files.stored, cache.get(repository_id, sha)) == (
        False,
        {},
        None,
    )


@pytest.mark.parametrize("fail", ["read", "write"])
def test_a_cache_that_cannot_read_or_write_is_logged_and_never_raises(
    caplog: pytest.LogCaptureFixture, fail: str
) -> None:
    cache = ArchiveCache(FakeArchiveFiles(fail=fail), max_bytes=1_000)
    with caplog.at_level(logging.WARNING, logger="tralala.repo_snapshot"):
        cache.put("repo-1", SHA_A, b"x")
        assert cache.get("repo-1", SHA_A) is None
    assert {"event": "repository_archive_cache_failed", "operation": fail} in [
        {key: line[key] for key in ("event", "operation")} for line in events(caplog.records)
    ]
