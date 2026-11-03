"""The code repository and board-link repositories over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db import values
from ...db.generated.registry import (
    BOARD_REPOSITORIES_COLUMNS,
    BOARDS_COLUMNS,
    REPOSITORIES_COLUMNS,
    BoardRepositoriesRow,
    BoardsRow,
    RepositoriesRow,
)
from ..code_repositories import (
    REPOSITORY_EDITABLE,
    LinkedBoard,
    MirrorRecord,
    RepositoryChanges,
)

_BOARD = "board__"

_REPOSITORY = (
    f"SELECT {sql.column_list(REPOSITORIES_COLUMNS)}"  # noqa: S608 - from generated columns
    " FROM repositories"
)
_REPOSITORY_BY_ID = text(f"{_REPOSITORY} WHERE id = :id")
_ALL_REPOSITORIES = text(f"{_REPOSITORY} ORDER BY name COLLATE NOCASE, id")
_BOARD_REPOSITORIES = text(
    f"SELECT {sql.column_list(REPOSITORIES_COLUMNS, 'r')}"  # noqa: S608 - from generated columns
    " FROM repositories r JOIN board_repositories l ON l.repository_id = r.id"
    " WHERE l.board_id = :board_id ORDER BY l.created_at, r.name COLLATE NOCASE, r.id"
)
_URL_TAKEN = text("SELECT id FROM repositories WHERE url = :url")
_URL_TAKEN_BY_OTHER = text("SELECT id FROM repositories WHERE url = :url AND id != :id")
_ADD_REPOSITORY = text(
    "INSERT INTO repositories"
    " (id, name, provider, url, branch, token_ciphertext, token_hint, enabled, last_checked_at,"
    "  last_check_status, last_check_detail, created_at, updated_at, default_branch, last_sha,"
    "  fetched_at, mirror_bytes, mirror_error)"
    " VALUES (:id, :name, :provider, :url, :branch, :token_ciphertext, :token_hint, :enabled,"
    "         :last_checked_at, :last_check_status, :last_check_detail, :created_at,"
    "         :updated_at, :default_branch, :last_sha, :fetched_at, :mirror_bytes, :mirror_error)"
)
_RECORD_CHECK = text(
    "UPDATE repositories SET last_checked_at = :now, last_check_status = :status,"
    " last_check_detail = :detail, updated_at = :now WHERE id = :id"
)
_RECORD_DEFAULT_BRANCH = text(
    "UPDATE repositories SET default_branch = :default_branch WHERE id = :id"
)
_RECORD_FETCH = text(
    "UPDATE repositories SET default_branch = COALESCE(:default_branch, default_branch),"
    " last_sha = :last_sha, fetched_at = :fetched_at, mirror_bytes = :mirror_bytes,"
    " mirror_error = NULL WHERE id = :id"
)
_RECORD_MIRROR_ERROR = text("UPDATE repositories SET mirror_error = :code WHERE id = :id")
_DELETE_REPOSITORY = text("DELETE FROM repositories WHERE id = :id")
_SEALED_TOKENS = text(
    "SELECT id, token_ciphertext FROM repositories WHERE token_ciphertext IS NOT NULL"
)
_RESEAL_TOKEN = text(
    "UPDATE repositories SET token_ciphertext = :token, updated_at = :now WHERE id = :id"
)

_LINKED_BOARDS = text(
    f"SELECT {sql.column_list(BOARD_REPOSITORIES_COLUMNS, 'l')},"  # noqa: S608 - from generated columns
    f" {sql.column_list(BOARDS_COLUMNS, 'b', _BOARD)}"
    " FROM board_repositories l JOIN boards b ON b.id = l.board_id"
    " ORDER BY b.name COLLATE NOCASE"
)
_LINK = (
    f"SELECT {sql.column_list(BOARD_REPOSITORIES_COLUMNS)}"  # noqa: S608 - from generated columns
    " FROM board_repositories"
)
_BOARD_LINKS = text(f"{_LINK} WHERE board_id = :id ORDER BY created_at, repository_id")
_ALL_BOARD_LINKS = text(f"{_LINK} ORDER BY created_at, repository_id")
_CLEAR_LINKS = text("DELETE FROM board_repositories WHERE board_id = :id")
_ADD_LINK = text(
    "INSERT INTO board_repositories"
    " (board_id, repository_id, created_at, focus_paths, exclude_paths)"
    " VALUES (:board_id, :repository_id, :created_at, :focus_paths, :exclude_paths)"
)


class SqlCodeRepositoryRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, repository_id: str) -> RepositoriesRow | None:
        row = self._connection.execute(_REPOSITORY_BY_ID, {"id": repository_id}).mappings().first()
        return None if row is None else RepositoriesRow.from_mapping(row)

    def all(self) -> list[RepositoriesRow]:
        result = self._connection.execute(_ALL_REPOSITORIES).mappings()
        return [RepositoriesRow.from_mapping(row) for row in result]

    def for_board(self, board_id: str) -> list[RepositoriesRow]:
        result = self._connection.execute(_BOARD_REPOSITORIES, {"board_id": board_id}).mappings()
        return [RepositoriesRow.from_mapping(row) for row in result]

    def url_taken(self, url: str, *, other_than: str | None = None) -> bool:
        if other_than is None:
            result = self._connection.execute(_URL_TAKEN, {"url": url})
        else:
            result = self._connection.execute(_URL_TAKEN_BY_OTHER, {"url": url, "id": other_than})
        return result.first() is not None

    def add(self, row: RepositoriesRow) -> None:
        self._connection.execute(
            _ADD_REPOSITORY,
            {
                "id": row.id,
                "name": row.name,
                "provider": row.provider,
                "url": row.url,
                "branch": row.branch,
                "token_ciphertext": row.token_ciphertext,
                "token_hint": row.token_hint,
                "enabled": row.enabled,
                "last_checked_at": row.last_checked_at,
                "last_check_status": row.last_check_status,
                "last_check_detail": row.last_check_detail,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "default_branch": row.default_branch,
                "last_sha": row.last_sha,
                "fetched_at": row.fetched_at,
                "mirror_bytes": row.mirror_bytes,
                "mirror_error": row.mirror_error,
            },
        )

    def update(self, repository_id: str, changes: RepositoryChanges) -> None:
        assignments = sql.assignments(changes, REPOSITORY_EDITABLE)
        statement = text(
            "UPDATE repositories"  # noqa: S608 - from REPOSITORY_EDITABLE
            f" SET {assignments} WHERE id = :id"
        )
        self._connection.execute(statement, {**changes, "id": repository_id})

    def record_check(self, repository_id: str, *, status: str, detail: str, now: str) -> None:
        parameters = {"now": now, "status": status, "detail": detail, "id": repository_id}
        self._connection.execute(_RECORD_CHECK, parameters)

    def record_default_branch(self, repository_id: str, default_branch: str) -> None:
        parameters = {"default_branch": default_branch, "id": repository_id}
        self._connection.execute(_RECORD_DEFAULT_BRANCH, parameters)

    def record_fetch(self, repository_id: str, record: MirrorRecord) -> None:
        self._connection.execute(
            _RECORD_FETCH,
            {
                "default_branch": record.default_branch,
                "last_sha": record.last_sha,
                "fetched_at": record.fetched_at,
                "mirror_bytes": record.mirror_bytes,
                "id": repository_id,
            },
        )

    def record_mirror_error(self, repository_id: str, code: str) -> None:
        self._connection.execute(_RECORD_MIRROR_ERROR, {"code": code, "id": repository_id})

    def delete(self, repository_id: str) -> None:
        self._connection.execute(_DELETE_REPOSITORY, {"id": repository_id})

    def sealed_tokens(self) -> dict[str, str]:
        result = self._connection.execute(_SEALED_TOKENS).mappings()
        return {values.text(row, "id"): values.text(row, "token_ciphertext") for row in result}

    def reseal(self, repository_id: str, ciphertext: str, *, now: str) -> None:
        parameters = {"token": ciphertext, "now": now, "id": repository_id}
        self._connection.execute(_RESEAL_TOKEN, parameters)


class SqlRepositoryLinkRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def linked_boards(self) -> list[LinkedBoard]:
        return [
            LinkedBoard(
                link=BoardRepositoriesRow.from_mapping(row),
                board=BoardsRow.from_mapping(values.prefixed(row, _BOARD)),
            )
            for row in self._connection.execute(_LINKED_BOARDS).mappings()
        ]

    def links(self, board_id: str) -> list[BoardRepositoriesRow]:
        result = self._connection.execute(_BOARD_LINKS, {"id": board_id}).mappings()
        return [BoardRepositoriesRow.from_mapping(row) for row in result]

    def by_board(self) -> dict[str, list[BoardRepositoriesRow]]:
        grouped: dict[str, list[BoardRepositoriesRow]] = {}
        for row in self._connection.execute(_ALL_BOARD_LINKS).mappings():
            link = BoardRepositoriesRow.from_mapping(row)
            grouped.setdefault(link.board_id, []).append(link)
        return grouped

    def clear(self, board_id: str) -> None:
        self._connection.execute(_CLEAR_LINKS, {"id": board_id})

    def add(self, row: BoardRepositoriesRow) -> None:
        self._connection.execute(
            _ADD_LINK,
            {
                "board_id": row.board_id,
                "repository_id": row.repository_id,
                "created_at": row.created_at,
                "focus_paths": row.focus_paths,
                "exclude_paths": row.exclude_paths,
            },
        )
