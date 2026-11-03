"""The registry database in memory: its repositories and their unit of work."""

from __future__ import annotations

import re
import string
from collections.abc import Collection, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.db.generated.registry import (
    ActorsRow,
    AgentsRow,
    ApiCredentialsRow,
    BoardAgentsRow,
    BoardRepositoriesRow,
    BoardsRow,
    BoardStatsRow,
    BoardTemplatesRow,
    IdempotencyRecordsRow,
    RepositoriesRow,
    RoleTemplatesRow,
    SessionsRow,
    UserCredentialsRow,
    UserInvitesRow,
)
from app.repositories.accounts import (
    ActorRepository,
    ActorSession,
    CredentialRepository,
    Invitation,
    InviteRepository,
    IssuedToken,
    OwnerTokens,
    SessionRepository,
    User,
    UserRepository,
)
from app.repositories.agents import (
    AgentChanges,
    AgentLinkRepository,
    AgentRepository,
    RoleTemplateChanges,
    RoleTemplateRepository,
)
from app.repositories.board_rows import (
    BOARD_SORTS,
    BoardChanges,
    BoardRowRepository,
    BoardStatsRepository,
)
from app.repositories.code_repositories import (
    CodeRepositoryRepository,
    LinkedBoard,
    MirrorRecord,
    RepositoryChanges,
    RepositoryLinkRepository,
)
from app.repositories.errors import ConstraintViolationError
from app.repositories.idempotency import RegistryIdempotencyRepository
from app.repositories.registry import RegistryUnitOfWork
from app.repositories.templates import BoardTemplateRepository

CREATED = "2026-11-01T09:00:00Z"


class ConstraintError(Exception):
    """What SQLite would refuse (a primary, unique or foreign key) where no service expects it:
    a test that sees it found a bug. A taken unique name raises ``ConstraintViolationError``, as the
    SQL repositories do, because the services answer that one."""


_ASCII_FOLD = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


def nocase(text: str) -> str:
    """SQLite's NOCASE collation: the 26 ASCII capitals fold to lower case, nothing else does."""
    return text.translate(_ASCII_FOLD)


def like(value: str, pattern: str) -> bool:
    """SQLite's ``LIKE``: ``%`` is any run, ``_`` one character, ASCII letters ignore case."""
    parts = [
        ".*" if char == "%" else "." if char == "_" else re.escape(char) for char in nocase(pattern)
    ]
    return re.fullmatch("".join(parts), nocase(value), flags=re.DOTALL) is not None


type LinkKey = tuple[str, str]


@dataclass(slots=True)
class RegistryState:
    """The rows of the registry, as a test sets them up and the services change them.

    Dictionaries keep insertion order, which stands in for SQLite's row order where a statement has
    no ``ORDER BY``. A board link is keyed by ``(board_id, agent_id | repository_id)``, an
    idempotency record by ``(actor_id, idempotency_key)``.
    """

    actors: dict[str, ActorsRow] = field(default_factory=dict[str, ActorsRow])
    sign_ins: dict[str, UserCredentialsRow] = field(default_factory=dict[str, UserCredentialsRow])
    sessions: dict[str, SessionsRow] = field(default_factory=dict[str, SessionsRow])
    invites: dict[str, UserInvitesRow] = field(default_factory=dict[str, UserInvitesRow])
    credentials: dict[str, ApiCredentialsRow] = field(
        default_factory=dict[str, ApiCredentialsRow]
    )
    boards: dict[str, BoardsRow] = field(default_factory=dict[str, BoardsRow])
    board_stats: dict[str, BoardStatsRow] = field(default_factory=dict[str, BoardStatsRow])
    board_templates: dict[str, BoardTemplatesRow] = field(
        default_factory=dict[str, BoardTemplatesRow]
    )
    role_templates: dict[str, RoleTemplatesRow] = field(
        default_factory=dict[str, RoleTemplatesRow]
    )
    agents: dict[str, AgentsRow] = field(default_factory=dict[str, AgentsRow])
    agent_links: dict[LinkKey, BoardAgentsRow] = field(
        default_factory=dict[LinkKey, BoardAgentsRow]
    )
    code_repositories: dict[str, RepositoriesRow] = field(
        default_factory=dict[str, RepositoriesRow]
    )
    repository_links: dict[LinkKey, BoardRepositoriesRow] = field(
        default_factory=dict[LinkKey, BoardRepositoriesRow]
    )
    idempotency: dict[LinkKey, IdempotencyRecordsRow] = field(
        default_factory=dict[LinkKey, IdempotencyRecordsRow]
    )

    def snapshot(self) -> RegistryState:
        return RegistryState(
            dict(self.actors),
            dict(self.sign_ins),
            dict(self.sessions),
            dict(self.invites),
            dict(self.credentials),
            dict(self.boards),
            dict(self.board_stats),
            dict(self.board_templates),
            dict(self.role_templates),
            dict(self.agents),
            dict(self.agent_links),
            dict(self.code_repositories),
            dict(self.repository_links),
            dict(self.idempotency),
        )

    def restore(self, snapshot: RegistryState) -> None:
        self.actors = snapshot.actors
        self.sign_ins = snapshot.sign_ins
        self.sessions = snapshot.sessions
        self.invites = snapshot.invites
        self.credentials = snapshot.credentials
        self.boards = snapshot.boards
        self.board_stats = snapshot.board_stats
        self.board_templates = snapshot.board_templates
        self.role_templates = snapshot.role_templates
        self.agents = snapshot.agents
        self.agent_links = snapshot.agent_links
        self.code_repositories = snapshot.code_repositories
        self.repository_links = snapshot.repository_links
        self.idempotency = snapshot.idempotency


def _require_actor(state: RegistryState, actor_id: str) -> None:
    """The foreign key every account row holds on ``actors``."""
    if actor_id not in state.actors:
        raise ConstraintError(f"actors.id {actor_id} does not exist")


# --- rows for a test to start from ---------------------------------------------------------------


def actor_row(
    actor_id: str,
    *,
    type_: str = "user",
    name: str = "",
    created_at: str = CREATED,
    disabled_at: str | None = None,
) -> ActorsRow:
    return ActorsRow(
        id=actor_id,
        type=type_,
        name=name or f"Actor {actor_id}",
        created_at=created_at,
        disabled_at=disabled_at,
    )


def sign_in_row(
    actor_id: str,
    *,
    password_hash: str = "",
    role: str = "member",
    theme_mode: str | None = None,
    theme_kit: str | None = None,
) -> UserCredentialsRow:
    return UserCredentialsRow(
        actor_id=actor_id,
        password_hash=password_hash or f"hashed:{actor_id}",
        updated_at=CREATED,
        role=role,
        theme_mode=theme_mode,
        theme_kit=theme_kit,
    )


def session_row(
    session_id: str,
    actor_id: str,
    *,
    token_hash: str,
    expires_at: str,
    last_seen_at: str = CREATED,
    revoked_at: str | None = None,
) -> SessionsRow:
    return SessionsRow(
        id=session_id,
        token_hash=token_hash,
        actor_id=actor_id,
        created_at=CREATED,
        expires_at=expires_at,
        last_seen_at=last_seen_at,
        revoked_at=revoked_at,
    )


def credential_row(
    credential_id: str,
    actor_id: str,
    *,
    token_hash: str = "",
    scopes: str = '["boards:read"]',
    owner_actor_id: str | None = None,
    created_at: str = CREATED,
    expires_at: str | None = None,
    last_used_at: str | None = None,
    revoked_at: str | None = None,
) -> ApiCredentialsRow:
    return ApiCredentialsRow(
        id=credential_id,
        actor_id=actor_id,
        name=f"Token {credential_id}",
        token_hash=token_hash or f"digest:{credential_id}",
        scopes=scopes,
        created_at=created_at,
        expires_at=expires_at,
        last_used_at=last_used_at,
        revoked_at=revoked_at,
        owner_actor_id=owner_actor_id,
    )


def invite_row(
    invite_id: str,
    actor_id: str,
    *,
    token_hash: str,
    expires_at: str,
    created_by_actor_id: str = "admin",
    used_at: str | None = None,
) -> UserInvitesRow:
    return UserInvitesRow(
        id=invite_id,
        actor_id=actor_id,
        token_hash=token_hash,
        created_by_actor_id=created_by_actor_id,
        created_at=CREATED,
        expires_at=expires_at,
        used_at=used_at,
    )


def board_row(board_id: str, *, name: str = "", status: str = "active") -> BoardsRow:
    return BoardsRow(
        id=board_id,
        name=name or f"Board {board_id}",
        description="",
        status=status,
        created_at=CREATED,
        updated_at=CREATED,
        archived_at=None,
        schema_version=1,
        schema_revision=None,
    )


def role_template_row(
    role_id: str,
    *,
    name: str = "",
    system_prompt: str = "",
    default_system_prompt: str | None = None,
    built_in: bool = False,
    builtin_key: str | None = None,
    scope: str = "board",
    updated_at: str = CREATED,
) -> RoleTemplatesRow:
    prompt = system_prompt or f"You are {role_id}."
    return RoleTemplatesRow(
        id=role_id,
        name=name or f"Role {role_id}",
        description=f"About {role_id}",
        system_prompt=prompt,
        default_system_prompt=prompt if default_system_prompt is None else default_system_prompt,
        built_in=1 if built_in else 0,
        builtin_key=builtin_key,
        created_at=CREATED,
        updated_at=updated_at,
        scope=scope,
    )


def agent_row(
    agent_id: str,
    *,
    name: str = "",
    description: str = "",
    role_template_id: str | None = None,
    role_prompt_override: str | None = None,
    connection_type: str = "openai_compatible",
    base_url: str = "http://10.0.0.5:8080/v1",
    model: str | None = None,
    api_key_ciphertext: str | None = None,
    api_key_hint: str | None = None,
    timeout_seconds: int = 30,
    enabled: bool = True,
    supports_json_schema: bool = False,
) -> AgentsRow:
    return AgentsRow(
        id=agent_id,
        name=name or f"Agent {agent_id}",
        description=description,
        role_template_id=role_template_id,
        role_prompt_override=role_prompt_override,
        connection_type=connection_type,
        base_url=base_url,
        model=model,
        api_key_ciphertext=api_key_ciphertext,
        api_key_hint=api_key_hint,
        temperature=None,
        max_output_tokens=None,
        timeout_seconds=timeout_seconds,
        enabled=1 if enabled else 0,
        last_test_status=None,
        last_test_message=None,
        last_tested_at=None,
        created_at=CREATED,
        updated_at=CREATED,
        supports_json_schema=1 if supports_json_schema else 0,
    )


def board_agent_row(board_id: str, agent_id: str, *, created_at: str = CREATED) -> BoardAgentsRow:
    """The link that puts an agent on a board's own list of workers."""
    return BoardAgentsRow(board_id=board_id, agent_id=agent_id, created_at=created_at)


def board_repository_row(
    board_id: str,
    repository_id: str,
    *,
    created_at: str = CREATED,
    focus_paths: str = "[]",
    exclude_paths: str = "[]",
) -> BoardRepositoriesRow:
    """The link that puts a repository on a board, with its globs as the column stores them."""
    return BoardRepositoriesRow(
        board_id=board_id,
        repository_id=repository_id,
        created_at=created_at,
        focus_paths=focus_paths,
        exclude_paths=exclude_paths,
    )


def repository_row(
    repository_id: str,
    *,
    name: str = "",
    url: str = "",
    branch: str | None = None,
    token_ciphertext: str | None = None,
    token_hint: str | None = None,
    enabled: bool = True,
    provider: str = "github",
) -> RepositoriesRow:
    return RepositoriesRow(
        id=repository_id,
        name=name or f"Repository {repository_id}",
        provider=provider,
        url=url or f"https://github.com/acme/{repository_id}",
        branch=branch,
        token_ciphertext=token_ciphertext,
        token_hint=token_hint,
        enabled=1 if enabled else 0,
        last_checked_at=None,
        last_check_status=None,
        last_check_detail=None,
        created_at=CREATED,
        updated_at=CREATED,
        default_branch=None,
        last_sha=None,
        fetched_at=None,
        mirror_bytes=None,
        mirror_error=None,
    )


def board_template_row(
    template_id: str,
    *,
    name: str = "",
    lists_json: str = "[]",
    labels_json: str = "[]",
) -> BoardTemplatesRow:
    return BoardTemplatesRow(
        id=template_id,
        name=name or f"Template {template_id}",
        description="",
        lists_json=lists_json,
        labels_json=labels_json,
        created_at=CREATED,
        updated_at=CREATED,
    )


# --- repositories --------------------------------------------------------------------------------


class FakeActorRepository:
    def __init__(self, state: RegistryState) -> None:
        self._state = state

    def any_user(self) -> bool:
        return any(actor.type == "user" for actor in self._state.actors.values())

    def enabled(self, actor_id: str) -> ActorsRow | None:
        actor = self._state.actors.get(actor_id)
        return actor if actor is not None and actor.disabled_at is None else None

    def many(self, actor_ids: Collection[str]) -> dict[str, ActorsRow]:
        return {
            actor_id: actor
            for actor_id, actor in self._state.actors.items()
            if actor_id in actor_ids
        }

    def add(self, row: ActorsRow) -> None:
        if row.id in self._state.actors:
            raise ConstraintError(f"actors.id {row.id} exists")
        self._state.actors[row.id] = row

    def disable(self, actor_id: str, *, now: str) -> None:
        actor = self._state.actors.get(actor_id)
        if actor is not None and actor.disabled_at is None:
            self._state.actors[actor_id] = actor.__replace__(disabled_at=now)

    def enable(self, actor_id: str) -> None:
        actor = self._state.actors.get(actor_id)
        if actor is not None:
            self._state.actors[actor_id] = actor.__replace__(disabled_at=None)


class FakeUserRepository:
    def __init__(self, state: RegistryState) -> None:
        self._state = state

    def _users(self) -> list[User]:
        return [
            User(actor=actor, credentials=self._state.sign_ins[actor.id])
            for actor in self._state.actors.values()
            if actor.type == "user" and actor.id in self._state.sign_ins
        ]

    def get(self, actor_id: str) -> User | None:
        return next((user for user in self._users() if user.actor.id == actor_id), None)

    def enabled_by_name(self, name: str) -> User | None:
        return next(
            (
                user
                for user in self._users()
                if user.actor.name == name and user.actor.disabled_at is None
            ),
            None,
        )

    def all(self) -> list[User]:
        return sorted(self._users(), key=lambda user: (user.actor.created_at, user.actor.name))

    def credentials(self, actor_id: str) -> UserCredentialsRow | None:
        return self._state.sign_ins.get(actor_id)

    def add(self, row: UserCredentialsRow) -> None:
        _require_actor(self._state, row.actor_id)
        if row.actor_id in self._state.sign_ins:
            raise ConstraintError(f"user_credentials.actor_id {row.actor_id} exists")
        self._state.sign_ins[row.actor_id] = row

    def _change(self, actor_id: str, row: UserCredentialsRow) -> None:
        self._state.sign_ins[actor_id] = row

    def set_role(self, actor_id: str, role: str) -> None:
        row = self._state.sign_ins.get(actor_id)
        if row is not None and row.role != role:
            self._change(actor_id, row.__replace__(role=role))

    def set_password(self, actor_id: str, password_hash: str, *, now: str) -> None:
        row = self._state.sign_ins.get(actor_id)
        if row is not None:
            self._change(actor_id, row.__replace__(password_hash=password_hash, updated_at=now))

    def set_preferences(
        self, actor_id: str, *, theme_mode: str | None, theme_kit: str | None, now: str
    ) -> None:
        row = self._state.sign_ins.get(actor_id)
        if row is not None:
            changed = row.__replace__(theme_mode=theme_mode, theme_kit=theme_kit, updated_at=now)
            self._change(actor_id, changed)

    def count_enabled_admins(self, *, exclude: str) -> int:
        return sum(
            1
            for user in self._users()
            if user.actor.disabled_at is None
            and user.credentials.role == "admin"
            and user.actor.id != exclude
        )


class FakeSessionRepository:
    def __init__(self, state: RegistryState) -> None:
        self._state = state

    def add(self, row: SessionsRow) -> None:
        _require_actor(self._state, row.actor_id)
        if row.id in self._state.sessions:
            raise ConstraintError(f"sessions.id {row.id} exists")
        if any(other.token_hash == row.token_hash for other in self._state.sessions.values()):
            raise ConstraintError("sessions.token_hash is unique")
        self._state.sessions[row.id] = row

    def by_token_hash(self, token_hash: str) -> ActorSession | None:
        for session in self._state.sessions.values():
            actor = self._state.actors.get(session.actor_id)
            if session.token_hash == token_hash and actor is not None:
                sign_in = self._state.sign_ins.get(actor.id)
                role = sign_in.role if sign_in is not None else None
                return ActorSession(session=session, actor=actor, role=role)
        return None

    def touch(self, session_id: str, *, now: str, seen_before: str) -> None:
        session = self._state.sessions.get(session_id)
        if session is not None and session.last_seen_at < seen_before:
            self._state.sessions[session_id] = session.__replace__(last_seen_at=now)

    def _revoke_where(self, wanted: str, *, by_actor: bool, now: str) -> int:
        revoked = 0
        for session_id, session in list(self._state.sessions.items()):
            key = session.actor_id if by_actor else session.token_hash
            if key == wanted and session.revoked_at is None:
                self._state.sessions[session_id] = session.__replace__(revoked_at=now)
                revoked += 1
        return revoked

    def revoke(self, token_hash: str, *, now: str) -> bool:
        return self._revoke_where(token_hash, by_actor=False, now=now) > 0

    def revoke_for_actor(self, actor_id: str, *, now: str) -> int:
        return self._revoke_where(actor_id, by_actor=True, now=now)

    def purge(self, *, now: str) -> int:
        gone = [
            session_id
            for session_id, session in self._state.sessions.items()
            if session.expires_at < now or session.revoked_at is not None
        ]
        for session_id in gone:
            del self._state.sessions[session_id]
        return len(gone)


class FakeInviteRepository:
    def __init__(self, state: RegistryState) -> None:
        self._state = state

    def by_token_hash(self, token_hash: str) -> Invitation | None:
        for invite in self._state.invites.values():
            actor = self._state.actors.get(invite.actor_id)
            if invite.token_hash == token_hash and actor is not None:
                return Invitation(invite=invite, actor=actor)
        return None

    def add(self, row: UserInvitesRow) -> None:
        _require_actor(self._state, row.actor_id)
        if row.id in self._state.invites:
            raise ConstraintError(f"user_invites.id {row.id} exists")
        if any(other.token_hash == row.token_hash for other in self._state.invites.values()):
            raise ConstraintError("user_invites.token_hash is unique")
        self._state.invites[row.id] = row

    def delete_unused(self, actor_id: str) -> None:
        self._state.invites = {
            invite_id: invite
            for invite_id, invite in self._state.invites.items()
            if not (invite.actor_id == actor_id and invite.used_at is None)
        }

    def mark_used(self, invite_id: str, *, now: str) -> None:
        invite = self._state.invites.get(invite_id)
        if invite is not None:
            self._state.invites[invite_id] = invite.__replace__(used_at=now)


class FakeCredentialRepository:
    def __init__(self, state: RegistryState) -> None:
        self._state = state

    def _issued(self, credential: ApiCredentialsRow) -> IssuedToken | None:
        actor = self._state.actors.get(credential.actor_id)
        if actor is None:
            return None
        owner = self._state.actors.get(credential.owner_actor_id or "")
        return IssuedToken(
            credential=credential,
            actor=actor,
            owner_name=owner.name if owner is not None else None,
        )

    def get(self, credential_id: str) -> IssuedToken | None:
        credential = self._state.credentials.get(credential_id)
        return None if credential is None else self._issued(credential)

    def by_token_hash(self, token_hash: str) -> IssuedToken | None:
        for credential in self._state.credentials.values():
            if credential.token_hash == token_hash:
                return self._issued(credential)
        return None

    def listing(self, owner_actor_id: str | None) -> list[IssuedToken]:
        newest_first = sorted(
            self._state.credentials.values(), key=lambda row: row.created_at, reverse=True
        )
        issued = [
            self._issued(credential)
            for credential in newest_first
            if owner_actor_id is None or credential.owner_actor_id == owner_actor_id
        ]
        return [token for token in issued if token is not None]

    def owner_counts(self) -> dict[str, OwnerTokens]:
        counts: dict[str, OwnerTokens] = {}
        for credential in self._state.credentials.values():
            owner = credential.owner_actor_id
            if owner is None or credential.revoked_at is not None:
                continue
            seen = counts.get(owner, OwnerTokens(live=0, last_used_at=None))
            used = [stamp for stamp in (seen.last_used_at, credential.last_used_at) if stamp]
            counts[owner] = OwnerTokens(live=seen.live + 1, last_used_at=max(used, default=None))
        return counts

    def add(self, row: ApiCredentialsRow) -> None:
        _require_actor(self._state, row.actor_id)
        if row.id in self._state.credentials:
            raise ConstraintError(f"api_credentials.id {row.id} exists")
        if any(other.token_hash == row.token_hash for other in self._state.credentials.values()):
            raise ConstraintError("api_credentials.token_hash is unique")
        self._state.credentials[row.id] = row

    def touch(self, credential_id: str, *, now: str) -> None:
        credential = self._state.credentials.get(credential_id)
        if credential is not None:
            self._state.credentials[credential_id] = credential.__replace__(last_used_at=now)

    def revoke(self, credential_id: str, *, now: str) -> bool:
        credential = self._state.credentials.get(credential_id)
        if credential is None or credential.revoked_at is not None:
            return False
        self._state.credentials[credential_id] = credential.__replace__(revoked_at=now)
        return True

    def live_actor_ids(self, owner_actor_id: str) -> list[str]:
        return [
            credential.actor_id
            for credential in self._state.credentials.values()
            if credential.owner_actor_id == owner_actor_id and credential.revoked_at is None
        ]

    def revoke_by_owner(self, owner_actor_id: str, *, now: str) -> None:
        for credential_id in [
            credential.id
            for credential in self._state.credentials.values()
            if credential.owner_actor_id == owner_actor_id and credential.revoked_at is None
        ]:
            self.revoke(credential_id, now=now)


def _board_sort_value(row: BoardsRow, column: str) -> str:
    match column:
        case "name":
            return row.name
        case "status":
            return row.status
        case "created_at":
            return row.created_at
        case _:
            return row.updated_at


class FakeBoardRowRepository:
    def __init__(self, state: RegistryState) -> None:
        self._state = state

    def get(self, board_id: str) -> BoardsRow | None:
        return self._state.boards.get(board_id)

    def _matching(self, status: str | None, contains: str | None) -> list[BoardsRow]:
        pattern = None if contains is None else f"%{contains}%"
        return [
            row
            for row in self._state.boards.values()
            if (status is None or row.status == status)
            and (pattern is None or like(row.name, pattern) or like(row.description, pattern))
        ]

    def count(self, *, status: str | None, contains: str | None) -> int:
        return len(self._matching(status, contains))

    def page(
        self,
        *,
        status: str | None,
        contains: str | None,
        sort: str,
        descending: bool,
        limit: int,
        offset: int,
    ) -> list[BoardsRow]:
        if sort not in BOARD_SORTS:
            raise ValueError(f"{sort!r} is not an allowed SQL identifier")
        rows = self._matching(status, contains)
        # ORDER BY <sort> <direction>, name: two stable sorts, the tie-break first. Every sort
        # column is NOT NULL text compared by code point, as SQLite's BINARY collation does.
        rows.sort(key=lambda row: row.name)
        rows.sort(key=lambda row: _board_sort_value(row, sort), reverse=descending)
        return rows[offset : offset + limit]

    def all(self) -> list[BoardsRow]:
        return list(self._state.boards.values())

    def with_status(self, status: str) -> list[BoardsRow]:
        return [row for row in self._state.boards.values() if row.status == status]

    def most_recent(self, *, status: str, limit: int) -> list[BoardsRow]:
        # ORDER BY updated_at DESC: a stable sort, so equal times keep the table's own order.
        rows = sorted(
            self.with_status(status), key=lambda row: row.updated_at, reverse=True
        )
        return rows[:limit]

    def add(self, row: BoardsRow) -> None:
        if row.id in self._state.boards:
            raise ConstraintError(f"boards.id {row.id} exists")
        self._state.boards[row.id] = row

    def update(self, board_id: str, changes: BoardChanges, *, now: str) -> None:
        if not changes:
            raise ConstraintError("an update without a column is not SQL")
        row = self._state.boards.get(board_id)
        if row is not None:
            self._state.boards[board_id] = row.__replace__(**changes, updated_at=now)

    def delete(self, board_id: str) -> None:
        self._state.boards.pop(board_id, None)
        # ON DELETE CASCADE from every table that references the board.
        self._state.board_stats.pop(board_id, None)
        self._state.agent_links = {
            key: link for key, link in self._state.agent_links.items() if key[0] != board_id
        }
        self._state.repository_links = {
            key: link for key, link in self._state.repository_links.items() if key[0] != board_id
        }


class FakeBoardStatsRepository:
    def __init__(self, state: RegistryState) -> None:
        self._state = state

    def for_boards(self, board_ids: Sequence[str]) -> dict[str, BoardStatsRow]:
        stored = self._state.board_stats
        return {board_id: stored[board_id] for board_id in board_ids if board_id in stored}

    def store(self, row: BoardStatsRow) -> None:
        if row.board_id not in self._state.boards:
            raise ConstraintError(f"boards.id {row.board_id} does not exist")
        self._state.board_stats[row.board_id] = row

    def forget(self, board_id: str) -> None:
        self._state.board_stats.pop(board_id, None)


class FakeBoardTemplateRepository:
    def __init__(self, state: RegistryState) -> None:
        self._state = state

    def _name_taken(self, name: str, *, other_than: str) -> bool:
        return any(
            nocase(row.name) == nocase(name) and row.id != other_than
            for row in self._state.board_templates.values()
        )

    def all(self) -> list[BoardTemplatesRow]:
        return sorted(self._state.board_templates.values(), key=lambda row: nocase(row.name))

    def get(self, template_id: str) -> BoardTemplatesRow | None:
        return self._state.board_templates.get(template_id)

    def add(self, row: BoardTemplatesRow) -> None:
        if row.id in self._state.board_templates:
            raise ConstraintError(f"board_templates.id {row.id} exists")
        if self._name_taken(row.name, other_than=row.id):
            raise ConstraintViolationError("board_templates.name is unique")
        self._state.board_templates[row.id] = row

    def update(self, row: BoardTemplatesRow) -> None:
        current = self._state.board_templates.get(row.id)
        if current is None:
            return
        if self._name_taken(row.name, other_than=row.id):
            raise ConstraintViolationError("board_templates.name is unique")
        self._state.board_templates[row.id] = current.__replace__(
            name=row.name,
            description=row.description,
            lists_json=row.lists_json,
            labels_json=row.labels_json,
            updated_at=row.updated_at,
        )

    def delete(self, template_id: str) -> None:
        self._state.board_templates.pop(template_id, None)


class FakeRoleTemplateRepository:
    def __init__(self, state: RegistryState) -> None:
        self._state = state

    def _name_taken(self, name: str, *, other_than: str) -> bool:
        return any(
            nocase(row.name) == nocase(name) and row.id != other_than
            for row in self._state.role_templates.values()
        )

    def all(self) -> list[RoleTemplatesRow]:
        return sorted(
            self._state.role_templates.values(),
            key=lambda row: (-row.built_in, nocase(row.name)),
        )

    def get(self, role_id: str) -> RoleTemplatesRow | None:
        return self._state.role_templates.get(role_id)

    def by_builtin_key(self, key: str) -> RoleTemplatesRow | None:
        return next(
            (row for row in self._state.role_templates.values() if row.builtin_key == key), None
        )

    def add(self, row: RoleTemplatesRow) -> None:
        if row.id in self._state.role_templates:
            raise ConstraintError(f"role_templates.id {row.id} exists")
        if self._name_taken(row.name, other_than=row.id):
            raise ConstraintViolationError("role_templates.name is unique")
        if row.builtin_key is not None and self.by_builtin_key(row.builtin_key) is not None:
            raise ConstraintViolationError("role_templates.builtin_key is unique")
        self._state.role_templates[row.id] = row

    def update(self, role_id: str, changes: RoleTemplateChanges, *, now: str) -> None:
        if not changes:
            raise ConstraintError("an update without a column is not SQL")
        row = self._state.role_templates.get(role_id)
        if row is None:
            return
        name = changes.get("name")
        if name is not None and self._name_taken(name, other_than=role_id):
            raise ConstraintViolationError("role_templates.name is unique")
        self._state.role_templates[role_id] = row.__replace__(**changes, updated_at=now)

    def delete(self, role_id: str) -> None:
        self._state.role_templates.pop(role_id, None)


class FakeAgentRepository:
    def __init__(self, state: RegistryState) -> None:
        self._state = state

    def _name_taken(self, name: str, *, other_than: str) -> bool:
        return any(
            nocase(row.name) == nocase(name) and row.id != other_than
            for row in self._state.agents.values()
        )

    def get(self, agent_id: str) -> AgentsRow | None:
        return self._state.agents.get(agent_id)

    def names(self, agent_ids: Collection[str]) -> dict[str, str]:
        return {
            agent_id: agent.name
            for agent_id, agent in self._state.agents.items()
            if agent_id in agent_ids
        }

    def listing(self, *, contains: str | None, enabled: bool | None) -> list[AgentsRow]:
        pattern = None if contains is None else f"%{contains}%"
        kept = [
            row
            for row in self._state.agents.values()
            if (pattern is None or like(row.name, pattern) or like(row.description, pattern))
            and (enabled is None or row.enabled == (1 if enabled else 0))
        ]
        return sorted(kept, key=lambda row: nocase(row.name))

    def count_by_role_template(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self._state.agents.values():
            if row.role_template_id is not None:
                counts[row.role_template_id] = counts.get(row.role_template_id, 0) + 1
        return counts

    def _scope(self, row: AgentsRow) -> str:
        # COALESCE(r.scope, 'board') over the LEFT JOIN: no template (or a missing one) is 'board'.
        template = (
            None
            if row.role_template_id is None
            else self._state.role_templates.get(row.role_template_id)
        )
        return "board" if template is None else template.scope

    def first_generator(
        self, connection_types: Collection[str], *, agent_ids: Collection[str] | None = None
    ) -> AgentsRow | None:
        kept = [
            row
            for row in self._state.agents.values()
            if row.enabled == 1
            and row.connection_type in connection_types
            and self._scope(row) != "organisation"
            and (agent_ids is None or row.id in agent_ids)
        ]
        return min(kept, key=lambda row: nocase(row.name), default=None)

    def role_scope(self, agent_id: str) -> str | None:
        row = self._state.agents.get(agent_id)
        return None if row is None else self._scope(row)

    def add(self, row: AgentsRow) -> None:
        if row.id in self._state.agents:
            raise ConstraintError(f"agents.id {row.id} exists")
        if self._name_taken(row.name, other_than=row.id):
            raise ConstraintViolationError("agents.name is unique")
        self._state.agents[row.id] = row

    def update(self, agent_id: str, changes: AgentChanges, *, now: str) -> None:
        if not changes:
            raise ConstraintError("an update without a column is not SQL")
        row = self._state.agents.get(agent_id)
        if row is None:
            return
        name = changes.get("name")
        if name is not None and self._name_taken(name, other_than=agent_id):
            raise ConstraintViolationError("agents.name is unique")
        self._state.agents[agent_id] = row.__replace__(**changes, updated_at=now)

    def record_test(
        self,
        agent_id: str,
        *,
        status: str,
        message: str,
        now: str,
        supports_json_schema: bool,
    ) -> None:
        row = self._state.agents.get(agent_id)
        if row is not None:
            self._state.agents[agent_id] = row.__replace__(
                last_test_status=status,
                last_test_message=message,
                last_tested_at=now,
                supports_json_schema=1 if supports_json_schema else 0,
            )

    def clear_role_template(self, role_id: str) -> None:
        for agent_id, row in list(self._state.agents.items()):
            if row.role_template_id == role_id:
                self._state.agents[agent_id] = row.__replace__(role_template_id=None)

    def delete(self, agent_id: str) -> None:
        self._state.agents.pop(agent_id, None)
        self._state.agent_links = {
            key: link for key, link in self._state.agent_links.items() if key[1] != agent_id
        }

    def sealed_keys(self) -> dict[str, str]:
        return {
            row.id: row.api_key_ciphertext
            for row in self._state.agents.values()
            if row.api_key_ciphertext is not None
        }

    def reseal(self, agent_id: str, ciphertext: str) -> None:
        row = self._state.agents.get(agent_id)
        if row is not None:
            self._state.agents[agent_id] = row.__replace__(api_key_ciphertext=ciphertext)


def _selection_order(link: BoardAgentsRow | BoardRepositoriesRow) -> tuple[str, str]:
    other = link.agent_id if isinstance(link, BoardAgentsRow) else link.repository_id
    return link.created_at, other


class FakeAgentLinkRepository:
    def __init__(self, state: RegistryState) -> None:
        self._state = state

    def agent_ids(self, board_id: str) -> list[str]:
        links = [link for link in self._state.agent_links.values() if link.board_id == board_id]
        return [link.agent_id for link in sorted(links, key=_selection_order)]

    def by_board(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for link in sorted(self._state.agent_links.values(), key=_selection_order):
            grouped.setdefault(link.board_id, []).append(link.agent_id)
        return grouped

    def clear(self, board_id: str) -> None:
        self._state.agent_links = {
            key: link for key, link in self._state.agent_links.items() if key[0] != board_id
        }

    def add(self, row: BoardAgentsRow) -> None:
        if row.board_id not in self._state.boards or row.agent_id not in self._state.agents:
            raise ConstraintError(f"board_agents ({row.board_id}, {row.agent_id}) has no parent")
        key = (row.board_id, row.agent_id)
        if key in self._state.agent_links:
            raise ConstraintError(f"board_agents {key} exists")
        self._state.agent_links[key] = row


class FakeCodeRepositoryRepository:
    def __init__(self, state: RegistryState) -> None:
        self._state = state

    @staticmethod
    def _ordered(rows: list[RepositoriesRow]) -> list[RepositoriesRow]:
        return sorted(rows, key=lambda row: (nocase(row.name), row.id))

    def get(self, repository_id: str) -> RepositoriesRow | None:
        return self._state.code_repositories.get(repository_id)

    def all(self) -> list[RepositoriesRow]:
        return self._ordered(list(self._state.code_repositories.values()))

    def for_board(self, board_id: str) -> list[RepositoriesRow]:
        linked = {key[1] for key in self._state.repository_links if key[0] == board_id}
        rows = self._state.code_repositories.values()
        return self._ordered([row for row in rows if row.id in linked])

    def url_taken(self, url: str, *, other_than: str | None = None) -> bool:
        return any(
            row.url == url and row.id != other_than
            for row in self._state.code_repositories.values()
        )

    def add(self, row: RepositoriesRow) -> None:
        if row.id in self._state.code_repositories:
            raise ConstraintError(f"repositories.id {row.id} exists")
        self._state.code_repositories[row.id] = row

    def update(self, repository_id: str, changes: RepositoryChanges) -> None:
        row = self._state.code_repositories.get(repository_id)
        if row is not None:
            self._state.code_repositories[repository_id] = row.__replace__(**changes)

    def record_check(self, repository_id: str, *, status: str, detail: str, now: str) -> None:
        row = self._state.code_repositories.get(repository_id)
        if row is not None:
            self._state.code_repositories[repository_id] = row.__replace__(
                last_checked_at=now,
                last_check_status=status,
                last_check_detail=detail,
                updated_at=now,
            )

    def record_default_branch(self, repository_id: str, default_branch: str) -> None:
        row = self._state.code_repositories.get(repository_id)
        if row is not None:
            self._state.code_repositories[repository_id] = row.__replace__(
                default_branch=default_branch
            )

    def record_fetch(self, repository_id: str, record: MirrorRecord) -> None:
        row = self._state.code_repositories.get(repository_id)
        if row is not None:
            self._state.code_repositories[repository_id] = row.__replace__(
                default_branch=record.default_branch or row.default_branch,
                last_sha=record.last_sha,
                fetched_at=record.fetched_at,
                mirror_bytes=record.mirror_bytes,
                mirror_error=None,
            )

    def record_mirror_error(self, repository_id: str, code: str) -> None:
        row = self._state.code_repositories.get(repository_id)
        if row is not None:
            self._state.code_repositories[repository_id] = row.__replace__(mirror_error=code)

    def clear_mirror(self, repository_id: str) -> None:
        row = self._state.code_repositories.get(repository_id)
        if row is not None:
            self._state.code_repositories[repository_id] = row.__replace__(
                last_sha=None, fetched_at=None, mirror_bytes=None, mirror_error=None
            )

    def delete(self, repository_id: str) -> None:
        self._state.code_repositories.pop(repository_id, None)
        self._state.repository_links = {
            key: link
            for key, link in self._state.repository_links.items()
            if key[1] != repository_id
        }

    def sealed_tokens(self) -> dict[str, str]:
        return {
            row.id: row.token_ciphertext
            for row in self._state.code_repositories.values()
            if row.token_ciphertext is not None
        }

    def reseal(self, repository_id: str, ciphertext: str, *, now: str) -> None:
        row = self._state.code_repositories.get(repository_id)
        if row is not None:
            self._state.code_repositories[repository_id] = row.__replace__(
                token_ciphertext=ciphertext, updated_at=now
            )


class FakeRepositoryLinkRepository:
    def __init__(self, state: RegistryState) -> None:
        self._state = state

    def linked_boards(self) -> list[LinkedBoard]:
        linked = [
            LinkedBoard(link=link, board=self._state.boards[link.board_id])
            for link in self._state.repository_links.values()
            if link.board_id in self._state.boards
        ]
        return sorted(linked, key=lambda entry: nocase(entry.board.name))

    def links(self, board_id: str) -> list[BoardRepositoriesRow]:
        links = [
            link for link in self._state.repository_links.values() if link.board_id == board_id
        ]
        return sorted(links, key=_selection_order)

    def by_board(self) -> dict[str, list[BoardRepositoriesRow]]:
        grouped: dict[str, list[BoardRepositoriesRow]] = {}
        for link in sorted(self._state.repository_links.values(), key=_selection_order):
            grouped.setdefault(link.board_id, []).append(link)
        return grouped

    def clear(self, board_id: str) -> None:
        self._state.repository_links = {
            key: link for key, link in self._state.repository_links.items() if key[0] != board_id
        }

    def add(self, row: BoardRepositoriesRow) -> None:
        parents = (
            row.board_id in self._state.boards
            and row.repository_id in self._state.code_repositories
        )
        if not parents:
            raise ConstraintError(
                f"board_repositories ({row.board_id}, {row.repository_id}) has no parent"
            )
        key = (row.board_id, row.repository_id)
        if key in self._state.repository_links:
            raise ConstraintError(f"board_repositories {key} exists")
        self._state.repository_links[key] = row


class FakeRegistryIdempotencyRepository:
    def __init__(self, state: RegistryState) -> None:
        self._state = state

    def get(self, actor_id: str, key: str) -> IdempotencyRecordsRow | None:
        return self._state.idempotency.get((actor_id, key))

    def put(self, row: IdempotencyRecordsRow) -> None:
        # INSERT OR REPLACE: the record held for the same actor and key is replaced.
        self._state.idempotency[(row.actor_id, row.idempotency_key)] = row


class FakeRegistryRepositories:
    def __init__(self, state: RegistryState) -> None:
        # Typed as the Protocols: pyright proves each fake implements its repository here.
        self.actors: ActorRepository = FakeActorRepository(state)
        self.users: UserRepository = FakeUserRepository(state)
        self.sessions: SessionRepository = FakeSessionRepository(state)
        self.invites: InviteRepository = FakeInviteRepository(state)
        self.credentials: CredentialRepository = FakeCredentialRepository(state)
        self.boards: BoardRowRepository = FakeBoardRowRepository(state)
        self.board_stats: BoardStatsRepository = FakeBoardStatsRepository(state)
        self.board_templates: BoardTemplateRepository = FakeBoardTemplateRepository(state)
        self.role_templates: RoleTemplateRepository = FakeRoleTemplateRepository(state)
        self.agents: AgentRepository = FakeAgentRepository(state)
        self.agent_links: AgentLinkRepository = FakeAgentLinkRepository(state)
        self.code_repositories: CodeRepositoryRepository = FakeCodeRepositoryRepository(state)
        self.repository_links: RepositoryLinkRepository = FakeRepositoryLinkRepository(state)
        self.idempotency: RegistryIdempotencyRepository = FakeRegistryIdempotencyRepository(
            state
        )


class FakeRegistryUnitOfWork:
    """Commits a writer that ends normally, rolls back one that raises; a reader never commits."""

    def __init__(self, state: RegistryState) -> None:
        self.state = state
        self.commits = 0
        self.rollbacks = 0

    @contextmanager
    def reader(self) -> Generator[FakeRegistryRepositories]:
        snapshot = self.state.snapshot()
        try:
            yield FakeRegistryRepositories(self.state)
        finally:
            self.state.restore(snapshot)

    @contextmanager
    def writer(self) -> Generator[FakeRegistryRepositories]:
        snapshot = self.state.snapshot()
        try:
            yield FakeRegistryRepositories(self.state)
        except BaseException:
            self.state.restore(snapshot)
            self.rollbacks += 1
            raise
        self.commits += 1


def registry_unit_of_work(state: RegistryState) -> RegistryUnitOfWork:
    """The fake as the Protocol a service takes; pyright proves the contract."""
    return FakeRegistryUnitOfWork(state)
