"""The repository workspace: what the model can list, read and search in a run's commits.

Archives are built in memory. A GitHub tarball wraps its files in ``<owner>-<repo>-<sha>/`` and a
mirror archive in ``snapshot/``; the workspace reads both alike and shows every path as
``<repository>/<path>``.
"""

from __future__ import annotations

import gzip
import io
import json
import tarfile

import pytest
from pydantic import JsonValue

from app.services.repo_workspace import (
    TOOL_DEFINITIONS,
    RepositoryWorkspace,
    ToolAnswer,
    WorkspaceLimits,
    WorkspaceSource,
)
from app.services.repo_workspace_tools import PARAMETERS, SIGNATURES, repeats_repetition

SHA = "abc123def456abc123def456abc123def456abcd"
MIRROR_SHA = "fedcba9876543210fedcba9876543210fedcba98"
DASH = "\u2013"

APP = {
    "README.md": b"# App\n\nRun it with make.\n",
    "docs/guide.md": b"# Guide\n\nInstall the app, then run it.\n",
    "src/app/main.py": b"def main():\n    return helper()\n",
    "src/app/util.py": b"def helper():\n    return 1\n",
    "node_modules/left-pad/index.js": b"module.exports = helper\n",
    "package-lock.json": b'{"helper": 1}\n',
    "assets/logo.png": b"\x89PNG helper",
    "data/blob.dat": b"helper\x00\x01\x02",
}
SITE = {"index.md": b"# Site\n\nWelcome to the helper site.\n", "pages/about.md": b"About us\n"}


def _tarball(files: dict[str, bytes], *, prefix: str = f"acme-app-{SHA}") -> bytes:
    """A gzip tarball of ``files`` below ``prefix``; the same files always give the same bytes."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        top = tarfile.TarInfo(prefix)
        top.type = tarfile.DIRTYPE
        archive.addfile(top)
        for path, payload in files.items():
            info = tarfile.TarInfo(f"{prefix}/{path}")
            info.size = len(payload)
            info.mtime = 0
            archive.addfile(info, io.BytesIO(payload))
    return gzip.compress(buffer.getvalue(), mtime=0)


def _workspace(
    *, max_chars: int = 60_000, limits: WorkspaceLimits | None = None
) -> RepositoryWorkspace:
    return RepositoryWorkspace(
        [
            WorkspaceSource("app", SHA, _tarball(APP)),
            WorkspaceSource("site", MIRROR_SHA, _tarball(SITE, prefix="snapshot")),
        ],
        max_chars=max_chars,
        limits=limits,
    )


def _one(
    files: dict[str, bytes], *, max_chars: int = 60_000, limits: WorkspaceLimits | None = None
) -> RepositoryWorkspace:
    source = WorkspaceSource("app", SHA, _tarball(files))
    return RepositoryWorkspace([source], max_chars=max_chars, limits=limits)


def _paths(answer: ToolAnswer) -> list[str]:
    return [line.split("  ")[0] for line in answer.text.splitlines()]


def _size(files: dict[str, bytes], *paths: str) -> int:
    return sum(len(files[path]) for path in paths)


# --- what the workspace holds -------------------------------------------------------------------


def test_two_repositories_appear_under_their_names_whatever_wraps_the_archive() -> None:
    workspace = _workspace()
    listing = workspace.list_files()
    assert listing.text.splitlines() == [
        f"app/README.md  {len(APP['README.md'])}",
        f"app/docs/guide.md  {len(APP['docs/guide.md'])}",
        f"app/src/app/main.py  {len(APP['src/app/main.py'])}",
        f"app/src/app/util.py  {len(APP['src/app/util.py'])}",
        f"site/index.md  {len(SITE['index.md'])}",
        f"site/pages/about.md  {len(SITE['pages/about.md'])}",
    ]
    assert (listing.entries, listing.truncated, listing.error) == (6, False, None)
    app_bytes = _size(APP, "README.md", "docs/guide.md", "src/app/main.py", "src/app/util.py")
    assert [
        (entry.name, entry.commit_sha, entry.files, entry.bytes, entry.left_out, entry.error)
        for entry in workspace.manifest()
    ] == [
        ("app", SHA, 4, app_bytes, 0, None),
        ("site", MIRROR_SHA, 2, _size(SITE, "index.md", "pages/about.md"), 0, None),
    ]
    assert workspace.describe().splitlines() == [
        f"app @ {SHA}: 4 files, {app_bytes} bytes of text",
        "  top level: README.md, docs/ (1 file), src/ (2 files)",
        f"site @ {MIRROR_SHA}: 2 files, {_size(SITE, 'index.md', 'pages/about.md')} bytes of text",
        "  top level: index.md, pages/ (1 file)",
    ]


@pytest.mark.parametrize(
    "hidden",
    [
        "app/node_modules/left-pad/index.js",
        "app/package-lock.json",
        "app/assets/logo.png",
        "app/data/blob.dat",
    ],
)
def test_noise_and_binary_files_are_invisible(hidden: str) -> None:
    workspace = _workspace()
    assert hidden not in workspace.list_files().text
    assert workspace.read_file(hidden).error == "not_found"
    assert hidden not in workspace.search("helper").text


def test_the_link_globs_choose_what_the_workspace_holds() -> None:
    source = WorkspaceSource(
        "app", SHA, _tarball(APP), focus=("src/*", "README.md"), exclude=("src/app/util.py",)
    )
    workspace = RepositoryWorkspace([source])
    assert _paths(workspace.list_files()) == ["app/README.md", "app/src/app/main.py"]
    assert workspace.search("helper").text == "app/src/app/main.py:2: return helper()"


def test_repositories_that_share_a_name_get_distinct_paths() -> None:
    workspace = RepositoryWorkspace(
        [
            WorkspaceSource("app", SHA, _tarball(SITE)),
            WorkspaceSource("app", MIRROR_SHA, _tarball(SITE, prefix="snapshot")),
            WorkspaceSource(" we/b ", SHA, _tarball(SITE)),
        ]
    )
    assert [entry.name for entry in workspace.manifest()] == ["app", "app-2", "we-b"]
    assert "app-2/index.md" in _paths(workspace.list_files())


@pytest.mark.parametrize(
    "archive", [b"not a tarball", _tarball(SITE)[:40]], ids=["garbage", "truncated"]
)
def test_an_unreadable_archive_is_a_manifest_error_and_the_rest_still_reads(archive: bytes) -> None:
    workspace = RepositoryWorkspace(
        [
            WorkspaceSource("broken", SHA, archive),
            WorkspaceSource("site", MIRROR_SHA, _tarball(SITE, prefix="snapshot")),
        ]
    )
    broken, site = workspace.manifest()
    assert (broken.error, broken.files, broken.bytes) == ("malformed_archive", 0, 0)
    assert (site.error, site.files) == (None, 2)
    assert _paths(workspace.list_files()) == ["site/index.md", "site/pages/about.md"]
    assert (
        workspace.describe().splitlines()[0] == f"broken @ {SHA}: not readable (malformed_archive)"
    )


def test_the_bounds_leave_files_out_visibly_and_later_files_still_come() -> None:
    files = {
        "README.md": b"# App\n",
        "docs/a.md": b"a\n",
        "docs/big.md": b"b" * 30 + b"\n",
        "docs/c.md": b"c\n",
        "src/huge.py": b"z" * 100,
        "src/d.py": b"d\n",
    }
    # Priority order: README.md, docs/a.md, docs/big.md, docs/c.md, src/d.py, src/huge.py.
    workspace = _one(files, limits=WorkspaceLimits(files=3, text_bytes=20, file_bytes=50))
    assert workspace.list_files().text.splitlines() == [
        "app/README.md  6",
        "app/docs/a.md  2",
        "app/docs/big.md  31  (left out)",
        "app/docs/c.md  2",
        "app/src/d.py  2  (left out)",
        "app/src/huge.py  100  (left out: too large to read)",
    ]
    (manifest,) = workspace.manifest()
    assert (manifest.files, manifest.bytes, manifest.left_out) == (3, 10, 3)
    assert "  3 files were left out" in workspace.describe()
    too_large = workspace.read_file("app/src/huge.py")
    assert too_large.error == "left_out"
    assert too_large.text.startswith("Error: 'app/src/huge.py' exists (100 bytes) but was left out")
    assert too_large.summary == "Asked for app/src/huge.py, which is too large to read"
    assert workspace.read_file("app/docs/big.md").summary == (
        "Asked for app/docs/big.md, which was left out"
    )
    assert workspace.search("b").matches == 0


def test_left_out_files_are_listed_up_to_a_bound() -> None:
    files = {"README.md": b"# App\n", "docs/a.md": b"a\n", "docs/b.md": b"b\n"}
    workspace = _one(files, limits=WorkspaceLimits(files=1, left_out_listed=1))
    assert _paths(workspace.list_files()) == ["app/README.md", "app/docs/a.md"]
    assert workspace.manifest()[0].left_out == 2


# --- list_files ---------------------------------------------------------------------------------


def test_list_files_below_a_directory_and_through_a_glob() -> None:
    workspace = _workspace()
    source = ["app/src/app/main.py", "app/src/app/util.py"]
    assert _paths(workspace.list_files("app/src")) == source
    assert _paths(workspace.list_files("./app/src/")) == source
    assert _paths(workspace.list_files("app\\src")) == source
    # ``*`` matches ``/`` too, and a glob may leave out the repository name.
    assert _paths(workspace.list_files(glob="*.md")) == [
        "app/README.md",
        "app/docs/guide.md",
        "site/index.md",
        "site/pages/about.md",
    ]
    assert _paths(workspace.list_files(glob="src/*.py")) == source
    assert _paths(workspace.list_files(glob="app/src/*/main.py")) == ["app/src/app/main.py"]
    assert _paths(workspace.list_files("site", "*.md")) == ["site/index.md", "site/pages/about.md"]
    assert _paths(workspace.list_files("app/README.md")) == ["app/README.md"]
    assert workspace.list_files("", "").entries == 6


def test_list_files_answers_what_it_cannot_list() -> None:
    workspace = _workspace()
    assert workspace.list_files(glob="*.rs").text == "No files match the glob '*.rs'."
    assert workspace.list_files("app/src", "*.rs").text == (
        "No files below 'app/src' match the glob '*.rs'."
    )
    nowhere = workspace.list_files("app/nowhere")
    assert nowhere.error == "not_found"
    assert nowhere.text == (
        "Error: no file or directory 'app/nowhere' in the workspace. Call list_files to see "
        "which paths exist."
    )
    assert "did you mean 'app/src'?" in workspace.list_files("src").text
    assert "Paths start with a repository name: app, site." in workspace.list_files("lib").text
    assert workspace.list_files(glob="*" * 201).error == "invalid_glob"


def test_a_listing_stops_at_a_thousand_entries_and_counts_the_rest() -> None:
    workspace = _one({f"src/m{index:04d}.py": b"x = 1\n" for index in range(1_050)})
    answer = workspace.list_files()
    lines = answer.text.splitlines()
    assert len(lines) == 1_001
    assert lines[0] == "app/src/m0000.py  6"
    assert lines[999] == "app/src/m0999.py  6"
    assert lines[-1] == "… 50 more; narrow path or glob"
    assert answer.summary == "Listed every file (1050 files, first 1000 shown)"
    assert (answer.entries, answer.truncated) == (1_050, True)


def test_a_listing_also_stops_at_the_character_bound() -> None:
    workspace = _one({f"src/m{index:04d}.py": b"x = 1\n" for index in range(200)}, max_chars=1_000)
    answer = workspace.list_files()
    assert len(answer.text) <= 1_000
    shown = len(answer.text.splitlines()) - 1
    assert answer.text.splitlines()[-1] == f"… {200 - shown} more; narrow path or glob"


# --- read_file ----------------------------------------------------------------------------------

NUMBERED = "".join(f"line {number}\n" for number in range(1, 31)).encode()


def test_read_file_numbers_the_lines_of_the_range() -> None:
    workspace = _one({"notes.txt": NUMBERED})
    answer = workspace.read_file("app/notes.txt", 3, 5)
    assert answer.text.splitlines() == [
        "app/notes.txt  lines 3-5 of 30",
        "   3| line 3",
        "   4| line 4",
        "   5| line 5",
    ]
    assert answer.summary == f"Read app/notes.txt, lines 3{DASH}5 of 30"
    assert (answer.files_read, answer.lines, answer.truncated) == (
        ("app/notes.txt",),
        (3, 5),
        False,
    )
    whole = workspace.read_file("app/notes.txt")
    assert whole.text.splitlines()[-1] == "  30| line 30"
    assert whole.lines == (1, 30)
    assert workspace.read_file("app/notes.txt", 29, 99).lines == (29, 30)


def test_line_endings_and_a_missing_final_newline_number_like_an_editor() -> None:
    workspace = _one(
        {"crlf.txt": b"one\r\ntwo\r\n", "open.txt": b"one\ntwo", "latin.txt": b"Malm\xf6\n"}
    )
    assert workspace.read_file("app/crlf.txt").text.splitlines()[1:] == ["   1| one", "   2| two"]
    assert workspace.read_file("app/open.txt").lines == (1, 2)
    assert workspace.read_file("app/latin.txt").text.splitlines()[1] == "   1| Malm\ufffd"


def test_a_long_read_comes_in_parts_that_continue_where_the_last_stopped() -> None:
    content = "".join(f"{'x' * 90} {number}\n" for number in range(1, 101)).encode()
    workspace = _one({"big.txt": content}, max_chars=2_000)
    seen: list[int] = []
    start = 1
    while True:
        answer = workspace.answer("read_file", {"path": "app/big.txt", "start_line": start})
        assert len(answer.text) <= 2_000
        lines = answer.text.splitlines()
        seen += [int(line.split("|", 1)[0]) for line in lines[1:] if "|" in line]
        if not lines[-1].startswith("… file continues"):
            assert answer.summary == f"Read app/big.txt, lines {start}{DASH}100 of 100"
            break
        assert answer.truncated
        follow = int(lines[-1].rsplit("=", 1)[1])
        assert lines[-1] == f"… file continues; call read_file with start_line={follow}"
        assert (
            answer.summary
            == f"Read app/big.txt, lines {start}{DASH}{follow - 1} of 100 (continues)"
        )
        start = follow
    assert seen == list(range(1, 101))


def test_a_line_longer_than_the_bound_is_cut_and_the_reading_moves_on() -> None:
    workspace = _one({"min.js": b"short\n" + b"y" * 5_000 + b"\nafter\n"}, max_chars=1_000)
    first = workspace.read_file("app/min.js")
    assert first.text.splitlines()[1:] == [
        "   1| short",
        "… file continues; call read_file with start_line=2",
    ]
    cut = workspace.read_file("app/min.js", 2)
    lines = cut.text.splitlines()
    assert lines[1].startswith("   2| yyyy")
    assert lines[1].endswith("… [line cut: it has 5000 characters]")
    assert lines[-1] == "… file continues; call read_file with start_line=3"
    assert len(cut.text) <= 1_000
    assert (cut.lines, cut.truncated) == ((2, 2), True)


def test_read_file_answers_what_it_cannot_read() -> None:
    workspace = _workspace()
    missing = workspace.read_file("app/docs/missing.md")
    assert missing.error == "not_found"
    assert missing.text.startswith("Error: no file or directory 'app/docs/missing.md'")
    assert missing.text.endswith("Call list_files to see which paths exist.")
    assert "did you mean 'app/docs/guide.md'?" in workspace.read_file("docs/guide.md").text
    assert "app, site." in workspace.read_file("other/x.md").text
    directory = workspace.read_file("app/src/")
    assert directory.error == "is_directory"
    assert directory.text == (
        "Error: 'app/src' is a directory with 2 files, not a file. Call list_files with path "
        "'app/src' to see them."
    )
    for start, end in ((10, None), (0, None), (3, 2)):
        assert workspace.read_file("app/README.md", start, end).error == "line_range"
    assert workspace.read_file("  ").error == "invalid_arguments"


# --- search -------------------------------------------------------------------------------------


def test_search_finds_literal_lines_with_their_paths_and_numbers() -> None:
    workspace = _workspace()
    answer = workspace.search("helper")
    assert answer.text.splitlines() == [
        "app/src/app/main.py:2: return helper()",
        "app/src/app/util.py:1: def helper():",
        "site/index.md:3: Welcome to the helper site.",
    ]
    assert (answer.matches, answer.entries, answer.truncated) == (3, 3, False)
    assert workspace.search("helper", glob="*.md").text == (
        "site/index.md:3: Welcome to the helper site."
    )
    # Literal: the characters of a regular expression mean themselves, and case counts.
    assert workspace.search("helper():").text == "app/src/app/util.py:1: def helper():"
    assert workspace.search("HELPER").text == "No lines match 'HELPER'."
    assert workspace.search("HELPER", glob="*.md").text == (
        "No lines match 'HELPER' in the files matching '*.md'."
    )


def test_search_with_a_regular_expression() -> None:
    workspace = _workspace()
    assert workspace.search(r"def \w+\(\)", regex=True).text.splitlines() == [
        "app/src/app/main.py:1: def main():",
        "app/src/app/util.py:1: def helper():",
    ]
    assert workspace.search("(?i)HELPER", glob="site/*", regex=True).matches == 1
    assert workspace.search("^About", regex=True).text == "site/pages/about.md:1: About us"


def test_search_stops_at_two_hundred_matches() -> None:
    content = "".join(f"todo {number}\n" for number in range(150)).encode()
    answer = _one({"a.txt": content, "b.txt": content}).search("todo")
    lines = answer.text.splitlines()
    assert len(lines) == 201
    assert lines[199] == "app/b.txt:50: todo 49"
    assert lines[-1] == "… more matches; narrow the pattern or glob"
    assert answer.summary == "Searched for 'todo': 200 matches in 2 files (more not shown)"
    assert (answer.matches, answer.entries, answer.truncated) == (200, 2, True)


def test_a_bad_or_costly_pattern_is_an_answer() -> None:
    workspace = _workspace()
    bad = workspace.search("foo(", regex=True)
    assert bad.error == "invalid_pattern"
    assert bad.text.startswith("Error: invalid regular expression: missing ), unterminated")
    costly = workspace.search("(a+)+$", regex=True)
    assert costly.error == "costly_pattern"
    assert "nested repetition" in costly.text
    assert workspace.search("x" * 201).error == "invalid_pattern"
    assert workspace.search("x" * 200).error is None
    assert workspace.search("").error == "invalid_arguments"
    assert workspace.search("helper", glob="*" * 201).error == "invalid_glob"
    # Literal search takes the same text as plain characters.
    assert workspace.search("(a+)+$").error is None


@pytest.mark.parametrize(
    ("pattern", "repeats"),
    [
        ("(a+)+", True),
        (r"(\w*\s)*", True),
        ("(?:x{2,}){3}", True),
        ("((ab)*c)+", True),
        ("(a|b)+", False),
        ("a+b+", False),
        (r"(\+)+", False),
        ("[+*]+", False),
        ("([)*])+", False),
        ("(ab){2}", False),
        ("(a{2})", False),
        (r"\(a+\)+", False),
        (r"def \w+\(\)", False),
    ],
)
def test_repeats_repetition(pattern: str, repeats: bool) -> None:
    assert repeats_repetition(pattern) is repeats


def test_long_lines_are_searched_safely_and_shown_around_the_match() -> None:
    line = "a" * 2_500 + " needle " + "b" * 500
    workspace = _one({"min.js": line.encode() + b"\n"})
    shown = workspace.search("needle").text.split(": ", 1)[1]
    assert "needle" in shown
    assert shown.startswith("…") and shown.endswith("…")
    assert len(shown) <= 302
    # A regular expression only reads the first 2 000 characters of a line.
    assert workspace.search("needle", regex=True).matches == 0
    head = workspace.search("^a{10}", regex=True).text.split(": ", 1)[1]
    assert head == "a" * 300 + "…"


# --- the dispatcher and the definitions ---------------------------------------------------------


def test_the_dispatcher_runs_each_tool_from_its_arguments() -> None:
    workspace = _workspace()
    assert workspace.answer("list_files", {}).entries == 6
    assert workspace.answer("list_files", None).entries == 6
    assert workspace.answer("list_files", "").entries == 6
    assert workspace.answer("list_files", {"path": "site", "glob": None}).entries == 2
    assert workspace.answer("read_file", {"path": "app/README.md", "start_line": 3}).lines == (3, 3)
    assert workspace.answer("read_file", '{"path": "app/README.md", "end_line": "2"}').lines == (
        1,
        2,
    )
    assert workspace.answer("read_file", {"path": "app/README.md", "start_line": 2.0}).lines == (
        2,
        3,
    )
    assert workspace.answer("search", {"pattern": r"def \w+", "regex": "true"}).matches == 2
    assert workspace.answer(" search ", {"pattern": "helper", "regex": False}).matches == 3


@pytest.mark.parametrize(
    ("tool", "arguments", "detail", "summary"),
    [
        ("read_file", {}, "path is required", "Called read_file without a path"),
        ("search", {"glob": "*.md"}, "pattern is required", "Called search without a pattern"),
        (
            "read_file",
            {"path": 7},
            "path must be a string",
            "Called read_file with a path that is not text",
        ),
        (
            "read_file",
            {"path": "app/README.md", "start_line": "two"},
            "start_line must be an integer",
            "Called read_file with a start_line that is not a whole number",
        ),
        (
            "read_file",
            {"path": "app/README.md", "end_line": True},
            "end_line must be an integer",
            "Called read_file with an end_line that is not a whole number",
        ),
        (
            "search",
            {"pattern": "x", "regex": "yes"},
            "regex must be true or false",
            "Called search with a regex that is not true or false",
        ),
        (
            "list_files",
            {"depth": 2},
            "unknown argument depth; it takes path, glob",
            "Called list_files with an unknown argument depth",
        ),
        (
            "list_files",
            [1, 2],
            "the arguments must be a JSON object",
            "Called list_files with arguments that are not a JSON object",
        ),
        (
            "search",
            "not json",
            "the arguments must be a JSON object",
            "Called search with arguments that are not a JSON object",
        ),
    ],
)
def test_the_dispatcher_answers_a_bad_call_with_what_to_send(
    tool: str, arguments: JsonValue, detail: str, summary: str
) -> None:
    answer = _workspace().answer(tool, arguments)
    assert answer.error == "invalid_arguments"
    assert answer.text == (
        f"Error: invalid arguments for {tool}: {detail}. Call it as {SIGNATURES[tool]}."
    )
    assert answer.summary == summary


def test_an_unknown_tool_is_an_answer() -> None:
    answer = _workspace().answer("write_file", {"path": "x"})
    assert answer.error == "unknown_tool"
    assert answer.text == (
        "Error: there is no tool 'write_file'; the tools are list_files, read_file, search."
    )


JSON_TYPES = frozenset({"string", "integer", "boolean", "number", "object", "array"})


def test_the_tool_definitions_are_functions_with_json_schema_parameters() -> None:
    assert json.loads(json.dumps(TOOL_DEFINITIONS)) == list(TOOL_DEFINITIONS)
    names: list[str] = []
    for definition in TOOL_DEFINITIONS:
        assert set(definition) == {"type", "function"}
        assert definition["type"] == "function"
        function = definition["function"]
        assert isinstance(function, dict)
        assert set(function) == {"name", "description", "parameters"}
        name, description, parameters = (
            function["name"],
            function["description"],
            function["parameters"],
        )
        assert isinstance(name, str)
        assert isinstance(description, str)
        assert 0 < len(description) <= 400
        assert isinstance(parameters, dict)
        assert parameters["type"] == "object"
        assert parameters["additionalProperties"] is False
        properties = parameters["properties"]
        required = parameters["required"]
        assert isinstance(properties, dict)
        assert isinstance(required, list)
        assert all(isinstance(field, str) and field in properties for field in required)
        for schema in properties.values():
            assert isinstance(schema, dict)
            assert schema["type"] in JSON_TYPES
            assert isinstance(schema["description"], str)
        # What the schema offers is exactly what the dispatcher takes.
        assert tuple(properties) == PARAMETERS[name]
        names.append(name)
    assert names == ["list_files", "read_file", "search"]


# --- what a person and the trace see ------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "arguments", "summary"),
    [
        ("list_files", {}, "Listed every file (6 files)"),
        ("list_files", {"path": "app/docs"}, "Listed app/docs/ (1 file)"),
        ("list_files", {"path": "app/README.md"}, "Listed app/README.md (1 file)"),
        ("list_files", {"glob": "*.md"}, "Listed files matching *.md (4 files)"),
        (
            "list_files",
            {"path": "site", "glob": "*.md"},
            "Listed files matching *.md in site/ (2 files)",
        ),
        ("list_files", {"glob": "*.rs"}, "Listed files matching *.rs (no files)"),
        ("list_files", {"path": "app/nowhere"}, "Asked to list app/nowhere, which does not exist"),
        (
            "list_files",
            {"glob": "*" * 201},
            "Listed files with a glob of 201 characters, which is too long",
        ),
        ("read_file", {"path": "app/README.md"}, f"Read app/README.md, lines 1{DASH}3 of 3"),
        (
            "read_file",
            {"path": "app/README.md", "start_line": 2, "end_line": 2},
            f"Read app/README.md, lines 2{DASH}2 of 3",
        ),
        (
            "read_file",
            {"path": "app/docs/missing.md"},
            "Asked for app/docs/missing.md, which does not exist",
        ),
        ("read_file", {"path": "app/docs"}, "Asked to read app/docs, which is a directory"),
        (
            "read_file",
            {"path": "app/README.md", "start_line": 9},
            "Asked for app/README.md from line 9, but it has 3 lines",
        ),
        (
            "read_file",
            {"path": "app/README.md", "start_line": 3, "end_line": 1},
            "Asked for app/README.md with an invalid line range",
        ),
        ("read_file", {"path": "/"}, "Called read_file without a path"),
        ("search", {"pattern": "helper"}, "Searched for 'helper': 3 matches in 3 files"),
        (
            "search",
            {"pattern": "helper", "glob": "*.md"},
            "Searched *.md for 'helper': 1 match in 1 file",
        ),
        (
            "search",
            {"pattern": "def", "regex": True},
            "Searched for 'def' as a pattern: 2 matches in 2 files",
        ),
        (
            "search",
            {"pattern": "nothing\nlike this"},
            "Searched for 'nothing like this': no matches",
        ),
        ("search", {"pattern": "x" * 80}, f"Searched for '{'x' * 59}…': no matches"),
        (
            "search",
            {"pattern": "foo(", "regex": True},
            "Searched for 'foo(' as a pattern: the pattern is not valid",
        ),
        (
            "search",
            {"pattern": "(a+)+", "regex": True},
            "Searched for '(a+)+' as a pattern: the pattern could take too long",
        ),
        (
            "search",
            {"pattern": "x" * 201},
            "Searched for a pattern of 201 characters, which is too long",
        ),
        ("search", {"pattern": ""}, "Searched for an empty pattern"),
        (
            "search",
            {"pattern": "x", "glob": "*" * 201},
            "Searched for 'x' with a glob of 201 characters, too long",
        ),
        ("write_file", {}, "Called an unknown tool 'write_file'"),
    ],
)
def test_every_answer_says_in_one_sentence_what_it_did(
    tool: str, arguments: JsonValue, summary: str
) -> None:
    assert _workspace().answer(tool, arguments).summary == summary


def test_every_answer_fits_the_bound() -> None:
    files = {
        f"src/m{index:03d}.py": ("def f():\n" + "    return 'helper'\n" * 50).encode()
        for index in range(300)
    }
    workspace = _one(files, max_chars=1_500)
    answers = [
        workspace.list_files(),
        workspace.read_file("app/src/m000.py"),
        workspace.search("helper"),
        workspace.search("re.*per", regex=True),
        workspace.read_file("x" * 5_000),
        workspace.answer("x" * 5_000, {}),
        workspace.answer("list_files", {"x" * 5_000: 1}),
    ]
    assert all(len(answer.text) <= 1_500 for answer in answers)
    assert all(len(answer.summary) <= 200 for answer in answers)


def test_the_trace_keeps_counts_and_paths_never_the_text() -> None:
    answer = _workspace().read_file("app/README.md")
    assert answer.trace() == {
        "summary": f"Read app/README.md, lines 1{DASH}3 of 3",
        "chars": len(answer.text),
        "files_read": ["app/README.md"],
        "lines": [1, 3],
        "entries": 0,
        "matches": 0,
        "truncated": False,
        "error": None,
    }
    assert "Run it with make" not in json.dumps(answer.trace())
    assert _workspace().search("helper").trace()["matches"] == 3
