"""Command-line entry point for inert repository validation and packaging."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from car_job_search.release import ReleaseRepositoryError, package_release, validate_repository


def main(arguments: list[str] | None = None) -> int:
    """Run a CLI command and return a stable shell exit code."""
    parser = argparse.ArgumentParser(prog="car_job_search")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--all", action="store_true", required=True)
    release = commands.add_parser("release")
    release_commands = release.add_subparsers(dest="release_command", required=True)
    package = release_commands.add_parser("package")
    package.add_argument("--output", type=Path, required=True)
    parsed = parser.parse_args(arguments)

    if parsed.command == "validate":
        failures = validate_repository()
        if failures:
            print("validation failed: " + "; ".join(failures), file=sys.stderr)
            return 1
        print("validation: OK")
        return 0
    try:
        package_release(parsed.output)
    except ReleaseRepositoryError as error:
        print(f"release package failed: {error}", file=sys.stderr)
        return 1
    print(f"release package: wrote {parsed.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
