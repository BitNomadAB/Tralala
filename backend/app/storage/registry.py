from __future__ import annotations

import json
import logging
import secrets
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..core.config import Settings
from ..core.context import ROLE_ADMIN
from ..core.security import (
    BOOTSTRAP_PASSWORD_FILE_NAME,
    INSECURE_BOOTSTRAP_PASSWORDS,
    hash_password,
    write_private_file,
)
from .sqlite import create_sqlite_engine, utcnow

logger = logging.getLogger("tralala.registry")


def _shift_iso(value: str, seconds: int) -> str:
    moment = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return (moment + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Registry:
    """Central registry database: global board metadata, actors and credentials."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = create_sqlite_engine(settings.registry_path)

    def initialize(self) -> None:
        """Kept for compatibility: schema readiness is enforced by the Migration Manager."""
        self.bootstrap_admin()

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        with self.engine.begin() as conn:
            yield conn

    def read(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(text(sql), params or {}).mappings()]

    def read_one(self, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        rows = self.read(sql, params)
        return rows[0] if rows else None

    # --- actors and credentials -------------------------------------------------

    def bootstrap_admin(self) -> None:
        if self.read_one("SELECT id FROM actors WHERE type='user' LIMIT 1"):
            return
        password = self.settings.bootstrap_password
        generated = password.strip().lower() in INSECURE_BOOTSTRAP_PASSWORDS
        if generated:
            password = secrets.token_urlsafe(18)
        actor_id = str(uuid.uuid4())
        now = utcnow()
        with self.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO actors (id, type, name, created_at, disabled_at)"
                    " VALUES (:id, 'user', :name, :now, NULL)"
                ),
                {"id": actor_id, "name": self.settings.bootstrap_username, "now": now},
            )
            conn.execute(
                text(
                    "INSERT INTO user_credentials (actor_id, password_hash, updated_at, role)"
                    " VALUES (:id, :hash, :now, :role)"
                ),
                {
                    "id": actor_id,
                    "hash": hash_password(password),
                    "now": now,
                    "role": ROLE_ADMIN,
                },
            )
        if generated:
            path = Path(self.settings.data_dir) / BOOTSTRAP_PASSWORD_FILE_NAME
            write_private_file(path, f"{password}\n")
            logger.warning(
                "TRALALA_BOOTSTRAP_PASSWORD was unset or a published placeholder; generated a "
                "one-time administrator password in %s (delete the file after first sign-in)",
                path,
            )

    def actor(self, actor_id: str) -> dict[str, Any] | None:
        return self.read_one(
            "SELECT * FROM actors WHERE id = :id AND disabled_at IS NULL", {"id": actor_id}
        )

    def user_by_name(self, name: str) -> dict[str, Any] | None:
        return self.read_one(
            "SELECT a.*, c.password_hash, c.role FROM actors a"
            " JOIN user_credentials c ON c.actor_id = a.id"
            " WHERE a.name = :name AND a.type = 'user' AND a.disabled_at IS NULL",
            {"name": name},
        )

    def user_by_id(self, actor_id: str) -> dict[str, Any] | None:
        return self.read_one(
            "SELECT a.*, c.password_hash, c.role FROM actors a"
            " JOIN user_credentials c ON c.actor_id = a.id"
            " WHERE a.id = :id AND a.type = 'user'",
            {"id": actor_id},
        )

    def list_users(self) -> list[dict[str, Any]]:
        return self.read(
            "SELECT a.id, a.name, a.created_at, a.disabled_at, c.role, c.updated_at"
            " FROM actors a JOIN user_credentials c ON c.actor_id = a.id"
            " WHERE a.type = 'user' ORDER BY a.created_at, a.name"
        )

    def create_user(self, *, name: str, password_hash: str, role: str) -> dict[str, Any]:
        actor_id = str(uuid.uuid4())
        now = utcnow()
        with self.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO actors (id, type, name, created_at, disabled_at)"
                    " VALUES (:id, 'user', :name, :now, NULL)"
                ),
                {"id": actor_id, "name": name, "now": now},
            )
            conn.execute(
                text(
                    "INSERT INTO user_credentials (actor_id, password_hash, updated_at, role)"
                    " VALUES (:id, :hash, :now, :role)"
                ),
                {"id": actor_id, "hash": password_hash, "now": now, "role": role},
            )
        return {"id": actor_id, "name": name, "role": role, "created_at": now}

    def set_user_role(self, actor_id: str, role: str) -> None:
        with self.connect() as conn:
            conn.execute(
                text(
                    "UPDATE user_credentials SET role = :role"
                    " WHERE actor_id = :id AND role != :role"
                ),
                {"id": actor_id, "role": role},
            )

    def set_user_password(self, actor_id: str, password_hash: str) -> None:
        with self.connect() as conn:
            conn.execute(
                text(
                    "UPDATE user_credentials SET password_hash = :hash, updated_at = :now"
                    " WHERE actor_id = :id"
                ),
                {"id": actor_id, "hash": password_hash, "now": utcnow()},
            )

    def enable_actor(self, actor_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                text("UPDATE actors SET disabled_at = NULL WHERE id = :id"), {"id": actor_id}
            )

    def user_preferences(self, actor_id: str) -> dict[str, Any]:
        row = self.read_one(
            "SELECT theme_mode, theme_kit FROM user_credentials WHERE actor_id = :id",
            {"id": actor_id},
        )
        return row or {"theme_mode": None, "theme_kit": None}

    def set_user_preferences(
        self, actor_id: str, *, theme_mode: str | None, theme_kit: str | None
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                text(
                    "UPDATE user_credentials SET theme_mode = :mode, theme_kit = :kit,"
                    " updated_at = :now WHERE actor_id = :id"
                ),
                {
                    "id": actor_id,
                    "mode": theme_mode,
                    "kit": theme_kit,
                    "now": utcnow(),
                },
            )

    def count_admins(self, *, exclude: str | None = None) -> int:
        row = self.read_one(
            "SELECT COUNT(*) AS total FROM actors a JOIN user_credentials c ON c.actor_id = a.id"
            " WHERE a.type = 'user' AND a.disabled_at IS NULL AND c.role = 'admin'"
            " AND a.id != :exclude",
            {"exclude": exclude or ""},
        )
        return int(row["total"]) if row else 0

    # --- enrolment invites -----------------------------------------------------

    def create_invite(
        self,
        *,
        actor_id: str,
        token_hash: str,
        created_by_actor_id: str,
        expires_at: str,
    ) -> dict[str, Any]:
        invite_id = str(uuid.uuid4())
        now = utcnow()
        with self.connect() as conn:
            # One live invite per account: a new link replaces an unused older one.
            conn.execute(
                text("DELETE FROM user_invites WHERE actor_id = :id AND used_at IS NULL"),
                {"id": actor_id},
            )
            conn.execute(
                text(
                    "INSERT INTO user_invites (id, actor_id, token_hash, created_by_actor_id,"
                    " created_at, expires_at, used_at)"
                    " VALUES (:id, :actor_id, :token_hash, :created_by, :now, :expires_at, NULL)"
                ),
                {
                    "id": invite_id,
                    "actor_id": actor_id,
                    "token_hash": token_hash,
                    "created_by": created_by_actor_id,
                    "now": now,
                    "expires_at": expires_at,
                },
            )
        return {
            "id": invite_id,
            "actor_id": actor_id,
            "created_at": now,
            "expires_at": expires_at,
        }

    def invite_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        return self.read_one(
            "SELECT i.*, a.name, a.disabled_at FROM user_invites i"
            " JOIN actors a ON a.id = i.actor_id WHERE i.token_hash = :hash",
            {"hash": token_hash},
        )

    def mark_invite_used(self, invite_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                text("UPDATE user_invites SET used_at = :now WHERE id = :id"),
                {"id": invite_id, "now": utcnow()},
            )

    def pending_invite(self, actor_id: str) -> dict[str, Any] | None:
        return self.read_one(
            "SELECT id, created_at, expires_at FROM user_invites"
            " WHERE actor_id = :id AND used_at IS NULL ORDER BY created_at DESC LIMIT 1",
            {"id": actor_id},
        )

    # --- sessions ---------------------------------------------------------------

    def create_session(
        self, *, token_hash: str, actor_id: str, expires_at: str
    ) -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        now = utcnow()
        with self.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO sessions"
                    " (id, token_hash, actor_id, created_at, expires_at, last_seen_at, revoked_at)"
                    " VALUES (:id, :hash, :actor_id, :now, :expires_at, :now, NULL)"
                ),
                {
                    "id": session_id,
                    "hash": token_hash,
                    "actor_id": actor_id,
                    "now": now,
                    "expires_at": expires_at,
                },
            )
        return {"id": session_id, "expires_at": expires_at}

    def session_by_hash(self, token_hash: str) -> dict[str, Any] | None:
        return self.read_one(
            "SELECT s.*, a.type AS actor_type, a.name AS actor_name, a.disabled_at, c.role"
            " FROM sessions s JOIN actors a ON a.id = s.actor_id"
            " LEFT JOIN user_credentials c ON c.actor_id = a.id"
            " WHERE s.token_hash = :hash",
            {"hash": token_hash},
        )

    def touch_session(self, session_id: str, *, min_interval_seconds: int = 300) -> None:
        now = utcnow()
        with self.connect() as conn:
            conn.execute(
                text(
                    "UPDATE sessions SET last_seen_at = :now WHERE id = :id"
                    " AND last_seen_at < :threshold"
                ),
                {
                    "id": session_id,
                    "now": now,
                    "threshold": _shift_iso(now, -min_interval_seconds),
                },
            )

    def revoke_session(self, token_hash: str) -> bool:
        with self.connect() as conn:
            result = conn.execute(
                text(
                    "UPDATE sessions SET revoked_at = :now"
                    " WHERE token_hash = :hash AND revoked_at IS NULL"
                ),
                {"hash": token_hash, "now": utcnow()},
            )
            return result.rowcount > 0

    def revoke_actor_sessions(self, actor_id: str) -> int:
        with self.connect() as conn:
            result = conn.execute(
                text(
                    "UPDATE sessions SET revoked_at = :now"
                    " WHERE actor_id = :id AND revoked_at IS NULL"
                ),
                {"id": actor_id, "now": utcnow()},
            )
            return int(result.rowcount or 0)

    def purge_expired_sessions(self) -> int:
        with self.connect() as conn:
            result = conn.execute(
                text("DELETE FROM sessions WHERE expires_at < :now OR revoked_at IS NOT NULL"),
                {"now": utcnow()},
            )
            return int(result.rowcount or 0)

    def create_actor(self, *, type_: str, name: str) -> dict[str, Any]:
        actor_id = str(uuid.uuid4())
        now = utcnow()
        with self.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO actors (id, type, name, created_at)"
                    " VALUES (:id, :type, :name, :now)"
                ),
                {"id": actor_id, "type": type_, "name": name, "now": now},
            )
        return {"id": actor_id, "type": type_, "name": name, "created_at": now}

    def disable_actor(self, actor_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                text("UPDATE actors SET disabled_at = :now WHERE id = :id AND disabled_at IS NULL"),
                {"id": actor_id, "now": utcnow()},
            )

    def create_credential(
        self,
        *,
        actor_id: str,
        name: str,
        token_hash: str,
        scopes: list[str],
        expires_at: str | None,
        owner_actor_id: str | None = None,
    ) -> dict[str, Any]:
        credential_id = str(uuid.uuid4())
        now = utcnow()
        with self.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO api_credentials"
                    " (id, actor_id, owner_actor_id, name, token_hash, scopes, created_at,"
                    "  expires_at)"
                    " VALUES (:id, :actor_id, :owner, :name, :token_hash, :scopes, :now,"
                    " :expires_at)"
                ),
                {
                    "id": credential_id,
                    "actor_id": actor_id,
                    "owner": owner_actor_id,
                    "name": name,
                    "token_hash": token_hash,
                    "scopes": json.dumps(scopes),
                    "now": now,
                    "expires_at": expires_at,
                },
            )
        return {
            "id": credential_id,
            "actor_id": actor_id,
            "owner_actor_id": owner_actor_id,
            "name": name,
            "scopes": scopes,
            "created_at": now,
            "expires_at": expires_at,
            "revoked_at": None,
            "last_used_at": None,
        }

    def list_credentials(self, owner_actor_id: str | None = None) -> list[dict[str, Any]]:
        """Tokens with their owner; ``owner_actor_id`` narrows the list to one person."""
        clause = " WHERE c.owner_actor_id = :owner" if owner_actor_id else ""
        rows = self.read(
            "SELECT c.id, c.actor_id, c.owner_actor_id, a.name AS actor_name,"
            " o.name AS owner_name, c.name, c.scopes, c.created_at,"
            " c.expires_at, c.last_used_at, c.revoked_at"
            " FROM api_credentials c JOIN actors a ON a.id = c.actor_id"
            " LEFT JOIN actors o ON o.id = c.owner_actor_id"
            f"{clause}"
            " ORDER BY c.created_at DESC",
            {"owner": owner_actor_id} if owner_actor_id else {},
        )
        for row in rows:
            row["scopes"] = json.loads(row["scopes"])
        return rows

    def credential(self, credential_id: str) -> dict[str, Any] | None:
        return self.read_one(
            "SELECT c.*, a.name AS actor_name FROM api_credentials c"
            " JOIN actors a ON a.id = c.actor_id WHERE c.id = :id",
            {"id": credential_id},
        )

    def credential_owner_counts(self) -> dict[str, dict[str, Any]]:
        """Live token count and last use per owner, for the user list."""
        rows = self.read(
            "SELECT owner_actor_id, COUNT(*) AS live, MAX(last_used_at) AS last_used_at"
            " FROM api_credentials"
            " WHERE owner_actor_id IS NOT NULL AND revoked_at IS NULL"
            " GROUP BY owner_actor_id"
        )
        return {str(row["owner_actor_id"]): row for row in rows}

    def revoke_credentials_by_owner(self, owner_actor_id: str) -> list[str]:
        """Revoke every live token one person issued; returns the agent actor ids behind them."""
        now = utcnow()
        with self.connect() as conn:
            actor_ids = [
                str(record[0])
                for record in conn.execute(
                    text(
                        "SELECT actor_id FROM api_credentials"
                        " WHERE owner_actor_id = :owner AND revoked_at IS NULL"
                    ),
                    {"owner": owner_actor_id},
                )
            ]
            conn.execute(
                text(
                    "UPDATE api_credentials SET revoked_at = :now"
                    " WHERE owner_actor_id = :owner AND revoked_at IS NULL"
                ),
                {"owner": owner_actor_id, "now": now},
            )
            for actor_id in actor_ids:
                conn.execute(
                    text(
                        "UPDATE actors SET disabled_at = :now"
                        " WHERE id = :id AND disabled_at IS NULL"
                    ),
                    {"id": actor_id, "now": now},
                )
        return actor_ids

    def credential_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        return self.read_one(
            "SELECT c.*, a.type AS actor_type, a.name AS actor_name, a.disabled_at"
            " FROM api_credentials c JOIN actors a ON a.id = c.actor_id"
            " WHERE c.token_hash = :hash",
            {"hash": token_hash},
        )

    def touch_credential(self, credential_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                text("UPDATE api_credentials SET last_used_at = :now WHERE id = :id"),
                {"id": credential_id, "now": utcnow()},
            )

    def revoke_credential(self, credential_id: str) -> bool:
        with self.connect() as conn:
            result = conn.execute(
                text(
                    "UPDATE api_credentials SET revoked_at = :now"
                    " WHERE id = :id AND revoked_at IS NULL"
                ),
                {"id": credential_id, "now": utcnow()},
            )
            return result.rowcount > 0

    # --- boards -----------------------------------------------------------------

    def list_board_rows(self) -> list[dict[str, Any]]:
        return self.read("SELECT * FROM boards ORDER BY updated_at DESC, name")

    def board(self, board_id: str) -> dict[str, Any] | None:
        return self.read_one("SELECT * FROM boards WHERE id = :id", {"id": board_id})

    def insert_board(
        self, board_id: str, name: str, description: str, status: str, schema_version: int
    ) -> None:
        now = utcnow()
        with self.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO boards"
                    " (id, name, description, status, created_at, updated_at, archived_at,"
                    "  schema_version)"
                    " VALUES (:id, :name, :description, :status, :now, :now, NULL, :version)"
                ),
                {
                    "id": board_id,
                    "name": name,
                    "description": description,
                    "status": status,
                    "now": now,
                    "version": schema_version,
                },
            )

    def update_board(self, board_id: str, **fields: Any) -> None:
        allowed = {
            "name",
            "description",
            "status",
            "archived_at",
            "schema_version",
            "schema_revision",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        updates["updated_at"] = utcnow()
        assignments = ", ".join(f"{key} = :{key}" for key in updates)
        with self.connect() as conn:
            conn.execute(
                text(f"UPDATE boards SET {assignments} WHERE id = :board_id"),
                {**updates, "board_id": board_id},
            )

    def delete_board_row(self, board_id: str) -> None:
        with self.connect() as conn:
            conn.execute(text("DELETE FROM boards WHERE id = :id"), {"id": board_id})

    # --- board counters ----------------------------------------------------------

    def board_stats(self, board_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not board_ids:
            return {}
        placeholders = ", ".join(f":id{index}" for index in range(len(board_ids)))
        params = {f"id{index}": value for index, value in enumerate(board_ids)}
        rows = self.read(f"SELECT * FROM board_stats WHERE board_id IN ({placeholders})", params)
        return {row["board_id"]: row for row in rows}

    def store_board_stats(
        self, board_id: str, loop_count: int, list_count: int, card_count: int, *, measured_at: str
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO board_stats"
                    " (board_id, loop_count, list_count, card_count, measured_at)"
                    " VALUES (:id, :loops, :lists, :cards, :measured_at)"
                    " ON CONFLICT(board_id) DO UPDATE SET"
                    "  loop_count = excluded.loop_count,"
                    "  list_count = excluded.list_count,"
                    "  card_count = excluded.card_count,"
                    "  measured_at = excluded.measured_at"
                ),
                {
                    "id": board_id,
                    "loops": loop_count,
                    "lists": list_count,
                    "cards": card_count,
                    "measured_at": measured_at,
                },
            )

    def forget_board_stats(self, board_id: str) -> None:
        with self.connect() as conn:
            conn.execute(text("DELETE FROM board_stats WHERE board_id = :id"), {"id": board_id})

    def forget_all_board_stats(self) -> None:
        with self.connect() as conn:
            conn.execute(text("DELETE FROM board_stats"))

    def dispose(self) -> None:
        self.engine.dispose()
