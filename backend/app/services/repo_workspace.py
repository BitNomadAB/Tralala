"""The repository workspace: a run's commits as three read-only tools for the model.

An analysis or RoadMap run whose agent takes tools lets the model read the board's repositories
itself (decision 0025): ``list_files``, ``read_file`` and ``search``, answered here from the index
``repo_workspace_index`` builds in memory from the archives the run fetched. Nothing is executed,
written or looked up on disk; a path is a key in the index, and repository text is data.

Every answer is a ``ToolAnswer``: ``text`` is what goes back to the model, ``summary`` one sentence
for a person watching the run, and the rest (files read, counts, an error code) is what the run's
trace records instead of the text. A tool never raises: an unknown tool, a bad argument, an unknown
path or an invalid pattern is an answer that says what went wrong and what to call instead.

Each answer fits the model's context window: at most ``max_chars`` characters, a long file in parts
with the line to continue from, at most ``MAX_LIST_ENTRIES`` paths and ``MAX_MATCHES`` matches.
A regular expression is held to ``MAX_PATTERN_CHARS``, refused when it repeats a group that itself
repeats (the shape that backtracks exponentially), and matched line by line against at most
``MAX_SEARCH_LINE_CHARS`` characters of each line, so a pattern from the model, or from text it
read, cannot hold the run. A literal search reads every line whole.

In a summary a path is always the full workspace path, repository name included, exactly as the
model sees it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Final

from pydantic import JsonValue

from .repo_workspace_index import (
    RepositoryManifest,
    WorkspaceFile,
    WorkspaceLimits,
    WorkspaceSource,
    build_index,
    clean_path,
)
from .repo_workspace_tools import (
    LIST_FILES,
    MAX_PATTERN_CHARS,
    READ_FILE,
    SEARCH,
    TOOL_DEFINITIONS,
    TOOL_NAMES,
    ArgumentError,
    compile_pattern,
    parse_arguments,
)

__all__ = [
    "LIST_FILES",
    "READ_FILE",
    "SEARCH",
    "TOOL_DEFINITIONS",
    "RepositoryManifest",
    "RepositoryWorkspace",
    "ToolAnswer",
    "WorkspaceLimits",
    "WorkspaceSource",
]

DEFAULT_MAX_CHARS: Final = 60_000
MIN_MAX_CHARS: Final = 1_000
MAX_LIST_ENTRIES: Final = 1_000
MAX_MATCHES: Final = 200
MAX_SEARCH_LINE_CHARS: Final = 2_000
MATCH_TEXT_CHARS: Final = 300
# What an answer keeps free for its last line ("… file continues; …") and a read's header.
TAIL_RESERVE: Final = 120
# Values the model sent, echoed in an answer or a summary, are cut to this many characters.
ECHO_CHARS: Final = 200
SUMMARY_VALUE_CHARS: Final = 60
# A summary's range ("lines 1-212") takes an en dash, escaped because Ruff flags the character.
_DASH: Final = "\u2013"


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolAnswer:
    """One tool call's answer. ``text`` goes back to the model and ``summary`` to a person watching
    the run; ``files_read`` (with ``lines``), ``entries``, ``matches``, ``truncated`` and ``error``
    are what the run's trace keeps instead of the text."""

    text: str
    summary: str
    files_read: tuple[str, ...] = ()
    lines: tuple[int, int] | None = None
    entries: int = 0
    matches: int = 0
    truncated: bool = False
    error: str | None = None

    @property
    def chars(self) -> int:
        return len(self.text)

    def trace(self) -> dict[str, JsonValue]:
        """The answer without its text: sizes, counts, the paths read and the summary."""
        return {
            "summary": self.summary,
            "chars": self.chars,
            "files_read": [*self.files_read],
            "lines": None if self.lines is None else [*self.lines],
            "entries": self.entries,
            "matches": self.matches,
            "truncated": self.truncated,
            "error": self.error,
        }


def _refused(code: str, text: str, summary: str) -> ToolAnswer:
    return ToolAnswer(text="Error: " + text, summary=summary, error=code)


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _echo(value: str) -> str:
    """A value the model sent, as an answer quotes it."""
    return _clip(value, ECHO_CHARS)


def _shown(value: str) -> str:
    """A value the model sent, as a summary shows it: one line, printable, short."""
    printable = "".join(char if char.isprintable() else " " for char in value)
    return _clip(" ".join(printable.split()), SUMMARY_VALUE_CHARS)


def _count(number: int, one: str, many: str) -> str:
    return f"{number} {one if number == 1 else many}"


def _below(path: str, where: str) -> bool:
    return not where or path == where or path.startswith(where + "/")


def _matches_glob(file: WorkspaceFile, glob: str | None) -> bool:
    """A glob matches the full path or the path inside the repository, so ``src/*.py`` works
    without the repository's name."""
    return glob is None or fnmatchcase(file.path, glob) or fnmatchcase(file.relative, glob)


def _excerpt(line: str, position: int) -> str:
    """At most ``MATCH_TEXT_CHARS`` of a matching line, around where it matched."""
    stripped = line.strip()
    if len(stripped) <= MATCH_TEXT_CHARS:
        return stripped
    position = max(0, position - (len(line) - len(line.lstrip())))
    start = max(0, min(position - MATCH_TEXT_CHARS // 3, len(stripped) - MATCH_TEXT_CHARS))
    end = start + MATCH_TEXT_CHARS
    return ("…" if start else "") + stripped[start:end] + ("…" if end < len(stripped) else "")


class RepositoryWorkspace:
    """A run's repositories, read once into memory, and the three tools that read them."""

    def __init__(
        self,
        sources: Sequence[WorkspaceSource],
        *,
        max_chars: int = DEFAULT_MAX_CHARS,
        limits: WorkspaceLimits | None = None,
    ) -> None:
        self._index = build_index(sources, limits)
        self._readable = [file for file in self._index.files.values() if file.left_out is None]
        # The model's context window decides this; below a sensible floor no answer is useful.
        self.max_chars = max(max_chars, MIN_MAX_CHARS)

    # --- what the workspace holds ------------------------------------------------------------

    def manifest(self) -> tuple[RepositoryManifest, ...]:
        """Per repository: its name in paths, the commit, its readable files and their bytes, the
        files left out, and the error when the archive could not be read."""
        return self._index.repositories

    def describe(self) -> str:
        """The workspace in a few lines: each repository's commit, files and bytes, its top-level
        entries, and what the bounds left out."""
        lines: list[str] = []
        for entry in self._index.repositories:
            if entry.error is not None:
                lines.append(f"{entry.name} @ {entry.commit_sha}: not readable ({entry.error})")
                continue
            lines.append(
                f"{entry.name} @ {entry.commit_sha}: {_count(entry.files, 'file', 'files')}, "
                f"{entry.bytes} bytes of text"
            )
            lines.append("  top level: " + self._top_level(entry.name))
            if entry.left_out:
                lines.append(
                    f"  {_count(entry.left_out, 'file was', 'files were')} left out (too large or "
                    "over the workspace's limits); list_files marks the ones it knows"
                )
        return "\n".join(lines)

    def _top_level(self, repository: str, limit: int = 50) -> str:
        counts: dict[str, int] = {}
        for file in self._index.files.values():
            if file.repository == repository:
                head, separator, _rest = file.relative.partition("/")
                key = head + "/" if separator else head
                counts[key] = counts.get(key, 0) + 1
        names = sorted(counts)
        shown = [
            f"{name} ({_count(counts[name], 'file', 'files')})" if name.endswith("/") else name
            for name in names[:limit]
        ]
        more = len(names) - limit
        return ", ".join(shown) + (f", … {more} more" if more > 0 else "") if shown else "(empty)"

    def _fit(self, content: str) -> str:
        return _clip(content, self.max_chars)

    # --- the tools ---------------------------------------------------------------------------

    def answer(self, tool_name: str, arguments: JsonValue) -> ToolAnswer:
        """Answer one tool call by name; any problem with the call is an answer, never an
        exception."""
        name = tool_name.strip()
        if name not in TOOL_NAMES:
            return _refused(
                "unknown_tool",
                f"there is no tool '{_echo(name)}'; the tools are list_files, read_file, search.",
                f"Called an unknown tool '{_shown(name)}'",
            )
        try:
            values = parse_arguments(name, arguments)
            if name == LIST_FILES:
                return self.list_files(values.string("path") or "", values.string("glob"))
            if name == READ_FILE:
                start = values.integer("start_line")
                return self.read_file(
                    values.string("path", required=True) or "",
                    1 if start is None else start,
                    values.integer("end_line"),
                )
            return self.search(
                values.string("pattern", required=True) or "",
                values.string("glob"),
                values.flag("regex") or False,
            )
        except ArgumentError as exc:
            return _refused(
                "invalid_arguments",
                f"invalid arguments for {name}: {exc.detail}. Call it as {exc.signature}.",
                f"Called {name} {exc.summary}",
            )

    def list_files(self, path: str = "", glob: str | None = None) -> ToolAnswer:
        """Paths and sizes below ``path``, optionally only those ``glob`` matches, sorted."""
        where = clean_path(path)
        pattern = (glob or "").strip() or None
        if pattern is not None and len(pattern) > MAX_PATTERN_CHARS:
            return _refused(
                "invalid_glob",
                f"the glob is {len(pattern)} characters; at most {MAX_PATTERN_CHARS} are allowed.",
                f"Listed files with a glob of {len(pattern)} characters, which is too long",
            )
        if where and where not in self._index.directories and where not in self._index.files:
            return self._unknown(where, f"Asked to list {_shown(where)}, which does not exist")
        found = [
            file
            for file in self._index.files.values()
            if _below(file.path, where) and _matches_glob(file, pattern)
        ]
        scope = self._list_scope(where, pattern)
        if not found:
            # Every directory and file holds at least one file, so only a glob can find none.
            below = f" below '{_echo(where)}'" if where else ""
            return ToolAnswer(
                text=f"No files{below} match the glob '{_echo(pattern or '')}'.",
                summary=f"{scope} (no files)",
            )
        lines: list[str] = []
        used = 0
        budget = self.max_chars - TAIL_RESERVE
        for file in found:
            line = f"{file.path}  {file.size}" + _left_out_mark(file)
            if len(lines) >= MAX_LIST_ENTRIES or used + len(line) + 1 > budget:
                break
            lines.append(line)
            used += len(line) + 1
        more = len(found) - len(lines)
        if more:
            lines.append(f"… {more} more; narrow path or glob")
        counted = _count(len(found), "file", "files")
        shown = f"{counted}, first {len(lines) - 1} shown" if more else counted
        return ToolAnswer(
            text=self._fit("\n".join(lines)),
            summary=f"{scope} ({shown})",
            entries=len(found),
            truncated=bool(more),
        )

    def _list_scope(self, where: str, pattern: str | None) -> str:
        place = where + ("/" if where in self._index.directories else "")
        if pattern is None:
            return f"Listed {_shown(place)}" if where else "Listed every file"
        matching = f"Listed files matching {_shown(pattern)}"
        return f"{matching} in {_shown(place)}" if where else matching

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> ToolAnswer:
        """A file's lines from ``start_line`` to ``end_line`` (inclusive), numbered, at most
        ``max_chars`` characters; a longer range ends with the line to continue from."""
        where = clean_path(path)
        if not where:
            return _refused(
                "invalid_arguments",
                "read_file needs the path of a file, like '<repository>/README.md'.",
                "Called read_file without a path",
            )
        file = self._index.files.get(where)
        if file is None:
            if where in self._index.directories:
                return self._directory(where)
            return self._unknown(where, f"Asked for {_shown(where)}, which does not exist")
        if file.left_out is not None:
            return self._left_out(file)
        if start_line < 1 or (end_line is not None and end_line < start_line):
            return _refused(
                "line_range",
                f"start_line must be 1 or more and end_line at least start_line (got "
                f"{start_line} and {end_line}).",
                f"Asked for {_shown(file.path)} with an invalid line range",
            )
        lines = file.lines()
        total = len(lines)
        if start_line > total:
            return _refused(
                "line_range",
                f"'{file.path}' has {_count(total, 'line', 'lines')}; start_line {start_line} is "
                "past its end.",
                f"Asked for {_shown(file.path)} from line {start_line}, but it has "
                f"{_count(total, 'line', 'lines')}",
            )
        last = total if end_line is None else min(end_line, total)
        body, shown, cut = self._numbered(lines, start_line, last, len(file.path))
        continues = shown < last
        parts = [f"{file.path}  lines {start_line}-{shown} of {total}", *body]
        if continues:
            parts.append(f"… file continues; call read_file with start_line={shown + 1}")
        return ToolAnswer(
            text=self._fit("\n".join(parts)),
            summary=f"Read {_shown(file.path)}, lines {start_line}{_DASH}{shown} of {total}"
            + (" (continues)" if continues else ""),
            files_read=(file.path,),
            lines=(start_line, shown),
            truncated=continues or cut,
        )

    def _numbered(
        self, lines: Sequence[str], start: int, last: int, header: int
    ) -> tuple[list[str], int, bool]:
        """Numbered lines from ``start`` until ``last`` or the budget, the last line shown and
        whether it was cut: a first line longer than the budget is, so every answer moves the
        reading on."""
        width = max(4, len(str(last)))
        budget = self.max_chars - TAIL_RESERVE - header
        body: list[str] = []
        used = 0
        for number in range(start, last + 1):
            source = lines[number - 1]
            line = f"{number:>{width}}| {source}"
            if used + len(line) + 1 > budget:
                if not body:
                    marker = f" … [line cut: it has {len(source)} characters]"
                    body.append(line[: max(width + 2, budget - len(marker))] + marker)
                    return body, number, True
                return body, number - 1, False
            body.append(line)
            used += len(line) + 1
        return body, last, False

    def _unknown(self, where: str, summary: str) -> ToolAnswer:
        names = [entry.name for entry in self._index.repositories]
        known = self._index.files.keys() | self._index.directories
        guesses = [f"{name}/{where}" for name in names if f"{name}/{where}" in known]
        if guesses:
            hint = f" Paths start with the repository name: did you mean '{_echo(guesses[0])}'?"
        elif where.split("/", 1)[0] not in names:
            hint = " Paths start with a repository name: " + ", ".join(names) + "."
        else:
            hint = ""
        return _refused(
            "not_found",
            f"no file or directory '{_echo(where)}' in the workspace.{hint} Call list_files to "
            "see which paths exist.",
            summary,
        )

    def _directory(self, where: str) -> ToolAnswer:
        below = sum(1 for file in self._index.files.values() if _below(file.path, where))
        return _refused(
            "is_directory",
            f"'{_echo(where)}' is a directory with {_count(below, 'file', 'files')}, not a file. "
            f"Call list_files with path '{_echo(where)}' to see them.",
            f"Asked to read {_shown(where)}, which is a directory",
        )

    @staticmethod
    def _left_out(file: WorkspaceFile) -> ToolAnswer:
        why = (
            "it is too large to read"
            if file.left_out == "too_large"
            else "the workspace's limits were reached before it"
        )
        return _refused(
            "left_out",
            f"'{file.path}' exists ({file.size} bytes) but was left out of the workspace: {why}. "
            "search cannot see it either.",
            f"Asked for {_shown(file.path)}, which "
            + ("is too large to read" if file.left_out == "too_large" else "was left out"),
        )

    def search(self, pattern: str, glob: str | None = None, regex: bool = False) -> ToolAnswer:
        """Lines that contain ``pattern`` (a literal, or with ``regex`` a Python regular
        expression), as ``path:line: text``, in path order, in the files ``glob`` matches."""
        label = f"'{_shown(pattern)}'" + (" as a pattern" if regex else "")
        files_glob = (glob or "").strip() or None
        refusal = self._search_refusal(pattern, files_glob, label)
        if refusal is not None:
            return refusal
        if regex:
            compiled, code, problem = compile_pattern(pattern)
            if compiled is None:
                what = "is not valid" if code == "invalid_pattern" else "could take too long"
                return _refused(code, problem + ".", f"Searched for {label}: the pattern {what}")
            find = _regex_finder(compiled)
        else:
            find = _literal_finder(pattern)
        hits: list[str] = []
        files: set[str] = set()
        used = 0
        budget = self.max_chars - TAIL_RESERVE
        more = False
        for file in self._readable:
            if more:
                break
            if not _matches_glob(file, files_glob) or (not regex and pattern not in file.text):
                continue
            for number, line in enumerate(file.lines(), start=1):
                position = find(line)
                if position is None:
                    continue
                hit = f"{file.path}:{number}: {_excerpt(line, position)}"
                if len(hits) >= MAX_MATCHES or used + len(hit) + 1 > budget:
                    more = True
                    break
                hits.append(hit)
                files.add(file.path)
                used += len(hit) + 1
        where = f"{_shown(files_glob)} " if files_glob else ""
        if not hits:
            in_glob = f" in the files matching '{_echo(files_glob)}'" if files_glob else ""
            return ToolAnswer(
                text=f"No lines match '{_echo(pattern)}'{in_glob}.",
                summary=f"Searched {where}for {label}: no matches",
            )
        matches = len(hits)
        found = f"{_count(matches, 'match', 'matches')} in {_count(len(files), 'file', 'files')}"
        if more:
            hits.append("… more matches; narrow the pattern or glob")
        return ToolAnswer(
            text=self._fit("\n".join(hits)),
            summary=f"Searched {where}for {label}: {found}" + (" (more not shown)" if more else ""),
            matches=matches,
            entries=len(files),
            truncated=more,
        )

    @staticmethod
    def _search_refusal(pattern: str, files_glob: str | None, label: str) -> ToolAnswer | None:
        if not pattern:
            return _refused(
                "invalid_arguments",
                "search needs a pattern that is not empty.",
                "Searched for an empty pattern",
            )
        if len(pattern) > MAX_PATTERN_CHARS:
            return _refused(
                "invalid_pattern",
                f"the pattern is {len(pattern)} characters; at most {MAX_PATTERN_CHARS} are "
                "allowed.",
                f"Searched for a pattern of {len(pattern)} characters, which is too long",
            )
        if files_glob is not None and len(files_glob) > MAX_PATTERN_CHARS:
            return _refused(
                "invalid_glob",
                f"the glob is {len(files_glob)} characters; at most {MAX_PATTERN_CHARS} are "
                "allowed.",
                f"Searched for {label} with a glob of {len(files_glob)} characters, too long",
            )
        return None


def _left_out_mark(file: WorkspaceFile) -> str:
    if file.left_out is None:
        return ""
    return "  (left out: too large to read)" if file.left_out == "too_large" else "  (left out)"


def _literal_finder(pattern: str) -> Callable[[str], int | None]:
    def find(line: str) -> int | None:
        position = line.find(pattern)
        return None if position < 0 else position

    return find


def _regex_finder(compiled: re.Pattern[str]) -> Callable[[str], int | None]:
    def find(line: str) -> int | None:
        match = compiled.search(line, 0, MAX_SEARCH_LINE_CHARS)
        return None if match is None else match.start()

    return find
