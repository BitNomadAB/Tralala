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
from ..code_repositories import REPOSITORY_EDITABLE, LinkedBoard, RepositoryChanges

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
    " WHERE l.board_id = :board_id ORDER BY r.name COLLATE NOCASE, r.id"
)
_URL_TAKEN = text("SELECT id FROM repositories WHERE url = :url")
_URL_TAKEN_BY_OTHER = text("SELECT id FROM repositories WHERE url = :url AND id != :id")
_ADD_REPOSITORY = text(
    "INSERT INTO repositories"
    " (id, name, provider, url, branch, token_ciphertext, token_hint, enabled, last_checked_at,"
    "  last_check_status, last_check_detail, created_at, updated_at)"
    " VALUES (:id, :name, :provider, :url, :branch, :token_ciphertext, :token_hint, :enabled,"
    "         :last_checked_at, :last_check_status, :last_check_detail, :created_at,"
    "         :updated_at)"
)
_RECORD_CHECK = text(
    "UPDATE repositories SET last_checked_at = :now, last_check_status = :status,"
    " last_check_detail = :detail, updated_at = :now WHERE id = :id"
)
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
_BOARD_REPOSITORY_IDS = text(
    "SELECT repository_id FROM board_repositories WHERE board_id = :id"
    " ORDER BY created_at, repository_id"
)
_ALL_BOARD_REPOSITORIES = text(
    "SELECT board_id, repository_id FROM board_repositories ORDER BY created_at, repository_id"
)
_CLEAR_LINKS = text("DELETE FROM board_repositories WHERE board_id = :id")
_ADD_LINK = text(
    "INSERT INTO board_repositories (board_id, repository_id, created_at)"
    " VALUES (:board_id, :repository_id, :created_at)"
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

    def repository_ids(self, board_id: str) -> list[str]:
        result = self._connection.execute(_BOARD_REPOSITORY_IDS, {"id": board_id}).mappings()
        return [values.text(row, "repository_id") for row in result]

    def by_board(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for row in self._connection.execute(_ALL_BOARD_REPOSITORIES).mappings():
            grouped.setdefault(values.text(row, "board_id"), []).append(
                values.text(row, "repository_id")
            )
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
            },
        )
