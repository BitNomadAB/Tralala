"""Schema chain control and optional FTS bootstrap."""

from __future__ import annotations

from . import runner
from .fts import ensure_fts

__all__ = ["ensure_fts", "runner"]
