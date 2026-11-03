"""The dependency checks: licence expressions, metadata reading, the policy and the allowlist.

``python -m tools.deps licences`` and ``audit`` read the installed packages and ask the network;
CI runs them. These tests hold the decisions in between to fixed inputs: how an SPDX expression is
parsed and decided, which metadata field a licence is read from, what the policy accepts, which
packages the requirement closure and the pnpm walk find, and when an accepted advisory stops
counting.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from pydantic import JsonValue

from tools.deps import DependencyCheckError, audit, licences, spdx
from tools.deps.licences import Package, Policy, PythonMetadata, Scoped

REPO_ROOT = Path(__file__).resolve().parents[3]

POLICY = Policy(allowed=("MIT", "Apache-2.0", "BSD-3-Clause", "BSD"))
SCOPED = Policy(POLICY.allowed, (Scoped("BlueOak-1.0.0", "npm", "minimatch", "lint tooling"),))
KNOWN = SCOPED.spellings.values()


def _npm(name: str, licence: str | None, source: str = "license") -> Package:
    return Package("npm", name, "1.0.0", None if licence is None else spdx.parse(licence), source)


# --- SPDX expressions -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "rendered"),
    [
        ("MIT", "MIT"),
        ("(MIT OR CC0-1.0)", "MIT OR CC0-1.0"),
        ("MIT OR Apache-2.0 AND BSD-3-Clause", "MIT OR Apache-2.0 AND BSD-3-Clause"),
        ("(MIT OR GPL-3.0-only) AND Apache-2.0", "(MIT OR GPL-3.0-only) AND Apache-2.0"),
        ("(MIT OR ISC) OR 0BSD", "MIT OR ISC OR 0BSD"),
        ("GPL-2.0-only WITH Classpath-exception-2.0", "GPL-2.0-only WITH Classpath-exception-2.0"),
        ("  Apache-2.0   AND   MIT ", "Apache-2.0 AND MIT"),
    ],
)
def test_an_expression_parses_and_renders_canonically(text: str, rendered: str) -> None:
    assert spdx.render(spdx.parse(text)) == rendered


def test_and_binds_tighter_than_or() -> None:
    expression = spdx.parse("MIT OR Apache-2.0 AND GPL-3.0-only")
    assert expression == spdx.AnyOf(
        (
            spdx.Licence("MIT"),
            spdx.AllOf((spdx.Licence("Apache-2.0"), spdx.Licence("GPL-3.0-only"))),
        )
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "MIT OR",
        "(MIT",
        "MIT)",
        "MIT Apache-2.0",
        "SEE LICENSE IN LICENSE.md",
        "mit or apache-2.0",  # operators are upper case
        "AND",
        "MIT WITH",
        "()",
    ],
)
def test_text_that_is_not_an_expression_is_refused(text: str) -> None:
    with pytest.raises(spdx.ExpressionError):
        spdx.parse(text)


@pytest.mark.parametrize(
    ("text", "allowed"),
    [
        ("MIT OR CC0-1.0", True),  # a choice: one allowed side is enough
        ("CC0-1.0 OR GPL-3.0-only", False),
        ("MIT AND Apache-2.0", True),
        ("MIT AND GPL-3.0-only", False),  # every licence applies
        ("(GPL-3.0-only OR MIT) AND Apache-2.0", True),
        ("Apache-2.0 WITH LLVM-exception", False),  # an exception is a licence of its own
    ],
)
def test_or_needs_one_side_and_and_needs_every_side(text: str, allowed: bool) -> None:
    def ok(name: str) -> bool:
        return name in {"MIT", "Apache-2.0"}

    assert spdx.satisfied(spdx.parse(text), ok) is allowed


def test_licences_lists_each_name_once_in_order() -> None:
    assert spdx.licences(spdx.parse("MIT OR (Apache-2.0 AND MIT)")) == ["MIT", "Apache-2.0"]


# --- reading a licence ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("metadata", "licence", "source"),
    [
        # PEP 639 wins over everything else.
        (
            PythonMetadata("Apache-2.0 OR BSD-3-Clause", "BSD", ("License :: OSI Approved",)),
            "Apache-2.0 OR BSD-3-Clause",
            "License-Expression",
        ),
        # An id in License is more precise than the BSD classifier.
        (
            PythonMetadata(None, "BSD-3-Clause", ("License :: OSI Approved :: BSD License",)),
            "BSD-3-Clause",
            "License",
        ),
        # The whole licence text, or a name that is no id: the classifier decides.
        (
            PythonMetadata(
                None,
                "Apache License\n   Version 2.0, January 2004",
                ("License :: OSI Approved :: Apache Software License",),
            ),
            "Apache-2.0",
            "classifiers",
        ),
        (
            PythonMetadata(
                None, "PSFL", ("License :: OSI Approved :: Python Software Foundation License",)
            ),
            "PSF-2.0",
            "classifiers",
        ),
        # Several classifiers apply together; "OSI Approved" alone names nothing.
        (
            PythonMetadata(
                None,
                None,
                (
                    "License :: OSI Approved",
                    "License :: OSI Approved :: MIT License",
                    "License :: OSI Approved :: Apache Software License",
                    "Programming Language :: Python",
                ),
            ),
            "MIT AND Apache-2.0",
            "classifiers",
        ),
        # A classifier without an id stays as its text, so the policy refuses it by name.
        (
            PythonMetadata(None, None, ("License :: Public Domain",)),
            "License :: Public Domain",
            "classifiers",
        ),
        # An SPDX id the policy does not name, and nothing better: read, then refused by name.
        (PythonMetadata(None, "GPL-3.0-only"), "GPL-3.0-only", "License"),
    ],
)
def test_a_python_licence_is_read_from_the_most_precise_field(
    metadata: PythonMetadata, licence: str, source: str
) -> None:
    expression, where = licences.python_licence(metadata, KNOWN)
    assert expression is not None
    assert (spdx.render(expression), where) == (licence, source)


@pytest.mark.parametrize(
    ("metadata", "reason"),
    [
        (PythonMetadata(), "no License-Expression, License or licence classifier"),
        (PythonMetadata(None, "UNKNOWN"), "is not an SPDX expression"),
        (PythonMetadata(None, "The MIT License\n\nCopyright"), "is not an SPDX expression"),
        (PythonMetadata("MIT OR"), "does not parse"),
    ],
)
def test_python_metadata_without_a_licence_is_unreadable(
    metadata: PythonMetadata, reason: str
) -> None:
    expression, where = licences.python_licence(metadata, KNOWN)
    assert expression is None
    assert reason in where


@pytest.mark.parametrize(
    ("licence", "legacy", "expected"),
    [
        ("(MIT OR CC0-1.0)", None, ("MIT OR CC0-1.0", "license")),
        (
            {"type": "BSD-3-Clause", "url": "https://example.com"},
            None,
            ("BSD-3-Clause", "license.type"),
        ),
        (None, [{"type": "MIT"}], ("MIT", "licenses")),
        (None, [{"type": "MIT"}, {"type": "Apache-2.0"}], ("MIT AND Apache-2.0", "licenses")),
    ],
)
def test_an_npm_licence_is_read_from_license_or_the_legacy_fields(
    licence: JsonValue, legacy: JsonValue, expected: tuple[str, str]
) -> None:
    expression, where = licences.npm_licence(licence, legacy)
    assert expression is not None
    assert (spdx.render(expression), where) == expected


@pytest.mark.parametrize(
    ("licence", "legacy"),
    [
        ("SEE LICENSE IN LICENSE.txt", None),
        (None, None),
        (None, ["MIT"]),
        (None, [{"type": "MIT"}, {"url": "https://example.com"}]),
        (None, []),
    ],
)
def test_an_npm_manifest_without_a_licence_is_unreadable(
    licence: JsonValue, legacy: JsonValue
) -> None:
    assert licences.npm_licence(licence, legacy)[0] is None


# --- the policy -----------------------------------------------------------------------------------


def test_a_licence_inside_the_policy_passes_and_is_counted_per_ecosystem() -> None:
    inventory = licences.check(
        [_npm("a", "MIT"), _npm("b", "mit"), Package("pypi", "c", "1", spdx.parse("MIT"), "x")],
        POLICY,
    )
    assert inventory.problems == []
    assert dict(inventory.counts["MIT"]) == {"npm": 2, "pypi": 1}  # ids ignore case


def test_a_licence_outside_the_policy_fails_naming_package_and_licence() -> None:
    inventory = licences.check([_npm("a", "MIT"), _npm("b", "GPL-3.0-only")], POLICY)
    assert len(inventory.problems) == 1
    assert inventory.problems[0].startswith("npm b 1.0.0: GPL-3.0-only (license) is not")


def test_a_scoped_licence_is_allowed_for_its_package_only() -> None:
    inventory = licences.check(
        [_npm("minimatch", "BlueOak-1.0.0"), _npm("other", "BlueOak-1.0.0")], SCOPED
    )
    assert [problem.split(":")[0] for problem in inventory.problems] == ["npm other 1.0.0"]


def test_a_scoped_licence_nothing_needs_any_more_fails() -> None:
    inventory = licences.check([_npm("minimatch", "MIT")], SCOPED)
    assert len(inventory.problems) == 1
    assert "allows BlueOak-1.0.0 for npm minimatch" in inventory.problems[0]


def test_an_override_covers_unreadable_metadata_only() -> None:
    override = licences.Override("pypi", "legacy", spdx.parse("MIT"), "LICENSE is MIT")
    policy = Policy(POLICY.allowed, (), (override,))
    unreadable = Package("pypi", "legacy", "1", None, "no License-Expression")
    used = licences.check([_npm("a", "MIT"), unreadable], policy)
    assert used.problems == []
    assert used.packages[1].source == "override: LICENSE is MIT"

    readable = Package("pypi", "legacy", "2", spdx.parse("MIT"), "License-Expression")
    stale = licences.check([_npm("a", "MIT"), readable], policy)
    assert len(stale.problems) == 1
    assert "override in licences.toml is stale" in stale.problems[0]

    absent = licences.check([_npm("a", "MIT")], policy)
    assert absent.problems == []
    assert absent.notes == ["the override for pypi legacy was not used: not installed here"]


def test_unreadable_metadata_without_an_override_fails() -> None:
    inventory = licences.check([_npm("a", "MIT"), _npm("odd", None, "no license field")], POLICY)
    assert len(inventory.problems) == 1
    assert (
        "npm odd 1.0.0: no licence the check can read (no license field)" in (inventory.problems[0])
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('allowed = ["MIT"]\nextra = 1\n', "extra"),
        ('allowed = ["MIT OR ISC"]\n', "list each licence on its own"),
        (
            'allowed = []\n[[scoped]]\nlicence = "X"\necosystem = "npm"\npackage = "p"\n'
            'reason = " "\n',
            "the reason is empty",
        ),
        (
            'allowed = []\n[[override]]\necosystem = "npm"\npackage = "p"\nlicence = "MIT OR"\n'
            'reason = "r"\n',
            "override p",
        ),
        ('allowed = []\n[[scoped]]\nlicence = "X"\necosystem = "deb"\npackage = "p"\n', "deb"),
    ],
)
def test_a_malformed_policy_is_refused(text: str, message: str) -> None:
    with pytest.raises(DependencyCheckError, match=re.escape(message)):
        licences.parse_policy(text)


# The family names AGENTS.md uses for the SPDX ids of licences.toml.
FAMILIES = {
    "MIT": "MIT",
    "MIT-0": "MIT-0",
    "ISC": "ISC",
    "0BSD": "0BSD",
    "BSD-2-Clause": "BSD",
    "BSD-3-Clause": "BSD",
    "BSD": "BSD",
    "Apache-2.0": "Apache-2.0",
    "PSF-2.0": "PSF",
    "Python-2.0": "PSF",
    "MPL-2.0": "MPL-2.0",
}


def test_licences_toml_is_the_list_in_agents_md() -> None:
    policy = licences.load_policy()
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    match = re.search(r"The current set is (.*?)Nothing copyleft", agents, re.S)
    assert match, "AGENTS.md no longer states the licence list"
    sentence = " ".join(match.group(1).split())
    scoped = set(re.findall(r"([\w.-]+) \(only `([^`]+)`", sentence))
    assert scoped == {(entry.licence, entry.package) for entry in policy.scoped}
    words = set(re.findall(r"[A-Za-z0-9][\w.-]*", re.sub(r"\([^)]*\)", "", sentence)))
    families = {word for word in words if not word.islower()} - {name for name, _ in scoped}
    assert set(policy.allowed) <= FAMILIES.keys(), "teach FAMILIES the new id's AGENTS.md name"
    assert families == {FAMILIES[name] for name in policy.allowed}


# --- what is installed ----------------------------------------------------------------------------


def _requires(graph: dict[str, list[str]]) -> Callable[[str], list[str]]:
    return lambda name: graph[name]


# `shared` is reached once without extras and once with `speed`, in both orders: a package seen
# before is followed again when a later path asks it for more.
@pytest.mark.parametrize(
    "app", [["lib", "server[standard]"], ["server[standard]", "lib"]], ids=["lib-first", "lib-last"]
)
def test_the_closure_follows_extras_and_markers(app: list[str]) -> None:
    graph = {
        "app": [*app, 'never; sys_platform == "no-such-platform"'],
        "lib": ["shared", 'optional; extra == "fast"'],
        "server": ['uvloop; extra == "standard"', 'shared[speed]; extra == "standard"'],
        "uvloop": [],
        "shared": ['speedup; extra == "speed"'],
        "speedup": [],
    }
    found = licences.closure([Requirement("app")], _requires(graph))
    assert found == {
        "app": frozenset(),
        "lib": frozenset(),
        "server": frozenset({"standard"}),
        "uvloop": frozenset(),
        "shared": frozenset({"speed"}),
        "speedup": frozenset(),
    }


def test_requirement_files_are_read_with_their_includes(tmp_path: Path) -> None:
    (tmp_path / "base.txt").write_text("# runtime\nfastapi>=0.115,<1\n", encoding="utf-8")
    (tmp_path / "dev.txt").write_text(
        "-r base.txt\n\npytest>=8  # the runner\nruff==0.17.3\n", encoding="utf-8"
    )
    assert licences.requirement_lines(tmp_path / "dev.txt") == [
        "fastapi>=0.115,<1",
        "pytest>=8",
        "ruff==0.17.3",
    ]
    (tmp_path / "odd.txt").write_text("-e .\n", encoding="utf-8")
    with pytest.raises(DependencyCheckError, match="does not follow"):
        licences.requirement_lines(tmp_path / "odd.txt")


def _package(store: Path, entry: str, name: str, version: str, licence: str) -> Path:
    directory = store / entry / "node_modules" / name
    directory.mkdir(parents=True)
    manifest = f'{{"name": "{name}", "version": "{version}", "license": "{licence}"}}'
    (directory / "package.json").write_text(manifest, encoding="utf-8")
    return directory


def _link(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("this account may not create symbolic links")


def test_the_npm_walk_follows_links_from_the_top_and_stays_in_the_store(tmp_path: Path) -> None:
    node_modules = tmp_path / "node_modules"
    store = node_modules / ".pnpm"
    app = _package(store, "app@1.0.0", "app", "1.0.0", "MIT")
    dep = _package(store, "@scope+dep@2.0.0", "@scope/dep", "2.0.0", "ISC")
    _package(store, "left-behind@0.1.0", "left-behind", "0.1.0", "GPL-3.0-only")
    outside = tmp_path / "elsewhere" / "tool"
    outside.mkdir(parents=True)
    (outside / "package.json").write_text('{"name": "tool", "version": "9.9.9"}', "utf-8")
    _link(node_modules / "app", app)
    _link(node_modules / "tool", outside)  # linked in by hand, not by the lockfile
    _link(store / "app@1.0.0" / "node_modules" / "@scope" / "dep", dep)
    found = licences.npm_packages(node_modules)
    assert [(package.name, package.version, package.source) for package in found] == [
        ("@scope/dep", "2.0.0", "license"),
        ("app", "1.0.0", "license"),
    ]


def test_the_npm_walk_needs_an_installed_tree(tmp_path: Path) -> None:
    with pytest.raises(DependencyCheckError, match="pnpm install"):
        licences.npm_packages(tmp_path / "node_modules")


# --- the audit allowlist --------------------------------------------------------------------------

TODAY = date(2026, 11, 3)


def _advisory(
    advisory_id: str = "GHSA-2c2m-wq9q-qgxw",
    ecosystem: audit.Ecosystem = "npm",
    expires: date = TODAY + timedelta(days=30),
    reason: str = "no fixed version yet",
) -> audit.Advisory:
    return audit.Advisory(advisory_id, ecosystem, "example", expires, reason)


def test_an_empty_allowlist_parses() -> None:
    assert audit.parse_allowlist("# nothing accepted\n") == []


def test_an_allowlist_entry_parses_with_a_toml_date() -> None:
    text = (
        '[[advisory]]\nid = "PYSEC-2026-1"\necosystem = "pypi"\npackage = "p"\n'
        'expires = 2026-12-01\nreason = "r"\n'
    )
    assert audit.parse_allowlist(text) == [
        audit.Advisory("PYSEC-2026-1", "pypi", "p", date(2026, 12, 1), "r")
    ]


@pytest.mark.parametrize(
    "text",
    [
        # no expiry date
        '[[advisory]]\nid = "GHSA-2c2m-wq9q-qgxw"\necosystem = "npm"\npackage = "p"\n'
        'reason = "r"\n',
        '[[advisory]]\nid = "X"\necosystem = "npm"\npackage = "p"\nexpires = 2026-12-01\n'
        'reason = "r"\nnote = "unknown key"\n',
        "[[advisory]]\nid = = 1\n",
    ],
)
def test_a_malformed_allowlist_is_refused(text: str) -> None:
    with pytest.raises(DependencyCheckError):
        audit.parse_allowlist(text)


@pytest.mark.parametrize(
    ("advisory", "problem"),
    [
        (_advisory(expires=TODAY), None),  # still valid on its last day
        (_advisory(expires=TODAY + timedelta(days=audit.MAX_DAYS)), None),
        (_advisory("PYSEC-2026-3552", "pypi"), None),
        (_advisory("CVE-2026-69247", "pypi"), None),
        (_advisory(expires=TODAY - timedelta(days=1)), "expired on 2026-11-02"),
        (_advisory(expires=TODAY + timedelta(days=audit.MAX_DAYS + 1)), "more than 90 days"),
        (_advisory("PYSEC-2026-3552", "npm"), "must be a GHSA id"),
        (_advisory("GHSA-short", "pypi"), "must be a GHSA, PYSEC or CVE id"),
        (_advisory(reason="  "), "must not be empty"),
    ],
)
def test_an_allowlist_entry_is_well_formed_current_and_short_lived(
    advisory: audit.Advisory, problem: str | None
) -> None:
    problems = audit.allowlist_problems([advisory], TODAY)
    if problem is None:
        assert problems == []
        assert audit.accepted([advisory], TODAY) == [advisory]
    else:
        assert len(problems) == 1
        assert problem in problems[0]
        assert audit.accepted([advisory], TODAY) == []  # the tools see the advisory again


def test_an_advisory_listed_twice_is_refused() -> None:
    problems = audit.allowlist_problems([_advisory(), _advisory()], TODAY)
    assert len(problems) == 1
    assert "listed twice" in problems[0]


def test_pip_audit_ignores_only_accepted_python_advisories() -> None:
    accepted = [_advisory(), _advisory("PYSEC-2026-1", "pypi")]
    assert audit.pip_audit_command("python", accepted) == [
        "python", "-m", "pip_audit", "--strict", "--progress-spinner", "off", "--aliases", "on",
        "-r", "requirements.txt", "-r", "requirements-dev.txt", "--ignore-vuln", "PYSEC-2026-1",
    ]  # fmt: skip


# The shape `pnpm audit --json` prints, cut to the fields the check reads.
PNPM_REPORT = """{
  "actions": [],
  "advisories": {
    "1": {"github_advisory_id": "GHSA-5gmw-xhrv-c9v3", "severity": "critical",
          "module_name": "tinypool", "title": "Prototype pollution", "patched_versions": ">=2.1.1",
          "findings": [{"version": "1.1.1", "paths": [".>vitest>tinypool"]}]},
    "2": {"github_advisory_id": "GHSA-gg6h-894w-4m9c", "severity": "high",
          "module_name": "re2js", "title": "Quadratic time", "patched_versions": ">=2.8.7",
          "findings": [{"version": "2.8.6", "paths": [".>markdownlint-cli2>markdownlint>re2js"]}]},
    "3": {"github_advisory_id": "GHSA-g3hv-75wg-m249", "severity": "moderate",
          "module_name": "minimatch", "findings": []},
    "4": {"github_advisory_id": "GHSA-238p-pmpm-9mq7", "severity": "low", "module_name": "katex"}
  },
  "muted": [],
  "metadata": {"vulnerabilities": {"low": 1, "moderate": 1, "high": 1, "critical": 1}}
}"""


def test_pnpm_findings_fail_from_high_up_unless_accepted() -> None:
    findings = audit.pnpm_findings(PNPM_REPORT)
    accepted = [_advisory("GHSA-gg6h-894w-4m9c")]
    failing, hidden, below = audit.npm_verdict(findings, accepted)
    assert [finding.id for finding in failing] == ["GHSA-5gmw-xhrv-c9v3"]
    assert [finding.package for finding in hidden] == ["re2js"]
    assert dict(below) == {"low": 1, "moderate": 1}
    assert failing[0].describe() == (
        "critical GHSA-5gmw-xhrv-c9v3 tinypool (1.1.1 via .>vitest>tinypool): "
        "Prototype pollution; fixed in >=2.1.1"
    )
    # A Python entry never hides an npm advisory.
    python_only = [_advisory("GHSA-gg6h-894w-4m9c", "pypi")]
    assert len(audit.npm_verdict(findings, python_only)[0]) == 2


@pytest.mark.parametrize("output", ["", "ERR_PNPM_AUDIT_BAD_RESPONSE", '{"error": {"code": "x"}}'])
def test_pnpm_output_without_a_report_fails(output: str) -> None:
    with pytest.raises(DependencyCheckError, match="pnpm audit gave no report"):
        audit.pnpm_findings(output)


def test_the_shipped_allowlist_and_policy_parse() -> None:
    licences.load_policy()
    for advisory in audit.load_allowlist():
        # The date is CI's business; the form is checked here, on the entry's own last day.
        assert audit.allowlist_problems([advisory], advisory.expires) == []
