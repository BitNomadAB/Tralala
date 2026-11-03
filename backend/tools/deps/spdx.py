"""SPDX licence expressions: parse ``MIT OR (Apache-2.0 AND BSD-3-Clause)`` and decide them.

The grammar is the one in SPDX 2.3 Annex D: ``WITH`` binds tighter than ``AND``, which binds
tighter than ``OR``, and parentheses group. Operators are upper case, as the specification says;
a licence id is matched without regard to case. ``OR`` is the licensee's choice, so it is satisfied
when any side is; ``AND`` needs every side. ``X WITH exception`` is one licence of its own, never
the bare ``X``: an exception changes the terms, so the policy has to name it to allow it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

_TOKEN = re.compile(r"\(|\)|[^\s()]+")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+:-]*")
_OPERATORS = frozenset({"AND", "OR", "WITH"})


class ExpressionError(ValueError):
    """The text is not an SPDX licence expression."""


@dataclass(frozen=True, slots=True)
class Licence:
    """One licence, ``Apache-2.0`` or ``Apache-2.0 WITH LLVM-exception``."""

    id: str


@dataclass(frozen=True, slots=True)
class AnyOf:
    """``a OR b``: the licensee picks one."""

    terms: tuple[Expression, ...]


@dataclass(frozen=True, slots=True)
class AllOf:
    """``a AND b``: every licence applies."""

    terms: tuple[Expression, ...]


type Expression = Licence | AnyOf | AllOf


def parse(text: str) -> Expression:
    """The expression ``text`` spells; ``ExpressionError`` when it is not one."""
    tokens = _TOKEN.findall(text)
    if not tokens:
        raise ExpressionError("empty licence expression")
    parser = _Parser(tokens, text)
    expression = parser.any_of()
    if parser.position != len(tokens):
        raise ExpressionError(f"unexpected {tokens[parser.position]!r} in {text!r}")
    return expression


def satisfied(expression: Expression, allowed: Callable[[str], bool]) -> bool:
    """Whether the licences ``allowed`` accepts are enough to use the package."""
    match expression:
        case Licence(id=licence):
            return allowed(licence)
        case AnyOf(terms=terms):
            return any(satisfied(term, allowed) for term in terms)
        case AllOf(terms=terms):
            return all(satisfied(term, allowed) for term in terms)


def licences(expression: Expression) -> list[str]:
    """Every licence the expression names, in order, each once."""
    match expression:
        case Licence(id=licence):
            return [licence]
        case AnyOf(terms=terms) | AllOf(terms=terms):
            return list(dict.fromkeys(name for term in terms for name in licences(term)))


def respell(expression: Expression, spelling: Callable[[str], str]) -> Expression:
    """The same expression with every licence id passed through ``spelling``."""
    match expression:
        case Licence(id=licence):
            return Licence(spelling(licence))
        case AnyOf(terms=terms):
            return AnyOf(tuple(respell(term, spelling) for term in terms))
        case AllOf(terms=terms):
            return AllOf(tuple(respell(term, spelling) for term in terms))


def render(expression: Expression) -> str:
    """The canonical text: single spaces, parentheses only where the precedence needs them."""
    match expression:
        case Licence(id=licence):
            return licence
        case AnyOf(terms=terms):
            return " OR ".join(render(term) for term in terms)
        case AllOf(terms=terms):
            return " AND ".join(
                f"({render(term)})" if isinstance(term, AnyOf) else render(term) for term in terms
            )


@dataclass(slots=True)
class _Parser:
    tokens: list[str]
    text: str
    position: int = 0

    def _peek(self) -> str | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def _take(self) -> str:
        token = self._peek()
        if token is None:
            raise ExpressionError(f"{self.text!r} ends where a licence is expected")
        self.position += 1
        return token

    def any_of(self) -> Expression:
        terms = [self.all_of()]
        while self._peek() == "OR":
            self.position += 1
            terms.append(self.all_of())
        return terms[0] if len(terms) == 1 else AnyOf(_flatten(terms, AnyOf))

    def all_of(self) -> Expression:
        terms = [self.atom()]
        while self._peek() == "AND":
            self.position += 1
            terms.append(self.atom())
        return terms[0] if len(terms) == 1 else AllOf(_flatten(terms, AllOf))

    def atom(self) -> Expression:
        word = self._take()
        if word == "(":
            inner = self.any_of()
            if self._take() != ")":
                raise ExpressionError(f"unbalanced parentheses in {self.text!r}")
            return inner
        name = self._identifier(word)
        if self._peek() == "WITH":
            self.position += 1
            name = f"{name} WITH {self._identifier(self._take())}"
        return Licence(name)

    def _identifier(self, token: str) -> str:
        if token in _OPERATORS or not _ID.fullmatch(token):
            raise ExpressionError(f"{token!r} is not a licence id in {self.text!r}")
        return token


def _flatten(terms: list[Expression], kind: type[AnyOf] | type[AllOf]) -> tuple[Expression, ...]:
    """``(a OR b) OR c`` is ``a OR b OR c``: one level per operator keeps rendering canonical."""
    flat: list[Expression] = []
    for term in terms:
        if isinstance(term, kind):
            flat.extend(term.terms)
        else:
            flat.append(term)
    return tuple(flat)
