"""Factory-defined role templates, loaded from a seed file.

The templates ship as ``app/seeds/role_seeds.json`` (outside the runtime ``data`` folder, which is
ignored by git and by the container build) so a new profile is a data change rather than a code
change, and so every installation is seeded with the same set. They are seeded once per
registry: users may edit them (the factory text is kept in ``default_system_prompt`` so it can be
restored) and may duplicate them into custom templates.

``scope`` decides where a template is used. ``board`` profiles answer inside one board and may be
selected for it; ``organisation`` profiles (Coordinator, Architect) work across the whole
installation, because their job is the overview that no single board can give them.

The file is validated at import: a missing key, a duplicate key or an unknown scope fails startup
instead of silently seeding a broken role.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, TypedDict

RoleScope = Literal["board", "organisation"]

SEED_PATH = Path(__file__).resolve().parent.parent / "seeds" / "role_seeds.json"
DISCUSSION_PLACEHOLDER = "{{discussion}}"
SCOPES: tuple[RoleScope, ...] = ("board", "organisation")


class BuiltinRole(TypedDict):
    key: str
    name: str
    description: str
    scope: RoleScope
    prompt: str


def _load(path: Path = SEED_PATH) -> tuple[BuiltinRole, ...]:
    document = json.loads(path.read_text(encoding="utf-8"))
    preamble = str(document.get("discussion_preamble") or "")
    roles: list[BuiltinRole] = []
    seen: set[str] = set()
    for entry in document.get("roles") or []:
        key = str(entry.get("key") or "").strip()
        scope = str(entry.get("scope") or "board")
        if not key or key in seen:
            raise RuntimeError(f"role seed {path} has an empty or duplicate key: {key!r}")
        if scope not in SCOPES:
            raise RuntimeError(f"role seed {path} has an unknown scope for {key}: {scope!r}")
        name = str(entry.get("name") or "").strip()
        prompt = str(entry.get("prompt") or "").replace(DISCUSSION_PLACEHOLDER, preamble).strip()
        if not name or not prompt:
            raise RuntimeError(f"role seed {path} has an incomplete role: {key!r}")
        seen.add(key)
        roles.append(
            {
                "key": key,
                "name": name,
                "description": str(entry.get("description") or "").strip(),
                "scope": scope,  # type: ignore[typeddict-item]
                "prompt": prompt,
            }
        )
    if not roles:
        raise RuntimeError(f"role seed {path} defines no roles")
    return tuple(roles)


BUILTIN_ROLES: tuple[BuiltinRole, ...] = _load()

BUILTIN_ROLE_KEYS: tuple[str, ...] = tuple(role["key"] for role in BUILTIN_ROLES)

# Organisation-wide profiles are not selectable per board: they need the whole picture.
BOARD_ROLES: tuple[BuiltinRole, ...] = tuple(
    role for role in BUILTIN_ROLES if role["scope"] == "board"
)
ORGANISATION_ROLES: tuple[BuiltinRole, ...] = tuple(
    role for role in BUILTIN_ROLES if role["scope"] == "organisation"
)
