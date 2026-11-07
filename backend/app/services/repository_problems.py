"""Why a repository could not be read, in one plain sentence that says what to do.

A repository is read in two places: the check in Settings, when a repository is added or its key
is replaced, and every analysis or RoadMap run. Both meet the same answers from the host (a key it
rejects, a repository it will not show, a limit, no answer at all) and from the archive (nothing a
run reads), so both take their sentence from here: a person who reads "The key cannot see app"
under the run and under the check knows it is the same problem, with the same remedy.

The sentences hold for every host Tralala reads: they name the key, the repository and what the
key needs, never a host's own words, its error text or the token. A failure is a short code
(``not_found``) in the run's record and the log; :func:`problem_text` is what a person reads.

A code arrives from the host's HTTP status (:func:`status_problem`), from the Git mirror
(``repo_mirror_git.MirrorError``) or from a snapshot that came back empty (the ``EMPTY_*`` codes,
``repo_snapshot_select.empty_reason``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from pydantic import JsonValue

# A commit's archive holds no file at all (an empty branch, or only submodules, whose files an
# archive never carries).
EMPTY_ARCHIVE: Final = "empty_archive"
# Every file is one a run skips: build output, dependencies, lock files, binaries.
NOTHING_READABLE: Final = "nothing_readable"
# The board's focus and exclude paths leave no file.
PATHS_MATCH_NOTHING: Final = "paths_match_nothing"
# The check only: the host shows the repository, but not its files.
CONTENTS_HIDDEN: Final = "contents_hidden"
EMPTY_CODES: Final = frozenset({EMPTY_ARCHIVE, NOTHING_READABLE, PATHS_MATCH_NOTHING})

# What the key needs on any host, for every sentence that asks for it.
READ_CONTENTS: Final = "give it read access to the repository's contents"

_TEXT: Final[Mapping[str, str]] = {
    "not_found": "The key cannot see {name}: " + READ_CONTENTS,
    "forbidden": (
        "The host refused the key access to {name}: " + READ_CONTENTS + " (an organisation may "
        "have to approve the key first)"
    ),
    CONTENTS_HIDDEN: "The key can see {name} but not its files: " + READ_CONTENTS,
    "unauthorized": (
        "The host rejected the key for {name}: it is wrong, expired or revoked; create a new one "
        "and replace it"
    ),
    "auth_failed": (
        "The host rejected the key for {name}, or wants one: add a key with read access to the "
        "repository's contents, or create a new one and replace it"
    ),
    "branch_missing": (
        "The branch of {name} does not exist: choose an existing branch, or leave the field empty "
        "for the repository's main branch"
    ),
    "invalid_url": "The URL of {name} is not one Tralala can read: correct it",
    "host_not_allowed": (
        "The host of {name} is not listed in TRALALA_REPOSITORY_HOSTS: an operator adds it there"
    ),
    "timeout": "Reading {name} took too long: try again, or narrow the board's focus paths",
    "unreachable": "The host of {name} did not answer as expected: try again later",
    "malformed_response": "The host's answer for {name} could not be understood: try again later",
    "redirect_refused": (
        "The host sent the download of {name} somewhere Tralala does not follow: try again later"
    ),
    "malformed_archive": "The archive of {name} could not be unpacked: try again later",
    "too_large": (
        "{name} is larger than this installation reads in one run: an operator raises the "
        "repository size limit"
    ),
    "git_missing": (
        "The git program is not installed where Tralala runs: an operator installs it, so that "
        "{name} can be mirrored"
    ),
    "fetch_failed": "Git could not read {name}: check the URL and the key",
    EMPTY_ARCHIVE: (
        "{name} holds no files at this commit: check the branch (an archive never carries the "
        "files of submodules)"
    ),
    NOTHING_READABLE: (
        "{name} has no file a run reads: every file is build output, a dependency, a lock file "
        "or binary"
    ),
    PATHS_MATCH_NOTHING: (
        "The board's focus and exclude paths for {name} leave no file: correct them in the "
        "board's settings (a folder is 'docs/**', not 'docs')"
    ),
}
# Without a key a private repository looks exactly like one that does not exist.
_WITHOUT_KEY: Final[Mapping[str, str]] = {
    "not_found": (
        "{name} was not found, or it is private: add a key with read access to the repository's "
        "contents, or check the URL"
    ),
    "forbidden": "The host refused to show {name} without a key: add one, " + READ_CONTENTS,
    "rate_limited": (
        "The host's limit for requests without a key was reached while reading {name}: add a key, "
        "which raises the limit, or try again later"
    ),
}
_RATE_LIMITED: Final = (
    "The host's limit for the key was reached while reading {name}: try again later"
)
_EXPIRED: Final = (
    "The host rejected the key for {name}; it worked before, so it has probably expired or been "
    "revoked: create a new one and replace it"
)


def problem_text(
    code: str, name: str, *, has_token: bool = True, worked_before: bool = False
) -> str:
    """The sentence for ``code``: what went wrong with ``name`` and what to do about it.

    ``has_token`` says whether a key was sent (without one, a private repository answers like a
    missing one); ``worked_before`` that an earlier check passed, so a rejected key has expired.
    """
    if code == "unauthorized" and worked_before:
        return _EXPIRED.format(name=name)
    if code == "rate_limited":
        template = _RATE_LIMITED if has_token else _WITHOUT_KEY["rate_limited"]
        return template.format(name=name)
    if not has_token and code in _WITHOUT_KEY:
        return _WITHOUT_KEY[code].format(name=name)
    template = _TEXT.get(code)
    if template is None:
        return f"{name} could not be read ({code}): try again, and check the key and the URL"
    return template.format(name=name)


def status_problem(status: int, *, rate_limited: bool = False) -> str:
    """The code of a host's HTTP answer that refused a read: what every provider's REST API means
    by 401, 403, 404 and 429. ``rate_limited`` is a 403 the host marked as its rate limit."""
    if status == 401:
        return "unauthorized"
    if status == 404:
        return "not_found"
    if status == 429 or (status == 403 and rate_limited):
        return "rate_limited"
    if status == 403:
        return "forbidden"
    return "unreachable"


def unread(
    entry: Mapping[str, JsonValue], code: str, *, has_token: bool = True
) -> dict[str, JsonValue]:
    """The entry of a repository that could not be read: its code and its sentence."""
    name = str(entry.get("name") or "the repository")
    return {**entry, "error": code, "problem": problem_text(code, name, has_token=has_token)}


def unread_notice(repositories: JsonValue, *, limit: int = 500) -> str | None:
    """What an analysis says about itself when a repository could not be read: written without
    that code, why, and what to do. ``repositories`` is the run's ``context.repositories``; None
    when every repository was read or none is linked. At most ``limit`` characters."""
    if not isinstance(repositories, list):
        return None
    named = [entry for entry in repositories if isinstance(entry, dict)]
    failed = [error_fields(entry) for entry in named if entry.get("error")]
    if not failed:
        return None
    problems = "; ".join(str(fields["problem"]).rstrip(".") for fields in failed)
    if len(failed) == len(named):
        text = (
            f"This analysis was written without the code, which could not be read ({problems}). "
            "Nothing it says about the code was checked against it: run the analysis again once "
            "the repository can be read."
        )
    else:
        text = (
            f"Part of the code could not be read ({problems}). What this analysis says about that "
            "part was not checked against it: run the analysis again once it can be read."
        )
    return text if len(text) <= limit else text[: limit - 1] + "…"


def error_fields(entry: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """A repository entry's failure as a run records and answers it: the code and its sentence.
    An entry from before the sentence existed gets it here; one without an error gets nothing."""
    code = entry.get("error")
    if not isinstance(code, str) or not code:
        return {}
    problem = entry.get("problem")
    if not isinstance(problem, str) or not problem:
        problem = problem_text(code, str(entry.get("name") or "the repository"))
    return {"error": code, "problem": problem}
