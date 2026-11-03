"""The repository Protocols implemented over a SQLAlchemy ``Connection``.

Statements are module-level ``text()`` constants. A select lists exactly the generated row's
columns (``sql.column_list`` of its column tuple) and maps each result through the row's checked
``from_mapping``. Every statement here is compiled against the migrated schema by
``python -m tools.dbgen``; no test opens a database for it.
"""
