"""Typed in-memory implementations of the repository Protocols, built on the generated rows.

A fake keeps its rows in plain dictionaries and does what the SQL implementation does to them, so
a service runs its real code against it. Each fake is assigned to its Protocol where it is used,
which makes pyright prove the contract; a schema change that changes a row breaks the fake at type
checking, before any test runs. Rows change through ``row.__replace__(...)`` rather than
``dataclasses.replace``, because pyright checks the field names and types of the former only.
"""
