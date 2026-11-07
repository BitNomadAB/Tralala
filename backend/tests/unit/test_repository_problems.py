"""The sentence a person reads when a repository could not be read: one per failure, the same in
the repository check and in a run, and the same for every host (PLN-012)."""

from __future__ import annotations

import pytest
from pydantic import JsonValue

from app.services.loop_generation_trace import repository_unreadable, unread_summary
from app.services.repo_mirror_git import ERROR_TEXT
from app.services.repository_problems import (
    EMPTY_CODES,
    error_fields,
    problem_text,
    status_problem,
    unread,
    unread_notice,
)

# Every code a run or a check can record: the host's answers, the archive's, the mirror's.
CODES = (
    "unauthorized",
    "forbidden",
    "not_found",
    "rate_limited",
    "contents_hidden",
    "branch_missing",
    "timeout",
    "unreachable",
    "malformed_response",
    "redirect_refused",
    "malformed_archive",
    "too_large",
    "invalid_url",
    # The mirror's other two are no failed read: a stale mirror was read, a cleanup is no read.
    *(code for code in ERROR_TEXT if code not in {"stale_mirror", "mirror_cleanup_failed"}),
    *sorted(EMPTY_CODES),  # sorted: every pytest worker must collect the same order
)


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "unauthorized"), (403, "forbidden"), (404, "not_found"), (429, "rate_limited")],
)
def test_each_refusal_of_a_host_has_its_code(status: int, code: str) -> None:
    assert status_problem(status) == code


def test_a_403_the_host_marks_as_its_rate_limit_is_the_rate_limit() -> None:
    assert status_problem(403, rate_limited=True) == "rate_limited"
    assert status_problem(502) == "unreachable"
    assert status_problem(200) == "unreachable"


@pytest.mark.parametrize(
    ("status", "with_key", "without_key"),
    [
        (
            401,
            "The host rejected the key for app: it is wrong, expired or revoked; create a new "
            "one and replace it",
            None,
        ),
        (
            403,
            "The host refused the key access to app: give it read access to the repository's "
            "contents (an organisation may have to approve the key first)",
            "The host refused to show app without a key: add one, give it read access to the "
            "repository's contents",
        ),
        (
            404,
            "The key cannot see app: give it read access to the repository's contents",
            "app was not found, or it is private: add a key with read access to the "
            "repository's contents, or check the URL",
        ),
        (
            429,
            "The host's limit for the key was reached while reading app: try again later",
            "The host's limit for requests without a key was reached while reading app: add a "
            "key, which raises the limit, or try again later",
        ),
    ],
)
def test_the_wording_per_status_says_what_to_do_with_and_without_a_key(
    status: int, with_key: str, without_key: str | None
) -> None:
    code = status_problem(status)
    assert problem_text(code, "app") == with_key
    assert problem_text(code, "app", has_token=False) == (without_key or with_key)


def test_a_rejected_key_that_worked_before_has_probably_expired() -> None:
    assert problem_text("unauthorized", "app", worked_before=True) == (
        "The host rejected the key for app; it worked before, so it has probably expired or been "
        "revoked: create a new one and replace it"
    )


@pytest.mark.parametrize("code", CODES)
def test_every_code_has_a_sentence_that_names_the_repository_and_no_host(code: str) -> None:
    for has_token in (True, False):
        text = problem_text(code, "app", has_token=has_token)
        assert "app" in text
        assert f"({code})" not in text  # a sentence of its own, not the fallback
        assert ":" in text  # what went wrong, then what to do
        assert "github" not in text.lower()


def test_an_unknown_code_still_names_the_repository_and_the_code() -> None:
    assert problem_text("strange", "app") == (
        "app could not be read (strange): try again, and check the key and the URL"
    )


def test_an_entry_from_before_the_sentence_gets_it_and_a_read_entry_gets_nothing() -> None:
    assert error_fields({"name": "app", "error": "not_found"}) == {
        "error": "not_found",
        "problem": problem_text("not_found", "app"),
    }
    assert error_fields({"name": "app", "error": "x", "problem": "Kept."}) == {
        "error": "x",
        "problem": "Kept.",
    }
    assert error_fields({"name": "app", "file_count": 3}) == {}
    assert unread({"name": "app"}, "timeout", has_token=False)["problem"] == problem_text(
        "timeout", "app"
    )


# --- the trace -----------------------------------------------------------------------------------


def test_a_failed_read_is_the_problem_in_plain_words_never_the_code() -> None:
    entry: dict[str, JsonValue] = {"name": "BitNomad", "error": "not_found"}
    assert repository_unreadable(entry) == (
        "The key cannot see BitNomad: give it read access to the repository's contents"
    )
    empty: dict[str, JsonValue] = {
        **unread({"name": "app"}, "empty_archive"),
        "commit_sha": "99d0c6ed" + "0" * 32,
    }
    assert repository_unreadable(empty).endswith("(commit 99d0c6ed)")


def test_the_stage_ends_with_what_the_run_goes_on_without() -> None:
    read: dict[str, JsonValue] = {"name": "app", "file_count": 3}
    failed: dict[str, JsonValue] = {"name": "docs", "error": "not_found"}
    assert unread_summary([read]) is None
    assert unread_summary([]) is None
    kind, text = unread_summary([failed]) or ("", "")
    assert kind == "error"
    assert text.startswith("No code was read: the run goes on from the Loop's documents alone")
    assert unread_summary([read, failed]) == (
        "limit",
        "Not read: docs; the run goes on with the rest of the code",
    )


# --- the analysis' own words ---------------------------------------------------------------------


def test_the_notice_says_the_analysis_was_written_without_the_code_and_why() -> None:
    failed: JsonValue = [{"name": "BitNomad", "error": "not_found"}]
    notice = unread_notice(failed) or ""
    assert notice.startswith("This analysis was written without the code, which could not be read")
    assert "The key cannot see BitNomad: give it read access to the repository's contents" in notice
    assert notice.endswith("run the analysis again once the repository can be read.")
    partial: JsonValue = [{"name": "app", "file_count": 2}, {"name": "docs", "error": "timeout"}]
    assert (unread_notice(partial) or "").startswith("Part of the code could not be read")
    assert unread_notice([{"name": "app", "file_count": 2}]) is None
    assert unread_notice("no enabled repository is linked to this board") is None
    assert len(unread_notice(failed * 20, limit=200) or "") == 200
