"""``python -m tools.deps licences``: the licence of every dependency, against the policy.

**Python.** The distributions ``requirements-dev.txt`` installs (it includes ``requirements.txt``),
followed through each distribution's own requirements with the extras asked for and the
environment markers of the interpreter running the check, read with ``importlib.metadata``. Not
``pip-licenses``: it reports whatever happens to be installed, so a stray package in a developer's
virtual environment would count and a missing one would go unnoticed, and it would be one more
dependency for the few lines of metadata reading below. A distribution's licence is, in order:

1. ``License-Expression`` (PEP 639), an SPDX expression by definition;
2. ``License``, when it is one line spelling an expression of licences the policy names (the field
   is free text: often an id, sometimes the whole licence, sometimes ``UNKNOWN``);
3. its ``License ::`` classifiers, each mapped to an SPDX id; several mean all of them, because the
   metadata does not say whether they are a choice; a classifier without an id here stays as its
   text, which the policy does not allow;
4. ``License`` when it spells any other SPDX expression (``GPL-3.0-only``), so the policy names it;
5. an ``[[override]]`` in ``licences.toml``, written by someone who read the licence file.

**Frontend.** Every ``package.json`` under ``frontend/node_modules/.pnpm``, which holds each
installed package once, runtime and development dependencies alike (``pnpm licenses list`` was
unreliable here). A package's licence is its ``license`` field (an SPDX expression), the legacy
``license.type``, every ``licenses[].type`` together, or an override.

The policy is ``licences.toml``: the licences AGENTS.md allows, the ones allowed for one package
only, and the overrides. The check fails on a licence outside it, on metadata it cannot read
without an override, and on a scoped licence or an override nothing needs any more.
"""

from __future__ import annotations

import re
import sys
import tomllib
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from functools import partial
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Final, Literal, NotRequired, Required, TypedDict

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from pydantic import ConfigDict, JsonValue, TypeAdapter, ValidationError, with_config

from . import BACKEND_ROOT, FRONTEND_ROOT, DependencyCheckError, spdx

POLICY_PATH = Path(__file__).with_name("licences.toml")
REQUIREMENTS = BACKEND_ROOT / "requirements-dev.txt"
NODE_MODULES = FRONTEND_ROOT / "node_modules"

type Ecosystem = Literal["pypi", "npm"]

# Trove classifiers with exactly one SPDX id. There is one Apache classifier for every version;
# Apache-2.0 is the only one in use. "BSD License" does not give the clause count, so it maps to
# the family label the policy names.
CLASSIFIERS: Final = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: MIT No Attribution License (MIT-0)": "MIT-0",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: BSD License": "BSD",
    "License :: OSI Approved :: Zero-Clause BSD (0BSD)": "0BSD",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
}
# A classifier, and License values packaging tools write, that name no licence at all.
_SAYS_NOTHING = frozenset({"License :: OSI Approved"})
_PLACEHOLDERS = frozenset({"UNKNOWN", "NONE", "OTHER"})
# pip: a comment starts at a '#' at the beginning of a line or after whitespace.
_COMMENT = re.compile(r"(^|\s)#.*$")


# --- the policy -----------------------------------------------------------------------------------


@with_config(ConfigDict(extra="forbid"))
class _ScopedData(TypedDict):
    licence: str
    ecosystem: Ecosystem
    package: str
    reason: str


@with_config(ConfigDict(extra="forbid"))
class _OverrideData(TypedDict):
    ecosystem: Ecosystem
    package: str
    licence: str
    reason: str


@with_config(ConfigDict(extra="forbid"))
class _PolicyData(TypedDict):
    allowed: list[str]
    scoped: NotRequired[list[_ScopedData]]
    override: NotRequired[list[_OverrideData]]


_POLICY = TypeAdapter(_PolicyData)


@dataclass(frozen=True, slots=True)
class Scoped:
    """A licence allowed for one package only."""

    licence: str
    ecosystem: Ecosystem
    package: str
    reason: str


@dataclass(frozen=True, slots=True)
class Override:
    """The licence of a package whose metadata cannot be read, from its licence file."""

    ecosystem: Ecosystem
    package: str
    licence: spdx.Expression
    reason: str


@dataclass(frozen=True, slots=True)
class Policy:
    allowed: tuple[str, ...]
    scoped: tuple[Scoped, ...] = ()
    overrides: tuple[Override, ...] = ()

    @property
    def spellings(self) -> dict[str, str]:
        """Every licence id the policy names, by its lower-case form (ids ignore case)."""
        names = [*self.allowed, *(entry.licence for entry in self.scoped)]
        return {name.lower(): name for name in names}

    def allows(self, ecosystem: Ecosystem, package: str, licence: str) -> bool:
        key = licence.lower()
        if key in {name.lower() for name in self.allowed}:
            return True
        return any(
            entry.licence.lower() == key
            and entry.ecosystem == ecosystem
            and entry.package == package
            for entry in self.scoped
        )

    def override(self, ecosystem: Ecosystem, package: str) -> Override | None:
        for entry in self.overrides:
            if entry.ecosystem == ecosystem and entry.package == package:
                return entry
        return None


def parse_policy(text: str) -> Policy:
    """``licences.toml`` as a ``Policy``; ``DependencyCheckError`` naming what is wrong."""
    try:
        data = _POLICY.validate_python(tomllib.loads(text))
    except (tomllib.TOMLDecodeError, ValidationError) as exc:
        raise DependencyCheckError(f"licences.toml: {exc}") from exc
    problems: list[str] = []
    for name in [*data["allowed"], *(entry["licence"] for entry in data.get("scoped", []))]:
        try:
            if not isinstance(spdx.parse(name), spdx.Licence):
                problems.append(f"{name!r} is an expression; list each licence on its own")
        except spdx.ExpressionError as exc:
            problems.append(str(exc))
    scoped = tuple(Scoped(**entry) for entry in data.get("scoped", []))
    overrides: list[Override] = []
    for entry in data.get("override", []):
        try:
            licence = spdx.parse(entry["licence"])
        except spdx.ExpressionError as exc:
            problems.append(f"override {entry['package']}: {exc}")
            continue
        overrides.append(Override(entry["ecosystem"], entry["package"], licence, entry["reason"]))
    for kind, entries in (("scoped", scoped), ("override", overrides)):
        seen: set[tuple[str, str, str]] = set()
        for entry in entries:
            licence = entry.licence if isinstance(entry, Scoped) else ""
            key = (entry.ecosystem, entry.package, licence)
            if key in seen:
                problems.append(f"{kind} {entry.package}: listed twice")
            seen.add(key)
            if not entry.reason.strip():
                problems.append(f"{kind} {entry.package}: the reason is empty")
    if problems:
        raise DependencyCheckError("licences.toml: " + "; ".join(problems))
    return Policy(tuple(data["allowed"]), scoped, tuple(overrides))


def load_policy(path: Path = POLICY_PATH) -> Policy:
    return parse_policy(path.read_text(encoding="utf-8"))


# --- reading a licence ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Package:
    ecosystem: Ecosystem
    name: str
    version: str
    licence: spdx.Expression | None
    # Where the licence was read, or why it could not be.
    source: str

    @property
    def label(self) -> str:
        return f"{self.ecosystem} {self.name} {self.version}"


@dataclass(frozen=True, slots=True)
class PythonMetadata:
    expression: str | None = None
    licence: str | None = None
    classifiers: tuple[str, ...] = ()


def _excerpt(text: str) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return repr(line if len(line) <= 60 else line[:57] + "...")


def _all_of(names: Iterable[str]) -> spdx.Expression:
    terms = tuple(spdx.Licence(name) for name in dict.fromkeys(names))
    return terms[0] if len(terms) == 1 else spdx.AllOf(terms)


def python_licence(
    metadata: PythonMetadata, known: Iterable[str]
) -> tuple[spdx.Expression | None, str]:
    """The licence a distribution's core metadata declares, and the field it came from."""
    if metadata.expression and metadata.expression.strip():
        try:
            return spdx.parse(metadata.expression), "License-Expression"
        except spdx.ExpressionError:
            return None, f"License-Expression {_excerpt(metadata.expression)} does not parse"
    text = (metadata.licence or "").strip()
    parsed: spdx.Expression | None = None
    if text and "\n" not in text and text.upper() not in _PLACEHOLDERS:
        try:
            parsed = spdx.parse(text)
        except spdx.ExpressionError:
            parsed = None
    names = {name.lower() for name in known}
    if parsed is not None and all(name.lower() in names for name in spdx.licences(parsed)):
        return parsed, "License"
    named = [
        classifier
        for classifier in metadata.classifiers
        if classifier.startswith("License ::") and classifier not in _SAYS_NOTHING
    ]
    if named:
        return _all_of(CLASSIFIERS.get(classifier, classifier) for classifier in named), (
            "classifiers"
        )
    if parsed is not None:
        return parsed, "License"  # ids the policy does not name: the check will say so
    if text:
        return None, f"License {_excerpt(text)} is not an SPDX expression"
    return None, "no License-Expression, License or licence classifier"


def _npm_expression(text: str, where: str) -> tuple[spdx.Expression | None, str]:
    try:
        return spdx.parse(text), where
    except spdx.ExpressionError:
        return None, f"{where} {_excerpt(text)} is not an SPDX expression"


def npm_licence(licence: JsonValue, licences: JsonValue) -> tuple[spdx.Expression | None, str]:
    """The licence a ``package.json`` declares (``license``, or the legacy forms)."""
    if isinstance(licence, str):
        return _npm_expression(licence, "license")
    if isinstance(licence, dict):
        kind = licence.get("type")
        if isinstance(kind, str):
            return _npm_expression(kind, "license.type")
    if isinstance(licences, list) and licences:
        kinds = [entry.get("type") for entry in licences if isinstance(entry, dict)]
        texts = [kind for kind in kinds if isinstance(kind, str)]
        if len(texts) == len(licences):
            parsed = [_npm_expression(text, "licenses") for text in texts]
            expressions = [expression for expression, _ in parsed if expression is not None]
            if len(expressions) == len(parsed):
                if len(expressions) == 1:
                    return expressions[0], "licenses"
                return spdx.AllOf(tuple(expressions)), "licenses"
    return None, "no license field"


# --- the check ------------------------------------------------------------------------------------


@dataclass(slots=True)
class Inventory:
    packages: list[Package] = field(default_factory=list[Package])
    counts: dict[str, Counter[Ecosystem]] = field(default_factory=dict[str, Counter[Ecosystem]])
    problems: list[str] = field(default_factory=list[str])
    notes: list[str] = field(default_factory=list[str])


def check(packages: Iterable[Package], policy: Policy) -> Inventory:
    """Every package's licence against the policy; problems fail the check, notes do not."""
    inventory = Inventory()
    spellings = policy.spellings
    used_scoped: set[Scoped] = set()
    seen: set[tuple[Ecosystem, str]] = set()
    for package in packages:
        seen.add((package.ecosystem, package.name))
        override = policy.override(package.ecosystem, package.name)
        licence, source = package.licence, package.source
        if licence is None and override is not None:
            licence, source = override.licence, f"override: {override.reason}"
        elif licence is not None and override is not None:
            inventory.problems.append(
                f"{package.label}: its metadata now reads {spdx.render(licence)} ({source}), so "
                "the override in licences.toml is stale; remove it"
            )
        if licence is None:
            inventory.problems.append(
                f"{package.label}: no licence the check can read ({source}); read the package's "
                "licence file and add an [[override]] with the reason to licences.toml"
            )
            continue
        licence = spdx.respell(licence, lambda name: spellings.get(name.lower(), name))
        inventory.packages.append(replace(package, licence=licence, source=source))
        named = {name.lower() for name in spdx.licences(licence)}
        used_scoped.update(
            entry
            for entry in policy.scoped
            if (entry.ecosystem, entry.package) == (package.ecosystem, package.name)
            and entry.licence.lower() in named
        )
        if not spdx.satisfied(licence, partial(policy.allows, package.ecosystem, package.name)):
            inventory.problems.append(
                f"{package.label}: {spdx.render(licence)} ({source}) is not a licence AGENTS.md "
                "allows; a new licence is an owner decision, never part of a dependency bump"
            )
        inventory.counts.setdefault(spdx.render(licence), Counter())[package.ecosystem] += 1
    inventory.problems.extend(
        f"licences.toml allows {entry.licence} for {entry.ecosystem} {entry.package}, and no "
        "installed package needs it any more; remove the entry and its mention in AGENTS.md"
        for entry in policy.scoped
        if entry not in used_scoped
    )
    inventory.notes.extend(
        f"the override for {entry.ecosystem} {entry.package} was not used: not installed here"
        for entry in policy.overrides
        if (entry.ecosystem, entry.package) not in seen
    )
    return inventory


# --- what is installed ----------------------------------------------------------------------------


def requirement_lines(path: Path) -> list[str]:
    """The requirement specifiers of a pip requirements file, following ``-r`` includes."""
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = _COMMENT.sub("", raw).strip()
        if not line:
            continue
        option, _, value = line.partition(" ")
        if option in {"-r", "--requirement"}:
            lines += requirement_lines(path.parent / value.strip())
        elif line.startswith("-"):
            raise DependencyCheckError(f"{path.name}: the inventory does not follow {line!r}")
        else:
            lines.append(line)
    return lines


def closure(
    roots: Iterable[Requirement], requires: Callable[[str], list[str]]
) -> dict[str, frozenset[str]]:
    """Every distribution ``roots`` pull in, with the extras asked of it, markers evaluated."""
    wanted: dict[str, frozenset[str]] = {}
    pending: list[tuple[Requirement, frozenset[str]]] = [(root, frozenset()) for root in roots]
    while pending:
        requirement, parent_extras = pending.pop()
        marker = requirement.marker
        if marker is not None and not any(
            marker.evaluate({"extra": extra}) for extra in ("", *sorted(parent_extras))
        ):
            continue
        name = canonicalize_name(requirement.name)
        extras = frozenset(canonicalize_name(extra) for extra in requirement.extras)
        before = wanted.get(name)
        if before is not None and extras <= before:
            continue
        wanted[name] = extras | (before or frozenset())
        pending.extend((Requirement(line), wanted[name]) for line in requires(name))
    return wanted


def _installed_requires(name: str) -> list[str]:
    try:
        return distribution(name).requires or []
    except PackageNotFoundError as exc:
        raise DependencyCheckError(
            f"{name} is required but not installed: run pip install -r requirements-dev.txt"
        ) from exc


def python_packages(requirements: Path, known: Iterable[str]) -> list[Package]:
    try:
        roots = [Requirement(line) for line in requirement_lines(requirements)]
    except InvalidRequirement as exc:
        raise DependencyCheckError(f"{requirements.name}: {exc}") from exc
    names = list(known)
    packages: list[Package] = []
    for name in sorted(closure(roots, _installed_requires)):
        installed = distribution(name)
        metadata = installed.metadata
        declared = PythonMetadata(
            metadata.get("License-Expression"),
            metadata.get("License"),
            tuple(str(classifier) for classifier in metadata.get_all("Classifier") or []),
        )
        licence, source = python_licence(declared, names)
        packages.append(Package("pypi", name, installed.version, licence, source))
    return packages


class _NpmManifest(TypedDict, total=False):
    name: Required[str]
    version: Required[str]
    license: JsonValue
    licenses: JsonValue


_MANIFEST = TypeAdapter(_NpmManifest)


def _entries(directory: Path) -> list[Path]:
    """The package directories (or links to them) in a ``node_modules`` directory."""
    if not directory.is_dir():
        return []
    found: list[Path] = []
    for entry in sorted(directory.iterdir()):
        if entry.name.startswith("."):
            continue  # .pnpm, .bin, .modules.yaml: pnpm's own bookkeeping
        if entry.name.startswith("@"):
            found += sorted(entry.iterdir())
        else:
            found.append(entry)
    return found


def npm_packages(node_modules: Path) -> list[Package]:
    """Every package the frontend's ``node_modules`` reaches, each name and version once.

    pnpm links each top-level dependency to ``.pnpm/<id>/node_modules/<name>``, and each package's
    own dependencies are the links beside it in that directory. Following the links from the top
    reads what this lockfile installed. The store directory can also hold packages an earlier
    install left behind, which pnpm keeps for a while, and a link that leaves the store (a tool a
    developer linked in by hand) is not the lockfile's either; neither counts.
    """
    store = (node_modules / ".pnpm").resolve()
    if not store.is_dir():
        raise DependencyCheckError(
            f"{store} is missing: run pnpm install --frozen-lockfile in frontend/ first"
        )
    found: dict[tuple[str, str], Package] = {}
    visited: set[Path] = set()
    pending = [entry.resolve() for entry in _entries(node_modules)]
    while pending:
        directory = pending.pop()
        manifest = directory / "package.json"
        if directory in visited or not directory.is_relative_to(store) or not manifest.is_file():
            continue
        visited.add(directory)
        try:
            data = _MANIFEST.validate_json(manifest.read_bytes())
        except ValidationError as exc:
            raise DependencyCheckError(f"{manifest}: not a package manifest: {exc}") from exc
        key = (data["name"], data["version"])
        if key not in found:
            licence, source = npm_licence(data.get("license"), data.get("licenses"))
            found[key] = Package("npm", key[0], key[1], licence, source)
        container = (
            directory.parent.parent if directory.parent.name.startswith("@") else (directory.parent)
        )
        if container.name == "node_modules" and container.parent.parent.name == ".pnpm":
            pending += [entry.resolve() for entry in _entries(container)]
    if not found:
        raise DependencyCheckError(f"{node_modules} links no packages; reinstall with pnpm")
    return [found[key] for key in sorted(found)]


# --- the command ----------------------------------------------------------------------------------


def _write(line: str = "") -> None:
    sys.stdout.write(line + "\n")


def report(inventory: Inventory, *, list_all: bool) -> list[str]:
    """The inventory as text: optionally every package, then the count per licence."""
    lines: list[str] = []
    if list_all:
        width = max((len(package.label) for package in inventory.packages), default=0)
        lines += [
            f"  {package.label:<{width}}  {spdx.render(package.licence)}  ({package.source})"
            for package in inventory.packages
            if package.licence is not None
        ]
        lines.append("")
    rows = sorted(inventory.counts.items(), key=lambda row: (-row[1].total(), row[0]))
    width = max([len("licence"), *(len(name) for name, _ in rows)])
    lines.append(f"  {'licence':<{width}}  {'pypi':>5}  {'npm':>5}")
    lines += [
        f"  {name:<{width}}  {counts['pypi']:>5}  {counts['npm']:>5}" for name, counts in rows
    ]
    return lines


def run(*, list_all: bool = False) -> int:
    policy = load_policy()
    python = python_packages(REQUIREMENTS, policy.spellings.values())
    npm = npm_packages(NODE_MODULES)
    inventory = check([*python, *npm], policy)
    _write(
        f"licences: {len(python)} Python distributions from requirements-dev.txt, "
        f"{len(npm)} npm packages in frontend/node_modules"
    )
    for line in report(inventory, list_all=list_all):
        _write(line)
    for note in inventory.notes:
        _write(f"licences: note: {note}")
    if inventory.problems:
        for problem in inventory.problems:
            sys.stderr.write(f"licences: {problem}\n")
        sys.stderr.write(f"licences: {len(inventory.problems)} problem(s)\n")
        return 1
    _write("licences: ok, every licence is one tools/deps/licences.toml allows")
    return 0
