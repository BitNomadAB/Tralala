"""The account repositories over SQLAlchemy.

A joined read selects each table's whole row: the first table under its own column names, every
joined one under a prefix (``sql.column_list(..., prefix=...)``), read back through
``values.prefixed``, so two tables' ``id`` or ``name`` never share a result key.
"""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection, RowMapping

from ...core import sql
from ...db import values
from ...db.generated.registry import (
    ACTORS_COLUMNS,
    API_CREDENTIALS_COLUMNS,
    SESSIONS_COLUMNS,
    USER_CREDENTIALS_COLUMNS,
    USER_INVITES_COLUMNS,
    ActorsRow,
    ApiCredentialsRow,
    SessionsRow,
    UserCredentialsRow,
    UserInvitesRow,
)
from ..accounts import ActorSession, Invitation, IssuedToken, OwnerTokens, User

_ACTOR = "actor__"
_SIGN_IN = "credentials__"
_ROLE = "user__role"
_OWNER_NAME = "owner__name"

# --- actors --------------------------------------------------------------------------------------

_ANY_USER = text("SELECT id FROM actors WHERE type = 'user' LIMIT 1")
_ENABLED_ACTOR = text(
    f"SELECT {sql.column_list(ACTORS_COLUMNS)}"  # noqa: S608 - from generated columns
    " FROM actors WHERE id = :id AND disabled_at IS NULL"
)
_MANY_ACTORS = text(
    f"SELECT {sql.column_list(ACTORS_COLUMNS)}"  # noqa: S608 - from generated columns
    " FROM actors WHERE id IN :ids"
).bindparams(bindparam("ids", expanding=True))
_ADD_ACTOR = text(
    "INSERT INTO actors (id, type, name, created_at, disabled_at)"
    " VALUES (:id, :type, :name, :created_at, :disabled_at)"
)
_DISABLE_ACTOR = text(
    "UPDATE actors SET disabled_at = :now WHERE id = :id AND disabled_at IS NULL"
)
_ENABLE_ACTOR = text("UPDATE actors SET disabled_at = NULL WHERE id = :id")

# --- users ---------------------------------------------------------------------------------------

_USER = (
    f"SELECT {sql.column_list(ACTORS_COLUMNS, 'a')},"  # noqa: S608 - from generated columns
    f" {sql.column_list(USER_CREDENTIALS_COLUMNS, 'c', _SIGN_IN)}"
    " FROM actors a JOIN user_credentials c ON c.actor_id = a.id"
)
_USER_BY_ID = text(f"{_USER} WHERE a.id = :id AND a.type = 'user'")
_ENABLED_USER_BY_NAME = text(
    f"{_USER} WHERE a.name = :name AND a.type = 'user' AND a.disabled_at IS NULL"
)
_ALL_USERS = text(f"{_USER} WHERE a.type = 'user' ORDER BY a.created_at, a.name")
_SIGN_IN_RECORD = text(
    f"SELECT {sql.column_list(USER_CREDENTIALS_COLUMNS)}"  # noqa: S608 - from generated columns
    " FROM user_credentials WHERE actor_id = :id"
)
_ADD_SIGN_IN = text(
    "INSERT INTO user_credentials"
    " (actor_id, password_hash, updated_at, role, theme_mode, theme_kit)"
    " VALUES (:actor_id, :password_hash, :updated_at, :role, :theme_mode, :theme_kit)"
)
_SET_ROLE = text(
    "UPDATE user_credentials SET role = :role WHERE actor_id = :id AND role != :role"
)
_SET_PASSWORD = text(
    "UPDATE user_credentials SET password_hash = :hash, updated_at = :now WHERE actor_id = :id"
)
_SET_PREFERENCES = text(
    "UPDATE user_credentials SET theme_mode = :mode, theme_kit = :kit, updated_at = :now"
    " WHERE actor_id = :id"
)
_COUNT_ENABLED_ADMINS = text(
    "SELECT COUNT(*) AS total FROM actors a JOIN user_credentials c ON c.actor_id = a.id"
    " WHERE a.type = 'user' AND a.disabled_at IS NULL AND c.role = 'admin'"
    " AND a.id != :exclude"
)

# --- sessions ------------------------------------------------------------------------------------

_SESSION_BY_HASH = text(
    f"SELECT {sql.column_list(SESSIONS_COLUMNS, 's')},"  # noqa: S608 - from generated columns
    f" {sql.column_list(ACTORS_COLUMNS, 'a', _ACTOR)}, c.role AS {_ROLE}"
    " FROM sessions s JOIN actors a ON a.id = s.actor_id"
    " LEFT JOIN user_credentials c ON c.actor_id = a.id"
    " WHERE s.token_hash = :hash"
)
_ADD_SESSION = text(
    "INSERT INTO sessions"
    " (id, token_hash, actor_id, created_at, expires_at, last_seen_at, revoked_at)"
    " VALUES (:id, :token_hash, :actor_id, :created_at, :expires_at, :last_seen_at, :revoked_at)"
)
_TOUCH_SESSION = text(
    "UPDATE sessions SET last_seen_at = :now WHERE id = :id AND last_seen_at < :threshold"
)
_REVOKE_SESSION = text(
    "UPDATE sessions SET revoked_at = :now WHERE token_hash = :hash AND revoked_at IS NULL"
)
_REVOKE_ACTOR_SESSIONS = text(
    "UPDATE sessions SET revoked_at = :now WHERE actor_id = :id AND revoked_at IS NULL"
)
_PURGE_SESSIONS = text("DELETE FROM sessions WHERE expires_at < :now OR revoked_at IS NOT NULL")

# --- invitations ---------------------------------------------------------------------------------

_INVITATION_BY_HASH = text(
    f"SELECT {sql.column_list(USER_INVITES_COLUMNS, 'i')},"  # noqa: S608 - from generated columns
    f" {sql.column_list(ACTORS_COLUMNS, 'a', _ACTOR)}"
    " FROM user_invites i JOIN actors a ON a.id = i.actor_id WHERE i.token_hash = :hash"
)
_ADD_INVITE = text(
    "INSERT INTO user_invites"
    " (id, actor_id, token_hash, created_by_actor_id, created_at, expires_at, used_at)"
    " VALUES (:id, :actor_id, :token_hash, :created_by_actor_id, :created_at, :expires_at,"
    "         :used_at)"
)
_DELETE_UNUSED_INVITES = text(
    "DELETE FROM user_invites WHERE actor_id = :id AND used_at IS NULL"
)
_MARK_INVITE_USED = text("UPDATE user_invites SET used_at = :now WHERE id = :id")

# --- API tokens ----------------------------------------------------------------------------------

_TOKEN = (
    f"SELECT {sql.column_list(API_CREDENTIALS_COLUMNS, 'c')},"  # noqa: S608 - from generated columns
    f" {sql.column_list(ACTORS_COLUMNS, 'a', _ACTOR)}, o.name AS {_OWNER_NAME}"
    " FROM api_credentials c JOIN actors a ON a.id = c.actor_id"
    " LEFT JOIN actors o ON o.id = c.owner_actor_id"
)
_TOKEN_BY_ID = text(f"{_TOKEN} WHERE c.id = :id")
_TOKEN_BY_HASH = text(f"{_TOKEN} WHERE c.token_hash = :hash")
_TOKENS = text(f"{_TOKEN} ORDER BY c.created_at DESC")
_TOKENS_OF_OWNER = text(f"{_TOKEN} WHERE c.owner_actor_id = :owner ORDER BY c.created_at DESC")
_OWNER_COUNTS = text(
    "SELECT owner_actor_id, COUNT(*) AS live, MAX(last_used_at) AS last_used_at"
    " FROM api_credentials WHERE owner_actor_id IS NOT NULL AND revoked_at IS NULL"
    " GROUP BY owner_actor_id"
)
_ADD_TOKEN = text(
    "INSERT INTO api_credentials"
    " (id, actor_id, owner_actor_id, name, token_hash, scopes, created_at, expires_at,"
    "  last_used_at, revoked_at)"
    " VALUES (:id, :actor_id, :owner_actor_id, :name, :token_hash, :scopes, :created_at,"
    "         :expires_at, :last_used_at, :revoked_at)"
)
_TOUCH_TOKEN = text("UPDATE api_credentials SET last_used_at = :now WHERE id = :id")
_REVOKE_TOKEN = text(
    "UPDATE api_credentials SET revoked_at = :now WHERE id = :id AND revoked_at IS NULL"
)
_LIVE_TOKEN_ACTORS = text(
    "SELECT actor_id FROM api_credentials WHERE owner_actor_id = :owner AND revoked_at IS NULL"
)
_REVOKE_OWNER_TOKENS = text(
    "UPDATE api_credentials SET revoked_at = :now"
    " WHERE owner_actor_id = :owner AND revoked_at IS NULL"
)


def _user(row: RowMapping) -> User:
    return User(
        actor=ActorsRow.from_mapping(row),
        credentials=UserCredentialsRow.from_mapping(values.prefixed(row, _SIGN_IN)),
    )


def _issued(row: RowMapping) -> IssuedToken:
    return IssuedToken(
        credential=ApiCredentialsRow.from_mapping(row),
        actor=ActorsRow.from_mapping(values.prefixed(row, _ACTOR)),
        owner_name=values.text_or_none(row, _OWNER_NAME),
    )


class SqlActorRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def any_user(self) -> bool:
        return self._connection.execute(_ANY_USER).first() is not None

    def enabled(self, actor_id: str) -> ActorsRow | None:
        row = self._connection.execute(_ENABLED_ACTOR, {"id": actor_id}).mappings().first()
        return None if row is None else ActorsRow.from_mapping(row)

    def many(self, actor_ids: Collection[str]) -> dict[str, ActorsRow]:
        if not actor_ids:
            return {}
        result = self._connection.execute(_MANY_ACTORS, {"ids": list(actor_ids)}).mappings()
        rows = [ActorsRow.from_mapping(row) for row in result]
        return {row.id: row for row in rows}

    def add(self, row: ActorsRow) -> None:
        self._connection.execute(
            _ADD_ACTOR,
            {
                "id": row.id,
                "type": row.type,
                "name": row.name,
                "created_at": row.created_at,
                "disabled_at": row.disabled_at,
            },
        )

    def disable(self, actor_id: str, *, now: str) -> None:
        self._connection.execute(_DISABLE_ACTOR, {"id": actor_id, "now": now})

    def enable(self, actor_id: str) -> None:
        self._connection.execute(_ENABLE_ACTOR, {"id": actor_id})


class SqlUserRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, actor_id: str) -> User | None:
        row = self._connection.execute(_USER_BY_ID, {"id": actor_id}).mappings().first()
        return None if row is None else _user(row)

    def enabled_by_name(self, name: str) -> User | None:
        result = self._connection.execute(_ENABLED_USER_BY_NAME, {"name": name})
        row = result.mappings().first()
        return None if row is None else _user(row)

    def all(self) -> list[User]:
        return [_user(row) for row in self._connection.execute(_ALL_USERS).mappings()]

    def credentials(self, actor_id: str) -> UserCredentialsRow | None:
        row = self._connection.execute(_SIGN_IN_RECORD, {"id": actor_id}).mappings().first()
        return None if row is None else UserCredentialsRow.from_mapping(row)

    def add(self, row: UserCredentialsRow) -> None:
        self._connection.execute(
            _ADD_SIGN_IN,
            {
                "actor_id": row.actor_id,
                "password_hash": row.password_hash,
                "updated_at": row.updated_at,
                "role": row.role,
                "theme_mode": row.theme_mode,
                "theme_kit": row.theme_kit,
            },
        )

    def set_role(self, actor_id: str, role: str) -> None:
        self._connection.execute(_SET_ROLE, {"id": actor_id, "role": role})

    def set_password(self, actor_id: str, password_hash: str, *, now: str) -> None:
        self._connection.execute(
            _SET_PASSWORD, {"id": actor_id, "hash": password_hash, "now": now}
        )

    def set_preferences(
        self, actor_id: str, *, theme_mode: str | None, theme_kit: str | None, now: str
    ) -> None:
        self._connection.execute(
            _SET_PREFERENCES, {"id": actor_id, "mode": theme_mode, "kit": theme_kit, "now": now}
        )

    def count_enabled_admins(self, *, exclude: str) -> int:
        result = self._connection.execute(_COUNT_ENABLED_ADMINS, {"exclude": exclude})
        return values.integer(result.mappings().one(), "total")


class SqlSessionRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def add(self, row: SessionsRow) -> None:
        self._connection.execute(
            _ADD_SESSION,
            {
                "id": row.id,
                "token_hash": row.token_hash,
                "actor_id": row.actor_id,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "last_seen_at": row.last_seen_at,
                "revoked_at": row.revoked_at,
            },
        )

    def by_token_hash(self, token_hash: str) -> ActorSession | None:
        result = self._connection.execute(_SESSION_BY_HASH, {"hash": token_hash})
        row = result.mappings().first()
        if row is None:
            return None
        return ActorSession(
            session=SessionsRow.from_mapping(row),
            actor=ActorsRow.from_mapping(values.prefixed(row, _ACTOR)),
            role=values.text_or_none(row, _ROLE),
        )

    def touch(self, session_id: str, *, now: str, seen_before: str) -> None:
        self._connection.execute(
            _TOUCH_SESSION, {"id": session_id, "now": now, "threshold": seen_before}
        )

    def revoke(self, token_hash: str, *, now: str) -> bool:
        result = self._connection.execute(_REVOKE_SESSION, {"hash": token_hash, "now": now})
        return result.rowcount > 0

    def revoke_for_actor(self, actor_id: str, *, now: str) -> int:
        result = self._connection.execute(_REVOKE_ACTOR_SESSIONS, {"id": actor_id, "now": now})
        return result.rowcount

    def purge(self, *, now: str) -> int:
        return self._connection.execute(_PURGE_SESSIONS, {"now": now}).rowcount


class SqlInviteRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def by_token_hash(self, token_hash: str) -> Invitation | None:
        result = self._connection.execute(_INVITATION_BY_HASH, {"hash": token_hash})
        row = result.mappings().first()
        if row is None:
            return None
        return Invitation(
            invite=UserInvitesRow.from_mapping(row),
            actor=ActorsRow.from_mapping(values.prefixed(row, _ACTOR)),
        )

    def add(self, row: UserInvitesRow) -> None:
        self._connection.execute(
            _ADD_INVITE,
            {
                "id": row.id,
                "actor_id": row.actor_id,
                "token_hash": row.token_hash,
                "created_by_actor_id": row.created_by_actor_id,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "used_at": row.used_at,
            },
        )

    def delete_unused(self, actor_id: str) -> None:
        self._connection.execute(_DELETE_UNUSED_INVITES, {"id": actor_id})

    def mark_used(self, invite_id: str, *, now: str) -> None:
        self._connection.execute(_MARK_INVITE_USED, {"id": invite_id, "now": now})


class SqlCredentialRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, credential_id: str) -> IssuedToken | None:
        row = self._connection.execute(_TOKEN_BY_ID, {"id": credential_id}).mappings().first()
        return None if row is None else _issued(row)

    def by_token_hash(self, token_hash: str) -> IssuedToken | None:
        row = self._connection.execute(_TOKEN_BY_HASH, {"hash": token_hash}).mappings().first()
        return None if row is None else _issued(row)

    def listing(self, owner_actor_id: str | None) -> list[IssuedToken]:
        if owner_actor_id is None:
            result = self._connection.execute(_TOKENS)
        else:
            result = self._connection.execute(_TOKENS_OF_OWNER, {"owner": owner_actor_id})
        return [_issued(row) for row in result.mappings()]

    def owner_counts(self) -> dict[str, OwnerTokens]:
        return {
            values.text(row, "owner_actor_id"): OwnerTokens(
                live=values.integer(row, "live"),
                last_used_at=values.text_or_none(row, "last_used_at"),
            )
            for row in self._connection.execute(_OWNER_COUNTS).mappings()
        }

    def add(self, row: ApiCredentialsRow) -> None:
        self._connection.execute(
            _ADD_TOKEN,
            {
                "id": row.id,
                "actor_id": row.actor_id,
                "owner_actor_id": row.owner_actor_id,
                "name": row.name,
                "token_hash": row.token_hash,
                "scopes": row.scopes,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "last_used_at": row.last_used_at,
                "revoked_at": row.revoked_at,
            },
        )

    def touch(self, credential_id: str, *, now: str) -> None:
        self._connection.execute(_TOUCH_TOKEN, {"id": credential_id, "now": now})

    def revoke(self, credential_id: str, *, now: str) -> bool:
        result = self._connection.execute(_REVOKE_TOKEN, {"id": credential_id, "now": now})
        return result.rowcount > 0

    def live_actor_ids(self, owner_actor_id: str) -> list[str]:
        result = self._connection.execute(_LIVE_TOKEN_ACTORS, {"owner": owner_actor_id})
        return [values.text(row, "actor_id") for row in result.mappings()]

    def revoke_by_owner(self, owner_actor_id: str, *, now: str) -> None:
        self._connection.execute(_REVOKE_OWNER_TOKENS, {"owner": owner_actor_id, "now": now})
