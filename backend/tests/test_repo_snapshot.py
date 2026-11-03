"""Repository snapshots: which files an analysis sees, in which order, and how GitHub is asked.

GitHub is an in-process ``httpx.MockTransport`` installed through the module's ``TRANSPORT``
hook, so no request leaves the process.
"""

from __future__ import annotations

import io
import tarfile
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.services import repo_snapshot
from app.services.repo_snapshot import SnapshotError, fetch_archive, read_snapshot, resolve_commit

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


# --- how GitHub is asked ------------------------------------------------------------------------


@pytest.fixture()
def github(monkeypatch: pytest.MonkeyPatch) -> Callable[[Callable[..., httpx.Response]], list]:
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


def test_the_commit_is_resolved_with_the_token(github: Any) -> None:
    seen = github(lambda request: httpx.Response(200, json={"sha": SHA}))
    assert resolve_commit("acme", "app", "main", TOKEN) == SHA
    assert str(seen[0].url) == "https://api.github.com/repos/acme/app/commits/main"
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"


def test_without_a_branch_the_default_head_is_read(github: Any) -> None:
    seen = github(lambda request: httpx.Response(200, json={"sha": SHA}))
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
    github: Any, status: int, headers: dict[str, str], code: str
) -> None:
    github(lambda request: httpx.Response(status, headers=headers, json={"message": "nope"}))
    with pytest.raises(SnapshotError) as failure:
        resolve_commit("acme", "app", "main", TOKEN)
    assert failure.value.code == code


def test_an_answer_without_a_sha_is_malformed(github: Any) -> None:
    github(lambda request: httpx.Response(200, json={"message": "no sha"}))
    with pytest.raises(SnapshotError) as failure:
        resolve_commit("acme", "app", "main", TOKEN)
    assert failure.value.code == "malformed_response"


def test_the_archive_comes_from_codeload_without_the_token(github: Any) -> None:
    archive = _tarball({"README.md": b"# App\n"})
    seen = github(_redirect(f"https://codeload.github.com/acme/app/legacy.tar.gz/{SHA}", archive))
    assert fetch_archive("acme", "app", SHA, TOKEN) == archive
    api_request, download = seen
    assert api_request.headers["authorization"] == f"Bearer {TOKEN}"
    assert download.url.host == "codeload.github.com"
    assert "authorization" not in download.headers


def test_a_redirect_away_from_codeload_is_refused(github: Any) -> None:
    seen = github(_redirect("https://evil.example.com/archive.tar.gz"))
    with pytest.raises(SnapshotError) as failure:
        fetch_archive("acme", "app", SHA, TOKEN)
    assert failure.value.code == "redirect_refused"
    assert len(seen) == 1


def test_an_archive_over_the_limit_is_refused(github: Any) -> None:
    oversized = b"\x1f\x8b" + b"0" * (repo_snapshot.ARCHIVE_MAX_BYTES + 1024)
    github(_redirect(f"https://codeload.github.com/acme/app/legacy.tar.gz/{SHA}", oversized))
    with pytest.raises(SnapshotError) as failure:
        fetch_archive("acme", "app", SHA, TOKEN)
    assert failure.value.code == "too_large"
