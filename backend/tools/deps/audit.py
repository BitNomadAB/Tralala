"""``python -m tools.deps audit``: known vulnerabilities in both dependency trees.

- **Python:** ``pip-audit -r requirements.txt -r requirements-dev.txt``. pip-audit resolves both
  files in a throwaway environment, as a fresh install does, and looks every distribution up in the
  PyPI advisory database. It has no severity filter, so any advisory fails. An accepted advisory is
  passed as ``--ignore-vuln``.
- **Frontend:** what ``pnpm audit --audit-level high`` decides, over every package the lockfile
  installs, runtime and development alike: a high or critical advisory fails, lower ones are
  counted and pass. The check reads ``pnpm audit --json`` and applies the rule itself, because
  pnpm's own ``--ignore`` does not ignore: it writes the id into ``package.json`` and skips the
  audit.

An advisory that cannot be fixed yet goes into ``audit_allowlist.toml`` with its ecosystem,
package, reason and an expiry date at most ``MAX_DAYS`` ahead. An expired entry fails the audit and
no longer hides its advisory, so an accepted risk is decided again instead of being forgotten. Both
tools always run, so one report shows everything that is wrong.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal, NotRequired, Required, TypedDict

from pydantic import ConfigDict, TypeAdapter, ValidationError, with_config

from . import BACKEND_ROOT, FRONTEND_ROOT, DependencyCheckError

ALLOWLIST_PATH = Path(__file__).with_name("audit_allowlist.toml")
# An accepted advisory is decided again at least once a quarter.
MAX_DAYS = 90
# The severities that fail the frontend audit, as `pnpm audit --audit-level high` would.
FAILING = frozenset({"high", "critical"})

type Ecosystem = Literal["pypi", "npm"]

# pnpm reports GitHub advisory ids; pip-audit accepts any id or alias it prints.
_GHSA = re.compile(r"GHSA(-[23456789cfghjmpqrvwx]{4}){3}")
_PYPI_ID = re.compile(rf"{_GHSA.pattern}|PYSEC-\d{{4}}-\d+|CVE-\d{{4}}-\d{{4,}}")


# --- the allowlist --------------------------------------------------------------------------------


@with_config(ConfigDict(extra="forbid"))
class _AdvisoryData(TypedDict):
    id: str
    ecosystem: Ecosystem
    package: str
    expires: date
    reason: str


@with_config(ConfigDict(extra="forbid"))
class _AllowlistData(TypedDict):
    advisory: NotRequired[list[_AdvisoryData]]


_ALLOWLIST = TypeAdapter(_AllowlistData)


@dataclass(frozen=True, slots=True)
class Advisory:
    id: str
    ecosystem: Ecosystem
    package: str
    expires: date
    reason: str


def parse_allowlist(text: str) -> list[Advisory]:
    try:
        data = _ALLOWLIST.validate_python(tomllib.loads(text))
    except (tomllib.TOMLDecodeError, ValidationError) as exc:
        raise DependencyCheckError(f"audit_allowlist.toml: {exc}") from exc
    return [Advisory(**entry) for entry in data.get("advisory", [])]


def load_allowlist(path: Path = ALLOWLIST_PATH) -> list[Advisory]:
    return parse_allowlist(path.read_text(encoding="utf-8"))


def allowlist_problems(advisories: Iterable[Advisory], today: date) -> list[str]:
    """Why an entry may not be applied: malformed, expired, or accepted for too long."""
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()
    for advisory in advisories:
        where = f"audit_allowlist.toml {advisory.ecosystem} {advisory.id} ({advisory.package})"
        pattern = _GHSA if advisory.ecosystem == "npm" else _PYPI_ID
        if not pattern.fullmatch(advisory.id):
            kind = "a GHSA id" if advisory.ecosystem == "npm" else "a GHSA, PYSEC or CVE id"
            problems.append(f"{where}: the id must be {kind}")
        if (advisory.ecosystem, advisory.id) in seen:
            problems.append(f"{where}: listed twice")
        seen.add((advisory.ecosystem, advisory.id))
        if not advisory.reason.strip() or not advisory.package.strip():
            problems.append(f"{where}: the package and the reason must not be empty")
        if advisory.expires < today:
            problems.append(
                f"{where}: expired on {advisory.expires.isoformat()}; fix it by a bump, or decide "
                "again and write a new reason and date"
            )
        elif advisory.expires > today + timedelta(days=MAX_DAYS):
            problems.append(
                f"{where}: expires more than {MAX_DAYS} days ahead; accept it for a quarter at most"
            )
    return problems


def accepted(advisories: Iterable[Advisory], today: date) -> list[Advisory]:
    """The entries that may hide an advisory: well-formed, current, dated within ``MAX_DAYS``."""
    return [advisory for advisory in advisories if not allowlist_problems([advisory], today)]


# --- pip-audit ------------------------------------------------------------------------------------


def pip_audit_command(python: str, advisories: Iterable[Advisory]) -> list[str]:
    command = [
        python, "-m", "pip_audit", "--strict", "--progress-spinner", "off", "--aliases", "on",
        "-r", "requirements.txt", "-r", "requirements-dev.txt",
    ]  # fmt: skip
    for advisory in advisories:
        if advisory.ecosystem == "pypi":
            command += ["--ignore-vuln", advisory.id]
    return command


# --- pnpm audit -----------------------------------------------------------------------------------


class _Finding(TypedDict, total=False):
    version: str
    paths: list[str]


class _PnpmAdvisory(TypedDict, total=False):
    github_advisory_id: Required[str]
    severity: Required[str]
    module_name: Required[str]
    title: str
    patched_versions: str
    findings: list[_Finding]


class _PnpmReport(TypedDict):
    advisories: dict[str, _PnpmAdvisory]


_PNPM_REPORT = TypeAdapter(_PnpmReport)


@dataclass(frozen=True, slots=True)
class NpmFinding:
    id: str
    severity: str
    package: str
    title: str
    patched: str
    found: tuple[str, ...]

    def describe(self) -> str:
        where = ", ".join(self.found) or "?"
        return (
            f"{self.severity} {self.id} {self.package} ({where}): {self.title}; "
            f"fixed in {self.patched or 'no release yet'}"
        )


def pnpm_findings(output: str) -> list[NpmFinding]:
    """The advisories in ``pnpm audit --json`` output; ``DependencyCheckError`` if it is none."""
    try:
        report = _PNPM_REPORT.validate_json(output)
    except ValidationError as exc:
        excerpt = " ".join(output.split())[:300] or "no output"
        raise DependencyCheckError(f"pnpm audit gave no report: {excerpt}") from exc
    findings: list[NpmFinding] = []
    for advisory in report["advisories"].values():
        found = tuple(
            f"{finding.get('version', '?')} via {path}"
            for finding in advisory.get("findings", [])
            for path in finding.get("paths", [])[:1]
        )
        findings.append(
            NpmFinding(
                advisory["github_advisory_id"],
                advisory["severity"],
                advisory["module_name"],
                advisory.get("title", ""),
                advisory.get("patched_versions", ""),
                found,
            )
        )
    return sorted(findings, key=lambda finding: (finding.severity, finding.id, finding.package))


def npm_verdict(
    findings: Iterable[NpmFinding], advisories: Iterable[Advisory]
) -> tuple[list[NpmFinding], list[NpmFinding], Counter[str]]:
    """The findings that fail, the ones an allowlist entry hides, and the rest by severity."""
    # By id, as both tools ignore: one advisory can name several packages (a tool and its parts).
    hidden = {advisory.id for advisory in advisories if advisory.ecosystem == "npm"}
    failing: list[NpmFinding] = []
    accepted_findings: list[NpmFinding] = []
    below: Counter[str] = Counter()
    for finding in findings:
        if finding.severity not in FAILING:
            below[finding.severity] += 1
        elif finding.id in hidden:
            accepted_findings.append(finding)
        else:
            failing.append(finding)
    return failing, accepted_findings, below


# --- the command ----------------------------------------------------------------------------------


def _say(line: str) -> None:
    sys.stdout.write(f"audit: {line}\n")
    sys.stdout.flush()


def _pip_audit(advisories: list[Advisory]) -> list[str]:
    _say("pip-audit over requirements.txt and requirements-dev.txt")
    command = pip_audit_command(sys.executable, advisories)
    # This interpreter, fixed arguments and ids that matched a pattern; nothing reaches a shell.
    result = subprocess.run(command, cwd=BACKEND_ROOT, check=False)  # noqa: S603
    if result.returncode != 0:
        return ["pip-audit reported a known vulnerability or could not finish (above)"]
    return []


def _pnpm_audit(advisories: list[Advisory]) -> list[str]:
    _say("pnpm audit over frontend/pnpm-lock.yaml (fails on high and critical)")
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        return ["pnpm is not on PATH; it audits the frontend lockfile"]
    # The pnpm on PATH with fixed arguments; nothing reaches a shell.
    result = subprocess.run(  # noqa: S603
        [pnpm, "audit", "--json"], cwd=FRONTEND_ROOT, capture_output=True, text=True, check=False
    )
    try:
        findings = pnpm_findings(result.stdout)
    except DependencyCheckError as exc:
        return [f"{exc} {' '.join(result.stderr.split())[:300]}".strip()]
    failing, hidden, below = npm_verdict(findings, advisories)
    for finding in hidden:
        _say(f"accepted: {finding.describe()}")
    if below:
        counts = ", ".join(f"{count} {severity}" for severity, count in sorted(below.items()))
        _say(f"below high, not failing: {counts}")
    for finding in failing:
        _say(finding.describe())
    if failing:
        return [f"pnpm audit found {len(failing)} high or critical advisory(ies) (above)"]
    _say("no high or critical advisory")
    return []


def run() -> int:
    today = datetime.now(UTC).date()
    advisories = load_allowlist()
    problems = allowlist_problems(advisories, today)
    applied = accepted(advisories, today)
    for advisory in applied:
        _say(
            f"accepted until {advisory.expires.isoformat()}: {advisory.ecosystem} {advisory.id} "
            f"({advisory.package}): {advisory.reason}"
        )
    problems += _pip_audit(applied)
    problems += _pnpm_audit(applied)
    if problems:
        for problem in problems:
            sys.stderr.write(f"audit: {problem}\n")
        return 1
    _say("ok, no known vulnerability beyond the accepted ones")
    return 0
