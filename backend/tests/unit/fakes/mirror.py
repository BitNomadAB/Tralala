"""The Git mirror without git or a disk: a fake ``RunGit`` that acts on fake ``MirrorFiles``.

:class:`FakeMirrorFiles` keeps each repository's directory as a :class:`FakeMirror` in memory and
``state.json`` as the bytes the real codec writes, so a test reads exactly what would be on disk.
:class:`FakeGit` records every argument list and environment it is given, holds them to the rules
the real runner enforces (the safety options, one of the six commands), and plays the remote: a
:class:`FakeRemote` per URL with its HEAD, its branches and the token it wants. A clone or fetch
moves the remote's commit into the fake mirror, hygiene drops what a fetch left behind, and
``archive`` builds the tar git would write, the commit in its global pax header.
"""

from __future__ import annotations

import io
import tarfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.services.repo_mirror_files import MirrorFiles, MirrorState, decode_state, encode_state
from app.services.repo_mirror_git import (
    GIT_DIR_OPTION,
    MirrorError,
    RunGit,
    args_problem,
    authorization_header,
    command_of,
)

ROOT = "/srv/tralala/data/repos"


@dataclass(slots=True)
class FakeMirror:
    """One repository's directory: the bare mirror (once a clone finished) and ``state.json``."""

    complete: bool = False
    branch: str = ""
    commit: str = ""
    files: dict[str, bytes] = field(default_factory=dict[str, bytes])
    config: dict[str, str] = field(default_factory=dict[str, str])
    size: int = 0
    garbage: int = 0
    state: bytes | None = None


class FakeMirrorFiles:
    def __init__(self) -> None:
        self.mirrors: dict[str, FakeMirror] = {}
        self.locked: set[str] = set()
        self.removed: list[str] = []

    def mirror_path(self, repository_id: str) -> str:
        return f"{ROOT}/{repository_id}/mirror.git"

    def has_mirror(self, repository_id: str) -> bool:
        mirror = self.mirrors.get(repository_id)
        return mirror is not None and mirror.complete

    def prepare(self, repository_id: str) -> None:
        self.mirrors.setdefault(repository_id, FakeMirror())

    def size(self, repository_id: str) -> int:
        mirror = self.mirrors.get(repository_id)
        return 0 if mirror is None else mirror.size + mirror.garbage

    def read_state(self, repository_id: str) -> MirrorState | None:
        mirror = self.mirrors.get(repository_id)
        if mirror is None or mirror.state is None:
            return None
        return decode_state(mirror.state)

    def write_state(self, repository_id: str, state: MirrorState) -> None:
        self.mirrors.setdefault(repository_id, FakeMirror()).state = encode_state(state)

    def remove(self, repository_id: str) -> None:
        if repository_id in self.locked:
            raise PermissionError(13, "held by another process")
        if self.mirrors.pop(repository_id, None) is not None:
            self.removed.append(repository_id)

    def repository_ids(self) -> list[str]:
        return sorted(self.mirrors)


@dataclass(slots=True)
class FakeRemote:
    """A Git host's repository: what HEAD names, each branch's commit and files, the size a fresh
    clone takes, what one fetch leaves behind before hygiene, and the token it wants (if any)."""

    head: str = "main"
    branches: dict[str, tuple[str, dict[str, bytes]]] = field(
        default_factory=dict[str, tuple[str, dict[str, bytes]]]
    )
    size: int = 1_000
    fetch_garbage: int = 500
    token: str | None = None
    failure: str | None = None

    def push(self, branch: str, commit: str, files: dict[str, bytes]) -> None:
        self.branches[branch] = (commit, files)


@dataclass(frozen=True, slots=True)
class GitCall:
    args: tuple[str, ...]
    env: Mapping[str, str]
    timeout: float
    max_output_bytes: int | None

    @property
    def command(self) -> str:
        return command_of(self.args)

    @property
    def git_dir(self) -> str | None:
        return next(
            (arg[len(GIT_DIR_OPTION) :] for arg in self.args if arg.startswith(GIT_DIR_OPTION)),
            None,
        )


def _after(args: Sequence[str], marker: str) -> list[str]:
    return list(args[list(args).index(marker) + 1 :])


def _tar(commit: str, files: Mapping[str, bytes], prefix: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(
        fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT, pax_headers={"comment": commit}
    ) as archive:
        for path, payload in files.items():
            info = tarfile.TarInfo(prefix + path)
            info.size = len(payload)
            info.mtime = 0
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


class FakeGit:
    """``RunGit`` against :class:`FakeRemote` hosts by URL and the mirrors in ``files``."""

    def __init__(self, files: FakeMirrorFiles, remotes: dict[str, FakeRemote]) -> None:
        self.files = files
        self.remotes = remotes
        self.calls: list[GitCall] = []

    @property
    def commands(self) -> list[str]:
        return [call.command for call in self.calls]

    def __call__(
        self,
        args: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout: float,
        max_output_bytes: int | None = None,
    ) -> bytes:
        call = GitCall(tuple(args), dict(env), timeout, max_output_bytes)
        self.calls.append(call)
        problem = args_problem(args)
        if problem is not None:
            raise AssertionError(f"the real runner would refuse {args}: {problem}")
        handlers = {
            "ls-remote": self._ls_remote,
            "clone": self._clone,
            "fetch": self._fetch,
            "reflog expire": self._reflog,
            "gc": self._gc,
            "archive": self._archive,
        }
        return handlers[call.command](call)

    def _remote(self, call: GitCall, url: str) -> FakeRemote:
        remote = self.remotes.get(url)
        if remote is None:
            raise MirrorError("not_found")
        if remote.failure is not None:
            raise MirrorError(remote.failure)
        if remote.token is not None:
            wanted = authorization_header(remote.token)
            if call.env.get("GIT_CONFIG_VALUE_0") != wanted:
                raise MirrorError("auth_failed")
        return remote

    def _mirror(self, call: GitCall) -> FakeMirror:
        path = call.git_dir or ""
        repository_id = path.removeprefix(ROOT + "/").removesuffix("/mirror.git")
        mirror = self.files.mirrors.get(repository_id)
        if mirror is None or not mirror.complete:
            raise MirrorError("not_found")
        return mirror

    def _ls_remote(self, call: GitCall) -> bytes:
        url, *patterns = _after(call.args, "--")
        remote = self._remote(call, url)
        lines = [f"ref: refs/heads/{remote.head}\tHEAD"]
        if remote.head in remote.branches:
            lines.append(f"{remote.branches[remote.head][0]}\tHEAD")
        for pattern in patterns:
            name = pattern.removeprefix("refs/heads/")
            if pattern != "HEAD" and name in remote.branches:
                lines.append(f"{remote.branches[name][0]}\t{pattern}")
        return ("\n".join(lines) + "\n").encode("utf-8")

    def _clone(self, call: GitCall) -> bytes:
        url, target = _after(call.args, "--")
        branch = _after(call.args, "--branch")[0]
        remote = self._remote(call, url)
        repository_id = target.removeprefix(ROOT + "/").removesuffix("/mirror.git")
        mirror = self.files.mirrors.get(repository_id)
        if mirror is None or mirror.complete:
            raise MirrorError("fetch_failed")  # git refuses a missing parent or a used target
        if branch not in remote.branches:
            raise MirrorError("not_found")
        commit, files = remote.branches[branch]
        mirror.complete, mirror.branch, mirror.commit, mirror.files = True, branch, commit, files
        mirror.config = {"core.bare": "true", "remote.origin.url": url}
        mirror.size, mirror.garbage = remote.size, 0
        return b""

    def _fetch(self, call: GitCall) -> bytes:
        url, refspec = _after(call.args, "--")
        mirror = self._mirror(call)
        remote = self._remote(call, url)
        branch = refspec.removeprefix("+refs/heads/").split(":", 1)[0]
        if branch not in remote.branches:
            raise MirrorError("not_found")
        commit, files = remote.branches[branch]
        if commit != mirror.commit:
            mirror.garbage += remote.fetch_garbage
        mirror.branch, mirror.commit, mirror.files = branch, commit, files
        mirror.size = remote.size
        return b""

    def _reflog(self, call: GitCall) -> bytes:
        self._mirror(call)
        return b""

    def _gc(self, call: GitCall) -> bytes:
        self._mirror(call).garbage = 0
        return b""

    def _archive(self, call: GitCall) -> bytes:
        mirror = self._mirror(call)
        prefix = next(arg for arg in call.args if arg.startswith("--prefix="))
        ref = call.args[-1]
        if ref != f"refs/heads/{mirror.branch}":
            raise MirrorError("not_found")
        tar = _tar(mirror.commit, mirror.files, prefix.removeprefix("--prefix="))
        if call.max_output_bytes is not None and len(tar) > call.max_output_bytes:
            raise MirrorError("too_large")
        return tar


def git_fits(git: FakeGit) -> RunGit:
    """Never called: pyright proves the fake runner fits the Protocol."""
    return git


def files_fit(files: FakeMirrorFiles) -> MirrorFiles:
    """Never called: pyright proves the fake files fit the Protocol."""
    return files
