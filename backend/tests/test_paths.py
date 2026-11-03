"""Request text that reaches a filesystem path, a response header or a log line."""

from __future__ import annotations

import pytest

from app.core.errors import NotFound, ValidationFailure
from app.core.identifiers import accepted_request_id, canonical_board_id
from app.services.backups import is_backup_name
from app.services.common import archive_file_name

BOARD_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"


@pytest.mark.parametrize(
    "value",
    [
        BOARD_ID,
        BOARD_ID.upper(),
        "{" + BOARD_ID + "}",
        "urn:uuid:" + BOARD_ID,
        BOARD_ID.replace("-", ""),
    ],
)
def test_a_board_id_is_always_written_in_canonical_form(value: str) -> None:
    assert canonical_board_id(value) == BOARD_ID
    assert canonical_board_id(value) == BOARD_ID


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-uuid",
        "../../registry",
        BOARD_ID + "/../other",
        BOARD_ID + "\\..\\other",
        BOARD_ID[:-1],
        None,
        42,
    ],
)
def test_anything_else_is_a_missing_board(value: object) -> None:
    with pytest.raises(NotFound) as refused:
        canonical_board_id(value)  # type: ignore[arg-type]
    assert refused.value.status_code == 404


@pytest.mark.parametrize(
    "name",
    [
        "backup-20260101T000000Z.sqlite",
        "backup-20260101T000000Z-pre-migration.sqlite",
        "backup-20260101T000000Z-pre-migration-2.sqlite",
        "backup-20261103T235959Z-manual.sqlite",
    ],
)
def test_a_backup_name_from_the_service_is_accepted(name: str) -> None:
    assert is_backup_name(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "backup-pre-migration.sqlite",
        "registry.sqlite",
        "../backup-20260101T000000Z.sqlite",
        "backup-20260101T000000Z.sqlite/../../registry.sqlite",
        "backup-20260101T000000Z/../x.sqlite",
        "backup-20260101T000000Z-..\\..\\x.sqlite",
        "backup-20260101T000000Z-Manual.sqlite",
        "backup-20260101T000000Z.sqlite.bak",
        "backup-2026010T000000Z.sqlite",
        " backup-20260101T000000Z.sqlite",
        "backup-20260101T000000Z.sqlite\n",
        "backup-20260101T000000Z-manual.sqlite\n",
        "backup-20260101T000000Z.sqlite\r\n",
        # Arabic-Indic digits are digits to Python's digit class, never to a backup name.
        "backup-\u0662\u0660\u0662\u0666\u0660\u0661\u0660\u0661T000000Z.sqlite",
    ],
)
def test_any_other_backup_name_is_refused(name: str) -> None:
    assert is_backup_name(name) is False


@pytest.mark.parametrize(
    "entry",
    [
        "attachments/..",
        "attachments/.",
        "attachments/x\\y.bin",
        "attachments/",
        "attachments/a\x00b",
    ],
)
def test_an_archive_entry_must_be_a_plain_filename(entry: str) -> None:
    with pytest.raises(ValidationFailure) as refused:
        archive_file_name(entry)
    assert refused.value.details == {"entry": entry}


@pytest.mark.parametrize(
    ("entry", "name"),
    [
        ("attachments/abc.bin", "abc.bin"),
        ("attachments/nested/deeper/abc.bin", "abc.bin"),
        ("abc.bin", "abc.bin"),
    ],
)
def test_a_normal_archive_entry_keeps_its_stored_name(entry: str, name: str) -> None:
    assert archive_file_name(entry) == name


@pytest.mark.parametrize("value", ["a", "req-1.2_3", BOARD_ID, "x" * 100])
def test_a_short_token_is_kept_as_the_request_id(value: str) -> None:
    assert accepted_request_id(value) is True


@pytest.mark.parametrize(
    "value",
    ["", "x" * 101, "req 1", "req/1", "req-1\n", "req-1\r\nSet-Cookie: a=b", "réq"],
)
def test_anything_else_gets_a_server_request_id(value: str) -> None:
    assert accepted_request_id(value) is False
