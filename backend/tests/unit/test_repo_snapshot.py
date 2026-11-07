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

from app.repositories.code_repositories import MirrorRecord
from app.services import repo_snapshot
from app.services.repo_archive_cache import ArchiveCache
from app.services.repo_snapshot import (
    MAX_MANIFEST_ENTRIES,
    ManifestEntry,
    RepositorySnapshotService,
    Snapshot,
    SnapshotError,
    fetch_archive,
    file_chars,
    manifest_entry_chars,
    path_selected,
    read_snapshot,
    resolve_commit,
    select_members,
)
from app.services.repositories import RepositoryEntry
from app.services.repository_problems import problem_text
from tests.unit.fakes.archives import FakeArchiveFiles

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


def _sent(snapshot: Snapshot) -> list[tuple[str, bool]]:
    return [(entry["path"], entry["sent"]) for entry in snapshot["manifest"]]


def _unsent_chars(manifest: list[ManifestEntry]) -> int:
    """The room a manifest is given: each entry counted in its longer, not-sent form."""
    return sum(
        manifest_entry_chars({"path": entry["path"], "bytes": entry["bytes"], "sent": False})
        for entry in manifest
    )


def test_too_many_files_stop_at_the_cap_and_the_manifest_still_lists_them_all() -> None:
    snapshot = read_snapshot(
        _tarball({f"src/file_{index:03d}.py": b"x = 1\n" for index in range(250)})
    )
    assert len(snapshot["files"]) == repo_snapshot.MAX_FILES
    assert snapshot["truncated"] is True
    assert _sent(snapshot) == [
        (f"src/file_{index:03d}.py", index < repo_snapshot.MAX_FILES) for index in range(250)
    ]
    assert snapshot["manifest_omitted"] == 0


def test_too_much_text_stops_at_the_cap() -> None:
    chunk = b"x" * 100_000
    snapshot = read_snapshot(_tarball({f"src/big_{index}.py": chunk for index in range(4)}))
    assert snapshot["truncated"] is True
    assert snapshot["text_bytes"] <= repo_snapshot.MAX_TEXT_BYTES


def test_a_file_over_the_text_cap_is_skipped_and_the_smaller_files_after_it_still_come() -> None:
    # The fixed snapshot used to end at the first file that did not fit, so every file after it
    # was never sent, and an analysis reported them as missing.
    huge = b"x" * (repo_snapshot.MAX_TEXT_BYTES + 1)
    snapshot = read_snapshot(
        _tarball(
            {
                "README.md": b"# App\n",
                "docs/a_huge.md": huge,
                "docs/guide.md": b"# Guide\n",
                "src/app.py": b"x = 1\n",
            }
        )
    )
    assert [file["path"] for file in snapshot["files"]] == [
        "README.md",
        "docs/guide.md",
        "src/app.py",
    ]
    assert snapshot["truncated"] is True
    # The manifest names every file in the same order, the skipped one with its size.
    assert snapshot["manifest"] == [
        {"path": "README.md", "bytes": 6, "sent": True},
        {"path": "docs/a_huge.md", "bytes": len(huge), "sent": False},
        {"path": "docs/guide.md", "bytes": 8, "sent": True},
        {"path": "src/app.py", "bytes": 6, "sent": True},
    ]


def test_a_file_over_the_budget_is_skipped_and_a_smaller_one_after_it_still_fits() -> None:
    archive = _tarball({"README.md": b"r" * 5_000, "src/app.py": b"x = 1\n"})
    whole = read_snapshot(archive)
    _readme, app = whole["files"]
    room = _unsent_chars(whole["manifest"]) + file_chars(app)
    cut = read_snapshot(archive, budget_chars=room)
    assert [file["path"] for file in cut["files"]] == ["src/app.py"]
    assert _sent(cut) == [("README.md", False), ("src/app.py", True)]
    assert cut["truncated"] is True
    assert cut["chars"] <= room


def test_the_budget_holds_the_manifest_first_and_the_files_share_what_it_leaves() -> None:
    archive = _tarball({"README.md": b"r" * 1000, "src/a.py": b"a" * 1000, "src/b.py": b"b" * 1000})
    whole = read_snapshot(archive)
    first, second, third = whole["files"]
    files = file_chars(first) + file_chars(second)
    budget = _unsent_chars(whole["manifest"]) + files
    cut = read_snapshot(archive, budget_chars=budget)
    # The same order as without a budget; the third file did not fit beside the manifest.
    assert [file["path"] for file in cut["files"]] == ["README.md", "src/a.py"]
    assert _sent(cut) == [("README.md", True), ("src/a.py", True), ("src/b.py", False)]
    manifest = sum(manifest_entry_chars(entry) for entry in cut["manifest"])
    assert (cut["truncated"], cut["chars"], cut["text_bytes"]) == (True, files + manifest, 2000)
    assert cut["chars"] <= budget
    whole_manifest = sum(manifest_entry_chars(entry) for entry in whole["manifest"])
    assert (whole["truncated"], whole["chars"]) == (
        False,
        files + file_chars(third) + whole_manifest,
    )
    # The files alone would have fitted two; the manifest's room leaves one.
    alone = read_snapshot(archive, budget_chars=files)
    assert [file["path"] for file in alone["files"]] == ["README.md"]


def test_the_manifest_is_bounded_and_counts_the_files_beyond_it() -> None:
    count = MAX_MANIFEST_ENTRIES + 3
    snapshot = read_snapshot(_tarball({f"src/m{index:04d}.py": b"x" for index in range(count)}))
    assert len(snapshot["manifest"]) == MAX_MANIFEST_ENTRIES
    assert snapshot["manifest_omitted"] == 3
    assert snapshot["manifest"][-1]["path"] == f"src/m{MAX_MANIFEST_ENTRIES - 1:04d}.py"


def test_a_budget_too_small_for_the_whole_manifest_lists_what_fits_and_counts_the_rest() -> None:
    archive = _tarball({f"src/m{index}.py": b"x = 1\n" for index in range(10)})
    whole = read_snapshot(archive)
    budget = _unsent_chars(whole["manifest"][:4])
    cut = read_snapshot(archive, budget_chars=budget)
    listed = [entry["path"] for entry in cut["manifest"]]
    assert listed == [f"src/m{index}.py" for index in range(4)]
    assert (cut["manifest_omitted"], cut["files"], cut["truncated"]) == (6, [], True)
    assert cut["chars"] <= budget


def test_text_that_is_not_utf8_is_kept_readable() -> None:
    snapshot = read_snapshot(_tarball({"notes.md": "Malmö".encode("latin-1")}))
    assert snapshot["files"][0]["content"] == "Malm�"


def test_a_broken_archive_is_a_named_failure() -> None:
    with pytest.raises(SnapshotError) as failure:
        read_snapshot(b"not a tarball")
    assert failure.value.code == "malformed_archive"


# --- a board link's globs choose the files --------------------------------------------------------

STEERED = {
    "README.md": b"# App\n",
    "AGENTS.md": b"# Rules\n",
    "package.json": b'{"name":"app"}\n',
    "docs/guide.md": b"# Guide\n",
    "docs/api/endpoints.md": b"# Endpoints\n",
    "Docs/upper.md": b"# Upper\n",
    "src/app.py": b"x = 1\n",
    "src/generated/client.py": b"y = 2\n",
    "node_modules/docs/index.md": b"skipped\n",
}


def _paths(*, focus: tuple[str, ...] = (), exclude: tuple[str, ...] = ()) -> list[str]:
    snapshot = read_snapshot(_tarball(STEERED), focus=focus, exclude=exclude)
    return [file["path"] for file in snapshot["files"]]


def test_without_globs_the_whole_repository_is_read_as_before() -> None:
    archive = _tarball(STEERED)
    assert read_snapshot(archive, focus=(), exclude=()) == read_snapshot(archive)
    assert _paths() == [
        "AGENTS.md",
        "README.md",
        "docs/guide.md",
        "docs/api/endpoints.md",
        "package.json",
        "Docs/upper.md",
        "src/app.py",
        "src/generated/client.py",
    ]


def test_focus_globs_keep_only_the_files_they_match_in_the_priority_order() -> None:
    # ``*`` matches ``/`` too, so ``docs/**`` and ``docs/*`` both reach every depth; the match is
    # case sensitive on every platform, so ``Docs/`` is another folder.
    assert _paths(focus=("docs/**",)) == ["docs/guide.md", "docs/api/endpoints.md"]
    assert _paths(focus=("docs/*",)) == ["docs/guide.md", "docs/api/endpoints.md"]
    assert _paths(focus=("src/*.py", "README.md")) == [
        "README.md",
        "src/app.py",
        "src/generated/client.py",
    ]
    assert _paths(focus=("nothing/**",)) == []


def test_exclude_globs_drop_the_files_they_match() -> None:
    assert _paths(exclude=("docs/**", "*.json", "Docs/*")) == [
        "AGENTS.md",
        "README.md",
        "src/app.py",
        "src/generated/client.py",
    ]


def test_exclude_wins_over_focus() -> None:
    assert _paths(focus=("src/**",), exclude=("src/generated/*",)) == ["src/app.py"]
    assert _paths(focus=("*.md",), exclude=("*.md",)) == []


def test_a_focus_glob_cannot_bring_back_what_is_never_read() -> None:
    assert _paths(focus=("node_modules/**",)) == []


def test_with_focus_globs_the_cap_falls_on_the_files_they_keep() -> None:
    files = {f"docs/page_{index:03d}.md": b"page\n" for index in range(250)}
    files.update({"README.md": b"# App\n", "src/app.py": b"x = 1\n"})
    snapshot = read_snapshot(_tarball(files), focus=("docs/**",))
    paths = [file["path"] for file in snapshot["files"]]
    assert len(paths) == repo_snapshot.MAX_FILES
    assert snapshot["truncated"] is True
    assert paths == [f"docs/page_{index:03d}.md" for index in range(repo_snapshot.MAX_FILES)]


def test_select_members_applies_the_globs_before_the_order() -> None:
    with tarfile.open(fileobj=io.BytesIO(_tarball(STEERED)), mode="r:gz") as archive:
        chosen = select_members(archive, focus=("*.md",), exclude=("docs/api/*",))
    assert [relative for _key, _member, relative in chosen] == [
        "AGENTS.md",
        "README.md",
        "docs/guide.md",
        "Docs/upper.md",
    ]


@pytest.mark.parametrize(
    ("path", "focus", "exclude", "kept"),
    [
        ("docs/a.md", (), (), True),
        ("docs/a.md", ("docs/*",), (), True),
        ("src/a.py", ("docs/*",), (), False),
        ("docs/a.md", (), ("docs/*",), False),
        ("docs/a.md", ("docs/*",), ("*.md",), False),
        ("README.md", ("readme.md",), (), False),
    ],
)
def test_path_selected(
    path: str, focus: tuple[str, ...], exclude: tuple[str, ...], kept: bool
) -> None:
    assert path_selected(path, focus, exclude) is kept


def test_the_prompt_states_the_caps() -> None:
    description = repo_snapshot.RepositorySnapshotService.describe()
    assert "128 MiB" in description and "200 files" in description and "200 KB" in description


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
        "default_branch": None,
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

    def record_fetch(self, repository_id: str, record: MirrorRecord) -> None:
        del repository_id, record
        raise AssertionError("a GitHub repository has no mirror")

    def record_mirror_error(self, repository_id: str, code: str) -> None:
        del repository_id, code
        raise AssertionError("a GitHub repository has no mirror")


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


def test_a_public_repository_is_read_without_a_token_and_a_known_commit_only_once(
    github: GitHub,
) -> None:
    seen = github(_github_serving({"app": _tarball({"README.md": b"# App"})}))
    archives = ArchiveCache(FakeArchiveFiles())
    service = RepositorySnapshotService(Repositories("app"), archives=archives)
    first = service.for_board("board-1", budget_chars=10_000)
    second = service.for_board("board-1", budget_chars=10_000)
    assert first == second
    assert all("authorization" not in request.headers for request in seen)
    # Both runs resolved the branch; only the first downloaded the archive of its commit.
    paths = [(request.url.host, request.url.path.split("/")[-2]) for request in seen]
    assert [path for path in paths if path[1] == "commits"] == [("api.github.com", "commits")] * 2
    downloads = [request for request in seen if request.url.host == "codeload.github.com"]
    assert len(downloads) == 1


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
    # What a snapshot uses of its share is its file and its manifest.
    alone = read_snapshot(small)
    used = file_chars(alone["files"][0]) + manifest_entry_chars(alone["manifest"][0])
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


def test_the_snapshot_reads_each_repository_through_its_links_globs(github: GitHub) -> None:
    github(_github_serving({"docs": _tarball(STEERED), "app": _tarball(STEERED)}))
    repositories = Repositories("docs", "app")
    docs = repositories.rows[0]
    docs["focus_paths"] = ["docs/**"]
    docs["exclude_paths"] = ["docs/api/*"]
    steered, whole = RepositorySnapshotService(repositories).for_board("board-1")
    assert [file["path"] for file in _files(steered)] == ["docs/guide.md"]
    # The manifest lists what the globs keep, never what they leave out.
    assert steered.get("manifest") == [{"path": "docs/guide.md", "bytes": 8, "sent": True}]
    assert (steered.get("focus_paths"), steered.get("exclude_paths")) == (
        ["docs/**"],
        ["docs/api/*"],
    )
    # A link without globs reads the whole repository, and its entry says nothing about globs.
    assert len(_files(whole)) == 8
    assert "focus_paths" not in whole and "exclude_paths" not in whole


def _files(entry: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    files = entry.get("files")
    assert isinstance(files, list)
    return [file for file in files if isinstance(file, dict)]


def test_a_github_entry_carries_the_manifest_of_every_file_sent_or_not(github: GitHub) -> None:
    huge = b"x" * (repo_snapshot.MAX_TEXT_BYTES + 1)
    archive = _tarball({"README.md": b"# App\n", "docs/a_huge.md": huge, "src/app.py": b"x = 1\n"})
    github(_github_serving({"app": archive}))
    (entry,) = RepositorySnapshotService(Repositories("app")).for_board("board-1")
    assert entry.get("manifest") == [
        {"path": "README.md", "bytes": 6, "sent": True},
        {"path": "docs/a_huge.md", "bytes": len(huge), "sent": False},
        {"path": "src/app.py", "bytes": 6, "sent": True},
    ]
    assert "manifest_omitted" not in entry
    assert [file["path"] for file in _files(entry)] == ["README.md", "src/app.py"]
    assert (entry.get("file_count"), entry.get("truncated")) == (2, True)


def test_an_archive_over_the_limit_is_refused(github: GitHub) -> None:
    oversized = b"\x1f\x8b" + b"0" * 2048
    github(_redirect(f"https://codeload.github.com/acme/app/legacy.tar.gz/{SHA}", oversized))
    with pytest.raises(SnapshotError) as failure:
        fetch_archive("acme", "app", SHA, TOKEN, max_bytes=1024)
    assert failure.value.code == "too_large"


def test_the_archive_limit_is_a_setting_of_the_service(github: GitHub) -> None:
    """TRALALA_REPOSITORY_ARCHIVE_MAX_BYTES reaches the download: a run whose archive is larger
    reads that repository as an error entry, never as a failed run."""
    github(_github_serving({"app": b"0" * 2048}))
    service = RepositorySnapshotService(Repositories("app"), archive_max_bytes=1024)
    (fetched,) = service.fetch("board-1")
    assert (fetched.archive, fetched.entry.get("error")) == (None, "too_large")
    assert service.snapshot_of([fetched]) == [fetched.entry]


def test_a_fetch_read_as_a_snapshot_is_the_snapshot_of_the_board(github: GitHub) -> None:
    """A run that fetched for the tools and then reads the snapshot (its provider refused the
    tools) sends what the single-call path would have sent, without fetching again."""
    seen = github(_github_serving({"app": _tarball({"README.md": b"# App", "src/a.py": b"x"})}))
    service = RepositorySnapshotService(Repositories("app"))
    fetched = service.fetch("board-1")
    assert [item.entry.get("commit_sha") for item in fetched] == [SHA]
    assert all(item.archive for item in fetched)
    requests = len(seen)
    assert service.snapshot_of(fetched, budget_chars=10_000) == service.for_board(
        "board-1", budget_chars=10_000
    )
    assert len(seen) == requests * 2  # for_board fetched again; snapshot_of did not


# --- a read that failed says so (PLN-012) ------------------------------------------------------


def test_a_repository_the_host_will_not_show_carries_the_sentence_a_person_reads(
    github: GitHub,
) -> None:
    github(_github_serving({}))
    (entry,) = RepositorySnapshotService(Repositories("app")).for_board("board-1")
    assert entry.get("error") == "not_found"
    # Read without a key: a private repository looks like a missing one, and the sentence says so.
    assert entry.get("problem") == problem_text("not_found", "app", has_token=False)


@pytest.mark.parametrize(
    ("files", "focus", "code"),
    [
        ({}, (), "empty_archive"),
        ({"node_modules/x/index.js": b"x", "logo.png": b"png", "pnpm-lock.yaml": b"l"}, (), None),
        ({"README.md": b"# App", "src/app.py": b"x = 1"}, ("lib/**",), "paths_match_nothing"),
        ({"README.md": b"# App"}, ("src",), "paths_match_nothing"),
    ],
)
def test_a_snapshot_with_nothing_to_read_is_a_failed_read_that_names_why(
    files: dict[str, bytes], focus: tuple[str, ...], code: str | None
) -> None:
    fetched = repo_snapshot.FetchedRepository(
        {"id": "repo-app", "name": "app", "commit_sha": SHA}, _tarball(files), focus
    )
    (entry,) = RepositorySnapshotService(Repositories()).snapshot_of([fetched])
    expected = code or "nothing_readable"
    assert entry.get("error") == expected
    assert entry.get("problem") == problem_text(expected, "app")
    assert "files" not in entry


def test_a_snapshot_with_files_is_never_marked_empty() -> None:
    fetched = repo_snapshot.FetchedRepository(
        {"id": "repo-app", "name": "app", "commit_sha": SHA}, _tarball({"README.md": b"# App"})
    )
    (entry,) = RepositorySnapshotService(Repositories()).snapshot_of([fetched])
    assert "error" not in entry and entry.get("file_count") == 1
