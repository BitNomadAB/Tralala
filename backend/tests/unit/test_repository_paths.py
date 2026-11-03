"""Focus and exclude globs on a board's repository links: what a request may carry, and how the
globs are stored, read back and handed to a snapshot.

The schema rules run on the request models themselves. The links run through the real
``RepositoryService`` on the in-memory registry of ``tests/unit/fakes``, so the link repository's
fake is what stores and returns the globs. Which files the globs keep is in
``test_repo_snapshot.py``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ValidationFailure
from app.schemas.boards import (
    MAX_GLOB_CHARS,
    MAX_GLOBS,
    BoardCreate,
    BoardUpdate,
    RepositoryPaths,
)
from app.services.repositories import RepositoryService
from app.services.repository_links import decode_globs, encode_globs, paths_by_repository
from tests.unit.fakes.registry import (
    FakeRegistryUnitOfWork,
    RegistryState,
    board_repository_row,
    board_row,
    repository_row,
)

NOW = "2026-11-03T10:00:00Z"
BOARD = "board-1"


# --- the request boundary ------------------------------------------------------------------------


def _refusal(payload: dict[str, object]) -> str:
    with pytest.raises(ValidationError) as failure:
        RepositoryPaths.model_validate(payload)
    [error] = failure.value.errors()
    return error["msg"]


def test_globs_within_the_limits_are_accepted_and_trimmed() -> None:
    paths = RepositoryPaths.model_validate(
        {"focus_paths": ["  docs/**  ", "src/*.py", "docs/..notes/*"], "exclude_paths": ["*.lock"]}
    )
    assert (paths.focus_paths, paths.exclude_paths) == (
        ["docs/**", "src/*.py", "docs/..notes/*"],
        ["*.lock"],
    )
    assert RepositoryPaths().model_dump() == {"focus_paths": [], "exclude_paths": []}
    full = RepositoryPaths.model_validate(
        {
            "focus_paths": [f"part{index}/*" for index in range(MAX_GLOBS)],
            "exclude_paths": ["x" * MAX_GLOB_CHARS],
        }
    )
    assert (len(full.focus_paths), len(full.exclude_paths[0])) == (20, 200)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"focus_paths": [f"part{index}/*" for index in range(21)]}, "at most 20 items"),
        ({"exclude_paths": ["x" * 201]}, "at most 200 characters"),
        ({"focus_paths": [""]}, "at least 1 character"),
        ({"focus_paths": ["   "]}, "at least 1 character"),
        ({"focus_paths": ["/etc/*"]}, "not an absolute path"),
        ({"focus_paths": ["C:/repository/*"]}, "not an absolute path"),
        ({"exclude_paths": ["c:docs"]}, "not an absolute path"),
        ({"exclude_paths": ["../secrets/*"]}, "'..' segment"),
        ({"exclude_paths": ["docs/../../outside/*"]}, "'..' segment"),
        ({"focus_paths": [".."]}, "'..' segment"),
        ({"focus_paths": ["docs\\*.md"]}, "never with a backslash"),
        ({"focus_paths": ["docs/*"], "include_paths": []}, "Extra inputs are not permitted"),
    ],
)
def test_a_glob_outside_the_rules_is_refused(payload: dict[str, object], message: str) -> None:
    assert message in _refusal(payload)


def test_a_board_request_names_the_repository_and_the_glob_it_refuses() -> None:
    created = BoardCreate.model_validate(
        {
            "name": "Platform",
            "repository_ids": ["repo-a"],
            "repository_paths": {"repo-a": {"focus_paths": ["docs/*"]}},
        }
    )
    assert created.repository_paths == {"repo-a": RepositoryPaths(focus_paths=["docs/*"])}
    assert BoardCreate(name="Platform").repository_paths == {}
    assert BoardUpdate().repository_paths is None
    with pytest.raises(ValidationError) as failure:
        BoardUpdate.model_validate(
            {"repository_paths": {"repo-a": {"exclude_paths": ["ok/*", "/abs"]}}}
        )
    [error] = failure.value.errors()
    assert error["loc"] == ("repository_paths", "repo-a", "exclude_paths", 1)
    with pytest.raises(ValidationError):
        BoardUpdate.model_validate(
            {"repository_paths": {f"repo-{index}": {} for index in range(51)}}
        )


# --- the stored links ----------------------------------------------------------------------------


def _service(settings: Settings) -> tuple[RegistryState, RepositoryService]:
    """A board and three enabled repositories: ``app``, ``docs`` and ``lib``."""
    state = RegistryState()
    state.boards[BOARD] = board_row(BOARD, name="Platform")
    for repository_id in ("app", "docs", "lib"):
        state.code_repositories[repository_id] = repository_row(repository_id, name=repository_id)
    return state, RepositoryService(settings, FakeRegistryUnitOfWork(state), clock=lambda: NOW)


FOCUSED = RepositoryPaths(focus_paths=["docs/*", "ö/*"], exclude_paths=["docs/old/*"])


def test_the_links_store_the_globs_as_json_text_and_read_them_back(settings: Settings) -> None:
    state, service = _service(settings)
    service.set_board_links(BOARD, ["app", "lib"], {"app": FOCUSED})
    assert state.repository_links == {
        (BOARD, "app"): board_repository_row(
            BOARD,
            "app",
            created_at=NOW,
            focus_paths='["docs/*", "ö/*"]',
            exclude_paths='["docs/old/*"]',
        ),
        (BOARD, "lib"): board_repository_row(BOARD, "lib", created_at=NOW),
    }
    with FakeRegistryUnitOfWork(state).reader() as repos:
        links = repos.repository_links.links(BOARD)
        grouped = repos.repository_links.by_board()
    assert [link.repository_id for link in links] == ["app", "lib"]
    assert grouped == {BOARD: links}
    assert paths_by_repository(links) == {
        "app": {"focus_paths": ["docs/*", "ö/*"], "exclude_paths": ["docs/old/*"]}
    }


def test_a_selection_without_paths_keeps_the_globs_of_the_repositories_that_stay(
    settings: Settings,
) -> None:
    state, service = _service(settings)
    service.set_board_links(BOARD, ["app", "lib"], {"app": FOCUSED})
    service.set_board_links(BOARD, ["app", "docs"])
    assert {key[1]: link.focus_paths for key, link in state.repository_links.items()} == {
        "app": '["docs/*", "ö/*"]',
        "docs": "[]",
    }
    # Paths, when given, are the whole answer: a repository without an entry reads all of it.
    service.set_board_links(BOARD, ["app", "docs"], {})
    assert {link.focus_paths for link in state.repository_links.values()} == {"[]"}


def test_paths_for_a_repository_the_board_does_not_link_are_refused_before_anything_is_written(
    settings: Settings,
) -> None:
    state, service = _service(settings)
    service.set_board_links(BOARD, ["app"])
    before = dict(state.repository_links)
    with pytest.raises(ValidationFailure) as caught:
        service.set_board_links(BOARD, ["app"], {"lib": FOCUSED, "docs": FOCUSED})
    assert caught.value.details == {"field": "repository_paths", "repository_ids": ["docs", "lib"]}
    assert state.repository_links == before


def test_a_snapshot_gets_each_repository_with_its_links_globs(settings: Settings) -> None:
    _state, service = _service(settings)
    service.set_board_links(BOARD, ["app", "lib"], {"app": FOCUSED})
    found = {
        entry["id"]: (entry.get("focus_paths"), entry.get("exclude_paths"))
        for entry in service.for_board(BOARD)
    }
    assert found == {"app": (["docs/*", "ö/*"], ["docs/old/*"]), "lib": ([], [])}
    # The repository list itself does not carry a board's globs.
    assert all("focus_paths" not in entry for entry in service.list(board_id=BOARD))


def test_the_column_text_is_a_json_array_of_strings() -> None:
    assert encode_globs([]) == "[]"
    assert decode_globs(encode_globs(["docs/*", "ö/*"])) == ["docs/*", "ö/*"]
    assert decode_globs('{"docs": 1}') == []
    assert decode_globs('["docs/*", 1, null]') == ["docs/*"]
