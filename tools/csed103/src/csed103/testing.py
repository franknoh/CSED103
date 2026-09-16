"""Compile assignment programs and run their input/output test cases."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .compilers import Toolchain, compile_problem, detect_toolchain
from .project import load_yaml


@dataclass
class TestResult:
    problem: str
    case: str
    passed: bool
    elapsed_ms: float
    reason: str = ""


def normalize_output(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    lines = [line.rstrip() for line in text.split("\n")]

    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)


def find_cases(
    test_dir: Path,
) -> list[tuple[Path, Path]]:
    if not test_dir.is_dir():
        return []

    cases: list[tuple[Path, Path]] = []

    for input_path in sorted(test_dir.glob("*.in")):
        output_path = input_path.with_suffix(".out")

        if not output_path.is_file():
            raise RuntimeError(f"missing expected output: {output_path}")

        cases.append((input_path, output_path))

    return cases


def run_case(
    executable: Path,
    input_path: Path,
    expected_path: Path,
    timeout: float,
    problem: str,
) -> TestResult:
    input_data = input_path.read_bytes()

    expected = expected_path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    start = time.perf_counter()

    try:
        proc = subprocess.run(
            [str(executable)],
            input=input_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )

    except subprocess.TimeoutExpired:
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        return TestResult(
            problem=problem,
            case=input_path.stem,
            passed=False,
            elapsed_ms=elapsed_ms,
            reason=f"timeout after {timeout:.3f}s",
        )

    elapsed_ms = (time.perf_counter() - start) * 1000.0

    stdout = proc.stdout.decode(
        "utf-8",
        errors="replace",
    )

    stderr = proc.stderr.decode(
        "utf-8",
        errors="replace",
    )

    if proc.returncode != 0:
        reason = f"exit code {proc.returncode}"

        if stderr.strip():
            reason += "\nstderr:\n" + stderr.rstrip()

        return TestResult(
            problem=problem,
            case=input_path.stem,
            passed=False,
            elapsed_ms=elapsed_ms,
            reason=reason,
        )

    actual = normalize_output(stdout)
    expected = normalize_output(expected)

    if actual != expected:
        return TestResult(
            problem=problem,
            case=input_path.stem,
            passed=False,
            elapsed_ms=elapsed_ms,
            reason=(
                "output mismatch\n"
                "--- expected ---\n"
                f"{expected}\n"
                "--- actual ---\n"
                f"{actual}"
            ),
        )

    return TestResult(
        problem=problem,
        case=input_path.stem,
        passed=True,
        elapsed_ms=elapsed_ms,
    )


def executable_path(
    directory: Path,
    problem: str,
    toolchain: Toolchain,
) -> Path:
    if os.name == "nt" or toolchain == "msvc":
        return directory / f"{problem}.exe"

    return directory / problem


def test_assignment(
    assignment: Path, *, compiler: Toolchain = "auto", timeout: float = 2.0
) -> int:
    manifest = load_yaml(assignment / "manifest.yaml")
    toolchain = detect_toolchain(compiler)
    problems = manifest.get("problems")

    if not isinstance(problems, dict) or not problems:
        raise RuntimeError("manifest must contain a non-empty 'problems' mapping")

    results: list[TestResult] = []
    compile_failures = 0

    print(f"Assignment : {assignment.name}")
    print(f"Toolchain  : {toolchain}")
    print()

    with tempfile.TemporaryDirectory(prefix="csed103-") as tmp:
        build_dir = Path(tmp)

        for problem, config in problems.items():
            if not isinstance(config, dict):
                print(f"[ERROR] {problem}: configuration must be a mapping")
                compile_failures += 1
                continue

            executable = executable_path(
                build_dir,
                problem,
                toolchain,
            )

            print(f"[BUILD] {problem}")

            try:
                ok, compiler_output = compile_problem(
                    assignment=assignment,
                    problem=problem,
                    config=config,
                    output=executable,
                    build_dir=build_dir,
                    toolchain=toolchain,
                )
            except RuntimeError as exc:
                print(f"[ERROR] {exc}")
                compile_failures += 1
                print()
                continue

            if not ok:
                print(f"[COMPILE FAIL] {problem}")

                if compiler_output:
                    print(compiler_output)

                compile_failures += 1
                print()
                continue

            if compiler_output:
                print(compiler_output)

            raw_test_dir = config.get(
                "tests",
                f"tests/{problem}",
            )

            test_dir = assignment / str(raw_test_dir)

            try:
                cases = find_cases(test_dir)
            except RuntimeError as exc:
                print(f"[ERROR] {problem}: {exc}")
                compile_failures += 1
                print()
                continue

            if not cases:
                print(f"[SKIP] {problem}: no test cases")
                print()
                continue

            print(f"[TEST] {problem}: {len(cases)} case(s)")

            for input_path, output_path in cases:
                result = run_case(
                    executable=executable,
                    input_path=input_path,
                    expected_path=output_path,
                    timeout=timeout,
                    problem=problem,
                )

                results.append(result)

                status = "PASS" if result.passed else "FAIL"

                print(f"  [{status}] {result.case:<24} {result.elapsed_ms:10.3f} ms")

                if not result.passed:
                    for line in result.reason.splitlines():
                        print(f"         {line}")

            print()

    passed = sum(result.passed for result in results)

    failed = len(results) - passed

    runtimes = [result.elapsed_ms for result in results]

    print("=" * 64)
    print("Test Summary")
    print("=" * 64)

    print(f"Toolchain        : {toolchain}")
    print(f"Compile failures : {compile_failures}")
    print(f"Cases            : {len(results)}")
    print(f"Passed           : {passed}")
    print(f"Failed           : {failed}")

    if results:
        print(f"Pass rate        : {passed / len(results) * 100:.1f}%")

        print(f"Total runtime    : {sum(runtimes):.3f} ms")

        print(f"Average runtime  : {sum(runtimes) / len(runtimes):.3f} ms")

        print(f"Maximum runtime  : {max(runtimes):.3f} ms")

    if compile_failures or failed:
        return 1

    return 0
