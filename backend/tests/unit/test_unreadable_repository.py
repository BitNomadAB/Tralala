"""An analysis whose repository could not be read says so (PLN-012), on the in-memory fakes.

The run goes on without the code, as the owner chose by default, but nothing reads as if the code
had been read: the repository stage holds an error step in plain words and a step that says what
the run goes on without, the run's based-on entry carries the same sentence, the model is told,
and the saved analysis opens its open questions with it. A snapshot with no file to read is a
failed read too, never a quiet empty workspace.
"""

from __future__ import annotations

import json

from pydantic import JsonValue

from app.services.loop_generation_prompts import UNREAD_REPOSITORIES
from app.services.loop_generation_runs import NO_REVISION, serialize_run
from app.services.repo_snapshot import FetchedRepository
from app.services.repository_problems import problem_text, unread
from tests.unit.test_loop_generation_tools import (
    SHA,
    VALID,
    World,
    fetched_app,
    make,
    start,
    tarball,
)

NOT_FOUND = "The key cannot see BitNomad: give it read access to the repository's contents"


def _hidden() -> FetchedRepository:
    """The owner's case: a private repository the key cannot see answers 404."""
    entry: dict[str, JsonValue] = {"id": "repo-1", "name": "BitNomad", "branch": "main"}
    return FetchedRepository(unread(entry, "not_found"), None)


def _stage(w: World, stage: str) -> list[tuple[str, str]]:
    return [(str(s["kind"]), str(s["text"])) for s in w.steps() if s["stage"] == stage]


def _analysis(w: World) -> dict[str, JsonValue]:
    (row,) = [row for row in w.state.documents if row.kind == "analysis_ai"]
    loaded: dict[str, JsonValue] = json.loads(row.payload_json or "{}")
    return loaded


def test_a_repository_the_key_cannot_see_is_an_error_step_and_the_run_goes_on() -> None:
    w = make([VALID], fetched=[_hidden()])
    w.repositories.entries = [dict(_hidden().entry)]
    start(w)
    assert w.run().status == "completed"
    steps = _stage(w, "repository")
    # Never a plain step: the stage of a failed read is never shown as done.
    assert steps[0] == ("error", NOT_FOUND)
    assert steps[1][0] == "error"
    assert steps[1][1].startswith("No code was read: the run goes on from the Loop's documents")
    assert all(kind != "step" for kind, _text in steps)
    assert "not_found" not in json.dumps(steps)


def test_the_based_on_entry_says_why_in_plain_words() -> None:
    w = make([VALID], fetched=[_hidden()])
    w.repositories.entries = [dict(_hidden().entry)]
    start(w)
    # The run as the API answers it, read back as JSON.
    sources: JsonValue = json.loads(json.dumps(serialize_run(w.run())["source_revisions"]))
    assert isinstance(sources, dict)
    listed = sources.get("repositories")
    assert isinstance(listed, list)
    (repository,) = listed
    assert isinstance(repository, dict)
    assert (repository["error"], repository["problem"]) == ("not_found", NOT_FOUND)


def test_the_model_is_told_and_the_saved_analysis_records_that_the_code_was_not_read() -> None:
    w = make([VALID], fetched=[_hidden()])
    w.repositories.entries = [dict(_hidden().entry)]
    start(w)
    assert UNREAD_REPOSITORIES in w.provider.seen[0].messages[0]["content"]
    analysis = _analysis(w)
    questions = analysis["open_questions"]
    assert isinstance(questions, list)
    first = str(questions[0])
    assert first.startswith("This analysis was written without the code")
    assert NOT_FOUND in first
    assert analysis["repository_revision"] == NO_REVISION
    # The document a person reads shows it as well, under the open questions.
    (human,) = [row for row in w.state.documents if row.kind == "analysis"]
    assert "This analysis was written without the code" in human.content
    # The run's own output stays the model's answer.
    output = json.loads(w.run().output_json)
    assert not any("without the code" in str(item) for item in output.get("open_questions", []))


def test_a_read_repository_leaves_the_analysis_as_the_model_wrote_it() -> None:
    w = make([VALID])
    start(w)
    assert all(kind != "error" for kind, _text in _stage(w, "repository"))
    analysis = _analysis(w)
    questions = analysis["open_questions"]
    assert isinstance(questions, list)
    assert not any("without the code" in str(item) for item in questions)
    assert analysis["repository_revision"] != NO_REVISION


def test_one_unread_repository_beside_a_read_one_is_a_limit_and_a_partial_notice() -> None:
    w = make([VALID], fetched=[fetched_app(), _hidden()])
    start(w)
    steps = _stage(w, "repository")
    assert ("error", NOT_FOUND) in steps
    assert ("limit", "Not read: BitNomad; the run goes on with the rest of the code") in steps
    questions = _analysis(w)["open_questions"]
    assert isinstance(questions, list)
    assert str(questions[0]).startswith("Part of the code could not be read")
    assert _analysis(w)["repository_revision"] != NO_REVISION


def test_a_workspace_with_no_file_to_read_is_a_failed_read_that_names_why() -> None:
    # The owner's second finding: the key could read the repository, yet the run found 0 files
    # and went on. Here the board's focus path names a folder without a glob, so nothing matches.
    entry: dict[str, JsonValue] = {"id": "repo-1", "name": "app", "commit_sha": SHA}
    steered = FetchedRepository(entry, tarball({"src/main.py": b"x = 1\n"}), ("src",))
    w = make([VALID], fetched=[steered])
    w.repositories.entries = [unread(entry, "paths_match_nothing")]
    start(w)
    steps = _stage(w, "repository")
    assert steps[0] == (
        "error",
        problem_text("paths_match_nothing", "app") + f" (commit {SHA[:8]})",
    )
    assert w.provider.seen[0].tools == []  # nothing to read, so no tools are offered


def test_an_archive_without_files_is_an_empty_commit_not_an_empty_workspace() -> None:
    entry: dict[str, JsonValue] = {"id": "repo-1", "name": "app", "commit_sha": SHA}
    w = make([VALID], fetched=[FetchedRepository(entry, tarball({}))])
    w.repositories.entries = [unread(entry, "empty_archive")]
    start(w)
    kind, text = _stage(w, "repository")[0]
    assert (kind, text.split(" (commit")[0]) == ("error", problem_text("empty_archive", "app"))
