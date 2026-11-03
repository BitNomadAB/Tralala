"""A mirrored repository's mirror over its life: it goes with the repository, with its last board
link, on "Rebuild mirror" and "Remove now", and with a startup sweep when its row is gone.

``RepositoryService`` runs its real code on the in-memory registry, and its ``MirrorService`` on the
fake git and mirror files of ``tests/unit/fakes/mirror.py``: a mirror is made the way a run makes
it (a fetch, then the outcome on the row), and a mirror the host will not let go of is a locked one
in the fake files. The composition root's startup is read from its source, because a unit test
never builds it.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.context import ActorContext, scopes_for_role
from app.core.errors import Conflict, Forbidden
from app.repositories.code_repositories import MirrorRecord
from app.services.repo_mirror import MirrorRequest, MirrorService
from app.services.repositories import MirrorControl, RepositoryService
from tests.unit.fakes.mirror import FakeGit, FakeMirror, FakeMirrorFiles, FakeRemote
from tests.unit.fakes.registry import (
    FakeRegistryUnitOfWork,
    RegistryState,
    board_row,
    repository_row,
)
from tests.unit.log_lines import events

NOW = "2026-11-03T10:00:00Z"
URL = "https://git.example.com/team/app.git"
LIB_URL = "https://git.example.com/team/lib.git"
SHA = "c" * 40
ADMIN = ActorContext(
    actor_id="admin-1",
    actor_type="user",
    actor_name="Ada",
    scopes=scopes_for_role("admin"),
    role="admin",
)
READER = ActorContext(
    actor_id="agent-2", actor_type="agent", actor_name="Reader", scopes=frozenset({"boards:read"})
)
SERVICES_INIT = Path(__file__).resolve().parents[2] / "app" / "services" / "__init__.py"


def mirror_fits(service: MirrorService) -> MirrorControl:
    """Never called: pyright proves the mirror service fits what RepositoryService takes."""
    return service


@dataclass(slots=True)
class World:
    state: RegistryState
    files: FakeMirrorFiles
    git: FakeGit
    service: RepositoryService
    mirror: MirrorService


def make(settings: Settings) -> World:
    """``app`` and ``lib`` read through the mirror, ``hub`` through the GitHub API; boards ``zeta``
    and ``alpha``, nothing linked yet."""
    allowed = settings.model_copy(update={"repository_hosts": "git.example.com"})
    state = RegistryState()
    state.boards = {"zeta": board_row("zeta", name="Zeta"), "alpha": board_row("alpha")}
    state.code_repositories = {
        "app": repository_row("app", name="app", provider="git_https", url=URL),
        "lib": repository_row("lib", name="lib", provider="git_https", url=LIB_URL),
        "hub": repository_row("hub", name="hub"),
    }
    remote = FakeRemote(head="main")
    remote.push("main", SHA, {"README.md": b"# App\n"})
    files = FakeMirrorFiles()
    git = FakeGit(files, {URL: remote, LIB_URL: FakeRemote(branches=dict(remote.branches))})
    mirror = MirrorService(
        git,
        files,
        hosts=allowed.allowed_repository_hosts,
        max_bytes=10_000,
        timeout_seconds=120,
        clock=lambda: NOW,
    )
    service = RepositoryService(
        allowed, FakeRegistryUnitOfWork(state), clock=lambda: NOW, mirror=mirror
    )
    return World(state, files, git, service, mirror)


def fetched(world: World, repository_id: str = "app") -> None:
    """The repository's mirror as a run leaves it: cloned, and the outcome on the row."""
    url = world.state.code_repositories[repository_id].url
    request = MirrorRequest(repository_id=repository_id, url=url, branch=None)
    latest = world.mirror.read_latest(request, None)
    record = MirrorRecord(
        default_branch=latest.head.default_branch,
        last_sha=latest.commit_sha,
        fetched_at=latest.head.fetched_at,
        mirror_bytes=latest.head.mirror_bytes,
    )
    world.service.record_fetch(repository_id, record)


def mirror_columns(world: World, repository_id: str = "app") -> tuple[object, ...]:
    row = world.state.code_repositories[repository_id]
    return (row.default_branch, row.last_sha, row.fetched_at, row.mirror_bytes, row.mirror_error)


@pytest.fixture
def world(settings: Settings) -> World:
    made = make(settings)
    fetched(made)
    assert made.files.has_mirror("app")
    assert mirror_columns(made) == ("main", SHA, NOW, 1_000, None)
    return made


# --- deleting the repository ---------------------------------------------------------------------


def test_deleting_a_mirrored_repository_removes_its_mirror_in_the_same_operation(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    world.service.set_board_links("zeta", ["app"])
    with caplog.at_level(logging.INFO, logger="tralala"):
        assert world.service.delete(ADMIN, "app") is True
    assert "app" not in world.state.code_repositories
    assert (world.files.removed, world.files.has_mirror("app")) == (["app"], False)
    assert world.state.repository_links == {}
    assert {"event": "repository_mirror_removed", "repository_id": "app"} in events(caplog.records)
    assert {"event": "repository_deleted", "repository_id": "app", "provider": "git_https"} in (
        events(caplog.records)
    )


def test_a_mirror_the_host_holds_keeps_the_row_until_remove_now_succeeds(world: World) -> None:
    world.service.set_board_links("zeta", ["app"])
    world.files.locked.add("app")
    with pytest.raises(Conflict) as refused:
        world.service.delete(ADMIN, "app")
    assert (refused.value.code, refused.value.details) == (
        "mirror_cleanup_failed",
        {"leftover": "repos/app"},
    )
    # Nothing else changed: the row, its link and the mirror stay, and the row says why.
    assert world.files.has_mirror("app")
    assert set(world.state.repository_links) == {("zeta", "app")}
    assert mirror_columns(world) == ("main", SHA, NOW, 1_000, "mirror_cleanup_failed")
    assert world.service.get("app").get("mirror_error") == "mirror_cleanup_failed"
    # "Remove now" (POST /repositories/{id}/mirror/remove) fails the same way while it is held ...
    with pytest.raises(Conflict) as again:
        world.service.remove_mirror(ADMIN, "app")
    assert again.value.code == "mirror_cleanup_failed"
    # ... and once the host lets go, the mirror goes and the row no longer describes one.
    world.files.locked.clear()
    entry = world.service.remove_mirror(ADMIN, "app")
    assert (entry.get("mirror_error"), entry.get("fetched_at"), entry.get("mirror_bytes")) == (
        None,
        None,
        None,
    )
    assert mirror_columns(world) == ("main", None, None, None, None)
    assert not world.files.has_mirror("app")
    assert world.service.delete(ADMIN, "app") is True
    assert "app" not in world.state.code_repositories


def test_deleting_a_github_repository_never_touches_a_mirror(world: World) -> None:
    world.service.delete(ADMIN, "hub")
    assert "hub" not in world.state.code_repositories
    assert (world.files.removed, world.files.has_mirror("app")) == ([], True)


# --- Remove now and Rebuild mirror ---------------------------------------------------------------


def test_rebuild_removes_the_mirror_and_the_next_run_clones_it_again(world: World) -> None:
    clones = world.git.commands.count("clone")
    entry = world.service.remove_mirror(ADMIN, "app")
    assert (entry["provider"], entry["default_branch"], entry.get("last_sha")) == (
        "git_https",
        "main",
        None,
    )
    assert not world.files.has_mirror("app")
    fetched(world)
    assert world.git.commands.count("clone") == clones + 1
    assert mirror_columns(world) == ("main", SHA, NOW, 1_000, None)


def test_only_a_mirrored_repository_has_a_mirror_to_remove(world: World) -> None:
    with pytest.raises(Conflict) as refused:
        world.service.remove_mirror(ADMIN, "hub")
    assert refused.value.code == "repository_not_mirrored"
    assert world.files.removed == []


def test_removing_a_mirror_asks_for_boards_admin(world: World) -> None:
    with pytest.raises(Forbidden):
        world.service.remove_mirror(READER, "app")
    assert world.files.has_mirror("app")


def test_without_git_there_is_no_mirror_to_remove_and_the_row_is_cleared(
    settings: Settings,
) -> None:
    made = make(settings)
    made.service.record_fetch(
        "app", MirrorRecord(default_branch="main", last_sha=SHA, fetched_at=NOW, mirror_bytes=9)
    )
    bare = RepositoryService(made.service.settings, made.service.store, clock=lambda: NOW)
    bare.remove_mirror(ADMIN, "app")
    assert mirror_columns(made) == ("main", None, None, None, None)
    assert bare.delete(ADMIN, "app") is True


# --- the last board link -------------------------------------------------------------------------


def test_a_mirror_goes_when_its_repository_loses_its_last_board_link(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    world.service.set_board_links("zeta", ["app", "hub"])
    world.service.set_board_links("alpha", ["app"])
    world.service.set_board_links("zeta", ["hub"])
    assert world.files.has_mirror("app")  # alpha still reads it
    with caplog.at_level(logging.INFO, logger="tralala"):
        world.service.set_board_links("alpha", [])
    assert (world.files.removed, world.files.has_mirror("app")) == (["app"], False)
    assert mirror_columns(world) == ("main", None, None, None, None)
    assert {"event": "repository_mirror_released", "repository_id": "app"} in events(caplog.records)
    # The row stays: a board may link it again, and its next run clones it.
    assert "app" in world.state.code_repositories


def test_unlinking_never_removes_a_mirror_another_selection_keeps(world: World) -> None:
    fetched(world, "lib")
    world.service.set_board_links("zeta", ["app", "lib"])
    world.service.set_board_links("zeta", ["lib", "hub"])
    assert (world.files.removed, world.files.has_mirror("lib")) == (["app"], True)


def test_a_mirror_that_cannot_be_released_never_fails_the_board_edit(world: World) -> None:
    world.service.set_board_links("zeta", ["app"])
    world.files.locked.add("app")
    world.service.set_board_links("zeta", [])
    assert world.state.repository_links == {}
    assert world.files.has_mirror("app")
    assert world.state.code_repositories["app"].mirror_error == "mirror_cleanup_failed"


# --- the startup sweep ---------------------------------------------------------------------------


def test_the_startup_sweep_removes_every_mirror_without_a_repository_row(world: World) -> None:
    world.files.mirrors["gone"] = FakeMirror(complete=True)
    world.files.mirrors["held"] = FakeMirror(complete=True)
    world.files.locked.add("held")
    assert world.service.sweep_mirrors() == ["gone"]
    assert sorted(world.files.mirrors) == ["app", "held"]
    world.files.locked.clear()
    assert world.service.sweep_mirrors() == ["held"]
    assert world.service.sweep_mirrors() == []


class UnlistableFiles(FakeMirrorFiles):
    def repository_ids(self) -> list[str]:
        raise PermissionError(13, "repos is not readable")


def test_a_sweep_that_cannot_list_the_mirrors_never_stops_the_start(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    made = make(settings)
    files = UnlistableFiles()
    mirror = MirrorService(
        FakeGit(files, {}), files, hosts=frozenset(), max_bytes=1, timeout_seconds=1
    )
    service = RepositoryService(made.service.settings, made.service.store, mirror=mirror)
    with caplog.at_level(logging.WARNING, logger="tralala.repositories"):
        assert service.sweep_mirrors() == []
    assert events(caplog.records) == [
        {"event": "repository_mirror_sweep_failed", "error": "PermissionError"}
    ]
    without_git = RepositoryService(made.service.settings, made.service.store)
    assert without_git.sweep_mirrors() == []


def _calls(function: ast.FunctionDef) -> list[str]:
    """``self.<a>.<b>(...)`` calls in source order, as ``a.b``."""
    found = [
        (node.lineno, node.col_offset, f"{node.func.value.attr}.{node.func.attr}")
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Attribute)
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "self"
    ]
    return [name for _line, _column, name in sorted(found)]


def test_the_start_sweeps_the_mirrors_once_the_registry_is_migrated() -> None:
    tree = ast.parse(SERVICES_INIT.read_text(encoding="utf-8"))
    initialize = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "initialize"
    )
    calls = _calls(initialize)
    assert calls.count("repository.sweep_mirrors") == 1
    assert calls.index("migrations.migrate_registry") < calls.index("repository.sweep_mirrors")
    assert calls.index("repository.sweep_mirrors") < calls.index("board.recover")
