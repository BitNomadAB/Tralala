"""GitHub repositories: which URLs are accepted, and what a listing may show of the token."""

from __future__ import annotations

import pytest

from app.core.errors import ValidationFailure
from app.db.generated.registry import RepositoriesRow
from app.services import repositories
from app.services.repositories import RepositoryService


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/app",
        "https://github.com/acme/app/",
        "https://github.com/acme/app.git",
        "  https://GitHub.com/acme/app  ",
        "https://www.github.com/acme/app",
    ],
)
def test_a_github_url_names_the_owner_and_the_repository(url: str) -> None:
    assert RepositoryService.parse(url) == ("acme", "app")
    assert RepositoryService.parse(url) == ("acme", "app")


def test_a_trailing_git_suffix_is_tolerated() -> None:
    assert repositories.RepositoryService.parse("https://github.com/acme/app.git") == (
        "acme",
        "app",
    )


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://github.com/acme/app",
        "git@github.com:acme/app.git",
        "https://token@github.com/acme/app",
        "https://user:secret@github.com/acme/app",
        "https://gitlab.example.com/acme/app",
        "https://github.com.example.com/acme/app",
        "https://github.com/acme",
        "https://github.com/acme/app/tree/main",
        "https://github.com/acme/.git",
    ],
)
def test_anything_else_is_refused(url: str) -> None:
    with pytest.raises(ValidationFailure):
        RepositoryService.parse(url)


ROW = RepositoriesRow(
    id="repo-1",
    name="acme app",
    provider="github",
    url="https://github.com/acme/app",
    branch=None,
    token_ciphertext="gAAAAAB-sealed",
    token_hint="••••1234",
    enabled=1,
    last_checked_at="2026-11-03T08:00:00Z",
    last_check_status="ok",
    last_check_detail="Read access confirmed",
    created_at="2026-11-01T09:00:00Z",
    updated_at="2026-11-03T08:00:00Z",
    default_branch=None,
    last_sha=None,
    fetched_at=None,
    mirror_bytes=None,
    mirror_error=None,
)


def test_a_listing_says_a_token_exists_but_never_carries_it() -> None:
    entry = RepositoryService.serialize(ROW, [{"id": "board-1", "name": "Board"}])
    assert "token_ciphertext" not in entry
    assert "gAAAAAB-sealed" not in entry.values()
    assert entry["has_token"] is True
    assert entry["enabled"] is True
    assert entry.get("token_hint") == "••••1234"
    assert entry["boards"] == [{"id": "board-1", "name": "Board"}]


def test_a_listing_keeps_the_order_of_the_columns_it_came_from() -> None:
    assert list(RepositoryService.serialize(ROW)) == [
        "id",
        "name",
        "provider",
        "url",
        "branch",
        "default_branch",
        "token_hint",
        "enabled",
        "last_checked_at",
        "last_check_status",
        "last_check_detail",
        "last_sha",
        "fetched_at",
        "mirror_bytes",
        "mirror_error",
        "created_at",
        "updated_at",
        "has_token",
        "boards",
    ]


def test_a_listing_without_health_hides_the_hint_and_the_check() -> None:
    entry = RepositoryService.serialize(ROW, with_health=False)
    assert list(entry) == [
        "id",
        "name",
        "provider",
        "url",
        "branch",
        "default_branch",
        "enabled",
        "created_at",
        "updated_at",
        "has_token",
        "boards",
    ]
    assert entry["boards"] == []


def test_a_repository_without_a_token_says_so() -> None:
    entry = RepositoryService.serialize(ROW.__replace__(token_ciphertext=None, enabled=0))
    assert entry["has_token"] is False
    assert entry["enabled"] is False
