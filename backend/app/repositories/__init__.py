"""Repository interfaces: what a service needs from the database, as typed ``Protocol``s.

Each module holds the Protocols of one area, shaped by the operations its services perform and
returning generated rows (``app.db.generated``) or small typed values. ``board.py`` is the unit of
work that hands a service those repositories inside one reader or writer. ``sql/`` implements them
over SQLAlchemy; the unit tests implement them in memory. A service imports from here, never from
``sql/`` or ``app.storage``.
"""
