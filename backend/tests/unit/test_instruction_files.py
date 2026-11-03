"""The instruction files describe the repository as it is.

``AGENTS.md`` is read before every change, so a stale line in it is followed, not ignored. Its
layout block once listed a directory that did not exist for days. These tests hold it, and the
documents that ship with the project, to the tree:

- every directory in the layout block exists, and a ``{a,b}`` group names exactly the parts the
  parent has;
- every command in the Commands section runs a script, venv interpreter, module and path that
  exist;
- every file path ``AGENTS.md`` names in its prose exists, unless it is runtime data or a local
  working document;
- every relative link in a shipped document resolves to a file (and heading) that ships, never
  into a local working document;
- the shipped documents and the code never call the project open source, except to deny it.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Sequence
from functools import cache
from importlib.metadata import packages_distributions
from pathlib import Path
from urllib.parse import unquote

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
AGENTS_MD = REPO_ROOT / "AGENTS.md"

# Created when the application or the journeys run; git-ignored, so AGENTS.md may name them
# although a fresh checkout does not contain them.
RUNTIME_PATHS = ("data/", "frontend/e2e/.data")
# AGENTS.md names files relative to the repository, the backend, the app package or the frontend.
PATH_BASES = ("", "backend", "backend/app", "frontend")
PATH_SUFFIXES = {".py", ".json", ".ts", ".tsx", ".js", ".mjs", ".css", ".md", ".toml", ".txt"}
# Legal text: its links are checked, but it names the open-source licences a contribution may
# carry, and AGENTS.md forbids editing it without an explicit request.
LICENCE_TEXTS = ("CLA.md",)
# pnpm's own commands; anything else after `pnpm` must be a script in package.json.
PNPM_BUILTINS = {"install", "add", "remove", "exec", "dlx"}
# Words in a command line that are a subcommand rather than a path (`ruff check app`,
# `tools.deps licences`).
SUBCOMMANDS = {"check", "format", "licences", "audit"}

_FENCE = re.compile(r"^ {0,3}(```|~~~).*?^ {0,3}\1[ \t]*$", re.MULTILINE | re.DOTALL)
_INLINE_CODE = re.compile(r"(`+)(.+?)\1", re.DOTALL)
_HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$", re.MULTILINE)
_INLINE_LINK = re.compile(r"\]\(\s*<?([^\s)>]*)>?")
# `[label]: target`, but not a footnote (`[^1]: text`).
_REFERENCE_LINK = re.compile(r"^ {0,3}\[(?!\^)[^\]]+\]:\s*<?([^\s>]+)>?", re.MULTILINE)
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_OPEN_SOURCE = re.compile(r"open[\s-]*source", re.IGNORECASE)
# The two ways the documents deny it: "not open source" and AGENTS.md's own rule.
_DENIAL = re.compile(r"\b(?:not|never describe the project as)\s+open[\s-]*source", re.I)


# --- parsing ------------------------------------------------------------------------------------


def section(markdown: str, title: str) -> str:
    """The body of the ``## title`` section, up to the next second-level heading."""
    match = re.search(rf"^## {re.escape(title)}[ \t]*\n(.*?)(?=^## |\Z)", markdown, re.M | re.S)
    assert match, f"AGENTS.md has no '## {title}' section"
    return match.group(1)


def fenced_blocks(markdown: str) -> list[str]:
    return [m.group(2) for m in re.finditer(r"^```(\w*)\n(.*?)^```", markdown, re.M | re.S)]


def expand(entry: str) -> list[str]:
    """``a/{b,c}`` -> ``a/b``, ``a/c``; anything else is returned as it is."""
    match = re.fullmatch(r"(.*)\{([^{}]*)\}(.*)", entry)
    if not match:
        return [entry]
    head, choices, tail = match.groups()
    return [f"{head}{choice.strip()}{tail}" for choice in choices.split(",")]


def layout_entries(agents: str) -> tuple[list[str], list[str]]:
    """The tracked entries and the commented, untracked ones of the layout block."""
    (block,) = fenced_blocks(section(agents, "Repository layout"))
    tracked: list[str] = []
    untracked: list[str] = []
    for line in block.splitlines():
        if not line.strip() or line[0].isspace():
            continue  # blank, or the continuation of a description
        if line.startswith("#"):
            words = line.lstrip("#").split()
            if words and words[0].endswith("/"):
                untracked.append(words[0])
            continue
        tracked.append(line.split()[0])
    return tracked, untracked


def command_blocks(agents: str) -> list[tuple[str, list[str]]]:
    """``(working directory, commands)`` for each "(run from `dir/`):" block."""
    blocks: list[tuple[str, list[str]]] = []
    pattern = r"run from `([^`]+)`\)?:\s*\n+```\w*\n(.*?)^```"
    for match in re.finditer(pattern, section(agents, "Commands"), re.M | re.S):
        directory, body = match.groups()
        commands = [re.sub(r"\s+#.*$", "", line).strip() for line in body.splitlines()]
        blocks.append((directory, [command for command in commands if command]))
    return blocks


def prose(markdown: str) -> str:
    """The text a reader follows: fenced blocks and inline code removed."""
    return _INLINE_CODE.sub(" ", _FENCE.sub("", markdown))


def anchors(markdown: str) -> set[str]:
    """GitHub's heading ids: lower case, punctuation dropped, spaces to hyphens, -1 for repeats."""
    seen: dict[str, int] = {}
    for heading in _HEADING.findall(_FENCE.sub("", markdown)):
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading).strip().lower()
        slug = "".join(ch for ch in text if ch.isalnum() or ch in " -_").replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        if count:
            seen[f"{slug}-{count}"] = 1
    return set(seen)


# --- checks -------------------------------------------------------------------------------------


def _inside(path: Path, root: Path, prefixes: Sequence[str]) -> bool:
    relative = path.resolve().relative_to(root.resolve()).as_posix() + "/"
    return any(relative.startswith(prefix.rstrip("/") + "/") for prefix in prefixes)


def _parts(directory: Path) -> set[str]:
    """Child directories that hold a file; a leftover holding only bytecode does not count."""
    return {
        child.name
        for child in directory.iterdir()
        if child.is_dir()
        and not child.name.startswith(".")
        and any(f.is_file() and "__pycache__" not in f.parts for f in child.rglob("*"))
    }


def layout_problems(agents: str, root: Path) -> list[str]:
    tracked, _ = layout_entries(agents)
    problems: list[str] = []
    for entry in tracked:
        problems.extend(
            f"{path}: listed in the layout block but not a directory"
            for path in expand(entry)
            if not (root / path).is_dir()
        )
        if "{" in entry:
            head = entry.split("{")[0]
            if (root / head).is_dir():
                listed = {Path(path).name for path in expand(entry)}
                problems.extend(
                    f"{entry}: does not list {head}{name}"
                    for name in sorted(_parts(root / head) - listed)
                )
    return problems


@cache
def _distributions(module: str) -> set[str]:
    return {name.lower() for name in packages_distributions().get(module, [])}


def _requirement_names(requirements: Path) -> set[str]:
    names: set[str] = set()
    for line in requirements.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("-r "):
            names |= _requirement_names(requirements.parent / line[3:].strip())
        elif line and not line.startswith(("#", "-")):
            name = re.match(r"[A-Za-z0-9_.-]+", line)
            if name:
                names.add(re.sub(r"[-_.]+", "-", name.group(0)).lower())
    return names


def _defines(module: Path, name: str) -> bool:
    tree = ast.parse(module.read_text(encoding="utf-8"))
    return any(
        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and node.name == name
        for node in tree.body
    )


def command_problems(directory: str, command: str, root: Path = REPO_ROOT) -> list[str]:
    """Why ``command``, run from ``directory``, would not do what AGENTS.md says it does."""
    cwd = root / directory
    tokens = shlex.split(command.replace("\\", "/"))
    program, args = tokens[0], tokens[1:]
    where = f"{directory} $ {command}"
    if program == "pnpm":
        package = cwd / "package.json"
        scripts = json.loads(package.read_text(encoding="utf-8"))["scripts"]
        if not args or (args[0] not in scripts and args[0] not in PNPM_BUILTINS):
            return [f"{where}: no such script in {package.relative_to(root).as_posix()}"]
        return []
    if Path(program).name not in {"python", "python.exe"}:
        return [f"{where}: unknown program {program!r}; teach this test what it runs"]
    # normpath, not resolve(): a POSIX venv's python is a symlink to the system interpreter.
    interpreter = Path(os.path.normpath(cwd / program))
    venv = Path(os.path.normpath(root / ".venv"))
    if interpreter.parent.parent != venv or interpreter.parent.name not in {"Scripts", "bin"}:
        return [f"{where}: {program} is not the repository's .venv interpreter"]
    if len(args) < 2 or args[0] != "-m":
        return [f"{where}: expected 'python -m <module>'"]
    module, rest = args[1], args[2:]
    declared = _requirement_names(root / "backend" / "requirements-dev.txt")
    problems: list[str] = []
    # A module of this repository (`-m tools.dbgen`) runs from the directory that holds it.
    local = cwd.joinpath(*module.split("."))
    if not (local / "__main__.py").is_file() and not _distributions(module) & declared:
        problems.append(f"{where}: module {module!r} is not in requirements-dev.txt")
    for arg in rest:
        if arg.startswith("-") or arg in SUBCOMMANDS:
            continue
        if ":" in arg:
            dotted, _, attribute = arg.partition(":")
            source = cwd / (dotted.replace(".", "/") + ".py")
            if not source.is_file() or not _defines(source, attribute):
                problems.append(f"{where}: {arg} does not resolve")
        elif not (cwd / arg).exists():
            problems.append(f"{where}: {arg} does not exist in {directory}")
    return problems


def named_paths(markdown: str) -> list[str]:
    """Inline code in prose that names a file or directory of this repository."""
    names: list[str] = []
    for _, code in _INLINE_CODE.findall(_FENCE.sub("", markdown)):
        code = code.strip()
        if code.startswith("/") or not re.fullmatch(r"[\w.*/-]+", code):
            continue  # an API route, or not a path at all
        suffix = Path(code.rstrip("/")).suffix
        if suffix in PATH_SUFFIXES or ("/" in code and not suffix):
            names.append(code)
    return names


def named_path_problems(markdown: str, root: Path, local: list[str]) -> list[str]:
    problems: list[str] = []
    for name in dict.fromkeys(named_paths(markdown)):
        if name.startswith(tuple(local) + RUNTIME_PATHS):
            continue
        if not any(list((root / base).glob(name.rstrip("/"))) for base in PATH_BASES):
            problems.append(f"`{name}`: no such path in the repository, backend, app or frontend")
    return problems


def link_problems(document: Path, root: Path, local: list[str]) -> list[str]:
    """Relative links in ``document`` that do not reach a shipped file and heading."""
    document, root = document.resolve(), root.resolve()
    markdown = document.read_text(encoding="utf-8")
    text = prose(markdown)
    targets = _INLINE_LINK.findall(text) + _REFERENCE_LINK.findall(text)
    problems: list[str] = []
    for target in targets:
        if not target or _SCHEME.match(target):
            continue  # external; this test does not use the network
        path_part, _, fragment = target.partition("#")
        if path_part:
            base = root if path_part.startswith("/") else document.parent
            resolved = (base / unquote(path_part.lstrip("/"))).resolve()
        else:
            resolved = document
        if not resolved.is_relative_to(root):
            problems.append(f"{target}: points outside the repository")
        elif not resolved.exists():
            problems.append(f"{target}: no such file")
        elif _inside(resolved, root, local):
            problems.append(f"{target}: a local working document, missing for everyone else")
        elif (
            fragment
            and resolved.suffix == ".md"
            and unquote(fragment).lower() not in anchors(resolved.read_text(encoding="utf-8"))
        ):
            problems.append(f"{target}: no heading with that id")
    return problems


def licence_claims(text: str) -> list[int]:
    """Line numbers where the text calls something open source without denying it."""
    denials = [denial.span() for denial in _DENIAL.finditer(text)]
    return [
        text.count("\n", 0, match.start()) + 1
        for match in _OPEN_SOURCE.finditer(text)
        if not any(start <= match.start() < end for start, end in denials)
    ]


def shipped_documents(local: list[str]) -> list[Path]:
    names = ("README.md", "AGENTS.md", "CONTRIBUTING.md", *LICENCE_TEXTS)
    documents = [REPO_ROOT / name for name in names]
    for folder in ("docs", "public_docs"):
        documents += sorted((REPO_ROOT / folder).rglob("*.md"))
    return [document for document in documents if not _inside(document, REPO_ROOT, local)]


# --- the repository ------------------------------------------------------------------------------


AGENTS = AGENTS_MD.read_text(encoding="utf-8")
_, LOCAL = layout_entries(AGENTS)


def test_the_layout_block_matches_the_tree() -> None:
    problems = layout_problems(AGENTS, REPO_ROOT)
    assert problems == [], "update the layout block in AGENTS.md:\n" + "\n".join(problems)


def test_the_layout_block_names_the_local_working_documents() -> None:
    assert LOCAL == ["docs/decisions/", "analysis/", ".ralph/"]


COMMANDS = [(directory, line) for directory, lines in command_blocks(AGENTS) for line in lines]


@pytest.mark.parametrize(("directory", "command"), COMMANDS)
def test_every_listed_command_can_run(directory: str, command: str) -> None:
    problems = command_problems(directory, command)
    assert problems == [], "fix the Commands section of AGENTS.md:\n" + "\n".join(problems)


def test_the_commands_section_covers_backend_and_frontend() -> None:
    assert [directory for directory, _ in command_blocks(AGENTS)] == ["backend/", "frontend/"]


def test_every_path_agents_md_names_exists() -> None:
    problems = named_path_problems(AGENTS, REPO_ROOT, LOCAL)
    assert problems == [], "AGENTS.md names a path that is gone:\n" + "\n".join(problems)


@pytest.mark.parametrize(
    "document",
    shipped_documents(LOCAL),
    ids=lambda document: document.relative_to(REPO_ROOT).as_posix(),
)
def test_links_in_shipped_documents_resolve(document: Path) -> None:
    problems = link_problems(document, REPO_ROOT, LOCAL)
    assert problems == [], "broken links:\n" + "\n".join(problems)


def test_no_document_or_source_calls_the_project_open_source() -> None:
    files = [doc for doc in shipped_documents(LOCAL) if doc.name not in LICENCE_TEXTS]
    files += [p for p in (REPO_ROOT / "backend" / "app").rglob("*") if p.suffix in {".py", ".json"}]
    sources = REPO_ROOT / "frontend" / "src"
    files += [p for p in sources.rglob("*") if p.suffix in {".ts", ".tsx", ".css", ".json"}]
    files.append(REPO_ROOT / "frontend" / "index.html")
    claims = [
        f"{path.relative_to(REPO_ROOT).as_posix()}:{line}"
        for path in files
        for line in licence_claims(path.read_text(encoding="utf-8"))
    ]
    assert claims == [], "the project is source-available, not open source:\n" + "\n".join(claims)


def test_runtime_and_working_paths_are_ignored_by_git() -> None:
    git = shutil.which("git")
    if git is None or not (REPO_ROOT / ".git").exists():
        pytest.skip("not running from a Git checkout")
    for path in [*LOCAL, *RUNTIME_PATHS, ".venv/"]:
        # A file inside the directory: a directory-only pattern cannot match a path that does
        # not exist yet, but it does match everything below it.
        probe = path.rstrip("/") + "/probe"
        ignored = subprocess.run(  # noqa: S603 - git with fixed arguments
            [git, "check-ignore", "--no-index", "--quiet", probe], cwd=REPO_ROOT, check=False
        )
        assert ignored.returncode == 0, f"{path} is not git-ignored"


# --- the checks catch what they are for -----------------------------------------------------------


LAYOUT = """\
## Repository layout

```text
pkg/{alpha,beta}
docs/            notes
                 continued
# Local:
#   scratch/     never shipped
```

## Next
"""


def _tree(root: Path, *files: str) -> Path:
    for name in files:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(b"x\n")
    return root


def test_the_layout_parser_reads_groups_descriptions_and_comments() -> None:
    assert layout_entries(LAYOUT) == (["pkg/{alpha,beta}", "docs/"], ["scratch/"])
    assert expand("pkg/{alpha, beta}") == ["pkg/alpha", "pkg/beta"]


def test_the_layout_check_accepts_a_matching_tree(tmp_path: Path) -> None:
    root = _tree(tmp_path, "pkg/alpha/a.py", "pkg/beta/b.py", "docs/n.md", "pkg/old/__pycache__/x")
    assert layout_problems(LAYOUT, root) == []


def test_the_layout_check_flags_a_removed_directory(tmp_path: Path) -> None:
    root = _tree(tmp_path, "pkg/alpha/a.py", "docs/n.md")
    assert layout_problems(LAYOUT, root) == [
        "pkg/beta: listed in the layout block but not a directory"
    ]


def test_the_layout_check_flags_an_unlisted_part(tmp_path: Path) -> None:
    root = _tree(tmp_path, "pkg/alpha/a.py", "pkg/beta/b.py", "pkg/gamma/c.py", "docs/n.md")
    assert layout_problems(LAYOUT, root) == ["pkg/{alpha,beta}: does not list pkg/gamma"]


@pytest.mark.parametrize(
    ("directory", "command", "problem"),
    [
        ("frontend/", "pnpm no-such-script", "no such script"),
        ("backend/", "python -m pytest", "not the repository's .venv interpreter"),
        ("backend/", r"..\.venv\Scripts\python.exe -m no_such_module", "not in requirements"),
        ("backend/", r"..\.venv\Scripts\python.exe -m tools.no_such_tool", "not in requirements"),
        ("backend/", r"..\.venv\Scripts\python.exe -m ruff check gone", "gone does not exist"),
        ("backend/", "../.venv/bin/python -m uvicorn app.main:missing", "does not resolve"),
        ("backend/", "make test", "unknown program"),
    ],
)
def test_the_command_check_flags_a_command_that_cannot_run(
    directory: str, command: str, problem: str
) -> None:
    problems = command_problems(directory, command)
    assert len(problems) == 1 and problem in problems[0], problems


def test_the_command_check_accepts_both_venv_layouts() -> None:
    for interpreter in (r"..\.venv\Scripts\python.exe", "../.venv/bin/python"):
        assert command_problems("backend/", f"{interpreter} -m ruff check app tests") == []


def test_the_command_check_accepts_a_module_of_the_repository() -> None:
    assert command_problems("backend/", "../.venv/bin/python -m tools.dbgen --check") == []


def test_the_path_check_flags_a_missing_file_and_skips_runtime_and_local_paths() -> None:
    markdown = (
        "Use `services/agent_tools.py`, `src/lib/markdown.tsx` and `scripts/` but not "
        "`services/gone.py`; `data/registry.sqlite`, `.ralph/progress.txt` and `/api/v1` are "
        "not repository paths, and `services/connections.validate_endpoint` names a function.\n"
        "```text\nignored/inside/a/fence.py\n```\n"
    )
    assert named_path_problems(markdown, REPO_ROOT, [".ralph/"]) == [
        "`services/gone.py`: no such path in the repository, backend, app or frontend"
    ]


def test_the_link_check_flags_broken_links(tmp_path: Path) -> None:
    _tree(tmp_path, "docs/Other.md", "scratch/note.md")
    (tmp_path / "docs" / "Other.md").write_text("# Other\n\n## First sign-in (local)\n")
    document = tmp_path / "docs" / "Guide.md"
    document.write_text(
        "# Guide\n\n## Shell — differences\n\n"
        "[ok](Other.md) [ok](Other.md#first-sign-in-local) [ok](#shell--differences)\n"
        "[web](https://example.com/x.md) [mail](mailto:someone@example.com)\n"
        "`[code](not-a-link.md)`\n"
        "[a](Missing.md) [b](Other.md#nowhere) [c](#nowhere)\n"
        "[d](../scratch/note.md) [e](../../outside.md)\n"
        "[ref]: Gone.md\n",
        encoding="utf-8",
    )
    assert link_problems(document, tmp_path, ["scratch/"]) == [
        "Missing.md: no such file",
        "Other.md#nowhere: no heading with that id",
        "#nowhere: no heading with that id",
        "../scratch/note.md: a local working document, missing for everyone else",
        "../../outside.md: points outside the repository",
        "Gone.md: no such file",
    ]


def test_anchors_follow_github_slugs() -> None:
    markdown = "# Docker (recommended)\n## The `code` path\n## Repeat\n## Repeat\n```\n# no\n```\n"
    assert anchors(markdown) == {
        "docker-recommended",
        "the-code-path",
        "repeat",
        "repeat-1",
    }


@pytest.mark.parametrize(
    "text",
    [
        "Tralala is open source.",
        "An Open-Source planning tool",
        "a free, open\nsource project",
        "It is not proprietary; it is open source.",
    ],
)
def test_the_licence_check_flags_a_claim(text: str) -> None:
    assert licence_claims(text)


@pytest.mark.parametrize(
    "text",
    [
        "Tralala is **source-available, not open source**.",
        "Never describe the project as open source in release notes.",
        "This project is source-available, not\nopen source.",
        "Source code is available under PolyForm Noncommercial.",
    ],
)
def test_the_licence_check_accepts_a_denial(text: str) -> None:
    assert licence_claims(text) == []
