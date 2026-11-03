"""The checked column converters every generated ``from_mapping`` calls."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from app.db import values
from app.db.generated.board import ListsRow
from app.db.generated.registry import ActorsRow

type Converter = Callable[[dict[str, object], str], object]


@pytest.mark.parametrize(
    ("convert", "value", "expected"),
    [
        (values.text, "x", "x"),
        (values.integer, 7, 7),
        (values.real, 0.5, 0.5),
        (values.real, 2, 2.0),
        (values.flag, 1, True),
        (values.flag, 0, False),
        (values.blob, b"\x00", b"\x00"),
    ],
)
def test_a_value_of_the_declared_type_passes(
    convert: Converter, value: object, expected: object
) -> None:
    assert convert({"column": value}, "column") == expected


@pytest.mark.parametrize(
    ("convert", "value"),
    [
        (values.text, 1),
        (values.text, None),
        (values.integer, "1"),
        (values.integer, True),
        (values.integer, 1.0),
        (values.real, "0.5"),
        (values.real, False),
        (values.flag, 2),
        (values.flag, True),
        (values.flag, "1"),
        (values.blob, "x"),
    ],
)
def test_a_value_of_another_type_names_the_column(convert: Converter, value: object) -> None:
    with pytest.raises(values.ColumnTypeError, match=r"^column: expected "):
        convert({"column": value}, "column")


@pytest.mark.parametrize(
    "convert",
    [
        values.text_or_none,
        values.integer_or_none,
        values.real_or_none,
        values.flag_or_none,
        values.blob_or_none,
    ],
)
def test_only_the_nullable_variants_accept_none(convert: Converter) -> None:
    assert convert({"column": None}, "column") is None


def test_a_generated_row_reads_its_columns_by_name_and_ignores_others() -> None:
    mapping: dict[str, object] = {
        "loop_id": "loop-1",
        "id": "list-1",
        "name": "To do",
        "position": 1024,
        "created_at": "2026-11-01T09:00:00Z",
        "updated_at": "2026-11-02T09:00:00Z",
        "archived_at": None,
        "card_count": 3,
    }

    row = ListsRow.from_mapping(mapping)

    assert row == ListsRow(
        id="list-1",
        name="To do",
        position=1024,
        created_at="2026-11-01T09:00:00Z",
        updated_at="2026-11-02T09:00:00Z",
        archived_at=None,
        loop_id="loop-1",
    )
    with pytest.raises(values.ColumnTypeError, match=r"^position: expected int, got str$"):
        ListsRow.from_mapping({**mapping, "position": "1024"})


def test_a_joined_tables_row_is_read_back_from_its_prefixed_columns() -> None:
    joined: dict[str, object] = {
        "id": "session-1",
        "actor__id": "actor-1",
        "actor__type": "user",
        "actor__name": "Ada",
        "actor__created_at": "2026-11-01T09:00:00Z",
        "actor__disabled_at": None,
    }

    actor = ActorsRow.from_mapping(values.prefixed(joined, "actor__"))

    assert actor == ActorsRow(
        id="actor-1", type="user", name="Ada", created_at="2026-11-01T09:00:00Z", disabled_at=None
    )
    with pytest.raises(KeyError, match="owner__id"):
        ActorsRow.from_mapping(values.prefixed(joined, "owner__"))
