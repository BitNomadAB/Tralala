"""Text that reaches a filesystem path: board ids, backup names and archive entries."""

from __future__ import annotations

import pytest

from app.core.errors import NotFound, ValidationFailure
from app.core.identifiers import canonical_board_id
from app.services.backups import BACKUP_PATTERN
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
    assert BACKUP_PATTERN.match(name)


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
    ],
)
def test_any_other_backup_name_is_refused(name: str) -> None:
    assert BACKUP_PATTERN.match(name) is None


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
