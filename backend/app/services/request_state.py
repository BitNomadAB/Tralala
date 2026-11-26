"""The sealed state of a question a key asks its person, and the check that opens it again.

MCP revision 2026-07-28 has no call from the server to the client. A tool that needs a person's
decision answers ``tools/call`` with ``inputRequests`` and an opaque ``requestState``; the client
repeats the call with ``inputResponses`` and that state. The state passes through the client, so
it is attacker-controlled input when it comes back. This module seals it and opens it again.

A state holds who asked (the actor's id and the id of the key, ``credential_id``, it authenticated
with), the tool, a hash of the call's decisive arguments, what the question was about when it was
asked (its ``subject``: the revision ids or the wait in force then, hashed with the call), when it
was issued, when it stops being valid and a random nonce. It is sealed with the installation
secret (``AuthService.secret_key``) through ``core/secrets.py``: encrypted and authenticated, so
only this installation can read or check it. A person may hold any number of keys; a state is
bound to the one key that asked, never to the person alone.

Opening a state refuses it with a typed reason (``RequestStateRefused.reason``) when it was changed
or is not a state at all, has expired, comes from another actor or key, belongs to another call, or
was used before. A state opens once: the nonce of every state opened is kept until the state would
have expired, and a second opening is refused. That set lives in this process only (AGENTS.md rule
8, one process per data directory): a restart forgets it, and the validity of a state
(``REQUEST_STATE_TTL``) then bounds how long a state used before the restart can be reused.

The clock is passed in, so a test sets the time instead of waiting. Nothing here sleeps or starts a
thread; the lock only keeps two requests that run in parallel from opening the same state twice.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Literal

from pydantic import JsonValue

from ..core.context import ActorContext
from ..core.errors import ValidationFailure
from ..core.secrets import SealedValueError, open_for_purpose, seal_for_purpose

# Fifteen minutes: long enough for a person to open the link, sign in and decide, short enough that
# a state that leaks, or one used before a restart emptied the set of used states, soon stops
# opening. A client that comes back later asks again and gets a new state.
REQUEST_STATE_TTL = timedelta(minutes=15)

# The purpose the sealing key is derived for, so no other sealed value opens as a state. Changing it
# only refuses the states issued in the last fifteen minutes.
_PURPOSE = "tralala-request-state-v1"
_VERSION = 1
# A state this module seals is a few hundred characters; a longer one is refused before it is
# opened, so a caller cannot make the process decrypt an arbitrarily large value.
MAX_STATE_CHARS = 4096

RefusalReason = Literal[
    "invalid",  # changed, malformed, sealed with another secret or not a state at all
    "expired",
    "wrong_actor",
    "wrong_credential",
    "wrong_call",
    "reused",
]
REFUSAL_REASONS: tuple[RefusalReason, ...] = (
    "invalid",
    "expired",
    "wrong_actor",
    "wrong_credential",
    "wrong_call",
    "reused",
)


class RequestStateRefused(ValidationFailure):
    """A ``requestState`` that does not open for this call, with the reason as a typed value.

    The message and details name the reason only, never what the state was about.
    """

    code = "request_state_refused"

    def __init__(self, reason: RefusalReason) -> None:
        super().__init__(f"The request state cannot be used: {reason}", details={"reason": reason})
        self.reason: RefusalReason = reason


@dataclass(frozen=True, slots=True)
class PendingCall:
    """The call a state belongs to: the tool and its decisive arguments.

    ``arguments`` are what the caller names and names again on the retry (for example the
    decision, ``board_id``, ``loop_id`` and ``card_id``). What the question was about when it was
    asked and the retry cannot name again (the revision ids or a wait in force then) is the
    state's ``subject``: ``RequestStateService.seal`` seals it inside the state and hashes it with
    the call, and ``open`` hands it back.
    """

    tool: str
    arguments: Mapping[str, JsonValue]

    def digest(self, subject: Mapping[str, JsonValue] | None = None) -> str:
        """SHA-256 of the tool, the arguments and ``subject`` as canonical JSON (sorted keys, no
        spaces)."""
        canonical = json.dumps(
            {
                "tool": self.tool,
                "arguments": dict(self.arguments),
                "subject": dict(subject or {}),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class OpenedState:
    """What an opened state held. Opening it used it up."""

    actor_id: str
    credential_id: str | None
    tool: str
    call_digest: str
    issued_at: datetime
    expires_at: datetime
    nonce: str
    subject: Mapping[str, JsonValue]


def system_clock() -> datetime:
    """The real time, the clock the composition root builds the service with."""
    return datetime.now(UTC)


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


def _moment(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, UTC)


def _text(payload: Mapping[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RequestStateRefused("invalid")
    return value


def _integer(payload: Mapping[str, JsonValue], key: str) -> int:
    value = payload.get(key)
    # bool is an int in Python, and never a time.
    if not isinstance(value, int) or isinstance(value, bool):
        raise RequestStateRefused("invalid")
    return value


def _decode(secret: str, state: str) -> OpenedState:
    """The state's fields, checked for shape only; ``invalid`` for anything else."""
    if not state or len(state) > MAX_STATE_CHARS:
        raise RequestStateRefused("invalid")
    try:
        raw = open_for_purpose(secret, _PURPOSE, state)
        payload: JsonValue = json.loads(raw.decode("utf-8"))
    except (SealedValueError, ValueError) as exc:  # a JSON or UTF-8 error is a ValueError
        raise RequestStateRefused("invalid") from exc
    if not isinstance(payload, dict) or payload.get("v") != _VERSION:
        raise RequestStateRefused("invalid")
    credential = payload.get("credential")
    if credential is not None and (not isinstance(credential, str) or not credential):
        raise RequestStateRefused("invalid")
    issued, expires = _integer(payload, "issued"), _integer(payload, "expires")
    if expires <= issued:
        raise RequestStateRefused("invalid")
    subject = payload.get("subject", {})
    if not isinstance(subject, dict):
        raise RequestStateRefused("invalid")
    return OpenedState(
        actor_id=_text(payload, "actor"),
        credential_id=credential,
        tool=_text(payload, "tool"),
        call_digest=_text(payload, "call"),
        issued_at=_moment(issued),
        expires_at=_moment(expires),
        nonce=_text(payload, "nonce"),
        subject=subject,
    )


class RequestStateService:
    """Seals the state of a pending question and opens it once, for the key and call that asked."""

    def __init__(self, secret: str, *, clock: Callable[[], datetime]) -> None:
        if not secret:
            raise ValueError("the request state needs the installation secret")
        self._secret = secret
        self._clock = clock
        self._lock = Lock()
        # The nonce of every state opened, with the epoch second at which that state expires.
        self._used: dict[str, int] = {}

    def _forget_expired(self, now: int) -> None:
        """Drop every used nonce whose state has expired; such a state is refused as expired."""
        for nonce in [nonce for nonce, expires in self._used.items() if expires <= now]:
            del self._used[nonce]

    def seal(
        self,
        actor: ActorContext,
        call: PendingCall,
        subject: Mapping[str, JsonValue] | None = None,
    ) -> str:
        """A new state for ``call``, asked by ``actor`` with the key it authenticated with, about
        ``subject`` (what the question was about when it was asked; empty when the call says it).

        Every state is new: a fresh nonce, issued now and valid for ``REQUEST_STATE_TTL``.
        """
        issued = _epoch(self._clock())
        with self._lock:
            self._forget_expired(issued)
        payload = {
            "v": _VERSION,
            "actor": actor.actor_id,
            "credential": actor.credential_id,
            "tool": call.tool,
            "call": call.digest(subject),
            "subject": dict(subject or {}),
            "issued": issued,
            "expires": issued + int(REQUEST_STATE_TTL.total_seconds()),
            "nonce": secrets.token_urlsafe(16),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return seal_for_purpose(self._secret, _PURPOSE, raw)

    def open(self, actor: ActorContext, call: PendingCall, state: str) -> OpenedState:
        """Check ``state`` for ``actor`` and ``call`` and use it up, or raise
        :class:`RequestStateRefused`.

        The checks run in this order: ``invalid``, ``expired``, ``wrong_actor``,
        ``wrong_credential``, ``wrong_call``, ``reused``. ``call`` is checked with the subject the
        state was sealed with, which comes back as ``OpenedState.subject``. A refused state is not
        used up, so a state shown by someone else stays the asker's; only a state that opens is.
        """
        opened = _decode(self._secret, state)
        now = _epoch(self._clock())
        if now >= _epoch(opened.expires_at):
            raise RequestStateRefused("expired")
        if opened.actor_id != actor.actor_id:
            raise RequestStateRefused("wrong_actor")
        if opened.credential_id != actor.credential_id:
            raise RequestStateRefused("wrong_credential")
        expected = call.digest(opened.subject)
        if opened.tool != call.tool or not hmac.compare_digest(opened.call_digest, expected):
            raise RequestStateRefused("wrong_call")
        with self._lock:
            self._forget_expired(now)
            if opened.nonce in self._used:
                raise RequestStateRefused("reused")
            self._used[opened.nonce] = _epoch(opened.expires_at)
        return opened

    def remembered(self) -> int:
        """How many used states the process still remembers; expired ones are forgotten on the
        next seal or open."""
        with self._lock:
            return len(self._used)
