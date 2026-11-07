"""A discussion run as the API answers it, and the lookup every run command starts from."""

from __future__ import annotations

from dataclasses import asdict

from ..core.errors import NotFound
from ..db.generated.board import DiscussionRoundsRow, DiscussionRunsRow
from ..repositories.board import BoardRepositories
from .discussion_synthesis import read_synthesis

RunEntry = dict[str, object]
"""A run as the API answers it: its columns, ``autonomy`` as a boolean and its rounds."""


def round_entry(row: DiscussionRoundsRow) -> dict[str, object]:
    """A round as the API answers it: its columns, with its decision support as ``synthesis``."""
    entry: dict[str, object] = dict(asdict(row))
    entry.pop("synthesis_json", None)
    entry["synthesis"] = read_synthesis(row.synthesis_json)
    return entry


def serialize_run(
    repos: BoardRepositories, run: DiscussionRunsRow, *, with_rounds: bool = True
) -> RunEntry:
    entry: RunEntry = dict(asdict(run))
    entry["autonomy"] = bool(run.autonomy)
    entry["rounds"] = (
        [round_entry(row) for row in repos.rounds.for_run(run.id)] if with_rounds else []
    )
    return entry


def recent_runs(
    repos: BoardRepositories, discussion_id: str, *, limit: int = 10
) -> list[RunEntry]:
    """The thread's latest runs, newest first, each with its rounds."""
    return [serialize_run(repos, run) for run in repos.runs.recent(discussion_id, limit=limit)]


def require_run(repos: BoardRepositories, discussion_id: str, run_id: str) -> DiscussionRunsRow:
    run = repos.runs.get(run_id)
    if run is None or run.discussion_id != discussion_id:
        raise NotFound("Discussion run not found")
    return run
