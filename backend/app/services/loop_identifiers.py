"""Deterministic human-readable references for Loops, Phases and Tickets.

UUIDs remain the internal identity. These keys only supplement them, so they are allocated
transactionally by the server and never rendered from model output.
"""

from __future__ import annotations

import unicodedata

LOOP_FALLBACK = "LP"
PHASE_FALLBACK = "PH"


def name_prefix(name: str, fallback: str) -> str:
    """First two normalized alphanumeric characters, upper case, padded to two.

    Accents are stripped, case is folded and non-alphanumerics are ignored. A name with no
    ASCII alphanumeric characters uses ``fallback``; a single character is padded with ``X``.
    """
    normalized = unicodedata.normalize("NFKD", name or "")
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    letters = [character.upper() for character in ascii_only if character.isalnum()]
    if not letters:
        return fallback
    prefix = "".join(letters[:2])
    return prefix if len(prefix) == 2 else f"{prefix}X"


def loop_prefix(name: str) -> str:
    return name_prefix(name, LOOP_FALLBACK)


def phase_prefix(name: str) -> str:
    return name_prefix(name, PHASE_FALLBACK)


def format_loop_key(prefix: str, sequence: int) -> str:
    return f"{prefix}{sequence:03d}"


def format_ticket_key(
    loop_key: str, phase_prefix_value: str, phase_number: int, ticket_sequence: int
) -> str:
    return f"{loop_key}-{phase_prefix_value}{phase_number:02d}-{ticket_sequence:03d}"


UNPLANNED_MARK = "UNP"


def format_unplanned_key(loop_key: str, sequence: int) -> str:
    """The key of a Ticket added outside a Loop's plan: ``<LoopKey>-UNP-<nnn>``."""
    return f"{loop_key}-{UNPLANNED_MARK}-{sequence:03d}"


def next_unplanned_sequence(loop_key: str, keys: list[str | None]) -> int:
    """One more than the highest unplanned sequence among ``keys``, so a key is never reused."""
    prefix = f"{loop_key}-{UNPLANNED_MARK}-"
    taken = [
        int(key[len(prefix) :])
        for key in keys
        if key is not None and key.startswith(prefix) and key[len(prefix) :].isdigit()
    ]
    return max(taken, default=0) + 1
