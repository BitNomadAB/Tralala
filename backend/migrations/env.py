"""Alembic environment shared by the registry and board chains.

The application never runs the Alembic CLI for migrations. ``app.storage.schema.runner``
builds a programmatic Config, selects the chain (``registry`` or ``board``) and supplies an
open connection, so migrations participate in a transaction the Migration Manager controls.
"""

from __future__ import annotations

import logging

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
logger = logging.getLogger("tralala.migrations.env")

target_metadata = config.attributes.get("target_metadata")
chain = config.attributes.get("chain", "unknown")


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    owned_engine = None
    if connection is None:
        section = config.get_section(config.config_ini_section, {}) or {}
        owned_engine = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
        connection = owned_engine.connect()
    try:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    finally:
        if owned_engine is not None:
            connection.close()
            owned_engine.dispose()


logger.info("running Alembic migrations for chain %s", chain)
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
