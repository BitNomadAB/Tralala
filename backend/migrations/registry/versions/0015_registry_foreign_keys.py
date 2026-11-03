"""Foreign keys for the registry columns that name an actor, each with its ON DELETE rule.

Three columns named an actor without a constraint: the account that owns an API token, the
administrator who issued an invite and the caller an idempotency record belongs to. The build
(``python -m tools.dbgen``) now requires a foreign key on every such column, an index that starts
with it and an explicit ON DELETE rule.

SQLite adds a foreign key only by rebuilding the table, which ``batch_alter_table`` does. The three
tables are referenced by no other table, so dropping the old copy fires no ON DELETE action.

A reference whose actor is gone is settled first, by what the column means; actors are only ever
disabled, never deleted, so the application itself cannot leave one behind:

- ``api_credentials.owner_actor_id`` is optional: NULL is a token without an owning account, which
  an administrator manages (as for tokens issued before ownership existed). A missing owner becomes
  NULL; the token keeps its scopes and stays revocable.
- ``idempotency_records.actor_id`` is a replay cache that is only ever read back by the same
  authenticated actor, so a record of an actor that does not exist can never be used and is
  removed.
- ``user_invites.created_by_actor_id`` is NOT NULL and cannot be cleared; a missing issuer stops
  the upgrade with the rows to repair (the Migration Manager keeps its pre-migration backup).

Revision ID: 0015_registry_foreign_keys
Revises: 0014_board_stats
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015_registry_foreign_keys"
down_revision: str | None = "0014_board_stats"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Data first. Python's sqlite3 opens the transaction at the first INSERT/UPDATE/DELETE and runs
    # DDL before it in autocommit mode, so starting with DML keeps every rebuild below inside the
    # one transaction the runner rolls back on failure.
    op.execute(
        "UPDATE api_credentials SET owner_actor_id = NULL"
        " WHERE owner_actor_id IS NOT NULL"
        " AND owner_actor_id NOT IN (SELECT id FROM actors)"
    )
    op.execute("DELETE FROM idempotency_records WHERE actor_id NOT IN (SELECT id FROM actors)")
    orphans = [
        str(invite)
        for (invite,) in op.get_bind().exec_driver_sql(
            "SELECT id FROM user_invites"
            " WHERE created_by_actor_id NOT IN (SELECT id FROM actors) ORDER BY id"
        )
    ]
    if orphans:
        raise RuntimeError(
            "user_invites.created_by_actor_id names an actor that does not exist in invite(s) "
            + ", ".join(orphans)
            + "; set it to an existing administrator's actor id and start again"
        )

    # RESTRICT: an account that issued tokens is not removed while they exist.
    with op.batch_alter_table("api_credentials", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_api_credentials_owner", "actors", ["owner_actor_id"], ["id"], ondelete="RESTRICT"
        )
    # RESTRICT: the issuer of an invite is part of its record.
    with op.batch_alter_table("user_invites", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_user_invites_created_by",
            "actors",
            ["created_by_actor_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index("ix_user_invites_created_by", "user_invites", ["created_by_actor_id"])
    # CASCADE: a replay record belongs to its caller and must never keep an actor from going.
    with op.batch_alter_table("idempotency_records", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_idempotency_records_actor", "actors", ["actor_id"], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported; restore a backup instead")
