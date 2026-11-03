"""RepositoryService's rules on an in-memory registry: the list, board links, edits, the GitHub
check and resealing.

The service runs its real code; only the repositories, the unit of work, the clock, the id source
and the GitHub call are replaced. Tokens are sealed with the real ``core.secrets``, so a test can
open what the service stored. URL parsing and the entry shape are in ``test_repositories.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pytest

from app.core.config import Settings
from app.core.context import ActorContext, scopes_for_role
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailure
from app.core.secrets import open_secret, open_secret_state, seal_secret
from app.repositories.registry import RegistryUnitOfWork
from app.schemas.repositories import RepositoryCreate, RepositoryUpdate
from app.services.repositories import GitHubGet, JsonObject, RepositoryService
from tests.unit.fakes.registry import (
    CREATED,
    FakeRegistryUnitOfWork,
    RegistryState,
    board_row,
    registry_unit_of_work,
    repository_row,
)

NOW = "2026-11-03T10:00:00Z"
TOKEN = "ghp-acme-1111"
OTHER_SECRET = "an-earlier-installation-secret-" + "q" * 24
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
API = "https://api.github.com/repos"


def unit_of_work_is_what_the_service_needs(state: RegistryState) -> RegistryUnitOfWork:
    """Never called: pyright proves the fake unit of work fits the Protocol the service takes."""
    return registry_unit_of_work(state)


@dataclass(slots=True)
class GitHub:
    """Answers each URL as told (404 otherwise) and remembers what it was asked."""

    answers: dict[str, tuple[int, JsonObject | None]] = field(
        default_factory=dict[str, tuple[int, JsonObject | None]]
    )
    calls: list[tuple[str, str | None]] = field(default_factory=list[tuple[str, str | None]])

    def __call__(self, url: str, *, token: str | None) -> tuple[int, JsonObject | None]:
        self.calls.append((url, token))
        return self.answers.get(url, (404, None))


def github_fits(github: GitHub) -> GitHubGet:
    """Never called: pyright proves the stand-in fits the Protocol."""
    return github


class Ids:
    """new-1, new-2, ... in call order."""

    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return f"new-{self.issued}"


@dataclass(slots=True)
class Repositories:
    state: RegistryState
    store: FakeRegistryUnitOfWork
    github: GitHub
    service: RepositoryService
    settings: Settings


def make_repositories(settings: Settings) -> Repositories:
    """``app`` (sealed token, linked to ``zeta``), ``lib`` (disabled) and ``Alpha``; boards
    ``zeta`` and ``alpha``."""
    state = RegistryState()
    state.boards = {
        "zeta": board_row("zeta", name="Zeta"),
        "alpha": board_row("alpha", name="alpha"),
    }
    state.code_repositories = {
        "app": repository_row(
            "app",
            name="app",
            url="https://github.com/acme/app",
            token_ciphertext=seal_secret(settings, TOKEN),
            token_hint="••••1111",
        ),
        "lib": repository_row("lib", name="Lib", enabled=False),
        "alpha-repo": repository_row("alpha-repo", name="Alpha"),
    }
    store = FakeRegistryUnitOfWork(state)
    github = GitHub()
    service = RepositoryService(
        settings, store, clock=lambda: NOW, new_id=Ids(), github_get=github
    )
    return Repositories(state, store, github, service, settings)


@pytest.fixture
def repos(settings: Settings) -> Repositories:
    made = make_repositories(settings)
    made.service.set_board_links("zeta", ["app", "lib"])
    made.service.set_board_links("alpha", ["app"])
    return made


# --- queries -------------------------------------------------------------------------------------


def test_the_list_is_by_name_without_regard_to_case_and_names_the_boards(
    repos: Repositories,
) -> None:
    entries = repos.service.list()
    assert [entry["id"] for entry in entries] == ["alpha-repo", "app", "lib"]
    assert entries[1]["boards"] == [
        {"id": "alpha", "name": "alpha"},
        {"id": "zeta", "name": "Zeta"},
    ]
    assert entries[0]["boards"] == []


def test_a_board_lists_only_what_it_links(repos: Repositories) -> None:
    assert [entry["id"] for entry in repos.service.list(board_id="zeta")] == ["app", "lib"]
    assert [entry["id"] for entry in repos.service.for_board("zeta")] == ["app"]
    with pytest.raises(NotFound) as caught:
        repos.service.list(board_id="nothing")
    assert caught.value.code == "board_not_found"


def test_without_health_the_hint_and_the_last_check_stay_hidden(repos: Repositories) -> None:
    entry = repos.service.get("app", with_health=False)
    assert "token_hint" not in entry
    assert "last_check_status" not in entry
    assert entry["has_token"] is True
    assert "token_hint" in repos.service.get("app")


def test_an_unknown_repository_is_not_found(repos: Repositories) -> None:
    with pytest.raises(NotFound) as caught:
        repos.service.get("nothing")
    assert caught.value.code == "repository_not_found"
    assert repos.service.token("nothing") is None


def test_the_token_opens_only_for_an_outbound_call(repos: Repositories) -> None:
    assert repos.service.token("app") == TOKEN
    assert repos.service.token("lib") is None


# --- board links ---------------------------------------------------------------------------------


def test_a_selection_replaces_the_previous_one_once_per_repository(repos: Repositories) -> None:
    repos.service.set_board_links("zeta", ["alpha-repo", "app", "alpha-repo"])
    assert [entry["id"] for entry in repos.service.list(board_id="zeta")] == ["alpha-repo", "app"]
    links = [link for link in repos.state.repository_links.values() if link.board_id == "zeta"]
    assert {link.created_at for link in links} == {NOW}


def test_a_selection_naming_an_unknown_repository_writes_nothing(repos: Repositories) -> None:
    with pytest.raises(NotFound) as caught:
        repos.service.set_board_links("zeta", ["alpha-repo", "nothing"])
    assert caught.value.code == "repository_not_found"
    assert [entry["id"] for entry in repos.service.list(board_id="zeta")] == ["app", "lib"]


# --- create, update, delete ----------------------------------------------------------------------


def test_a_new_repository_is_named_after_its_url_and_its_token_is_sealed(
    repos: Repositories, caplog: pytest.LogCaptureFixture
) -> None:
    payload = RepositoryCreate(url=" https://github.com/acme/tool.git ", token="ghp-tool-2222")
    with caplog.at_level(logging.INFO, logger="tralala.repositories"):
        entry = repos.service.create(ADMIN, payload)
    row = repos.state.code_repositories["new-1"]
    assert (row.name, row.url, row.branch, row.provider) == (
        "tool",
        "https://github.com/acme/tool.git",
        None,
        "github",
    )
    assert open_secret(repos.settings, row.token_ciphertext or "") == "ghp-tool-2222"
    assert (row.token_hint, row.enabled, row.created_at, row.updated_at) == (
        "••••2222",
        1,
        NOW,
        NOW,
    )
    assert (entry["has_token"], entry["boards"]) == (True, [])
    assert '"repository_created"' in caplog.text
    assert '"has_token": true' in caplog.text
    assert "ghp-tool-2222" not in caplog.text


def test_a_new_repository_takes_its_name_and_branch_trimmed(repos: Repositories) -> None:
    payload = RepositoryCreate(
        url="https://github.com/acme/tool", name="  Tool  ", branch="  ", enabled=False
    )
    repos.service.create(ADMIN, payload)
    row = repos.state.code_repositories["new-1"]
    assert (row.name, row.branch, row.enabled, row.token_ciphertext) == ("Tool", None, 0, None)


def test_a_url_already_in_the_list_is_refused(repos: Repositories) -> None:
    with pytest.raises(Conflict) as caught:
        repos.service.create(ADMIN, RepositoryCreate(url="https://github.com/acme/app"))
    assert caught.value.code == "repository_duplicate"
    with pytest.raises(ValidationFailure):
        repos.service.create(ADMIN, RepositoryCreate(url="http://github.com/acme/x"))
    assert set(repos.state.code_repositories) == {"app", "lib", "alpha-repo"}


def test_an_edit_always_stamps_the_time(repos: Repositories) -> None:
    repos.service.update(ADMIN, "lib", RepositoryUpdate())
    assert repos.state.code_repositories["lib"].updated_at == NOW


def test_an_edit_writes_what_it_names(repos: Repositories) -> None:
    repos.service.update(
        ADMIN,
        "lib",
        RepositoryUpdate(name=" Library ", branch=" main ", enabled=True, token="ghp-lib-3333"),
    )
    row = repos.state.code_repositories["lib"]
    assert (row.name, row.branch, row.enabled, row.token_hint) == (
        "Library",
        "main",
        1,
        "••••3333",
    )
    assert open_secret(repos.settings, row.token_ciphertext or "") == "ghp-lib-3333"
    repos.service.update(ADMIN, "lib", RepositoryUpdate(branch="  "))
    assert repos.state.code_repositories["lib"].branch is None


def test_a_token_is_cleared_on_request_but_not_together_with_a_new_one(
    repos: Repositories,
) -> None:
    with pytest.raises(ValidationFailure) as caught:
        repos.service.update(ADMIN, "app", RepositoryUpdate(token="x", clear_token=True))
    assert caught.value.details == {"field": "token"}
    repos.service.update(ADMIN, "app", RepositoryUpdate(clear_token=True))
    row = repos.state.code_repositories["app"]
    assert (row.token_ciphertext, row.token_hint) == (None, None)


def test_a_new_url_is_parsed_and_must_not_be_another_repositorys(repos: Repositories) -> None:
    with pytest.raises(Conflict):
        repos.service.update(ADMIN, "lib", RepositoryUpdate(url="https://github.com/acme/app"))
    with pytest.raises(ValidationFailure):
        repos.service.update(ADMIN, "lib", RepositoryUpdate(url="https://github.com/acme"))
    repos.service.update(ADMIN, "app", RepositoryUpdate(url=" https://github.com/acme/app "))
    assert repos.state.code_repositories["app"].url == "https://github.com/acme/app"


def test_a_deleted_repository_leaves_every_board_that_linked_it(repos: Repositories) -> None:
    assert repos.service.delete(ADMIN, "app") is True
    assert [entry["id"] for entry in repos.service.list(board_id="zeta")] == ["lib"]
    with pytest.raises(NotFound):
        repos.service.delete(ADMIN, "app")


def test_each_command_asks_for_boards_admin(repos: Repositories) -> None:
    with pytest.raises(Forbidden):
        repos.service.create(READER, RepositoryCreate(url="https://github.com/acme/x"))
    with pytest.raises(Forbidden):
        repos.service.update(READER, "app", RepositoryUpdate(name="x"))
    with pytest.raises(Forbidden):
        repos.service.delete(READER, "app")
    with pytest.raises(Forbidden):
        repos.service.check(READER, "app")
    assert repos.github.calls == []


# --- the GitHub check ----------------------------------------------------------------------------


def test_a_readable_repository_reports_what_github_says_with_the_stored_token(
    repos: Repositories,
) -> None:
    repos.github.answers[f"{API}/acme/app"] = (
        200,
        {"default_branch": "main", "private": True, "size": 123, "token": "never shown"},
    )
    result = repos.service.check(ADMIN, "app")
    assert result == {
        "status": "ok",
        "detail": "acme/app is readable",
        "default_branch": "main",
        "private": True,
        "size_kb": 123,
        "checked_at": NOW,
    }
    assert repos.github.calls == [(f"{API}/acme/app", TOKEN)]
    row = repos.state.code_repositories["app"]
    assert (row.last_check_status, row.last_check_detail, row.last_checked_at, row.updated_at) == (
        "ok",
        "acme/app is readable",
        NOW,
        NOW,
    )


def test_a_branch_that_does_not_exist_is_reported_as_missing(repos: Repositories) -> None:
    repos.state.code_repositories["app"] = repos.state.code_repositories["app"].__replace__(
        branch="feature"
    )
    repos.github.answers[f"{API}/acme/app"] = (200, {})
    result = repos.service.check(ADMIN, "app")
    assert (result["status"], result["detail"], result["size_kb"]) == (
        "branch_missing",
        "Branch 'feature' does not exist",
        None,
    )
    assert repos.github.calls[1] == (f"{API}/acme/app/branches/feature", TOKEN)
    repos.github.answers[f"{API}/acme/app/branches/feature"] = (200, {"name": "feature"})
    found = repos.service.check(ADMIN, "app")
    assert (found["status"], found["size_kb"], found["private"]) == ("ok", 0, False)


@pytest.mark.parametrize(
    ("answer", "status", "detail"),
    [
        ((401, None), "unauthorized", "The token was rejected"),
        ((404, None), "not_found", "Repository not found, or the token cannot see it"),
        ((403, None), "forbidden", "GitHub refused the request (scope or rate limit)"),
        ((502, None), "unreachable", "GitHub answered 502"),
        ((200, None), "unreachable", "GitHub answered 200"),
    ],
)
def test_a_refusal_is_named_by_its_class_never_by_githubs_words(
    repos: Repositories, answer: tuple[int, JsonObject | None], status: str, detail: str
) -> None:
    repos.github.answers[f"{API}/acme/lib"] = answer
    result = repos.service.check(ADMIN, "lib")
    assert result == {
        "status": status,
        "detail": detail,
        "default_branch": None,
        "private": None,
        "size_kb": None,
        "checked_at": NOW,
    }
    assert repos.github.calls == [(f"{API}/acme/lib", None)]
    assert repos.state.code_repositories["lib"].last_check_status == status


def test_a_size_that_is_not_a_number_fails_as_int_would(repos: Repositories) -> None:
    repos.github.answers[f"{API}/acme/app"] = (200, {"size": [1]})
    with pytest.raises(TypeError):
        repos.service.check(ADMIN, "app")
    repos.github.answers[f"{API}/acme/app"] = (200, {"size": "12"})
    assert repos.service.check(ADMIN, "app")["size_kb"] == 12


def test_an_unknown_repository_is_not_checked(repos: Repositories) -> None:
    with pytest.raises(NotFound):
        repos.service.check(ADMIN, "nothing")
    assert repos.github.calls == []


# --- secret rotation -----------------------------------------------------------------------------


def test_tokens_sealed_with_the_previous_secret_move_to_the_current_one(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    previous = settings.model_copy(update={"secret_key": OTHER_SECRET})
    rotated = settings.model_copy(update={"previous_secret_key": OTHER_SECRET})
    repos = make_repositories(rotated)
    current = repos.state.code_repositories["app"]
    repos.state.code_repositories["lib"] = repos.state.code_repositories["lib"].__replace__(
        token_ciphertext=seal_secret(previous, "ghp-old-4444")
    )
    repos.state.code_repositories["alpha-repo"] = repos.state.code_repositories[
        "alpha-repo"
    ].__replace__(token_ciphertext="not-a-sealed-value")
    with caplog.at_level(logging.WARNING, logger="tralala.repositories"):
        assert repos.service.reseal_tokens() == 1
    moved = repos.state.code_repositories["lib"]
    assert open_secret_state(rotated, moved.token_ciphertext or "") == ("ghp-old-4444", True)
    assert moved.updated_at == NOW
    assert repos.state.code_repositories["app"] == current
    assert repos.state.code_repositories["alpha-repo"].updated_at == CREATED
    assert "repository alpha-repo has a token that no configured secret can open" in caplog.text
    assert repos.service.reseal_tokens() == 0
