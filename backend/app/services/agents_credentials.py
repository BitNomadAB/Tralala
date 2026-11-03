"""Provider keys of agent profiles: sealed before they are stored, re-sealed after a secret change.

Keys are sealed with ``core.secrets``; a response carries only ``has_api_key`` and the hint.
``services.agents`` calls these when an agent is saved and once at startup.
"""

from __future__ import annotations

import logging

from ..core.config import Settings
from ..core.secrets import CredentialError, open_secret_state, seal_secret, secret_hint
from ..repositories.agents import AgentChanges
from ..repositories.registry import RegistryUnitOfWork

logger = logging.getLogger("tralala.agents")


def credential_changes(settings: Settings, api_key: str | None) -> AgentChanges:
    """``None`` leaves the stored key alone; an empty key removes it; any other is sealed."""
    if api_key is None:
        return {}
    if not api_key:
        return {"api_key_ciphertext": None, "api_key_hint": None}
    return {
        "api_key_ciphertext": seal_secret(settings, api_key),
        "api_key_hint": secret_hint(api_key),
    }


def reseal_provider_keys(settings: Settings, store: RegistryUnitOfWork) -> int:
    """Re-seal provider keys that were sealed with TRALALA_PREVIOUS_SECRET_KEY.

    Called once at startup: after a secret change every key moves to the new secret, so the
    previous one can be dropped from the environment afterwards.
    """
    with store.reader() as repos:
        sealed = repos.agents.sealed_keys()
    resealed: dict[str, str] = {}
    for agent_id, ciphertext in sealed.items():
        try:
            value, current = open_secret_state(settings, ciphertext)
        except CredentialError:
            logger.warning("agent %s has a credential that no configured secret can open", agent_id)
            continue
        if not current:
            resealed[agent_id] = seal_secret(settings, value)
    if resealed:
        with store.writer() as repos:
            for agent_id, ciphertext in resealed.items():
                repos.agents.reseal(agent_id, ciphertext)
    return len(resealed)
