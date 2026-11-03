"""What a repository raises in place of the database driver's own errors."""

from __future__ import annotations


class ConstraintViolationError(Exception):
    """The database refused a write for one of its constraints (a unique name, a key).

    A SQL repository raises it in place of the driver's integrity error on the writes a service
    answers for, so the service can report a taken name without knowing the database. It leaves
    the unit of work like any other exception, so the transaction is rolled back.
    """
