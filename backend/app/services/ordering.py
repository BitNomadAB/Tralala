"""Gap-based positions for ordered siblings (lists of a Loop, cards of a list, checklist items).

Positions are integers spaced by ``POSITION_GAP``, so a move usually writes one row: the moved row
takes the midpoint between its new neighbours. Only when no integer is left between them are the
siblings renumbered to multiples of the gap, in their current order, first.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

POSITION_GAP = 1024


@dataclass(frozen=True, slots=True)
class Placement:
    """Where a row goes, and the sibling positions to write first (empty when the gaps suffice)."""

    position: int
    renumbered: tuple[tuple[str, int], ...] = ()


def place(siblings: Sequence[tuple[str, int]], index: int | None) -> Placement:
    """The position for a row at ``index`` (0-based; None appends) among ``siblings``.

    ``siblings`` are ``(id, position)`` in display order (position, then id) and do not include the
    row being placed. An index past the end appends.
    """
    if not siblings:
        return Placement(POSITION_GAP)
    target = len(siblings) if index is None else max(0, min(index, len(siblings)))
    if target == len(siblings):
        return Placement(siblings[-1][1] + POSITION_GAP)
    renumbered = tuple(
        (sibling_id, number * POSITION_GAP) for number, (sibling_id, _) in enumerate(siblings, 1)
    )
    if target == 0:
        first = siblings[0][1]
        if first > 1:
            return Placement(first // 2)
        return Placement(POSITION_GAP // 2, renumbered)
    previous, following = siblings[target - 1][1], siblings[target][1]
    if following - previous > 1:
        return Placement((previous + following) // 2)
    previous, following = renumbered[target - 1][1], renumbered[target][1]
    return Placement((previous + following) // 2, renumbered)
