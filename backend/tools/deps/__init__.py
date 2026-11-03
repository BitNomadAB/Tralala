"""``python -m tools.deps``: the dependency checks, run from ``backend/`` like CI does.

- ``licences``: the licence of every Python distribution ``requirements-dev.txt`` installs and of
  every package in ``frontend/node_modules``, against ``licences.toml`` (the list in AGENTS.md).
- ``audit``: known vulnerabilities, ``pip-audit`` for the backend and ``pnpm audit`` for the
  frontend, with the accepted advisories of ``audit_allowlist.toml``.

Both need the installed dependencies of both sides; ``audit`` also needs the network.
"""

from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = BACKEND_ROOT.parent / "frontend"


class DependencyCheckError(Exception):
    """A check cannot run or its configuration is wrong; the message says what to change."""
