from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import DependencyCheckError, audit, licences


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.deps",
        description="Check the licences and the known vulnerabilities of every dependency.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser(
        "licences", help="fail on a licence outside tools/deps/licences.toml (AGENTS.md)"
    )
    inventory.add_argument(
        "--list", action="store_true", help="also print every package with its licence"
    )
    commands.add_parser("audit", help="pip-audit and pnpm audit with audit_allowlist.toml")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "licences":
            return licences.run(list_all=bool(arguments.list))
        return audit.run()
    except DependencyCheckError as exc:
        sys.stderr.write(f"deps: {exc}\n")
        return 1


raise SystemExit(main())
