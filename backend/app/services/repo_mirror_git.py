"""Git as a subprocess: the one place the backend starts a program, and the rules it runs under.

A repository with the provider ``git_https`` is read from a shallow bare mirror the backend keeps
under ``<data>/repos/<repository_id>/`` (``repo_mirror.py``). Everything that mirror needs of git
goes through :class:`RunGit`, and :class:`SubprocessGit` here is the only ``subprocess`` call in the
application. What it may run is fixed:

- **Six commands.** ``ls-remote``, ``clone``, ``fetch``, ``archive``, ``reflog expire`` and ``gc``
  (:data:`COMMANDS`). The runner refuses any other argument list before it starts a process.
- **Nothing from a repository runs.** Every invocation starts with ``-c core.hooksPath=/dev/null
  -c core.fsmonitor=false -c protocol.allow=never -c protocol.https.allow=always``
  (:data:`SAFETY_OPTIONS`), the argument list goes to the program without a shell, the mirror is
  bare (no working tree, nothing checked out), and its files only ever reach a prompt as text.
- **No configuration but ours.** ``GIT_CONFIG_NOSYSTEM=1``, ``GIT_CONFIG_GLOBAL=/dev/null`` and an
  empty ``HOME`` keep the system's and the account's git configuration out, and
  ``GIT_TERMINAL_PROMPT=0`` makes a host that wants credentials fail instead of waiting for a
  person. The runner builds the environment itself, so no ``GIT_*`` variable of the backend's own
  process reaches git, and ``GIT_CEILING_DIRECTORIES`` keeps git from taking a directory above the
  mirrors for a repository whose configuration it should read.
- **The token only in the environment.** It travels as ``http.extraHeader`` through
  ``GIT_CONFIG_COUNT``, ``GIT_CONFIG_KEY_0`` and ``GIT_CONFIG_VALUE_0`` of the one process that
  needs it: never in the URL, the argument list, the mirror's ``config``, ``state.json``, a log line
  or a run. The header is HTTP Basic with the token as the password, which is what git itself sends
  for ``https://user:token@host/...`` and what Git hosts accept for an access token in place of a
  password; Bearer is not accepted by every host for Git over HTTPS. The user name is
  ``x-access-token``, which hosts that take a token as the password ignore, unless the stored token
  is written as ``<user>:<token>`` for a host that checks the name.

A failure is a :class:`MirrorError` whose code an operator can act on (:data:`ERROR_TEXT`). Git's
own words are logged as a short excerpt only; the header is never in them, because it is never in
the argument list or the URL.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol
from urllib.parse import SplitResult, urlsplit

logger = logging.getLogger("tralala.repo_mirror_git")

SAFETY_OPTIONS: Final = (
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "protocol.allow=never",
    "-c",
    "protocol.https.allow=always",
)
COMMANDS: Final = (
    ("ls-remote",),
    ("clone",),
    ("fetch",),
    ("archive",),
    ("reflog", "expire"),
    ("gc",),
)
GIT_DIR_OPTION: Final = "--git-dir="
# The user name sent with a token; a name, not a secret, which hosts that take a token ignore.
TOKEN_USER: Final = "x-access-token"  # noqa: S105 - a fixed user name, not a password
# Program variables the runner passes on: where programs are, and what Windows needs to start one.
_PASSED_ON = ("PATH", "SYSTEMROOT")
_STDERR_BYTES = 8192
_DETAIL_CHARS = 200

# What each failure means to an operator. The check endpoint and the run show these, never git's
# own words. ``stale_mirror`` is not a failure: the run used the last good mirror.
ERROR_TEXT: Final[Mapping[str, str]] = {
    "host_not_allowed": "The host is not listed in TRALALA_REPOSITORY_HOSTS",
    "invalid_url": "The URL is not an https URL of a Git repository",
    "auth_failed": "The host wants credentials, or refused the token",
    "not_found": "Repository or branch not found, or the token cannot see it",
    "timeout": "Git did not finish within TRALALA_REPOSITORY_FETCH_TIMEOUT_SECONDS",
    "too_large": "The mirror is larger than TRALALA_REPOSITORY_MIRROR_MAX_BYTES",
    "git_missing": "The git program is not installed where the backend runs",
    "fetch_failed": "Git could not read the repository",
    "stale_mirror": "The last fetch failed; the run used the last good mirror",
    "mirror_cleanup_failed": "The mirror's directory could not be removed",
}

SHA_PATTERN: Final = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_BRANCH_CHARACTERS = re.compile(r"[A-Za-z0-9._/+-]{1,200}")

# Phrases git and the hosts use, lower-cased; the first group that matches names the failure.
_AUTH_PHRASES = (
    "authentication failed",
    "could not read username",
    "could not read password",
    "terminal prompts disabled",
    "access denied",
    "returned error: 401",
    "returned error: 403",
)
_NOT_FOUND_PHRASES = (
    "not found",
    "does not appear to be a git repository",
    "returned error: 404",
    "couldn't find remote ref",
    "not a valid object name",
)
_TIMEOUT_PHRASES = ("timed out", "timeout was reached")


class MirrorError(Exception):
    """A mirror operation that failed. ``code`` is what reaches the row, the run and the log."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RunGit(Protocol):
    """One git command: ``args`` after the program's name, the environment it adds, and bounds."""

    def __call__(
        self,
        args: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout: float,
        max_output_bytes: int | None = None,
    ) -> bytes:
        """What git wrote to stdout. ``MirrorError`` on a non-zero exit (with the code its message
        reads as), a timeout, a missing program, or more output than ``max_output_bytes``."""
        ...


# --- arguments and environment --------------------------------------------------------------------


def git_args(*command: str, git_dir: str | None = None) -> list[str]:
    """``command`` behind the safety options, run on the mirror at ``git_dir`` when one is named."""
    location = [] if git_dir is None else [GIT_DIR_OPTION + git_dir]
    return [*SAFETY_OPTIONS, *location, *command]


def command_of(args: Sequence[str]) -> str:
    """The command an argument list runs, as :data:`COMMANDS` names it (``""`` for none)."""
    rest = list(args[len(SAFETY_OPTIONS) :])
    if rest and rest[0].startswith(GIT_DIR_OPTION):
        rest = rest[1:]
    for command in COMMANDS:
        if tuple(rest[: len(command)]) == command:
            return " ".join(command)
    return ""


def args_problem(args: Sequence[str]) -> str | None:
    """Why ``args`` may not run, or None: the safety options come first, then at most the
    mirror's ``--git-dir``, then one of the six commands."""
    if tuple(args[: len(SAFETY_OPTIONS)]) != SAFETY_OPTIONS:
        return "the safety options do not come first"
    if not command_of(args):
        return "not one of the commands the mirror runs"
    return None


def authorization_header(token: str) -> str:
    """The ``http.extraHeader`` value that carries ``token`` as an HTTP Basic password."""
    user, separator, secret = token.partition(":")
    credential = token if separator and user and secret else f"{TOKEN_USER}:{token}"
    return "Authorization: Basic " + base64.b64encode(credential.encode("utf-8")).decode("ascii")


def git_environment(token: str | None) -> dict[str, str]:
    """The variables every git command gets: no system or account configuration, no prompt, and
    the token, when there is one, as configuration of this one process."""
    env = {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "HOME": "",
    }
    if token:
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
        env["GIT_CONFIG_VALUE_0"] = authorization_header(token)
    return env


# --- what git is given and what it answers --------------------------------------------------------


def git_url_problem(url: str, hosts: frozenset[str]) -> str | None:
    """None for an https URL of a repository on one of ``hosts``; else ``invalid_url`` or
    ``host_not_allowed``. Credentials in the URL are refused: the token is stored sealed."""
    candidate = url.strip()
    if not candidate or any(character.isspace() or ord(character) < 32 for character in candidate):
        return "invalid_url"
    parts = urlsplit(candidate)
    if not _port_valid(parts):
        return "invalid_url"
    if parts.scheme != "https" or parts.username or parts.password or parts.query:
        return "invalid_url"
    if parts.fragment or not [segment for segment in parts.path.split("/") if segment]:
        return "invalid_url"
    if (parts.hostname or "").lower() not in hosts:
        return "host_not_allowed"
    return None


def _port_valid(parts: SplitResult) -> bool:
    try:
        port = parts.port
    except ValueError:
        return False
    return port is None or port > 0


def valid_branch(name: str) -> bool:
    """A branch name that is safe on a command line and in a refspec: letters, digits and
    ``._/+-``, no leading ``-``, ``.`` or ``/``, no ``..`` or ``//``, not ending in ``.lock``."""
    if not _BRANCH_CHARACTERS.fullmatch(name):
        return False
    if name.startswith(("-", ".", "/")) or name.endswith(("/", ".", ".lock")):
        return False
    return ".." not in name and "//" not in name and "/." not in name


@dataclass(frozen=True, slots=True, kw_only=True)
class RemoteRefs:
    """What ``git ls-remote --symref`` listed: the branch HEAD names and the branches it showed."""

    head: str | None
    branches: Mapping[str, str] = field(default_factory=dict[str, str])


def parse_ls_remote(output: str) -> RemoteRefs:
    """``ref: refs/heads/main<TAB>HEAD`` names the default branch; ``<sha><TAB>refs/heads/x`` a
    branch."""
    head: str | None = None
    branches: dict[str, str] = {}
    for line in output.splitlines():
        if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
            head = line[len("ref: refs/heads/") : -len("\tHEAD")]
            continue
        sha, _tab, name = line.partition("\t")
        if name.startswith("refs/heads/") and SHA_PATTERN.fullmatch(sha):
            branches[name[len("refs/heads/") :]] = sha
    return RemoteRefs(head=head, branches=branches)


def classify_failure(stderr: str) -> str:
    """The code for what git wrote before it gave up."""
    text = stderr.lower()
    if any(phrase in text for phrase in _AUTH_PHRASES):
        return "auth_failed"
    if any(phrase in text for phrase in _NOT_FOUND_PHRASES):
        return "not_found"
    if any(phrase in text for phrase in _TIMEOUT_PHRASES):
        return "timeout"
    return "fetch_failed"


def failure_detail(stderr: str) -> str:
    """A short excerpt for the log: git's first ``fatal:`` or ``error:`` line, bounded, with
    anything after an ``Authorization`` cut off in case a host ever echoes one."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    chosen = next(
        (line for line in lines if line.startswith(("fatal:", "error:"))), lines[0] if lines else ""
    )
    cut = chosen.lower().find("authorization")
    if cut >= 0:
        chosen = chosen[:cut] + "[redacted]"
    return chosen[:_DETAIL_CHARS]


# --- the real runner ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SubprocessGit:
    """The real :class:`RunGit`: ``binary`` with the argument list, no shell, from ``work_dir`` (the
    mirrors' directory), in an environment built here and not inherited."""

    binary: str
    work_dir: Path

    def __call__(
        self,
        args: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout: float,
        max_output_bytes: int | None = None,
    ) -> bytes:
        problem = args_problem(args)
        if problem is not None:
            raise ValueError(f"refused git arguments: {problem}")
        command = command_of(args)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        process_env = {name: os.environ[name] for name in _PASSED_ON if name in os.environ}
        process_env.setdefault("PATH", os.defpath)
        process_env |= {"LC_ALL": "C", "GIT_CEILING_DIRECTORIES": str(self.work_dir.parent)}
        process_env |= env
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            try:
                completed = subprocess.run(  # noqa: S603 - a checked argument list, no shell
                    [self.binary, *args],
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=err,
                    env=process_env,
                    cwd=self.work_dir,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                logger.warning("git_command_failed", extra={"command": command, "code": "timeout"})
                raise MirrorError("timeout") from exc
            except OSError as exc:
                logger.warning(
                    "git_command_failed",
                    extra={"command": command, "code": "git_missing", "error": type(exc).__name__},
                )
                raise MirrorError("git_missing") from exc
            if completed.returncode != 0:
                err.seek(0)
                stderr = err.read(_STDERR_BYTES).decode("utf-8", errors="replace")
                code = classify_failure(stderr)
                logger.warning(
                    "git_command_failed",
                    extra={
                        "command": command,
                        "code": code,
                        "returncode": completed.returncode,
                        "detail": failure_detail(stderr),
                    },
                )
                raise MirrorError(code)
            size = out.seek(0, os.SEEK_END)
            if max_output_bytes is not None and size > max_output_bytes:
                logger.warning(
                    "git_command_failed",
                    extra={"command": command, "code": "too_large", "output_bytes": size},
                )
                raise MirrorError("too_large")
            out.seek(0)
            return out.read()
