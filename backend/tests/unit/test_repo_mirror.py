"""The Tralala-managed Git mirror: clone, fetch, hygiene, fallback, budget, token and git's rules.

``MirrorService`` runs its real code against ``tests/unit/fakes/mirror.py``: a fake ``RunGit`` that
records every command and plays the remote, acting on fake mirror files in memory. No git program
runs and no file is written. The pure helpers of ``repo_mirror_git`` and ``repo_mirror_files`` are
tested at the end.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import tarfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.services.repo_mirror import (
    ARCHIVE_MAX_BYTES,
    MirrorRequest,
    MirrorService,
    archive_commit,
)
from app.services.repo_mirror_files import (
    MirrorState,
    canonical_repository_id,
    decode_state,
    encode_state,
)
from app.services.repo_mirror_git import (
    COMMANDS,
    SAFETY_OPTIONS,
    MirrorError,
    SubprocessGit,
    args_problem,
    authorization_header,
    classify_failure,
    failure_detail,
    git_args,
    git_environment,
    git_url_problem,
    parse_ls_remote,
    valid_branch,
)
from app.services.repo_snapshot import read_snapshot
from tests.unit.fakes.mirror import ROOT, FakeGit, FakeMirrorFiles, FakeRemote
from tests.unit.log_lines import lines

URL = "https://git.example.com/team/app.git"
OTHER_URL = "https://git.example.com/team/lib.git"
HOSTS = frozenset({"git.example.com"})
REPO = "8c1f6c5e-2b7d-4e8a-9f3c-0d1e2f3a4b5c"
OTHER = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
SHA_1 = "1" * 40
SHA_2 = "2" * 40
TOKEN = "glpat-mirror-secret-7777"
FILES_1 = {"README.md": b"# App\n", "src/app.py": b"print(1)\n"}
FILES_2 = {"README.md": b"# App, second edition\n", "src/app.py": b"print(2)\n"}
SIX = {" ".join(command) for command in COMMANDS}


class Clock:
    """2026-11-03T10:00:01Z, :02Z, ... one second per call."""

    def __init__(self) -> None:
        self.ticks = 0

    def __call__(self) -> str:
        self.ticks += 1
        return f"2026-11-03T10:00:{self.ticks:02d}Z"


@dataclass(slots=True)
class Mirror:
    files: FakeMirrorFiles
    remote: FakeRemote
    git: FakeGit
    service: MirrorService


def make_mirror(*, head: str = "main", max_bytes: int = 10_000, token: str | None = None) -> Mirror:
    remote = FakeRemote(head=head, token=token)
    remote.push(head, SHA_1, FILES_1)
    files = FakeMirrorFiles()
    git = FakeGit(files, {URL: remote, OTHER_URL: FakeRemote(branches=dict(remote.branches))})
    service = MirrorService(
        git, files, hosts=HOSTS, max_bytes=max_bytes, timeout_seconds=120, clock=Clock()
    )
    return Mirror(files, remote, git, service)


def request(
    *, branch: str | None = None, url: str = URL, repository_id: str = REPO
) -> MirrorRequest:
    return MirrorRequest(repository_id=repository_id, url=url, branch=branch)


def after_options(args: tuple[str, ...]) -> tuple[str, ...]:
    return args[len(SAFETY_OPTIONS) :]


def paths(archive: bytes) -> list[str]:
    return [file["path"] for file in read_snapshot(archive)["files"]]


# --- clone, then fetch ---------------------------------------------------------------------------


def test_the_first_read_clones_and_the_second_fetches() -> None:
    mirror = make_mirror()
    first = mirror.service.read_latest(request(), None)
    assert mirror.git.commands == ["ls-remote", "clone", "archive"]
    ls_remote, clone, _archive = mirror.git.calls
    assert after_options(ls_remote.args) == ("ls-remote", "--symref", "--", URL, "HEAD")
    assert after_options(clone.args) == (
        "clone",
        "--bare",
        "--depth",
        "1",
        "--single-branch",
        "--branch",
        "main",
        "--no-tags",
        "--",
        URL,
        f"{ROOT}/{REPO}/mirror.git",
    )
    mirror.git.calls.clear()
    second = mirror.service.read_latest(request(), None)
    assert mirror.git.commands == ["ls-remote", "fetch", "reflog expire", "gc", "archive"]
    assert after_options(mirror.git.calls[1].args) == (
        f"--git-dir={ROOT}/{REPO}/mirror.git",
        "fetch",
        "--depth",
        "1",
        "--prune",
        "--no-tags",
        "--update-head-ok",
        "--no-auto-gc",
        "--",
        URL,
        "+refs/heads/main:refs/heads/main",
    )
    assert (first.commit_sha, second.commit_sha) == (SHA_1, SHA_1)
    assert (first.head.fetched_at, second.head.fetched_at) == (
        "2026-11-03T10:00:01Z",
        "2026-11-03T10:00:02Z",
    )
    assert paths(second.archive) == ["README.md", "src/app.py"]
    assert mirror.files.read_state(REPO) == {
        "url": URL,
        "branch": "main",
        "default_branch": "main",
        "last_sha": SHA_1,
        "fetched_at": "2026-11-03T10:00:02Z",
        "mirror_bytes": 1_000,
        "last_error": None,
    }


@pytest.mark.parametrize("head", ["main", "master"])
def test_without_a_branch_the_remotes_head_names_it(head: str) -> None:
    mirror = make_mirror(head=head)
    latest = mirror.service.read_latest(request(), None)
    assert (latest.head.branch, latest.head.default_branch) == (head, head)
    assert after_options(mirror.git.calls[1].args)[5:7] == ("--branch", head)
    state = mirror.files.read_state(REPO)
    assert state is not None and (state["branch"], state["default_branch"]) == (head, head)


def test_an_explicit_branch_wins_and_the_remote_is_not_asked_for_its_head() -> None:
    mirror = make_mirror()
    mirror.remote.push("release", SHA_2, FILES_2)
    latest = mirror.service.read_latest(request(branch="release"), None)
    assert mirror.git.commands == ["clone", "archive"]
    assert (latest.head.branch, latest.head.default_branch, latest.commit_sha) == (
        "release",
        None,
        SHA_2,
    )


def test_a_new_remote_commit_appears_in_the_second_run() -> None:
    mirror = make_mirror()
    first = mirror.service.read_latest(request(), None)
    mirror.remote.push("main", SHA_2, FILES_2)
    second = mirror.service.read_latest(request(), None)
    assert (first.commit_sha, second.commit_sha) == (SHA_1, SHA_2)
    contents = {file["path"]: file["content"] for file in read_snapshot(second.archive)["files"]}
    assert contents["README.md"] == "# App, second edition\n"
    state = mirror.files.read_state(REPO)
    assert state is not None and state["last_sha"] == SHA_2


def test_a_new_default_branch_or_url_clones_again() -> None:
    mirror = make_mirror()
    mirror.service.read_latest(request(), None)
    mirror.remote.push("trunk", SHA_2, FILES_2)
    mirror.remote.head = "trunk"
    mirror.git.calls.clear()
    moved = mirror.service.read_latest(request(), None)
    assert mirror.git.commands == ["ls-remote", "clone", "archive"]
    assert (moved.head.branch, moved.commit_sha, mirror.files.removed) == ("trunk", SHA_2, [REPO])
    mirror.git.calls.clear()
    mirror.service.read_latest(request(url=OTHER_URL), None)
    assert mirror.git.commands == ["ls-remote", "clone", "archive"]


# --- a failed fetch -----------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["auth_failed", "not_found", "timeout", "fetch_failed"])
def test_a_failed_fetch_after_a_good_one_falls_back_to_the_last_good_mirror(
    code: str, caplog: pytest.LogCaptureFixture
) -> None:
    mirror = make_mirror()
    good = mirror.service.read_latest(request(), None)
    mirror.remote.push("main", SHA_2, FILES_2)
    mirror.remote.failure = code
    with caplog.at_level(logging.WARNING, logger="tralala.repo_mirror"):
        stale = mirror.service.read_latest(request(), None)
    assert stale.head.stale_mirror is True
    assert (stale.head.fetched_at, stale.head.fetch_error) == (good.head.fetched_at, code)
    assert (stale.commit_sha, paths(stale.archive)) == (SHA_1, ["README.md", "src/app.py"])
    state = mirror.files.read_state(REPO)
    assert state is not None
    assert (state["fetched_at"], state["last_sha"], state["last_error"]) == (
        good.head.fetched_at,
        SHA_1,
        code,
    )
    assert [line["event"] for line in lines(caplog.records)] == ["repository_mirror_stale"]


def test_a_fetch_of_an_explicit_branch_that_fails_falls_back_too() -> None:
    mirror = make_mirror()
    mirror.service.read_latest(request(branch="main"), None)
    mirror.remote.failure = "timeout"
    mirror.git.calls.clear()
    stale = mirror.service.read_latest(request(branch="main"), None)
    assert mirror.git.commands == ["fetch", "archive"]
    assert (stale.head.stale_mirror, stale.head.fetch_error) == (True, "timeout")


def test_without_a_good_mirror_the_failure_is_the_answer_and_nothing_is_left() -> None:
    mirror = make_mirror()
    mirror.remote.failure = "auth_failed"
    with pytest.raises(MirrorError) as caught:
        mirror.service.read_latest(request(), None)
    assert caught.value.code == "auth_failed"
    mirror.remote.failure = None
    mirror.remote.head = "gone"  # HEAD names a branch the clone cannot find
    with pytest.raises(MirrorError) as missing:
        mirror.service.read_latest(request(), None)
    assert missing.value.code == "not_found"
    assert mirror.files.mirrors == {}


# --- hygiene and size ----------------------------------------------------------------------------


def test_hygiene_follows_every_fetch_and_keeps_the_mirror_to_one_commit() -> None:
    mirror = make_mirror(max_bytes=1_200)
    mirror.service.read_latest(request(), None)
    for commit in ("3" * 40, "4" * 40, "5" * 40):
        mirror.remote.push("main", commit, FILES_2)
        mirror.service.read_latest(request(), None)
    commands = mirror.git.commands
    fetches = [index for index, command in enumerate(commands) if command == "fetch"]
    assert len(fetches) == 3
    for index in fetches:
        reflog, gc = mirror.git.calls[index + 1], mirror.git.calls[index + 2]
        assert after_options(reflog.args)[1:] == ("reflog", "expire", "--expire=now", "--all")
        assert after_options(gc.args)[1:] == ("gc", "--prune=now", "--quiet")
        assert reflog.git_dir == gc.git_dir == mirror.git.calls[index].git_dir
    # A fetch leaves 500 bytes behind; without the hygiene the mirror would pass its 1 200.
    state = mirror.files.read_state(REPO)
    assert state is not None and state["mirror_bytes"] == 1_000


def test_a_mirror_over_budget_after_gc_is_removed_and_cloned_on_the_next_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    mirror = make_mirror(max_bytes=1_500)
    mirror.service.read_latest(request(), None)
    mirror.remote.push("main", SHA_2, FILES_2)
    mirror.remote.size = 2_000
    mirror.git.calls.clear()
    with (
        caplog.at_level(logging.WARNING, logger="tralala.repo_mirror"),
        pytest.raises(MirrorError) as caught,
    ):
        mirror.service.read_latest(request(), None)
    assert caught.value.code == "too_large"
    assert mirror.git.commands == ["ls-remote", "fetch", "reflog expire", "gc"]
    assert REPO not in mirror.files.mirrors
    assert lines(caplog.records)[0]["mirror_bytes"] == 2_000
    mirror.remote.size = 1_200
    mirror.git.calls.clear()
    assert mirror.service.read_latest(request(), None).commit_sha == SHA_2
    assert mirror.git.commands == ["ls-remote", "clone", "archive"]


def test_a_fresh_clone_over_budget_is_removed_as_well() -> None:
    mirror = make_mirror(max_bytes=500)
    with pytest.raises(MirrorError) as caught:
        mirror.service.read_latest(request(), None)
    assert caught.value.code == "too_large"
    assert mirror.files.mirrors == {}


def test_an_archive_is_bounded() -> None:
    mirror = make_mirror()
    mirror.service.fetch_latest(request(), None)
    assert mirror.git.calls[-1].command == "clone"
    archived = mirror.service.archive(REPO, "main")
    assert mirror.git.calls[-1].max_output_bytes == ARCHIVE_MAX_BYTES
    assert archived.commit_sha == SHA_1
    with pytest.raises(MirrorError) as caught:
        mirror.service.archive(REPO, "elsewhere")
    assert caught.value.code == "not_found"


# --- the token and git's rules -------------------------------------------------------------------


def test_the_token_travels_only_in_the_environment_of_the_git_process(
    caplog: pytest.LogCaptureFixture,
) -> None:
    mirror = make_mirror(token=TOKEN)
    with caplog.at_level(logging.DEBUG, logger="tralala"):
        mirror.service.read_latest(request(), TOKEN)
        mirror.remote.push("main", SHA_2, FILES_2)
        mirror.service.read_latest(request(), TOKEN)
        mirror.remote.failure = "timeout"
        mirror.service.read_latest(request(), TOKEN)
    header = authorization_header(TOKEN)
    secrets = (TOKEN, header, base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode())
    for call in mirror.git.calls:
        assert not any(secret in arg for arg in call.args for secret in secrets)
        carried = [name for name, value in call.env.items() if any(s in value for s in secrets)]
        network = call.command in ("ls-remote", "clone", "fetch")
        assert carried == (["GIT_CONFIG_VALUE_0"] if network else [])
        if network:
            assert (call.env["GIT_CONFIG_COUNT"], call.env["GIT_CONFIG_KEY_0"]) == (
                "1",
                "http.extraHeader",
            )
            assert call.env["GIT_CONFIG_VALUE_0"] == header
    stored = mirror.files.mirrors[REPO]
    assert stored.state is not None
    assert not any(secret.encode() in stored.state for secret in secrets)
    assert not any(secret in json.dumps(stored.config) for secret in secrets)
    log = json.dumps(lines(caplog.records))
    assert "repository_mirror_fetched" in log
    assert not any(secret in log for secret in secrets)


def test_a_host_that_wants_a_token_refuses_a_fetch_without_one() -> None:
    mirror = make_mirror(token=TOKEN)
    with pytest.raises(MirrorError) as caught:
        mirror.service.read_latest(request(), None)
    assert caught.value.code == "auth_failed"
    assert "GIT_CONFIG_COUNT" not in mirror.git.calls[0].env


def test_a_host_outside_the_allowlist_is_refused_before_git_runs() -> None:
    mirror = make_mirror()
    with pytest.raises(MirrorError) as caught:
        mirror.service.read_latest(request(url="https://code.example.org/team/app.git"), None)
    assert caught.value.code == "host_not_allowed"
    with pytest.raises(MirrorError) as remote:
        mirror.service.ls_remote_default_branch("https://code.example.org/team/app.git", None)
    assert remote.value.code == "host_not_allowed"
    assert mirror.git.calls == []


def test_a_host_taken_off_the_allowlist_is_refused_even_with_a_good_mirror() -> None:
    mirror = make_mirror()
    mirror.service.read_latest(request(), None)
    narrowed = MirrorService(
        mirror.git,
        mirror.files,
        hosts=frozenset({"other.example.com"}),
        max_bytes=10_000,
        timeout_seconds=120,
    )
    mirror.git.calls.clear()
    with pytest.raises(MirrorError) as caught:
        narrowed.read_latest(request(), None)
    assert caught.value.code == "host_not_allowed"
    assert mirror.git.calls == []


def test_every_command_carries_the_safety_options_and_is_one_of_six() -> None:
    mirror = make_mirror(token=TOKEN, max_bytes=1_200)
    mirror.service.ls_remote_default_branch(URL, TOKEN, branch="main")
    mirror.service.read_latest(request(), TOKEN)
    mirror.remote.push("main", SHA_2, FILES_2)
    mirror.service.read_latest(request(), TOKEN)
    mirror.remote.failure = "fetch_failed"
    mirror.service.read_latest(request(), TOKEN)
    mirror.remote.failure = None
    mirror.remote.size = 5_000
    with pytest.raises(MirrorError):
        mirror.service.read_latest(request(), TOKEN)
    assert set(mirror.git.commands) == SIX
    for call in mirror.git.calls:
        assert call.args[: len(SAFETY_OPTIONS)] == SAFETY_OPTIONS
        assert call.command in SIX
        assert args_problem(call.args) is None
        assert call.timeout == 120
        assert {name: call.env[name] for name in git_environment(None)} == {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "HOME": "",
        }


def test_the_check_asks_the_remote_only() -> None:
    mirror = make_mirror()
    mirror.remote.push("release", SHA_2, FILES_2)
    found = mirror.service.ls_remote_default_branch(URL, None, branch="release")
    missing = mirror.service.ls_remote_default_branch(URL, None, branch="nothing")
    assert (found.default_branch, found.branch_found, missing.branch_found) == ("main", True, False)
    assert after_options(mirror.git.calls[0].args) == (
        "ls-remote",
        "--symref",
        "--",
        URL,
        "HEAD",
        "refs/heads/release",
    )
    assert mirror.git.commands == ["ls-remote", "ls-remote"]
    assert mirror.files.mirrors == {}


# --- removal -------------------------------------------------------------------------------------


def test_remove_and_the_orphan_sweep(caplog: pytest.LogCaptureFixture) -> None:
    mirror = make_mirror()
    mirror.service.read_latest(request(), None)
    mirror.service.read_latest(request(url=OTHER_URL, repository_id=OTHER), None)
    assert mirror.service.sweep_orphans({REPO}) == [OTHER]
    assert mirror.files.repository_ids() == [REPO]
    mirror.files.locked.add(REPO)
    with caplog.at_level(logging.WARNING, logger="tralala.repo_mirror"):
        with pytest.raises(MirrorError) as caught:
            mirror.service.remove(REPO)
        assert mirror.service.sweep_orphans(set()) == []
    assert caught.value.code == "mirror_cleanup_failed"
    assert [line["event"] for line in lines(caplog.records)] == [
        "repository_mirror_cleanup_failed",
        "repository_mirror_cleanup_failed",
    ]
    mirror.files.locked.clear()
    mirror.service.remove(REPO)
    assert mirror.files.mirrors == {}


# --- the pure parts ------------------------------------------------------------------------------


def test_ls_remote_output_names_the_default_branch_and_the_branches() -> None:
    output = f"ref: refs/heads/master\tHEAD\n{SHA_1}\tHEAD\n{SHA_2}\trefs/heads/release\n"
    refs = parse_ls_remote(output)
    assert (refs.head, dict(refs.branches)) == ("master", {"release": SHA_2})
    assert parse_ls_remote("").head is None


@pytest.mark.parametrize(
    ("stderr", "code"),
    [
        ("fatal: Authentication failed for 'https://git.example.com/team/app/'", "auth_failed"),
        ("fatal: could not read Username for '...': terminal prompts disabled", "auth_failed"),
        ("remote: HTTP Basic: Access denied\nfatal: Authentication failed", "auth_failed"),
        ("fatal: unable to access '...': The requested URL returned error: 403", "auth_failed"),
        ("remote: Repository not found.\nfatal: repository '...' not found", "not_found"),
        ("fatal: couldn't find remote ref refs/heads/nothing", "not_found"),
        ("fatal: unable to access '...': Operation timed out after 30001 milliseconds", "timeout"),
        ("fatal: unable to access '...': Could not resolve host: git.example.com", "fetch_failed"),
        ("", "fetch_failed"),
    ],
)
def test_a_failure_is_named_by_what_git_wrote(stderr: str, code: str) -> None:
    assert classify_failure(stderr) == code


def test_the_log_excerpt_is_short_and_never_carries_a_header() -> None:
    stderr = "warning: redirecting\nfatal: unable to access: Authorization: Basic c2VjcmV0\n"
    assert failure_detail(stderr) == "fatal: unable to access: [redacted]"
    assert failure_detail("plain words\n") == "plain words"
    assert len(failure_detail("fatal: " + "x" * 500)) == 200
    assert failure_detail("") == ""


def test_the_header_carries_the_token_as_a_basic_password() -> None:
    def decoded(token: str) -> str:
        value = authorization_header(token).removeprefix("Authorization: Basic ")
        return base64.b64decode(value).decode()

    assert decoded(TOKEN) == f"x-access-token:{TOKEN}"
    assert decoded("deploy-user:s3cret") == "deploy-user:s3cret"
    assert decoded(":odd") == "x-access-token::odd"


def test_the_environment_shuts_out_other_configuration_and_carries_the_token_alone() -> None:
    assert git_environment(None) == {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "HOME": "",
    }
    with_token = git_environment(TOKEN)
    assert {key: with_token[key] for key in with_token if key.startswith("GIT_CONFIG_")} == {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": authorization_header(TOKEN),
    }


@pytest.mark.parametrize(
    "args",
    [
        ["clone", "--", URL],
        [*SAFETY_OPTIONS[:6], "clone", "--", URL],
        [*SAFETY_OPTIONS, "config", "core.hooksPath", "hooks"],
        [*SAFETY_OPTIONS, "-c", "core.sshCommand=evil", "fetch"],
        [*SAFETY_OPTIONS, "--git-dir=/x", "--git-dir=/y", "gc"],
        [*SAFETY_OPTIONS, "submodule", "update"],
        [*SAFETY_OPTIONS, "reflog", "delete"],
        [*SAFETY_OPTIONS],
    ],
)
def test_the_runner_refuses_any_other_argument_list(args: list[str]) -> None:
    assert args_problem(args) is not None


def test_the_arguments_put_the_safety_options_first() -> None:
    assert git_args("gc", "--quiet", git_dir="/m") == [
        *SAFETY_OPTIONS,
        "--git-dir=/m",
        "gc",
        "--quiet",
    ]
    assert args_problem(git_args("ls-remote", "--", URL)) is None


def test_the_real_runner_refuses_another_argument_list_before_anything_starts() -> None:
    # The check comes first: no directory is created and no process is started.
    runner = SubprocessGit("git", Path(ROOT))
    with pytest.raises(ValueError, match="refused git arguments"):
        runner(["config", "core.hooksPath", "hooks"], env={}, timeout=1)
    with pytest.raises(ValueError, match="refused git arguments"):
        runner([*SAFETY_OPTIONS, "submodule", "update"], env={}, timeout=1)


@pytest.mark.parametrize(
    ("url", "problem"),
    [
        (URL, None),
        ("https://GIT.example.com:8443/team/app", None),
        ("https://code.example.org/team/app.git", "host_not_allowed"),
        ("http://git.example.com/team/app.git", "invalid_url"),
        ("https://user:secret@git.example.com/team/app.git", "invalid_url"),
        ("https://token@git.example.com/team/app.git", "invalid_url"),
        ("https://git.example.com/", "invalid_url"),
        ("https://git.example.com/team/app.git?x=1", "invalid_url"),
        ("https://git.example.com/team/app.git#main", "invalid_url"),
        ("https://git.example.com:99999/team/app.git", "invalid_url"),
        ("https://git.example.com/team/a pp.git", "invalid_url"),
        ("ext::sh -c touch% /tmp/x", "invalid_url"),
        ("", "invalid_url"),
    ],
)
def test_a_url_is_https_on_an_allowed_host_without_credentials(
    url: str, problem: str | None
) -> None:
    assert git_url_problem(url, HOSTS) == problem


@pytest.mark.parametrize("name", ["main", "master", "release/2026.11", "feature-x+y", "v1_2"])
def test_a_plain_branch_name_is_valid(name: str) -> None:
    assert valid_branch(name)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "-x",
        "--upload-pack=evil",
        ".hidden",
        "/abs",
        "a/",
        "a..b",
        "a//b",
        "a/.b",
        "x.lock",
        "a b",
        "a:b",
        "a~1",
        "x" * 201,
    ],
)
def test_anything_else_is_not_a_branch_the_mirror_names(name: str) -> None:
    assert not valid_branch(name)


def test_the_commit_comes_from_the_archives_own_header() -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        info = tarfile.TarInfo("snapshot/README.md")
        archive.addfile(info, io.BytesIO(b""))
    assert archive_commit(buffer.getvalue()) is None
    assert archive_commit(b"not a tar") is None


def test_state_json_round_trips_and_anything_else_reads_as_none() -> None:
    state: MirrorState = {
        "url": URL,
        "branch": "main",
        "default_branch": "main",
        "last_sha": SHA_1,
        "fetched_at": "2026-11-03T10:00:01Z",
        "mirror_bytes": 1_000,
        "last_error": None,
    }
    raw = encode_state(state)
    assert raw.endswith(b"\n") and b"\r" not in raw
    assert decode_state(raw) == state
    for broken in (b"", b"[]", b"\xff", b'{"url": "x"}', b'{"url": 1, "branch": "main"}'):
        assert decode_state(broken) is None
    loose = decode_state(b'{"url": "u", "branch": "b", "mirror_bytes": true, "last_sha": 7}')
    assert loose is not None and (loose["mirror_bytes"], loose["last_sha"]) == (None, None)


def test_only_a_canonical_uuid_names_a_mirror_directory() -> None:
    assert canonical_repository_id(REPO) == REPO
    for other in ("../etc", REPO.upper(), "repo-1", ""):
        assert canonical_repository_id(other) is None
