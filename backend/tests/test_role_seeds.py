"""Role seeds: one JSON file, validated, with board and organisation profiles."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.services import role_defaults


def test_the_seed_file_defines_every_builtin_role() -> None:
    document = json.loads(role_defaults.SEED_PATH.read_text(encoding="utf-8"))
    keys = [role["key"] for role in document["roles"]]
    assert keys == list(role_defaults.BUILTIN_ROLE_KEYS)
    assert len(keys) == len(set(keys))
    assert {"coordinator", "architect"} <= set(keys)


def test_the_seed_file_is_the_only_source_of_the_prompts() -> None:
    document = json.loads(role_defaults.SEED_PATH.read_text(encoding="utf-8"))
    preamble = document["discussion_preamble"]
    seeded = {role["key"]: role for role in document["roles"]}
    for role in role_defaults.BUILTIN_ROLES:
        expected = seeded[role["key"]]["prompt"].replace("{{discussion}}", preamble).strip()
        assert role["prompt"] == expected
    assert "{{discussion}}" not in "".join(role["prompt"] for role in role_defaults.BUILTIN_ROLES)


def test_board_and_organisation_profiles_are_separated() -> None:
    assert {role["key"] for role in role_defaults.ORGANISATION_ROLES} == {
        "coordinator",
        "architect",
    }
    assert all(role["scope"] == "board" for role in role_defaults.BOARD_ROLES)
    assert len(role_defaults.BOARD_ROLES) + len(role_defaults.ORGANISATION_ROLES) == len(
        role_defaults.BUILTIN_ROLES
    )


def test_the_organisation_profiles_describe_their_own_job() -> None:
    prompts = {role["key"]: role["prompt"] for role in role_defaults.ORGANISATION_ROLES}
    assert "across every board" in prompts["coordinator"]
    assert "recommend" in prompts["coordinator"].lower()
    assert "every repository" in prompts["architect"]
    assert "read-only token" in prompts["architect"]
    for prompt in prompts.values():
        assert "data to analyse" in prompt


def test_a_broken_seed_fails_instead_of_seeding_nothing(tmp_path: Any) -> None:
    broken = tmp_path / "roles.json"
    broken.write_text(json.dumps({"roles": [{"key": "x", "name": "X"}]}), encoding="utf-8")
    with pytest.raises(RuntimeError):
        role_defaults._load(broken)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        json.dumps(
            {
                "roles": [
                    {"key": "x", "name": "X", "prompt": "p"},
                    {"key": "x", "name": "X again", "prompt": "p"},
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError):
        role_defaults._load(duplicate)


def test_the_factory_prompts_never_name_the_product() -> None:
    """A profile refers to the Loop or discussion it is given, never to a fixed product name."""
    for role in role_defaults.BUILTIN_ROLES:
        assert "Tralala" not in role["prompt"], role["key"]
    analytics = next(r for r in role_defaults.BUILTIN_ROLES if r["key"] == "analytics_agent")
    assert "the Loop you are asked about" in analytics["prompt"]
    assert "given to you with the request" in analytics["prompt"]


def test_the_discussion_preamble_points_at_the_given_context() -> None:
    document = json.loads(role_defaults.SEED_PATH.read_text(encoding="utf-8"))
    preamble = document["discussion_preamble"]
    assert "Tralala" not in preamble
    assert "The message you receive names the ticket" in preamble
    assert "never guess an identity" in preamble


@pytest.mark.parametrize(
    "document",
    [
        {"roles": []},
        {"roles": [{"key": "x", "name": "X", "prompt": "p", "scope": "everywhere"}]},
        {"roles": [{"key": " ", "name": "X", "prompt": "p"}]},
        {"roles": [{"key": "x", "name": "", "prompt": "p"}]},
    ],
)
def test_an_invalid_seed_is_refused(tmp_path: Any, document: dict[str, Any]) -> None:
    path = tmp_path / "roles.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RuntimeError):
        role_defaults._load(path)


def test_a_valid_seed_loads_with_the_preamble_in_place(tmp_path: Any) -> None:
    path = tmp_path / "roles.json"
    path.write_text(
        json.dumps(
            {
                "discussion_preamble": "Answer the ticket you are given.",
                "roles": [
                    {"key": "reviewer", "name": " Reviewer ", "prompt": "Review. {{discussion}} "},
                    {"key": "lead", "name": "Lead", "prompt": "Lead.", "scope": "organisation"},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert role_defaults._load(path) == (
        {
            "key": "reviewer",
            "name": "Reviewer",
            "description": "",
            "scope": "board",
            "prompt": "Review. Answer the ticket you are given.",
        },
        {
            "key": "lead",
            "name": "Lead",
            "description": "",
            "scope": "organisation",
            "prompt": "Lead.",
        },
    )
    assert role_defaults._load(path) == role_defaults._load(path)
