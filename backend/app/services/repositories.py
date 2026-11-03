"""GitHub repositories: one registry-level list; boards choose which ones they are about.

Links live in ``board_repositories`` and are written from the board create/update payload, because
that is where a person decides what the board concerns. The token follows the provider-key pattern:
sealed with ``core/secrets.py``, stored as ciphertext plus a short hint, never returned by an
endpoint and never written to a log. The service also owns the "can I see this repository" check -
the only way an operator verifies the credential. Its answer names the repository and a failure
class, never the token.

The service reaches the registry only through the repositories and the registry unit of work
(``app/repositories``); the clock, the id source and the GitHub call are passed in, with the real
ones as defaults, so every rule here runs in a unit test without a database or a network.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import NotRequired, Protocol, TypedDict, TypeIs
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import JsonValue

from ..core.config import Settings
from ..core.context import ActorContext
from ..core.dates import utcnow
from ..core.errors import Conflict, NotFound, ValidationFailure
from ..core.secrets import (
    CredentialError,
    open_secret,
    open_secret_state,
    seal_secret,
    secret_hint,
)
from ..db.generated.registry import BoardRepositoriesRow, RepositoriesRow
from ..repositories.code_repositories import RepositoryChanges
from ..repositories.registry import RegistryUnitOfWork
from ..schemas.repositories import RepositoryCreate, RepositoryUpdate

logger = logging.getLogger("tralala.repositories")

ALLOWED_HOSTS = frozenset({"github.com", "www.github.com"})
API_BASE = "https://api.github.com"
CHECK_TIMEOUT_SECONDS = 10.0

type JsonObject = dict[str, JsonValue]


class BoardReference(TypedDict):
    id: str
    name: str


class RepositoryEntry(TypedDict):
    """A repository as the API returns it: whether a token exists, never the token.

    Without health (a caller without ``boards:admin``) the hint and the last check are left out.
    """

    id: str
    name: str
    provider: str
    url: str
    branch: str | None
    token_hint: NotRequired[str | None]
    enabled: bool
    last_checked_at: NotRequired[str | None]
    last_check_status: NotRequired[str | None]
    last_check_detail: NotRequired[str | None]
    created_at: str
    updated_at: str
    has_token: bool
    boards: list[BoardReference]


class CheckOutcome(TypedDict):
    """What GitHub said about the repository, without the token or GitHub's own text."""

    status: str
    detail: str
    default_branch: JsonValue
    private: bool | None
    size_kb: int | None
    checked_at: str


class GitHubGet(Protocol):
    """One read-only GitHub API call: the status code and the JSON object it answered, if any."""

    def __call__(self, url: str, *, token: str | None) -> tuple[int, JsonObject | None]: ...


def _json_object(value: object) -> TypeIs[JsonObject]:
    """A parsed JSON body that is an object: its keys are strings and its values JSON."""
    return isinstance(value, dict)


def _size_kb(value: JsonValue) -> int:
    """GitHub's ``size`` as ``int()`` reads it; nothing (or zero) is 0."""
    if not value:
        return 0
    if isinstance(value, (list, dict)):
        raise TypeError(f"size is not a number: {type(value).__name__}")
    return int(value)


def _new_id() -> str:
    return str(uuid4())


def _github_get(
    url: str, *, token: str | None, timeout: float = CHECK_TIMEOUT_SECONDS
) -> tuple[int, JsonObject | None]:
    """One read-only GitHub API call; injected into the service, so tests never reach it."""
    import httpx

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "tralala",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        response = client.get(url, headers=headers)
    try:
        payload: object = response.json()
    except ValueError:
        payload = None
    return response.status_code, payload if _json_object(payload) else None


class RepositoryService:
    def __init__(
        self,
        settings: Settings,
        store: RegistryUnitOfWork,
        *,
        clock: Callable[[], str] = utcnow,
        new_id: Callable[[], str] = _new_id,
        github_get: GitHubGet = _github_get,
    ) -> None:
        self.settings = settings
        self.store = store
        self._clock = clock
        self._new_id = new_id
        self._github_get = github_get

    # --- parsing and serialization ---------------------------------------------------------------

    @staticmethod
    def parse(url: str) -> tuple[str, str]:
        """Return ``(owner, name)`` for a GitHub https URL and reject everything else."""
        candidate = (url or "").strip()
        if not candidate:
            raise ValidationFailure("Repository URL is required")
        parts = urlsplit(candidate)
        if parts.scheme != "https":
            raise ValidationFailure("Repository URL must use https", details={"field": "url"})
        if parts.username or parts.password:
            raise ValidationFailure("Repository URL must not embed credentials")
        host = (parts.hostname or "").lower()
        if host not in ALLOWED_HOSTS:
            raise ValidationFailure(
                "Only github.com repositories are supported",
                details={"allowed": sorted(ALLOWED_HOSTS)},
            )
        segments = [segment for segment in parts.path.split("/") if segment]
        if len(segments) != 2:
            raise ValidationFailure(
                "Repository URL must be https://github.com/<owner>/<repository>",
                details={"field": "url"},
            )
        owner, name = segments
        if name.endswith(".git"):
            name = name[: -len(".git")]
        if not owner or not name:
            raise ValidationFailure("Repository URL must name an owner and a repository")
        return owner, name

    @staticmethod
    def serialize(
        row: RepositoriesRow,
        boards: list[BoardReference] | None = None,
        *,
        with_health: bool = True,
    ) -> RepositoryEntry:
        """A repository entry. ``with_health=False`` hides the credential hint and check history.

        A caller without ``boards:admin`` still needs to see which repositories exist and which
        boards use them (board dialogs offer the list), but the token hint and the outcome of the
        last access check are administration detail.
        """
        if with_health:
            return {
                "id": row.id,
                "name": row.name,
                "provider": row.provider,
                "url": row.url,
                "branch": row.branch,
                "token_hint": row.token_hint,
                "enabled": bool(row.enabled),
                "last_checked_at": row.last_checked_at,
                "last_check_status": row.last_check_status,
                "last_check_detail": row.last_check_detail,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "has_token": bool(row.token_ciphertext),
                "boards": boards or [],
            }
        return {
            "id": row.id,
            "name": row.name,
            "provider": row.provider,
            "url": row.url,
            "branch": row.branch,
            "enabled": bool(row.enabled),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "has_token": bool(row.token_ciphertext),
            "boards": boards or [],
        }

    def _row(self, repository_id: str) -> RepositoriesRow | None:
        with self.store.reader() as repos:
            return repos.code_repositories.get(repository_id)

    def _require(self, repository_id: str) -> RepositoriesRow:
        row = self._row(repository_id)
        if row is None:
            raise NotFound("Repository not found", code="repository_not_found")
        return row

    def boards_by_repository(self) -> dict[str, list[BoardReference]]:
        with self.store.reader() as repos:
            linked = repos.repository_links.linked_boards()
        grouped: dict[str, list[BoardReference]] = {}
        for entry in linked:
            grouped.setdefault(entry.link.repository_id, []).append(
                {"id": entry.board.id, "name": entry.board.name}
            )
        return grouped

    def _open_token(self, row: RepositoriesRow) -> str | None:
        if not row.token_ciphertext:
            return None
        return open_secret(self.settings, row.token_ciphertext)

    def token(self, repository_id: str) -> str | None:
        """Decrypt the stored token for an outbound call; never call this to fill a response."""
        row = self._row(repository_id)
        return None if row is None else self._open_token(row)

    # --- queries ---------------------------------------------------------------------------------

    def list(
        self, *, board_id: str | None = None, with_health: bool = True
    ) -> list[RepositoryEntry]:
        with self.store.reader() as repos:
            if board_id:
                if repos.boards.get(board_id) is None:
                    raise NotFound("Board not found", code="board_not_found")
                rows = repos.code_repositories.for_board(board_id)
            else:
                rows = repos.code_repositories.all()
        boards = self.boards_by_repository()
        return [self.serialize(row, boards.get(row.id), with_health=with_health) for row in rows]

    def get(self, repository_id: str, *, with_health: bool = True) -> RepositoryEntry:
        row = self._require(repository_id)
        return self.serialize(
            row, self.boards_by_repository().get(repository_id), with_health=with_health
        )

    def for_board(self, board_id: str) -> list[RepositoryEntry]:
        """Enabled repositories the board selected, for the analysis context."""
        return [record for record in self.list(board_id=board_id) if record["enabled"]]

    # --- board links -----------------------------------------------------------------------------

    def validate_ids(self, repository_ids: list[str]) -> None:
        """Every id must exist before it is written to a board."""
        with self.store.reader() as repos:
            for repository_id in repository_ids:
                if repos.code_repositories.get(repository_id) is None:
                    raise NotFound("Repository not found", code="repository_not_found")

    def set_board_links(self, board_id: str, repository_ids: list[str]) -> None:
        """Replace a board's selection; called after the board row exists."""
        self.validate_ids(repository_ids)
        now = self._clock()
        with self.store.writer() as repos:
            repos.repository_links.clear(board_id)
            for repository_id in dict.fromkeys(repository_ids):
                repos.repository_links.add(
                    BoardRepositoriesRow(
                        board_id=board_id, repository_id=repository_id, created_at=now
                    )
                )

    # --- commands --------------------------------------------------------------------------------

    def create(self, actor: ActorContext, payload: RepositoryCreate) -> RepositoryEntry:
        actor.require("boards:admin")
        _owner, name = self.parse(payload.url)
        now = self._clock()
        token = payload.token
        row = RepositoriesRow(
            id=self._new_id(),
            name=(payload.name or name).strip(),
            provider="github",
            url=payload.url.strip(),
            branch=(payload.branch or "").strip() or None,
            token_ciphertext=seal_secret(self.settings, token) if token else None,
            token_hint=secret_hint(token) if token else None,
            enabled=1 if payload.enabled else 0,
            last_checked_at=None,
            last_check_status=None,
            last_check_detail=None,
            created_at=now,
            updated_at=now,
        )
        with self.store.reader() as repos:
            duplicate = repos.code_repositories.url_taken(row.url)
        if duplicate:
            raise Conflict("That repository is already in the list", code="repository_duplicate")
        with self.store.writer() as repos:
            repos.code_repositories.add(row)
        logger.info(
            "repository_created",
            extra={"repository_id": row.id, "has_token": bool(row.token_ciphertext)},
        )
        return self.get(row.id)

    def update(
        self, actor: ActorContext, repository_id: str, payload: RepositoryUpdate
    ) -> RepositoryEntry:
        actor.require("boards:admin")
        self._require(repository_id)
        if payload.clear_token and payload.token:
            raise ValidationFailure(
                "Send either a token or clear_token, not both", details={"field": "token"}
            )
        changes: RepositoryChanges = {"updated_at": self._clock()}
        if payload.name is not None:
            changes["name"] = payload.name.strip()
        if payload.url is not None:
            self.parse(payload.url)
            url = payload.url.strip()
            changes["url"] = url
            with self.store.reader() as repos:
                duplicate = repos.code_repositories.url_taken(url, other_than=repository_id)
            if duplicate:
                raise Conflict(
                    "That repository is already in the list", code="repository_duplicate"
                )
        if payload.branch is not None:
            changes["branch"] = payload.branch.strip() or None
        if payload.enabled is not None:
            changes["enabled"] = 1 if payload.enabled else 0
        if payload.token:
            changes["token_ciphertext"] = seal_secret(self.settings, payload.token)
            changes["token_hint"] = secret_hint(payload.token)
        elif payload.clear_token:
            changes["token_ciphertext"] = None
            changes["token_hint"] = None
        with self.store.writer() as repos:
            repos.code_repositories.update(repository_id, changes)
        return self.get(repository_id)

    def delete(self, actor: ActorContext, repository_id: str) -> bool:
        actor.require("boards:admin")
        self._require(repository_id)
        with self.store.writer() as repos:
            repos.code_repositories.delete(repository_id)
        return True

    # --- verification ----------------------------------------------------------------------------

    def check(self, actor: ActorContext, repository_id: str) -> CheckOutcome:
        """Ask GitHub whether the token can read the repository; store a sanitized outcome."""
        actor.require("boards:admin")
        row = self._require(repository_id)
        owner, name = self.parse(row.url)
        token = self._open_token(row)
        status_code, payload = self._github_get(f"{API_BASE}/repos/{owner}/{name}", token=token)
        now = self._clock()
        result: CheckOutcome
        if status_code == 200 and payload is not None:
            branch = row.branch
            if branch:
                branch_status, _ = self._github_get(
                    f"{API_BASE}/repos/{owner}/{name}/branches/{branch}", token=token
                )
                if branch_status == 404:
                    result = self._outcome(
                        "branch_missing", f"Branch '{branch}' does not exist", now
                    )
                    self._store_check(repository_id, result, now)
                    return result
            result = {
                "status": "ok",
                "detail": f"{owner}/{name} is readable",
                "default_branch": payload.get("default_branch"),
                "private": bool(payload.get("private")),
                "size_kb": _size_kb(payload.get("size")),
                "checked_at": now,
            }
        elif status_code == 401:
            result = self._outcome("unauthorized", "The token was rejected", now)
        elif status_code == 404:
            result = self._outcome(
                "not_found", "Repository not found, or the token cannot see it", now
            )
        elif status_code == 403:
            result = self._outcome(
                "forbidden", "GitHub refused the request (scope or rate limit)", now
            )
        else:
            result = self._outcome("unreachable", f"GitHub answered {status_code}", now)
        self._store_check(repository_id, result, now)
        return result

    @staticmethod
    def _outcome(status: str, detail: str, now: str) -> CheckOutcome:
        return {
            "status": status,
            "detail": detail,
            "default_branch": None,
            "private": None,
            "size_kb": None,
            "checked_at": now,
        }

    def _store_check(self, repository_id: str, result: CheckOutcome, now: str) -> None:
        with self.store.writer() as repos:
            repos.code_repositories.record_check(
                repository_id, status=result["status"], detail=result["detail"], now=now
            )

    def reseal_tokens(self) -> int:
        """Re-seal tokens that only the previous secret opens, like provider keys."""
        with self.store.reader() as repos:
            sealed = repos.code_repositories.sealed_tokens()
        resealed: dict[str, str] = {}
        for repository_id, ciphertext in sealed.items():
            try:
                value, current = open_secret_state(self.settings, ciphertext)
            except CredentialError:
                logger.warning(
                    "repository %s has a token that no configured secret can open", repository_id
                )
                continue
            if not current:
                resealed[repository_id] = seal_secret(self.settings, value)
        if resealed:
            now = self._clock()
            with self.store.writer() as repos:
                for repository_id, ciphertext in resealed.items():
                    repos.code_repositories.reseal(repository_id, ciphertext, now=now)
        return len(resealed)
