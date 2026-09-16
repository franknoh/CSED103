"""The single command-line entry point for assignment tooling."""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
from pathlib import Path

from .build import build_report, build_submission
from .ppy import build_ppy
from .project import (
    assignments,
    clean_assignment,
    find_root,
    load_yaml,
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
        prog="csed103", description="Build, test, and package assignments."
    )
    parser.add_argument(
        "--root", type=Path, help="project directory (default: discover from cwd)"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser(
        "build", help="generate sources, build reports, or package submissions"
    )
    targets = build.add_subparsers(dest="target", required=True)
    for name, help_text in (
        ("report", "build a PDF report"),
        ("submission", "build a submission ZIP"),
    ):
        target = targets.add_parser(name, help=help_text)
        target.add_argument("assignment")
        target.add_argument(
            "--pdf-engine", help="Pandoc PDF engine (default: PDF_ENGINE or xelatex)"
        )
    ppy = targets.add_parser(
        "ppy", help="emit the PPY targets declared in manifest.yaml"
    )
    ppy.add_argument(
        "assignment",
        nargs="?",
        help="omit to process all assignments with PPY targets",
    )
    all_builds = targets.add_parser(
        "all", help="test, build report, and package every assignment"
    )
    all_builds.add_argument(
        "assignment", nargs="?", help="limit the full build to one assignment"
    )
    all_builds.add_argument(
        "--pdf-engine", help="Pandoc PDF engine (default: PDF_ENGINE or xelatex)"
    )
    add_test_options(all_builds)

    test = commands.add_parser(
        "test", help="compile and test an assignment, or all assignments"
    )
    test.add_argument("assignment", nargs="?", help="omit to test all assignments")
    add_test_options(test)

    clean = commands.add_parser("clean", help="remove assignment out directories")
    clean.add_argument("assignment", nargs="?", help="omit to clean all assignments")
    return parser


def run_assignment(root: Path, assignment: Path, args: argparse.Namespace) -> int:
    if args.command == "test":
        return test_assignment(assignment, compiler=args.compiler, timeout=args.timeout)
    if args.command == "clean":
        clean_assignment(assignment)
        return 0
    if args.target == "ppy":
        build_ppy(assignment)
    elif args.target == "all":
        if test_assignment(assignment, compiler=args.compiler, timeout=args.timeout):
            return 1
        build_report(assignment, pdf_engine=args.pdf_engine)
        build_submission(root, assignment, pdf_engine=args.pdf_engine)
    elif args.target == "report":
        build_report(assignment, pdf_engine=args.pdf_engine)
    else:
        build_submission(root, assignment, pdf_engine=args.pdf_engine)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        root = find_root(args.root)
        selected = (
            [resolve_assignment(root, args.assignment)]
            if args.assignment
            else assignments(root)
        )
        if args.command == "build" and args.target == "ppy" and not args.assignment:
            selected = [
                path for path in selected if "ppy" in load_yaml(path / "manifest.yaml")
            ]
            if not selected:
                raise RuntimeError("no assignments with PPY targets found")
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
