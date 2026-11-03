"""``RegistryIdempotencyRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db.generated.registry import IDEMPOTENCY_RECORDS_COLUMNS, IdempotencyRecordsRow

_GET = text(
    f"SELECT {sql.column_list(IDEMPOTENCY_RECORDS_COLUMNS)}"  # noqa: S608 - from generated columns
    " FROM idempotency_records WHERE actor_id = :actor_id AND idempotency_key = :key"
)
_PUT = text(
    "INSERT OR REPLACE INTO idempotency_records"
    " (actor_id, idempotency_key, request_hash, response_json, created_at, expires_at)"
    " VALUES (:actor_id, :idempotency_key, :request_hash, :response_json, :created_at,"
    "         :expires_at)"
)


class SqlRegistryIdempotencyRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, actor_id: str, key: str) -> IdempotencyRecordsRow | None:
        parameters = {"actor_id": actor_id, "key": key}
        row = self._connection.execute(_GET, parameters).mappings().first()
        return None if row is None else IdempotencyRecordsRow.from_mapping(row)

    def put(self, row: IdempotencyRecordsRow) -> None:
        self._connection.execute(
            _PUT,
            {
                "actor_id": row.actor_id,
                "idempotency_key": row.idempotency_key,
                "request_hash": row.request_hash,
                "response_json": row.response_json,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
            },
        )
