"""The archive entry check boards and backups share."""

from __future__ import annotations

from pathlib import Path

from ..core.errors import ValidationFailure


def archive_file_name(entry: str) -> str:
    """The bare filename of an archive member, or a rejection.

    A zip entry is attacker-controlled text, and the two hosts disagree about what separates a path:
    Windows treats ``\\`` as a separator and POSIX does not. Comparing the name to the entry after
    taking only its last component, and refusing dot entries, keeps the write inside the board's own
    attachments directory on either host.
    """
    name = entry.rsplit("/", 1)[-1]
    if name in {"", ".", ".."} or "\\" in name or "/" in name or "\x00" in name:
        raise ValidationFailure(
            "Board archive contains an invalid attachment entry", details={"entry": entry}
        )
    if Path(name).name != name:
        raise ValidationFailure(
            "Board archive contains an invalid attachment entry", details={"entry": entry}
        )
    return name


__all__ = ["archive_file_name"]
