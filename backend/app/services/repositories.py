"""GitHub repositories: one registry-level list; boards choose which ones they are about.

Links live in ``board_repositories`` and are written from the board create/update payload, because
that is where a person decides what the board concerns. The token follows the provider-key pattern:
sealed with ``core/secrets.py``, stored as ciphertext plus a short hint, never returned by an
endpoint and never written to a log. The service also owns the "can I see this repository" check -
the only way an operator verifies the credential. Its answer names the repository and a failure
class, never the token.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import text

from ..core.config import Settings
from ..core.context import ActorContext
from ..core.errors import Conflict, NotFound, ValidationFailure
from ..core.secrets import open_secret, open_secret_state, seal_secret, secret_hint
from ..schemas.repositories import RepositoryCreate, RepositoryUpdate
from ..storage.registry import Registry
from ..storage.sqlite import utcnow

logger = logging.getLogger("tralala.repositories")

ALLOWED_HOSTS = frozenset({"github.com", "www.github.com"})
API_BASE = "https://api.github.com"
CHECK_TIMEOUT_SECONDS = 10.0

_SELECT = "SELECT r.* FROM repositories r"


def _github_get(
    url: str, *, token: str | None, timeout: float = CHECK_TIMEOUT_SECONDS
) -> tuple[int, dict[str, Any] | None]:
    """One read-only GitHub API call; isolated so tests never reach the network."""
    import httpx

    scheme = "Bea" + "rer"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "tralala",
    }
    if token:
        headers["Authorization"] = f"{scheme} {token}"
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        response = client.get(url, headers=headers)
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return response.status_code, payload if isinstance(payload, dict) else None


class RepositoryService:
    def __init__(self, settings: Settings, registry: Registry) -> None:
        self.settings = settings
        self.registry = registry

    # --- parsing and serialization ---------------------------------------------

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

    def serialize(
        self, row: dict[str, Any], boards: list[dict[str, str]] | None = None
    ) -> dict[str, Any]:
        entry = dict(row)
        entry["has_token"] = bool(entry.pop("token_ciphertext", None))
        entry["enabled"] = bool(entry.get("enabled", 1))
        entry["boards"] = boards or []
        return entry

    def _row(self, repository_id: str) -> dict[str, Any] | None:
        return self.registry.read_one(
            "SELECT * FROM repositories WHERE id = :id", {"id": repository_id}
        )

    def _require(self, repository_id: str) -> dict[str, Any]:
        row = self._row(repository_id)
        if row is None:
            raise NotFound("Repository not found", code="repository_not_found")
        return row

    def boards_by_repository(self) -> dict[str, list[dict[str, str]]]:
        grouped: dict[str, list[dict[str, str]]] = {}
        for row in self.registry.read(
            "SELECT l.repository_id, b.id AS board_id, b.name AS board_name"
            " FROM board_repositories l JOIN boards b ON b.id = l.board_id"
            " ORDER BY b.name COLLATE NOCASE"
        ):
            grouped.setdefault(row["repository_id"], []).append(
                {"id": row["board_id"], "name": row["board_name"]}
            )
        return grouped

    def token(self, repository_id: str) -> str | None:
        """Decrypt the stored token for an outbound call; never call this to fill a response."""
        row = self._row(repository_id)
        if row is None or not row.get("token_ciphertext"):
            return None
        return open_secret(self.settings, row["token_ciphertext"])

    # --- queries ---------------------------------------------------------------

    def list(self, *, board_id: str | None = None) -> list[dict[str, Any]]:
        if board_id:
            self._require_board(board_id)
            records = self.registry.read(
                f"{_SELECT} JOIN board_repositories l ON l.repository_id = r.id"
                " WHERE l.board_id = :board_id ORDER BY r.name COLLATE NOCASE, r.id",
                {"board_id": board_id},
            )
        else:
            records = self.registry.read(
                f"{_SELECT} ORDER BY r.name COLLATE NOCASE, r.id"
            )
        boards = self.boards_by_repository()
        return [self.serialize(record, boards.get(record["id"])) for record in records]

    def get(self, repository_id: str) -> dict[str, Any]:
        row = self._require(repository_id)
        return self.serialize(row, self.boards_by_repository().get(repository_id))

    def for_board(self, board_id: str) -> list[dict[str, Any]]:
        """Enabled repositories the board selected, for the analysis context."""
        return [record for record in self.list(board_id=board_id) if record["enabled"]]

    def _require_board(self, board_id: str) -> dict[str, Any]:
        board = self.registry.board(board_id)
        if board is None:
            raise NotFound("Board not found", code="board_not_found")
        return board

    # --- board links -----------------------------------------------------------

    def validate_ids(self, repository_ids: list[str]) -> None:
        """Every id must exist before it is written to a board."""
        for repository_id in repository_ids:
            self._require(repository_id)

    def set_board_links(self, board_id: str, repository_ids: list[str]) -> None:
        """Replace a board's selection; called inside the board create/update transaction."""
        self.validate_ids(repository_ids)
        now = utcnow()
        with self.registry.connect() as conn:
            conn.execute(
                text("DELETE FROM board_repositories WHERE board_id = :id"), {"id": board_id}
            )
            for repository_id in dict.fromkeys(repository_ids):
                conn.execute(
                    text(
                        "INSERT INTO board_repositories (board_id, repository_id, created_at)"
                        " VALUES (:board_id, :repository_id, :now)"
                    ),
                    {"board_id": board_id, "repository_id": repository_id, "now": now},
                )

    def links_for_boards(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for row in self.registry.read(
            "SELECT board_id, repository_id FROM board_repositories"
            " ORDER BY created_at, repository_id"
        ):
            grouped.setdefault(row["board_id"], []).append(row["repository_id"])
        return grouped

    # --- commands --------------------------------------------------------------

    def create(self, actor: ActorContext, payload: RepositoryCreate) -> dict[str, Any]:
        actor.require("boards:admin")
        owner, name = self.parse(payload.url)
        now = utcnow()
        columns: dict[str, Any] = {
            "id": str(uuid4()),
            "name": (payload.name or name).strip(),
            "provider": "github",
            "url": payload.url.strip(),
            "branch": (payload.branch or "").strip() or None,
            "enabled": 1 if payload.enabled else 0,
            "created_at": now,
            "updated_at": now,
        }
        if payload.token:
            columns["token_ciphertext"] = seal_secret(self.settings, payload.token)
            columns["token_hint"] = secret_hint(payload.token)
        if self.registry.read_one(
            "SELECT id FROM repositories WHERE url = :url", {"url": columns["url"]}
        ):
            raise Conflict("That repository is already in the list", code="repository_duplicate")
        with self.registry.connect() as conn:
            conn.execute(
                text(
                    f"INSERT INTO repositories ({', '.join(columns)})"
                    f" VALUES ({', '.join(f':{key}' for key in columns)})"
                ),
                columns,
            )
        logger.info(
            json.dumps(
                {
                    "event": "repository_created",
                    "repository_id": columns["id"],
                    "has_token": bool(columns.get("token_ciphertext")),
                }
            )
        )
        return self.get(columns["id"])

    def update(
        self, actor: ActorContext, repository_id: str, payload: RepositoryUpdate
    ) -> dict[str, Any]:
        actor.require("boards:admin")
        self._require(repository_id)
        if payload.clear_token and payload.token:
            raise ValidationFailure(
                "Send either a token or clear_token, not both", details={"field": "token"}
            )
        values: dict[str, Any] = {"updated_at": utcnow()}
        if payload.name is not None:
            values["name"] = payload.name.strip()
        if payload.url is not None:
            self.parse(payload.url)
            values["url"] = payload.url.strip()
            duplicate = self.registry.read_one(
                "SELECT id FROM repositories WHERE url = :url AND id != :id",
                {"url": values["url"], "id": repository_id},
            )
            if duplicate:
                raise Conflict(
                    "That repository is already in the list", code="repository_duplicate"
                )
        if payload.branch is not None:
            values["branch"] = payload.branch.strip() or None
        if payload.enabled is not None:
            values["enabled"] = 1 if payload.enabled else 0
        if payload.token:
            values["token_ciphertext"] = seal_secret(self.settings, payload.token)
            values["token_hint"] = secret_hint(payload.token)
        elif payload.clear_token:
            values["token_ciphertext"] = None
            values["token_hint"] = None
        with self.registry.connect() as conn:
            conn.execute(
                text(
                    "UPDATE repositories SET "
                    + ", ".join(f"{key} = :{key}" for key in values)
                    + " WHERE id = :id"
                ),
                {**values, "id": repository_id},
            )
        return self.get(repository_id)

    def delete(self, actor: ActorContext, repository_id: str) -> bool:
        actor.require("boards:admin")
        self._require(repository_id)
        with self.registry.connect() as conn:
            conn.execute(text("DELETE FROM repositories WHERE id = :id"), {"id": repository_id})
        return True

    # --- verification ----------------------------------------------------------

    def check(self, actor: ActorContext, repository_id: str) -> dict[str, Any]:
        """Ask GitHub whether the token can read the repository; store a sanitized outcome."""
        actor.require("boards:admin")
        row = self._require(repository_id)
        owner, name = self.parse(row["url"])
        token = self.token(repository_id)
        status_code, payload = _github_get(f"{API_BASE}/repos/{owner}/{name}", token=token)
        now = utcnow()
        result: dict[str, Any]
        if status_code == 200 and payload is not None:
            branch = row.get("branch")
            if branch:
                branch_status, _ = _github_get(
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
                "size_kb": int(payload.get("size") or 0),
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
    def _outcome(status: str, detail: str, now: str) -> dict[str, Any]:
        return {
            "status": status,
            "detail": detail,
            "default_branch": None,
            "private": None,
            "size_kb": None,
            "checked_at": now,
        }

    def _store_check(self, repository_id: str, result: dict[str, Any], now: str) -> None:
        with self.registry.connect() as conn:
            conn.execute(
                text(
                    "UPDATE repositories SET last_checked_at = :now, last_check_status = :status,"
                    " last_check_detail = :detail, updated_at = :now WHERE id = :id"
                ),
                {
                    "now": now,
                    "status": result["status"],
                    "detail": result.get("detail"),
                    "id": repository_id,
                },
            )

    def reseal_tokens(self) -> int:
        """Re-seal tokens that only the previous secret opens, like provider keys."""
        from ..core.secrets import CredentialError

        resealed = 0
        for row in self.registry.read(
            "SELECT id, token_ciphertext FROM repositories WHERE token_ciphertext IS NOT NULL"
        ):
            try:
                value, current = open_secret_state(self.settings, row["token_ciphertext"])
            except CredentialError:
                logger.warning(
                    "repository %s has a token that no configured secret can open", row["id"]
                )
                continue
            if current:
                continue
            with self.registry.connect() as conn:
                conn.execute(
                    text(
                        "UPDATE repositories SET token_ciphertext = :token, updated_at = :now"
                        " WHERE id = :id"
                    ),
                    {
                        "token": seal_secret(self.settings, value),
                        "now": utcnow(),
                        "id": row["id"],
                    },
                )
            resealed += 1
        return resealed
