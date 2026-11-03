"""Gap-based positions: where a row goes among its siblings, and when they are renumbered."""

from __future__ import annotations

import pytest

from app.services.ordering import POSITION_GAP, Placement, place

SPACED = [("a", 1024), ("b", 2048), ("c", 3072)]
CROWDED = [("a", 1), ("b", 2), ("c", 3)]


def test_the_first_row_takes_one_gap() -> None:
    assert place([], None) == Placement(POSITION_GAP)
    assert place([], 5) == Placement(POSITION_GAP)


@pytest.mark.parametrize("index", [None, 3, 4, 1000])
def test_appending_goes_one_gap_past_the_last(index: int | None) -> None:
    assert place(SPACED, index) == Placement(4096)


@pytest.mark.parametrize(("index", "position"), [(0, 512), (-3, 512), (1, 1536), (2, 2560)])
def test_an_index_takes_the_middle_of_its_gap(index: int, position: int) -> None:
    assert place(SPACED, index) == Placement(position)


def test_the_front_with_no_room_renumbers_first() -> None:
    assert place([("a", 1), ("b", 9)], 0) == Placement(512, (("a", 1024), ("b", 2048)))


def test_a_used_up_gap_renumbers_in_display_order_first() -> None:
    renumbered = (("a", 1024), ("b", 2048), ("c", 3072))

    assert place(CROWDED, 1) == Placement(1536, renumbered)
    assert place(CROWDED, 2) == Placement(2560, renumbered)


def test_a_gap_of_two_still_has_a_middle() -> None:
    assert place([("a", 1), ("b", 3)], 1) == Placement(2)


def test_the_same_siblings_and_index_give_the_same_placement() -> None:
    assert place(CROWDED, 1) == place(list(CROWDED), 1)
