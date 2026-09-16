"""The single command-line entry point for assignment tooling."""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
from pathlib import Path

from .project import (
    assignments,
    find_root,
    resolve_assignment,
)
from .testing import test_assignment


def positive_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be a number") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be a finite positive number")
    return timeout


def add_test_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--compiler", choices=("auto", "gcc", "clang", "msvc"), default="auto"
    )
    parser.add_argument(
        "--timeout", type=positive_timeout, default=2.0, metavar="SECONDS"
    )


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="csed103", description="Compile and test assignments."
    )
    parser.add_argument(
        "--root", type=Path, help="project directory (default: discover from cwd)"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    test = commands.add_parser(
        "test", help="compile and test an assignment, or all assignments"
    )
    test.add_argument("assignment", nargs="?", help="omit to test all assignments")
    add_test_options(test)

    return parser


def run_assignment(root: Path, assignment: Path, args: argparse.Namespace) -> int:
    return test_assignment(assignment, compiler=args.compiler, timeout=args.timeout)


def main(argv: list[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        root = find_root(args.root)
        selected = (
            [resolve_assignment(root, args.assignment)]
            if args.assignment
            else assignments(root)
        )
        failed = False
        for assignment in selected:
            try:
                status = run_assignment(root, assignment, args)
            except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
                print(f"error: {assignment.name}: {exc}", file=sys.stderr)
                status = 1
            failed |= status != 0
        return int(failed)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
