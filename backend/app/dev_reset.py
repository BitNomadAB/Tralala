"""Explicit development reset for this early-stage redesign.

There is no production data to preserve and no in-place conversion of pre-Loop boards. This
command names the data directory it will erase, requires deliberate confirmation and never runs
from application startup.

    cd backend
    python -m app.dev_reset --confirm
    python -m app.dev_reset --confirm --data-dir C:\\tralala-data
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import TypedDict

from .core.config import Settings, get_settings
from .core.platform import remove_tree
from .core.security import SECRET_FILE_NAME

logger = logging.getLogger("tralala.dev_reset")


class ResetPlan(TypedDict):
    """The data directory, what a reset removes from it, and what it keeps."""

    data_dir: str
    targets: list[str]
    keeps: list[str]


class ResetResult(TypedDict):
    """The data directory and what the reset removed."""

    data_dir: str
    removed: list[str]


def _resolve_settings(data_dir: str | None) -> Settings:
    if data_dir:
        return Settings(data_dir=Path(data_dir))
    return get_settings()


def plan(settings: Settings) -> ResetPlan:
    """Describe exactly what a reset would remove; used by the CLI and by tests."""
    data_dir = Path(settings.data_dir)
    targets: list[Path] = []
    if settings.registry_path.exists():
        targets.append(Path(settings.registry_path))
    if settings.boards_dir.exists():
        targets.extend(sorted(settings.boards_dir.iterdir()))
    if settings.backups_dir.exists():
        targets.extend(sorted(settings.backups_dir.iterdir()))
    return {
        "data_dir": str(data_dir.resolve()),
        "targets": [str(target) for target in targets],
        "keeps": [str(Path(settings.data_dir) / SECRET_FILE_NAME)],
    }


def reset(settings: Settings, *, confirm: bool) -> ResetResult:
    """Remove every board database, its assets and its backups. Requires ``confirm=True``."""
    overview = plan(settings)
    if not confirm:
        raise RuntimeError(
            "Refusing to erase data without confirmation. Re-run with --confirm after checking "
            f"the data directory: {overview['data_dir']}"
        )
    removed: list[str] = []
    registry_path = Path(settings.registry_path)
    if registry_path.exists():
        for suffix in ("", "-wal", "-shm"):
            candidate = registry_path.with_name(registry_path.name + suffix)
            if candidate.exists():
                candidate.unlink()
        removed.append(str(registry_path))
    for directory in (settings.boards_dir, settings.backups_dir):
        if directory.exists():
            remove_tree(directory, profile=settings.file_profile)
            removed.append(str(directory))
    return {"data_dir": overview["data_dir"], "removed": removed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Erase Tralala development data before recreating the schema"
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required. Confirms that the listed data directory may be erased.",
    )
    parser.add_argument("--data-dir", default=None, help="Data directory to reset")
    args = parser.parse_args(argv)
    # The command talks to a person: plain lines on stdout, as print wrote them. A no-op when the
    # caller has configured logging already.
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    settings = _resolve_settings(args.data_dir)
    overview = plan(settings)
    logger.info("Tralala data directory: %s", overview["data_dir"])
    logger.info("Will remove:")
    for target in overview["targets"] or ["(nothing — already empty)"]:
        logger.info("  - %s", target)
    logger.info("Will keep:")
    for target in overview["keeps"]:
        logger.info("  - %s", target)
    if not args.confirm:
        logger.info("Not confirmed. Re-run with --confirm to erase this data directory.")
        return 2
    result = reset(settings, confirm=True)
    logger.info(
        "Removed %d item(s). The next start creates a clean schema.", len(result["removed"])
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
