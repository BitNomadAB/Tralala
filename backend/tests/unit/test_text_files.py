"""Text files keep LF line endings and carry no byte-order mark, on every platform.

Two guards live here:

- Every text-mode file write in ``app/`` states its newline handling. On Windows a text-mode write
  turns each ``"\\n"`` into ``"\\r\\n"``; passing ``newline=""`` (or writing bytes) keeps exactly
  what the code wrote, so a file produced on Windows is byte-identical to one produced on Linux.
- Every file tracked by Git is stored with LF line endings and starts without a UTF-8 BOM.
  ``.gitattributes`` normalises line endings on ``git add`` but leaves a BOM alone, and a file Git
  took for binary is not normalised at all.
"""

from __future__ import annotations

import ast
import codecs
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.security import write_private_file

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"
REPO_ROOT = BACKEND_ROOT.parent

# A string that is a file mode for open(); tarfile's "w:gz" and file names are not.
_FILE_MODE = re.compile(r"[rwxabt+]+")
# Callables whose mode is the second positional argument; for any other `.open(...)` and for the
# tempfile constructors it is the first.
_MODE_SECOND = {"open", "io.open", "codecs.open", "os.fdopen"}
_TEMPFILES = {"TemporaryFile", "NamedTemporaryFile", "SpooledTemporaryFile"}


def _dotted(func: ast.expr) -> str:
    parts: list[str] = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    # `Path(p).open` must not read as the builtin `open`, so an expression base keeps a placeholder.
    parts.append(func.id if isinstance(func, ast.Name) else "<expr>")
    return ".".join(reversed(parts))


def _mode_argument(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == "mode":
            return keyword.value
    position = 1 if name in _MODE_SECOND else 0
    if len(call.args) <= position:
        return None
    candidate = call.args[position]
    # `archive.open(name)` or `Path.open("w")`: only a literal that looks like a mode is one.
    if name not in _MODE_SECOND and not (
        isinstance(candidate, ast.Constant)
        and isinstance(candidate.value, str)
        and _FILE_MODE.fullmatch(candidate.value)
    ):
        return None
    return candidate


def text_writes_without_newline(source: str, filename: str = "<source>") -> list[str]:
    """Return ``file:line: reason`` for every text-mode write that does not pass ``newline=``."""
    findings: list[str] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not isinstance(node, ast.Call):
            continue
        if any(keyword.arg == "newline" for keyword in node.keywords):
            continue
        name = _dotted(node.func)
        last = name.rsplit(".", 1)[-1]
        where = f"{filename}:{node.lineno}"
        if last == "write_text":
            findings.append(f"{where}: write_text() without newline=")
            continue
        if last not in {"open", "fdopen"} and last not in _TEMPFILES:
            continue
        mode = _mode_argument(node, name)
        if mode is None:
            continue  # the default mode reads, or (tempfile) writes bytes
        if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)):
            findings.append(f"{where}: {name}() with a computed mode cannot be checked")
            continue
        writes = any(flag in mode.value for flag in "wax+")
        if writes and "b" not in mode.value:
            findings.append(f"{where}: {name}(mode={mode.value!r}) without newline=")
    return findings


@pytest.mark.parametrize(
    "source",
    [
        'open(path, "w")',
        'open(path, mode="a", encoding="utf-8")',
        'io.open(path, "w+")',
        'os.fdopen(fd, "w", encoding="utf-8")',
        'Path(path).open("w")',
        'path.write_text(value, encoding="utf-8")',
        'tempfile.NamedTemporaryFile("w", delete=False)',
        "open(path, mode)",
    ],
)
def test_the_guard_flags_a_text_write_without_newline(source: str) -> None:
    assert text_writes_without_newline(source)


@pytest.mark.parametrize(
    "source",
    [
        'open(path, "w", newline="")',
        'open(path, "wb")',
        'open(path, "a+b")',
        "open(path)",
        'open(path, "r", encoding="utf-8")',
        'os.fdopen(fd, "w", encoding="utf-8", newline="")',
        'path.write_text(value, encoding="utf-8", newline="")',
        "path.write_bytes(data)",
        "archive.open(name)",
        'tarfile.open(fileobj=buffer, mode="r:gz")',
        "tempfile.NamedTemporaryFile(delete=False)",
    ],
)
def test_the_guard_accepts_bytes_reads_and_explicit_newlines(source: str) -> None:
    assert text_writes_without_newline(source) == []


def test_every_text_write_in_app_states_its_newline() -> None:
    findings: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        relative = path.relative_to(BACKEND_ROOT).as_posix()
        findings += text_writes_without_newline(path.read_text(encoding="utf-8"), relative)
    assert findings == [], "pass newline='' (or write bytes):\n" + "\n".join(findings)


def test_a_private_file_is_written_with_lf(tmp_path: Path) -> None:
    target = tmp_path / "secret"
    write_private_file(target, "first\nsecond\n")
    assert target.read_bytes() == b"first\nsecond\n"


def _tracked_files() -> list[tuple[str, str]]:
    git = shutil.which("git")
    if git is None or not (REPO_ROOT / ".git").exists():
        pytest.skip("not running from a Git checkout")
    listing = subprocess.run(  # noqa: S603 - git with fixed arguments
        [git, "ls-files", "--eol", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    entries: list[tuple[str, str]] = []
    for entry in listing.split("\0"):
        if entry:
            # "i/lf    w/lf    attr/text=auto eol=lf \tpath/to/file"
            info, _, path = entry.partition("\t")
            entries.append((info.split()[0], path))
    return entries


def test_tracked_files_are_stored_with_lf_and_without_bom() -> None:
    problems: list[str] = []
    for index_eol, path in _tracked_files():
        if index_eol in {"i/crlf", "i/mixed"}:
            problems.append(f"{path}: stored with CRLF line endings ({index_eol})")
        if index_eol == "i/-text":
            continue  # binary
        file = REPO_ROOT / path
        if not file.is_file():
            continue  # deleted in the working tree, not yet staged
        with file.open("rb") as handle:
            if handle.read(len(codecs.BOM_UTF8)) == codecs.BOM_UTF8:
                problems.append(f"{path}: starts with a UTF-8 byte-order mark")
    assert problems == [], "\n".join(problems)
