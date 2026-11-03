"""Repository snapshots: which files an analysis sees, in which order, and how GitHub is asked.

GitHub is an in-process ``httpx.MockTransport`` installed through the module's ``TRANSPORT``
hook, so no request leaves the process.
"""

from __future__ import annotations

import io
import tarfile
from collections.abc import Callable

import httpx
import pytest
from pydantic import JsonValue

from app.services import repo_snapshot
from app.services.repo_snapshot import (
    RepositorySnapshotService,
    SnapshotError,
    fetch_archive,
    file_chars,
    read_snapshot,
    resolve_commit,
)
from app.services.repositories import RepositoryEntry

SHA = "abc123def456abc123def456abc123def456abcd"
TOKEN = "ghp_repository_token_value"


def _tarball(files: dict[str, bytes], *, prefix: str = "acme-app") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path, payload in files.items():
            info = tarfile.TarInfo(f"{prefix}-{SHA}/{path}")
            info.size = len(payload)
            info.mtime = 0
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


# --- what an analysis sees ----------------------------------------------------------------------


def test_the_files_an_analysis_needs_come_first_and_noise_is_skipped() -> None:
    snapshot = read_snapshot(
        _tarball(
            {
                "src/deep/nested/module.py": b"def work():\n    return 1\n",
                "package.json": b'{"name":"app"}\n',
                "docs/guide.md": b"# Guide\n",
                "README.md": b"# App\n",
                "AGENTS.md": b"# Rules\n",
                "node_modules/left-pad/index.js": b"module.exports = 1\n",
                "package-lock.json": b"{}",
                "logo.png": b"\x89PNG\r\n\x1a\n\x00\x00",
                "blob.bin": b"\x00\x01\x02\x03",
                "src/data.raw": b"\x00binary",
                "empty.txt": b"",
            }
        )
    )
    assert [entry["path"] for entry in snapshot["files"]] == [
        "AGENTS.md",
        "README.md",
        "docs/guide.md",
        "package.json",
        "src/deep/nested/module.py",
    ]
    assert snapshot["truncated"] is False
    assert snapshot["text_bytes"] == sum(entry["bytes"] for entry in snapshot["files"])


def test_the_same_archive_gives_the_same_snapshot_whatever_the_member_order() -> None:
    files = {"b.md": b"b", "a.md": b"a", "src/x.py": b"x = 1\n", "docs/z.md": b"z"}
    reordered = dict(reversed(list(files.items())))
    first = read_snapshot(_tarball(files))
    assert read_snapshot(_tarball(files)) == first
    assert read_snapshot(_tarball(reordered)) == first


def test_too_many_files_stop_at_the_cap() -> None:
    snapshot = read_snapshot(
        _tarball({f"src/file_{index:03d}.py": b"x = 1\n" for index in range(250)})
    )
    assert len(snapshot["files"]) == repo_snapshot.MAX_FILES
    assert snapshot["truncated"] is True


def test_too_much_text_stops_at_the_cap() -> None:
    chunk = b"x" * 100_000
    snapshot = read_snapshot(_tarball({f"src/big_{index}.py": chunk for index in range(4)}))
    assert snapshot["truncated"] is True
    assert snapshot["text_bytes"] <= repo_snapshot.MAX_TEXT_BYTES


def test_a_budget_cuts_the_snapshot_where_the_next_file_would_not_fit() -> None:
    archive = _tarball({"README.md": b"r" * 1000, "src/a.py": b"a" * 1000, "src/b.py": b"b" * 1000})
    whole = read_snapshot(archive)
    first, second, third = whole["files"]
    budget = file_chars(first) + file_chars(second)
    cut = read_snapshot(archive, budget_chars=budget)
    # The same order as without a budget, stopped before the file that would not fit.
    assert [file["path"] for file in cut["files"]] == ["README.md", "src/a.py"]
    assert (cut["truncated"], cut["chars"], cut["text_bytes"]) == (True, budget, 2000)
    assert (whole["truncated"], whole["chars"]) == (False, budget + file_chars(third))


def test_text_that_is_not_utf8_is_kept_readable() -> None:
    snapshot = read_snapshot(_tarball({"notes.md": "Malmö".encode("latin-1")}))
    assert snapshot["files"][0]["content"] == "Malm�"


def test_a_broken_archive_is_a_named_failure() -> None:
    with pytest.raises(SnapshotError) as failure:
        read_snapshot(b"not a tarball")
    assert failure.value.code == "malformed_archive"


def test_the_prompt_states_the_caps() -> None:
    description = repo_snapshot.RepositorySnapshotService.describe()
    assert "2 MB" in description and "200 files" in description and "200 KB" in description


type GitHub = Callable[[Callable[[httpx.Request], httpx.Response]], list[httpx.Request]]


# --- how GitHub is asked ------------------------------------------------------------------------


@pytest.fixture()
def github(monkeypatch: pytest.MonkeyPatch) -> GitHub:
    def install(handler: Callable[[httpx.Request], httpx.Response]) -> list[httpx.Request]:
        seen: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        monkeypatch.setattr(repo_snapshot, "TRANSPORT", httpx.MockTransport(record))
        return seen

    return install


def _redirect(location: str, archive: bytes = b"") -> Callable[[httpx.Request], httpx.Response]:
    def handle(request: httpx.Request) -> httpx.Response:
        if "/tarball/" in str(request.url):
            return httpx.Response(302, headers={"location": location})
        return httpx.Response(200, content=archive)

    return handle


def test_the_commit_is_resolved_with_the_token(github: GitHub) -> None:
    seen = github(lambda _request: httpx.Response(200, json={"sha": SHA}))
    assert resolve_commit("acme", "app", "main", TOKEN) == SHA
    assert str(seen[0].url) == "https://api.github.com/repos/acme/app/commits/main"
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"


def test_without_a_branch_the_default_head_is_read(github: GitHub) -> None:
    seen = github(lambda _request: httpx.Response(200, json={"sha": SHA}))
    resolve_commit("acme", "app", None, None)
    assert str(seen[0].url).endswith("/commits/HEAD")
    assert "authorization" not in seen[0].headers


@pytest.mark.parametrize(
    ("status", "headers", "code"),
    [
        (401, {}, "unauthorized"),
        (404, {}, "not_found"),
        (429, {}, "rate_limited"),
        (403, {"x-ratelimit-remaining": "0"}, "rate_limited"),
        (403, {}, "forbidden"),
        (500, {}, "unreachable"),
    ],
)
def test_a_refusal_is_named_the_way_an_operator_reads_it(
    github: GitHub, status: int, headers: dict[str, str], code: str
) -> None:
    github(lambda _request: httpx.Response(status, headers=headers, json={"message": "nope"}))
    with pytest.raises(SnapshotError) as failure:
        resolve_commit("acme", "app", "main", TOKEN)
    assert failure.value.code == code


def test_an_answer_without_a_sha_is_malformed(github: GitHub) -> None:
    github(lambda _request: httpx.Response(200, json={"message": "no sha"}))
    with pytest.raises(SnapshotError) as failure:
        resolve_commit("acme", "app", "main", TOKEN)
    assert failure.value.code == "malformed_response"


def test_the_archive_comes_from_codeload_without_the_token(github: GitHub) -> None:
    archive = _tarball({"README.md": b"# App\n"})
    seen = github(_redirect(f"https://codeload.github.com/acme/app/legacy.tar.gz/{SHA}", archive))
    assert fetch_archive("acme", "app", SHA, TOKEN) == archive
    api_request, download = seen
    assert api_request.headers["authorization"] == f"Bearer {TOKEN}"
    assert download.url.host == "codeload.github.com"
    assert "authorization" not in download.headers


def test_a_redirect_away_from_codeload_is_refused(github: GitHub) -> None:
    seen = github(_redirect("https://evil.example.com/archive.tar.gz"))
    with pytest.raises(SnapshotError) as failure:
        fetch_archive("acme", "app", SHA, TOKEN)
    assert failure.value.code == "redirect_refused"
    assert len(seen) == 1


# --- a board's repositories share the budget ------------------------------------------------------


def _entry(name: str) -> RepositoryEntry:
    return {
        "id": f"repo-{name}",
        "name": name,
        "provider": "github",
        "url": f"https://github.com/acme/{name}",
        "branch": "main",
        "enabled": True,
        "created_at": "2026-11-03T10:00:00Z",
        "updated_at": "2026-11-03T10:00:00Z",
        "has_token": False,
        "boards": [],
    }


class Repositories:
    """RepositoryService as a snapshot reads it: the board's repositories in link order."""

    def __init__(self, *names: str) -> None:
        self.rows = [_entry(name) for name in names]

    def for_board(self, board_id: str) -> list[RepositoryEntry]:
        del board_id
        return self.rows

    def token(self, repository_id: str) -> str | None:
        del repository_id
        return None


def _github_serving(archives: dict[str, bytes]) -> Callable[[httpx.Request], httpx.Response]:
    """GitHub for the repositories of ``acme``: a commit for each, its archive through codeload;
    a repository without an archive is not found."""

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host == "codeload.github.com":  # /acme/<name>/legacy.tar.gz/<sha>
            return httpx.Response(200, content=archives[path.split("/")[2]])
        name = path.split("/")[3]  # /repos/acme/<name>/...
        if name not in archives:
            return httpx.Response(404)
        if "/commits/" in path:
            return httpx.Response(200, json={"sha": SHA})
        location = f"https://codeload.github.com/acme/{name}/legacy.tar.gz/{SHA}"
        return httpx.Response(302, headers={"location": location})

    return handle


def _budgets(entries: list[dict[str, JsonValue]]) -> list[tuple[JsonValue, JsonValue, JsonValue]]:
    return [
        (entry["name"], entry.get("budget_chars"), entry.get("snapshot_chars_included"))
        for entry in entries
    ]


def test_two_repositories_share_the_budget_and_what_one_leaves_carries_over(
    github: GitHub,
) -> None:
    small = _tarball({"README.md": b"s" * 1000})
    large = _tarball({f"src/m{index}.py": b"x" * 1000 for index in range(20)})
    github(_github_serving({"docs": small, "app": large}))
    service = RepositorySnapshotService(Repositories("docs", "app"))
    entries = service.for_board("board-1", budget_chars=10_000)
    used = file_chars(read_snapshot(small)["files"][0])
    # Link order: docs gets half and uses one file; app gets everything docs left.
    assert _budgets(entries) == [
        ("docs", 5_000, used),
        ("app", 10_000 - used, entries[1]["snapshot_chars_included"]),
    ]
    included = entries[1]["snapshot_chars_included"]
    assert isinstance(included, int) and 10_000 - used - 1_100 < included <= 10_000 - used
    assert [entry.get("content_omitted") for entry in entries] == [False, False]


def test_a_repository_that_fails_leaves_its_share_to_the_next(github: GitHub) -> None:
    github(_github_serving({"app": _tarball({"README.md": b"r" * 100})}))
    service = RepositorySnapshotService(Repositories("gone", "app"))
    gone, app = service.for_board("board-1", budget_chars=8_000)
    assert (gone.get("error"), gone.get("budget_chars")) == ("not_found", None)
    assert app.get("budget_chars") == 8_000


def test_a_repository_without_room_for_its_first_file_says_its_content_is_omitted(
    github: GitHub,
) -> None:
    github(_github_serving({"app": _tarball({"README.md": b"r" * 1000})}))
    (entry,) = RepositorySnapshotService(Repositories("app")).for_board("board-1", budget_chars=50)
    assert (entry.get("files"), entry.get("content_omitted"), entry.get("truncated")) == (
        [],
        True,
        True,
    )


def test_an_archive_over_the_limit_is_refused(github: GitHub) -> None:
    oversized = b"\x1f\x8b" + b"0" * (repo_snapshot.ARCHIVE_MAX_BYTES + 1024)
    github(_redirect(f"https://codeload.github.com/acme/app/legacy.tar.gz/{SHA}", oversized))
    with pytest.raises(SnapshotError) as failure:
        fetch_archive("acme", "app", SHA, TOKEN)
    assert failure.value.code == "too_large"
