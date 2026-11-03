"""Startup recovery: the work a stopped process left unfinished in each board (runs, mention jobs,
generation runs) is resolved before the application serves requests.

One board can never stop startup. A board whose database SQLite cannot read is stepped past, logged
once with its id, and left in the status it has (the Migration Manager, which runs first, has
already marked it); a board mid-repair or without its database is stepped past as before.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence

from ..core.errors import BoardUnreadable, NotFound, ServiceUnavailable

logger = logging.getLogger("tralala")

type Recover = Callable[[str], int]
"""Resolve one board's interrupted work of one kind; how many items it resolved."""


def recover_async_work(board_ids: Iterable[str], recoverers: Sequence[Recover]) -> int:
    """Run every recoverer on every board, in order; the number of items resolved in total."""
    recovered = 0
    for board_id in board_ids:
        try:
            for recover in recoverers:
                recovered += recover(board_id)
        except BoardUnreadable:
            logger.error(
                "board_database_unreadable",
                extra={"board_id": board_id, "skipped": "async_work_recovery"},
            )
        except (NotFound, ServiceUnavailable):
            # A board mid-repair is resolved by the Migration Manager or on its next start.
            continue
    if recovered:
        logger.info("async_work_recovered", extra={"items": recovered})
    return recovered
