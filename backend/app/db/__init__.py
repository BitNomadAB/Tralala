"""Typed database rows, generated from the Alembic migrations by ``python -m tools.dbgen``.

The migrations are the only description of the schema. The build tool migrates both chains into
an in-memory database, writes one frozen dataclass per table into ``generated/`` and records what
it read in a manifest; nothing written by hand mirrors a table.
"""
