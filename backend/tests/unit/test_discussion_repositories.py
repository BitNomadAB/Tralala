"""The discussion repository surface board discussions build on, on the in-memory fakes: closing
and reopening a thread, the ``board_level`` and ``state`` filters of ``newest``, and the read
markers (``mark``, ``get`` and which threads are unread for an actor)."""

from __future__ import annotations

from app.db.generated.board import DiscussionMessagesRow, DiscussionThreadsRow
from app.repositories.board import BoardRepositories
from tests.unit.fakes.board import (
    CREATED,
    BoardState,
    FakeBoardRepositories,
    card_row,
    discussion_row,
    list_row,
    loop_row,
)

ADA = "actor-ada"
GRACE = "actor-grace"
EARLY = "2026-11-26T09:00:00Z"
LATER = "2026-11-26T10:00:00Z"
LATEST = "2026-11-26T11:00:00Z"


def repositories(*threads: DiscussionThreadsRow) -> tuple[BoardState, BoardRepositories]:
    state = BoardState()
    state.loops["loop-1"] = loop_row("loop-1")
    state.lists["list-1"] = list_row("list-1", "loop-1", 0)
    state.cards["card-1"] = card_row("card-1", "list-1", "loop-1")
    for row in threads:
        state.discussions[row.id] = row
    return state, FakeBoardRepositories(state)


def message(
    message_id: str,
    discussion_id: str,
    *,
    author: str,
    created_at: str,
    deleted_at: str | None = None,
) -> DiscussionMessagesRow:
    return DiscussionMessagesRow(
        id=message_id,
        discussion_id=discussion_id,
        parent_message_id=None,
        author_actor_id=author,
        author_type="user",
        author_name=author,
        author_role=None,
        content="words",
        status="posted",
        model=None,
        created_at=created_at,
        deleted_at=deleted_at,
        round_number=0,
        content_sha256=None,
        answer_json="{}",
        after_closed=0,
        ref_card_id=None,
    )


# --- close and reopen ----------------------------------------------------------------------------


def test_close_records_who_closed_the_thread_and_when() -> None:
    state, repos = repositories(discussion_row("t1", status="discussing"))

    repos.threads.close("t1", actor_id=ADA, now=LATER)

    row = state.discussions["t1"]
    assert (row.status, row.closed_at, row.closed_by_actor_id) == ("closed", LATER, ADA)
    assert (row.updated_at, row.last_activity_at) == (LATER, LATER)


def test_reopen_makes_a_closed_thread_discussing_and_forgets_who_closed_it() -> None:
    state, repos = repositories(discussion_row("t1", status="discussing"))
    repos.threads.close("t1", actor_id=ADA, now=LATER)

    repos.threads.reopen("t1", now=LATEST)

    row = state.discussions["t1"]
    assert (row.status, row.closed_at, row.closed_by_actor_id) == ("discussing", None, None)
    assert (row.updated_at, row.last_activity_at) == (LATEST, LATEST)


def test_close_and_reopen_of_an_unknown_thread_change_nothing() -> None:
    state, repos = repositories(discussion_row("t1"))

    repos.threads.close("missing", actor_id=ADA, now=LATER)
    repos.threads.reopen("missing", now=LATER)

    assert list(state.discussions) == ["t1"]
    assert state.discussions["t1"].closed_at is None


def test_a_new_thread_and_message_start_not_closed_and_point_at_nothing() -> None:
    row = discussion_row("t1")
    assert (row.closed_at, row.closed_by_actor_id) == (None, None)
    note = message("m1", "t1", author=ADA, created_at=CREATED)
    assert (note.after_closed, note.ref_card_id) == (0, None)


# --- newest: board_level and state ---------------------------------------------------------------


def threads_for_filters() -> tuple[BoardState, BoardRepositories]:
    return repositories(
        discussion_row("board-open", status="discussing").__replace__(last_activity_at=LATEST),
        discussion_row("board-closed", status="closed").__replace__(last_activity_at=LATER),
        discussion_row("ticket-open", card_id="card-1").__replace__(last_activity_at=EARLY),
        discussion_row("ticket-closed", card_id="card-1", status="closed"),
    )


def ids(rows: list[DiscussionThreadsRow]) -> list[str]:
    return [row.id for row in rows]


def test_newest_without_the_new_filters_reads_every_thread_as_before() -> None:
    _, repos = threads_for_filters()

    rows = repos.threads.newest(status=None, card_id=None, limit=10)

    assert ids(rows) == ["board-open", "board-closed", "ticket-open", "ticket-closed"]


def test_newest_board_level_keeps_threads_without_a_ticket_or_only_those_with_one() -> None:
    _, repos = threads_for_filters()

    board = repos.threads.newest(status=None, card_id=None, limit=10, board_level=True)
    ticket = repos.threads.newest(status=None, card_id=None, limit=10, board_level=False)

    assert ids(board) == ["board-open", "board-closed"]
    assert ids(ticket) == ["ticket-open", "ticket-closed"]


def test_newest_state_open_is_every_status_but_closed() -> None:
    _, repos = threads_for_filters()

    open_rows = repos.threads.newest(status=None, card_id=None, limit=10, state="open")
    closed = repos.threads.newest(status=None, card_id=None, limit=10, state="closed")

    assert ids(open_rows) == ["board-open", "ticket-open"]
    assert ids(closed) == ["board-closed", "ticket-closed"]


def test_newest_combines_the_new_filters_with_status_card_and_limit() -> None:
    _, repos = threads_for_filters()

    assert ids(
        repos.threads.newest(status=None, card_id=None, limit=10, board_level=True, state="closed")
    ) == ["board-closed"]
    assert ids(repos.threads.newest(status="open", card_id="card-1", limit=10, state="open")) == [
        "ticket-open"
    ]
    assert ids(repos.threads.newest(status=None, card_id=None, limit=1, state="open")) == [
        "board-open"
    ]


# --- read markers --------------------------------------------------------------------------------


def test_mark_sets_the_actors_marker_and_moves_it_on_the_next_read() -> None:
    _, repos = repositories(discussion_row("t1"))
    assert repos.reads.get("t1", ADA) is None

    repos.reads.mark("t1", ADA, now=EARLY)
    first = repos.reads.get("t1", ADA)
    repos.reads.mark("t1", ADA, now=LATER)
    second = repos.reads.get("t1", ADA)

    assert first is not None and first.last_read_at == EARLY
    assert second is not None and second.last_read_at == LATER
    assert repos.reads.get("t1", GRACE) is None


def test_own_messages_never_make_a_thread_unread() -> None:
    state, repos = repositories(discussion_row("t1"))
    state.discussion_messages.append(message("m1", "t1", author=ADA, created_at=LATER))

    assert repos.reads.unread_ids(ADA, ["t1"]) == set()


def test_a_message_from_someone_else_after_the_marker_makes_the_thread_unread() -> None:
    state, repos = repositories(discussion_row("t1"))
    repos.reads.mark("t1", ADA, now=EARLY)
    state.discussion_messages.append(message("m1", "t1", author=GRACE, created_at=LATER))

    assert repos.reads.unread_ids(ADA, ["t1"]) == {"t1"}

    repos.reads.mark("t1", ADA, now=LATEST)
    assert repos.reads.unread_ids(ADA, ["t1"]) == set()


def test_a_message_at_or_before_the_marker_is_read() -> None:
    state, repos = repositories(discussion_row("t1"))
    state.discussion_messages.append(message("m1", "t1", author=GRACE, created_at=EARLY))
    state.discussion_messages.append(message("m2", "t1", author=GRACE, created_at=LATER))
    repos.reads.mark("t1", ADA, now=LATER)

    assert repos.reads.unread_ids(ADA, ["t1"]) == set()


def test_a_deleted_message_does_not_make_a_thread_unread() -> None:
    state, repos = repositories(discussion_row("t1"))
    repos.reads.mark("t1", ADA, now=EARLY)
    state.discussion_messages.append(
        message("m1", "t1", author=GRACE, created_at=LATER, deleted_at=LATEST)
    )

    assert repos.reads.unread_ids(ADA, ["t1"]) == set()


def test_no_marker_is_unread_once_someone_else_has_written() -> None:
    state, repos = repositories(discussion_row("t1"), discussion_row("t2"))
    state.discussion_messages.append(message("m1", "t1", author=GRACE, created_at=EARLY))

    assert repos.reads.unread_ids(ADA, ["t1", "t2"]) == {"t1"}


def test_unread_ids_answers_only_for_the_threads_asked_about() -> None:
    state, repos = repositories(discussion_row("t1"), discussion_row("t2"))
    state.discussion_messages.append(message("m1", "t1", author=GRACE, created_at=EARLY))
    state.discussion_messages.append(message("m2", "t2", author=GRACE, created_at=EARLY))

    assert repos.reads.unread_ids(ADA, ["t2"]) == {"t2"}
    assert repos.reads.unread_ids(ADA, []) == set()


def test_markers_are_per_actor() -> None:
    state, repos = repositories(discussion_row("t1"))
    state.discussion_messages.append(message("m1", "t1", author=GRACE, created_at=LATER))
    repos.reads.mark("t1", GRACE, now=EARLY)

    assert repos.reads.unread_ids(ADA, ["t1"]) == {"t1"}
    assert repos.reads.unread_ids(GRACE, ["t1"]) == set()
