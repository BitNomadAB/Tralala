"""A ``git_https`` repository in a run's snapshot: the mirror's archive through the shared reader.

``RepositorySnapshotService`` runs with the real ``MirrorService`` over the fake git and files of
``tests/unit/fakes/mirror.py``. The entry a run receives carries the provider, the branch, the
commit, when it was fetched and whether that fetch failed, and the files went through the same
``read_snapshot`` and budget as a GitHub archive.
"""

from __future__ import annotations

import io
import json
import logging
import tarfile

import pytest
from pydantic import JsonValue

from app.repositories.code_repositories import MirrorRecord
from app.services.repo_mirror import MirrorService
from app.services.repo_mirror_git import authorization_header
from app.services.repo_snapshot import RepositorySnapshotService, read_snapshot
from app.services.repositories import RepositoryEntry
from tests.unit.fakes.mirror import FakeGit, FakeMirrorFiles, FakeRemote
from tests.unit.log_lines import lines

APP_URL = "https://git.example.com/team/app.git"
LIB_URL = "https://git.example.com/team/lib.git"
SHA = "a" * 40
NEXT_SHA = "b" * 40
TOKEN = "glpat-snapshot-secret-9999"
FILES = {
    "README.md": b"# App\n",
    "docs/guide.md": b"# Guide\n",
    "src/app.py": b"x = 1\n" * 200,
    "node_modules/x/index.js": b"skipped\n",
}


def _entry(repository_id: str, url: str, *, branch: str | None = None) -> RepositoryEntry:
    return {
        "id": repository_id,
        "name": repository_id,
        "provider": "git_https",
        "url": url,
        "branch": branch,
        "default_branch": None,
        "enabled": True,
        "created_at": "2026-11-03T10:00:00Z",
        "updated_at": "2026-11-03T10:00:00Z",
        "has_token": False,
        "boards": [],
    }


class Rows:
    """RepositoryService as the snapshot uses it, remembering what it was told to record."""

    def __init__(self, *entries: RepositoryEntry, tokens: dict[str, str] | None = None) -> None:
        self.rows = list(entries)
        self.tokens = tokens or {}
        self.fetches: dict[str, MirrorRecord] = {}
        self.errors: dict[str, str] = {}

    def for_board(self, board_id: str) -> list[RepositoryEntry]:
        del board_id
        return self.rows

    def token(self, repository_id: str) -> str | None:
        return self.tokens.get(repository_id)

    def record_fetch(self, repository_id: str, record: MirrorRecord) -> None:
        self.fetches[repository_id] = record

    def record_mirror_error(self, repository_id: str, code: str) -> None:
        self.errors[repository_id] = code


class Board:
    def __init__(self, *entries: RepositoryEntry, tokens: dict[str, str] | None = None) -> None:
        self.app = FakeRemote()
        self.app.push("main", SHA, FILES)
        self.lib = FakeRemote(head="master")
        self.lib.push("master", SHA, {"README.md": b"# Lib\n" * 50})
        self.files = FakeMirrorFiles()
        self.git = FakeGit(self.files, {APP_URL: self.app, LIB_URL: self.lib})
        self.ticks = 0
        self.mirror = MirrorService(
            self.git,
            self.files,
            hosts=frozenset({"git.example.com"}),
            max_bytes=10_000,
            timeout_seconds=120,
            clock=self._clock,
        )
        self.rows = Rows(*entries, tokens=tokens)
        self.service = RepositorySnapshotService(self.rows, mirror=self.mirror)

    def _clock(self) -> str:
        self.ticks += 1
        return f"2026-11-03T11:00:{self.ticks:02d}Z"


def _github_shaped(files: dict[str, bytes]) -> bytes:
    """The same files as GitHub would wrap them: ``<owner>-<repo>-<sha>/`` first."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path, payload in files.items():
            info = tarfile.TarInfo(f"team-app-{SHA}/{path}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _without_files(entry: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {key: value for key, value in entry.items() if key != "files"}


def test_a_mirrored_repository_goes_through_the_same_reader_and_budget() -> None:
    board = Board(_entry("app", APP_URL))
    budget = 900
    (entry,) = board.service.for_board("board-1", budget_chars=budget)
    expected = read_snapshot(_github_shaped(FILES), budget_chars=budget)
    assert entry["files"] == [dict(file) for file in expected["files"]]
    assert _without_files(entry) == {
        "id": "app",
        "name": "app",
        "url": APP_URL,
        "branch": "main",
        "provider": "git_https",
        "commit_sha": SHA,
        "fetched_at": "2026-11-03T11:00:01Z",
        "stale_mirror": False,
        "file_count": 2,
        "truncated": True,
        "budget_chars": budget,
        "snapshot_chars_included": expected["chars"],
        "content_omitted": False,
    }
    assert board.rows.fetches == {
        "app": MirrorRecord(
            default_branch="main",
            last_sha=SHA,
            fetched_at="2026-11-03T11:00:01Z",
            mirror_bytes=1_000,
        )
    }
    assert board.git.commands == ["ls-remote", "clone", "archive"]


def test_a_mirrored_repository_is_read_through_its_links_globs() -> None:
    entry = _entry("app", APP_URL)
    entry["focus_paths"] = ["docs/*", "src/*"]
    entry["exclude_paths"] = ["src/*"]
    board = Board(entry)
    (steered,) = board.service.for_board("board-1")
    expected = read_snapshot(_github_shaped(FILES), focus=["docs/*", "src/*"], exclude=["src/*"])
    assert steered["files"] == [dict(file) for file in expected["files"]]
    assert [file["path"] for file in expected["files"]] == ["docs/guide.md"]
    assert (steered["focus_paths"], steered["exclude_paths"]) == (["docs/*", "src/*"], ["src/*"])


def test_a_second_run_fetches_and_sees_the_new_commit() -> None:
    board = Board(_entry("app", APP_URL))
    board.service.for_board("board-1")
    board.app.push("main", NEXT_SHA, {"README.md": b"# App 2\n"})
    (entry,) = board.service.for_board("board-1")
    assert (entry["commit_sha"], entry["stale_mirror"], entry["fetched_at"]) == (
        NEXT_SHA,
        False,
        "2026-11-03T11:00:02Z",
    )
    assert "fetch" in board.git.commands


def test_a_failed_fetch_reads_the_last_good_mirror_and_says_so() -> None:
    board = Board(_entry("app", APP_URL))
    board.service.for_board("board-1")
    board.app.push("main", NEXT_SHA, {"README.md": b"# App 2\n"})
    board.app.failure = "timeout"
    (entry,) = board.service.for_board("board-1", budget_chars=50_000)
    assert (entry["commit_sha"], entry["fetched_at"]) == (SHA, "2026-11-03T11:00:01Z")
    assert (entry["stale_mirror"], entry["fetch_error"]) == (True, "timeout")
    assert entry["file_count"] == 3
    assert board.rows.errors == {"app": "timeout"}


def test_a_repository_without_a_mirror_is_an_error_entry_and_the_next_gets_its_share(
    caplog: pytest.LogCaptureFixture,
) -> None:
    board = Board(_entry("app", APP_URL), _entry("lib", LIB_URL))
    board.app.failure = "auth_failed"
    with caplog.at_level(logging.WARNING, logger="tralala.repo_snapshot"):
        app, lib = board.service.for_board("board-1", budget_chars=8_000)
    assert app == {
        "id": "app",
        "name": "app",
        "url": APP_URL,
        "branch": None,
        "provider": "git_https",
        "error": "auth_failed",
    }
    assert (lib["branch"], lib["budget_chars"], lib["commit_sha"]) == ("master", 8_000, SHA)
    assert board.rows.errors == {"app": "auth_failed"}
    failed = [
        line for line in lines(caplog.records) if line["event"] == "repository_snapshot_failed"
    ]
    assert [(line["repository_id"], line["code"]) for line in failed] == [("app", "auth_failed")]


def test_the_token_never_reaches_the_run_or_the_log(caplog: pytest.LogCaptureFixture) -> None:
    board = Board(_entry("app", APP_URL), tokens={"app": TOKEN})
    board.app.token = TOKEN
    with caplog.at_level(logging.DEBUG, logger="tralala"):
        (entry,) = board.service.for_board("board-1")
    assert entry["commit_sha"] == SHA
    header = authorization_header(TOKEN)
    for secret in (TOKEN, header.removeprefix("Authorization: Basic ")):
        assert secret not in json.dumps(entry)
        assert secret not in json.dumps(lines(caplog.records))
        assert all(secret not in arg for call in board.git.calls for arg in call.args)
    assert "repository_snapshot_captured" in json.dumps(lines(caplog.records))


def test_a_host_outside_the_allowlist_is_refused_at_fetch() -> None:
    board = Board(_entry("app", "https://code.example.org/team/app.git"))
    (entry,) = board.service.for_board("board-1")
    assert entry["error"] == "host_not_allowed"
    assert board.git.calls == []


def test_without_a_mirror_service_the_entry_says_git_is_missing() -> None:
    rows = Rows(_entry("app", APP_URL))
    (entry,) = RepositorySnapshotService(rows).for_board("board-1")
    assert entry["error"] == "git_missing"
    assert rows.errors == {"app": "git_missing"}
