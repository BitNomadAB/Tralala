"""The repository workspace's three tools as the model sees them, and the checks on its calls.

``TOOL_DEFINITIONS`` are OpenAI-compatible function definitions (``{"type": "function",
"function": {"name", "description", "parameters"}}``, the parameters a JSON Schema object); the
descriptions are written for the model. ``parse_arguments`` turns what a call sent (parsed JSON, or
JSON text a model sent as a string) into ``CallArguments``, whose readers return typed values or
raise ``ArgumentError``: what was wrong, for the model and, in a few words, for a person watching
the run. ``RepositoryWorkspace.answer`` (``repo_workspace``) turns that error into an answer, so a
bad call never reaches the run as an exception.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Final

from pydantic import JsonValue

LIST_FILES: Final = "list_files"
READ_FILE: Final = "read_file"
SEARCH: Final = "search"
TOOL_NAMES: Final = frozenset({LIST_FILES, READ_FILE, SEARCH})

type JsonObject = dict[str, JsonValue]

# What each tool takes, and how an answer about a bad call names the right one.
PARAMETERS: Final[dict[str, tuple[str, ...]]] = {
    LIST_FILES: ("path", "glob"),
    READ_FILE: ("path", "start_line", "end_line"),
    SEARCH: ("pattern", "glob", "regex"),
}
SIGNATURES: Final[dict[str, str]] = {
    LIST_FILES: "list_files(path?: string, glob?: string)",
    READ_FILE: "read_file(path: string, start_line?: integer, end_line?: integer)",
    SEARCH: "search(pattern: string, glob?: string, regex?: boolean)",
}
_WHOLE_NUMBER = re.compile(r"-?[0-9]+")
_GLOB_HELP = "'*' also matches '/', and the repository name may be left out"
# A search pattern and a glob are at most this long; the search definition says so to the model.
MAX_PATTERN_CHARS: Final = 200
_COUNTED = re.compile(r"\{(?:[0-9]+,?[0-9]*|,[0-9]+)\}")

TOOL_DEFINITIONS: Final[tuple[JsonObject, ...]] = (
    {
        "type": "function",
        "function": {
            "name": LIST_FILES,
            "description": (
                "List the files of the board's repositories with their size in bytes, sorted by "
                "path. Every path starts with the repository name: '<repository>/<path>'. Build "
                "output, dependencies, lock files, binary and empty files are never listed; a file "
                "marked 'left out' exists but cannot be read."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Directory to list, e.g. 'myrepo/docs'. Empty lists every repository."
                        ),
                    },
                    "glob": {
                        "type": "string",
                        "description": (
                            f"Only paths matching this glob, e.g. '*.md' or 'src/*test*'; "
                            f"{_GLOB_HELP}."
                        ),
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": READ_FILE,
            "description": (
                "Read a text file with line numbers. A long file comes in parts: the answer then "
                "ends with the start_line to continue from."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The file's path as list_files shows it.",
                    },
                    "start_line": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "First line to return; 1 is the first line (default).",
                    },
                    "end_line": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Last line to return, inclusive (default: as far as fits).",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": SEARCH,
            "description": (
                "Find the lines that contain a pattern in every readable file, answered as "
                "'path:line: text', at most 200 matches. The pattern is literal and "
                "case-sensitive unless regex is true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_PATTERN_CHARS,
                        "description": (
                            "The text to find. With regex, a Python regular expression; "
                            "(?i) makes it case-insensitive."
                        ),
                    },
                    "glob": {
                        "type": "string",
                        "description": (
                            f"Only search files matching this glob, e.g. '*.py'; {_GLOB_HELP}."
                        ),
                    },
                    "regex": {
                        "type": "boolean",
                        "description": "Treat the pattern as a regular expression (default false).",
                    },
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
        },
    },
)


def _a(name: str) -> str:
    return ("an " if name[:1] in {"a", "e", "i", "o", "u"} else "a ") + name


class ArgumentError(Exception):
    """A call the tool cannot run: ``detail`` for the model, ``summary`` the words that end
    "Called <tool> …" for a person, and the tool's signature."""

    def __init__(self, tool: str, detail: str, summary: str) -> None:
        super().__init__(detail)
        self.detail = detail
        self.summary = summary
        self.signature = SIGNATURES[tool]


@dataclass(frozen=True, slots=True)
class CallArguments:
    """One call's arguments, known names only; a JSON ``null`` counts as left out."""

    tool: str
    values: JsonObject

    def string(self, name: str, *, required: bool = False) -> str | None:
        value = self.values.get(name)
        if value is None:
            if required:
                raise ArgumentError(self.tool, f"{name} is required", f"without {_a(name)}")
            return None
        if not isinstance(value, str):
            raise ArgumentError(
                self.tool, f"{name} must be a string", f"with {_a(name)} that is not text"
            )
        return value

    def integer(self, name: str) -> int | None:
        """A whole number; ``12.0`` and ``"12"`` are read as 12, ``true`` is not a number."""
        value = self.values.get(name)
        if value is None:
            return None
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and _WHOLE_NUMBER.fullmatch(value.strip()):
            return int(value.strip())
        raise ArgumentError(
            self.tool, f"{name} must be an integer", f"with {_a(name)} that is not a whole number"
        )

    def flag(self, name: str) -> bool | None:
        """A boolean; the strings ``"true"`` and ``"false"`` are read as one."""
        value = self.values.get(name)
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
            return value.strip().lower() == "true"
        raise ArgumentError(
            self.tool, f"{name} must be true or false", f"with {_a(name)} that is not true or false"
        )


def parse_arguments(tool: str, arguments: JsonValue) -> CallArguments:
    """A call's arguments as an object of the tool's known names, or an ``ArgumentError``."""
    value: JsonValue = arguments
    if isinstance(value, str):
        # Some models send the arguments as JSON text inside the JSON: read it once more.
        source = value.strip()
        try:
            value = json.loads(source) if source else None
        except ValueError:
            value = source
    if value is None:
        return CallArguments(tool, {})
    if not isinstance(value, dict):
        raise ArgumentError(
            tool,
            "the arguments must be a JSON object",
            "with arguments that are not a JSON object",
        )
    unknown = sorted(set(value) - set(PARAMETERS[tool]))
    if unknown:
        listed = ", ".join(name[:60] for name in unknown[:10])
        raise ArgumentError(
            tool,
            f"unknown argument {listed}; it takes {', '.join(PARAMETERS[tool])}",
            f"with an unknown argument {unknown[0][:60]}",
        )
    return CallArguments(tool, {key: item for key, item in value.items() if item is not None})


# --- regular expressions ---------------------------------------------------------------------


def _quantifier(pattern: str, index: int) -> int:
    """The length of a repetition (``*``, ``+``, ``{m,n}``) starting at ``index``, else 0."""
    if index >= len(pattern):
        return 0
    if pattern[index] in "*+":
        return 1
    counted = _COUNTED.match(pattern, index)
    return 0 if counted is None else len(counted.group(0))


def _class_end(pattern: str, start: int) -> int:
    """The index just past the character class that opens at ``start``."""
    index = start + 1
    if index < len(pattern) and pattern[index] == "^":
        index += 1
    if index < len(pattern) and pattern[index] == "]":
        index += 1
    while index < len(pattern) and pattern[index] != "]":
        index += 2 if pattern[index] == "\\" else 1
    return index + 1


def repeats_repetition(pattern: str) -> bool:
    """Whether a repeated group repeats something itself: ``(a+)+``, ``(\\w*\\s)*``,
    ``(?:x{2,}){3}``. That is the shape that makes a backtracking engine take exponential time;
    an escaped bracket or a character class (``[+*]``) is not a repetition."""
    groups = [False]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 2
        elif char == "[":
            index = _class_end(pattern, index)
        elif char == "(":
            groups.append(False)
            index += 1
        elif char == ")" and len(groups) > 1:
            inner = groups.pop()
            repeated = _quantifier(pattern, index + 1)
            if inner and repeated:
                return True
            groups[-1] = groups[-1] or inner or bool(repeated)
            index += 1 + repeated
        else:
            repeated = _quantifier(pattern, index)
            groups[-1] = groups[-1] or bool(repeated)
            index += repeated or 1
    return False


def compile_pattern(pattern: str) -> tuple[re.Pattern[str] | None, str, str]:
    """The compiled regular expression, or ``None`` with an error code (``invalid_pattern``,
    ``costly_pattern``) and what to tell the model."""
    try:
        compiled = re.compile(pattern)
    except (re.error, OverflowError, RecursionError) as exc:
        return None, "invalid_pattern", f"invalid regular expression: {exc}"
    if repeats_repetition(pattern):
        return (
            None,
            "costly_pattern",
            "the regular expression repeats a group that itself repeats (like (a+)+), which can "
            "take exponential time; rewrite it without the nested repetition",
        )
    return compiled, "", ""
