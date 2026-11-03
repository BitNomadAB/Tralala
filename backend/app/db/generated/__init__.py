"""Rows generated from the Alembic migrations.

The modules beside this file (``registry.py``, ``board.py``) and ``manifest.json`` are written by
``python -m tools.dbgen`` and are not tracked. Importing a row before they exist fails here with
the command that writes them, instead of with a bare "No module named".
"""

from __future__ import annotations

from pathlib import Path

from ..freshness import MISSING

if not all((Path(__file__).parent / f"{name}.py").is_file() for name in ("registry", "board")):
    raise ImportError(MISSING)
