"""A face for people that keeps its template, for the RoadMap fixtures of the tests.

Every Ticket of a RoadMap handed in or generated carries a face (``services/ticket_face.py``); a
fixture spreads ``FACE`` into each planned Ticket and sets its own fields after it.
"""

from __future__ import annotations

from pydantic import JsonValue

FACE: dict[str, JsonValue] = {
    "summary": "People can sign in with their own account.",
    "why": "Nobody can use the board without signing in.",
    "if_skipped": "Everyone shares one account and nobody knows who changed what.",
    "pros": ["Each change has a name on it"],
    "cons": ["One more screen before the board"],
    "steps": ["Show a sign-in form on the start page", "Say who is signed in at the top"],
}
