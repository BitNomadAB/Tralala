"""The address of a decision that waits for a person, and the setting that makes it absolute.

``decision_path`` mirrors the frontend's ``loopHref``, ``loopPagePath`` and ``ticketPagePath``;
``dialog=completion``, ``focus=clear-wait`` and ``focus=confirm`` are the contract with the web UI.
``public_url`` is checked once, when the settings are read, so a server never starts with an
address it cannot build a link on.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

from app.core.config import Settings, checked_public_url
from app.services import decision_links
from app.services.decision_links import Decision, decision_link, decision_path

BOARD = "2f1c7a52-3d0e-4b8a-9c61-0d5e8f7a4b13"
LOOP = "8b6e2d14-7f3a-4c95-a0d2-61e9b3c7f508"
CARD = "c4a9f0e7-1b2d-4e36-8f5a-9d7c3b1e0a62"
LOOP_PAGE = f"/boards/{BOARD}/loops/{LOOP}"
TICKET_PAGE = f"{LOOP_PAGE}/tickets/{CARD}"
PUBLIC = "https://tralala.example.com"

PATHS: dict[Decision, str] = {
    "analysis": f"{LOOP_PAGE}?tab=plan&doc=analysis",
    "roadmap": f"{LOOP_PAGE}?tab=plan&doc=roadmap",
    "implementation": f"{LOOP_PAGE}?dialog=completion",
    "qa": f"{LOOP_PAGE}?dialog=completion",
    "wait": f"{TICKET_PAGE}?focus=clear-wait",
    "confirmation": f"{TICKET_PAGE}?focus=confirm",
    "info": f"{LOOP_PAGE}?tab=plan&doc=info",
}
ON_A_TICKET: frozenset[Decision] = frozenset({"wait", "confirmation"})


def _card(decision: Decision) -> str | None:
    return CARD if decision in ON_A_TICKET else None


def test_every_decision_has_a_path() -> None:
    assert set(PATHS) == set(get_args(Decision))


@pytest.mark.parametrize(("decision", "expected"), sorted(PATHS.items()))
def test_each_decision_opens_its_own_place(decision: Decision, expected: str) -> None:
    path = decision_path(decision, board_id=BOARD, loop_id=LOOP, card_id=_card(decision))
    assert path == expected


def test_each_id_reaches_the_path_url_encoded_as_given() -> None:
    # The ids are kept as the caller gives them, in either case, and encoded as encodeURIComponent
    # does, so the path is the one ticketPagePath builds in the browser from the same ids. A UUID's
    # text needs no escaping; every spelling that would is refused below.
    board, loop, card = BOARD.upper(), "8B6E2D14-7f3a-4C95-a0d2-61E9B3C7F508", CARD.upper()
    path = decision_path("confirmation", board_id=board, loop_id=loop, card_id=card)
    assert path == f"/boards/{board}/loops/{loop}/tickets/{card}?focus=confirm"
    assert decision_path("analysis", board_id=board, loop_id=loop) == (
        f"/boards/{board}/loops/{loop}?tab=plan&doc=analysis"
    )


NOT_A_UUID = [
    "",
    "BE007",
    "BE007-LA01-001",
    "../../registry.sqlite",
    f"{BOARD}/../{LOOP}",
    f"{BOARD}?tab=kanban",
    f"{BOARD}#top",
    f"{BOARD}%2F",
    f"{{{BOARD}}}",
    f"urn:uuid:{BOARD}",
    BOARD.replace("-", ""),
    f" {BOARD}",
    f"{BOARD}\n",
    f"{BOARD[:-1]}g",
]


@pytest.mark.parametrize("value", NOT_A_UUID)
@pytest.mark.parametrize("field", ["board_id", "loop_id", "card_id"])
def test_an_id_that_is_not_a_uuid_is_refused(field: str, value: str) -> None:
    ids = {"board_id": BOARD, "loop_id": LOOP, "card_id": CARD} | {field: value}
    with pytest.raises(ValueError, match=f"^{field} must be a UUID$"):
        decision_link(
            "wait",
            board_id=ids["board_id"],
            loop_id=ids["loop_id"],
            card_id=ids["card_id"],
            public_url=PUBLIC,
        )


@pytest.mark.parametrize("decision", sorted(ON_A_TICKET))
def test_a_decision_on_a_ticket_needs_its_card_id(decision: Decision) -> None:
    with pytest.raises(ValueError, match="needs card_id"):
        decision_path(decision, board_id=BOARD, loop_id=LOOP)
    with pytest.raises(ValueError, match="needs card_id"):
        decision_link(decision, board_id=BOARD, loop_id=LOOP, public_url=PUBLIC)


@pytest.mark.parametrize("decision", sorted(set(PATHS) - ON_A_TICKET))
def test_a_decision_on_the_loop_page_takes_no_card_id(decision: Decision) -> None:
    with pytest.raises(ValueError, match="takes no card_id"):
        decision_path(decision, board_id=BOARD, loop_id=LOOP, card_id=CARD)


@pytest.mark.parametrize("public_url", [PUBLIC, f"{PUBLIC}/", f"{PUBLIC}//"])
@pytest.mark.parametrize(("decision", "path"), sorted(PATHS.items()))
def test_with_a_public_url_the_link_is_absolute(
    public_url: str, decision: Decision, path: str
) -> None:
    link = decision_link(
        decision, board_id=BOARD, loop_id=LOOP, card_id=_card(decision), public_url=public_url
    )
    assert link == f"{PUBLIC}{path}"


@pytest.mark.parametrize("public_url", [None, ""])
@pytest.mark.parametrize(("decision", "path"), sorted(PATHS.items()))
def test_without_a_public_url_the_link_is_the_path(
    public_url: str | None, decision: Decision, path: str
) -> None:
    link = decision_link(
        decision, board_id=BOARD, loop_id=LOOP, card_id=_card(decision), public_url=public_url
    )
    assert link == path


@pytest.mark.parametrize("configured", [PUBLIC, f"{PUBLIC}/"])
def test_the_link_is_built_on_the_setting_as_the_server_reads_it(configured: str) -> None:
    public_url = Settings(public_url=configured).public_url
    assert public_url == PUBLIC
    link = decision_link("wait", board_id=BOARD, loop_id=LOOP, card_id=CARD, public_url=public_url)
    assert link == f"{PUBLIC}{TICKET_PAGE}?focus=clear-wait"


def test_the_module_reads_no_request_and_no_storage() -> None:
    # Only the standard library: no request to take a Host or X-Forwarded-* header from, no
    # settings read behind the caller's back, no SQLAlchemy, storage or repository.
    source = Path(decision_links.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, "the module imports nothing of the app"
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert imported == {"__future__", "re", "typing", "urllib.parse"}


# --- the setting -----------------------------------------------------------------------------


def test_public_url_is_unset_by_default() -> None:
    assert Settings.model_fields["public_url"].default is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (PUBLIC, PUBLIC),
        (f"{PUBLIC}/", PUBLIC),
        (f"  {PUBLIC}/  ", PUBLIC),
        ("http://localhost:8080", "http://localhost:8080"),
        ("http://192.168.1.20:8080/", "http://192.168.1.20:8080"),
        ("http://[::1]:8080/", "http://[::1]:8080"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_public_url_takes_an_http_or_https_address(value: str | None, expected: str | None) -> None:
    assert checked_public_url(value) == expected
    assert Settings(public_url=value).public_url == expected


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        ("ftp://tralala.example.com", "must start with http:// or https://"),
        ("javascript:alert(1)", "must start with http:// or https://"),
        ("tralala.example.com", "must start with http:// or https://"),
        ("https://admin:secret@tralala.example.com", "must not carry a user name or password"),
        ("https://admin@tralala.example.com", "must not carry a user name or password"),
        (f"{PUBLIC}/?board=1", r"must not have a query \(\?\.\.\.\)"),
        (f"{PUBLIC}?", r"must not have a query \(\?\.\.\.\)"),
        (f"{PUBLIC}/#top", r"must not have a fragment \(#\.\.\.\)"),
        (f"{PUBLIC}#", r"must not have a fragment \(#\.\.\.\)"),
        ("https://", "must name a host"),
        ("https:///boards", "must name a host"),
        ("https:tralala.example.com", "must name a host"),
        (f"{PUBLIC}:99999", "has a port that is not a number"),
        (f"{PUBLIC}:http", "has a port that is not a number"),
        ("https://tralala example.com", "must not contain spaces or control characters"),
        ("https://tralala.example.com\t/x", "must not contain spaces or control characters"),
        ("https://[::1", "is not a URL"),
    ],
)
def test_public_url_refuses_what_a_link_cannot_be_built_on(value: str, problem: str) -> None:
    with pytest.raises(ValueError, match=rf"^public_url \(TRALALA_PUBLIC_URL\) {problem}"):
        checked_public_url(value)
    # The same check stops the settings, so the server does not start with the value.
    with pytest.raises(ValidationError, match=rf"public_url \(TRALALA_PUBLIC_URL\) {problem}"):
        Settings(public_url=value)


class EnvironmentSettings(Settings):
    """The settings from the environment alone, without a ``.env`` file."""

    model_config = SettingsConfigDict(env_file=None)


def test_public_url_is_read_from_tralala_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRALALA_PUBLIC_URL", f"{PUBLIC}/")
    assert EnvironmentSettings().public_url == PUBLIC
    # docker compose hands an unset variable over as empty text, which means unset.
    monkeypatch.setenv("TRALALA_PUBLIC_URL", "")
    assert EnvironmentSettings().public_url is None
    monkeypatch.setenv("TRALALA_PUBLIC_URL", "ftp://tralala.example.com")
    with pytest.raises(ValidationError, match=r"public_url \(TRALALA_PUBLIC_URL\) must start"):
        EnvironmentSettings()
