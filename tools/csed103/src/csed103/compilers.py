"""C/C++ compiler selection, compilation, and linking."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Toolchain = Literal["auto", "gcc", "clang", "msvc"]

C_EXTENSIONS = {".c"}
CXX_EXTENSIONS = {".cc", ".cpp", ".cxx"}

COMPILE_EXTENSIONS = C_EXTENSIONS | CXX_EXTENSIONS


@dataclass(frozen=True)
class Compiler:
    executable: str
    style: Literal["unix", "msvc"]
    language: Literal["c", "cxx"]


def detect_toolchain(requested: Toolchain) -> Toolchain:
    if requested != "auto":
        return requested

    if os.name == "nt" and shutil.which("cl"):
        return "msvc"

    if shutil.which("gcc") and shutil.which("g++"):
        return "gcc"

    if shutil.which("clang") and shutil.which("clang++"):
        return "clang"

    raise RuntimeError("no supported compiler toolchain found")


def get_compiler(
    toolchain: Toolchain,
    language: Literal["c", "cxx"],
) -> Compiler:
    if toolchain == "gcc":
        name = "gcc" if language == "c" else "g++"

        executable = shutil.which(name)

        if executable is None:
            raise RuntimeError(f"compiler not found: {name}")

        return Compiler(executable, "unix", language)

    if toolchain == "clang":
        name = "clang" if language == "c" else "clang++"

        executable = shutil.which(name)

        if executable is None:
            raise RuntimeError(f"compiler not found: {name}")

        return Compiler(executable, "unix", language)

    if toolchain == "msvc":
        executable = shutil.which("cl")

        if executable is None:
            raise RuntimeError("compiler not found: cl.exe")

        return Compiler(executable, "msvc", language)

    raise RuntimeError(f"unsupported toolchain: {toolchain}")


def source_language(
    source: Path,
) -> Literal["c", "cxx"]:
    suffix = source.suffix.lower()

    if suffix in C_EXTENSIONS:
        return "c"

    if suffix in CXX_EXTENSIONS:
        return "cxx"

    raise RuntimeError(f"unsupported source extension: {source}")


def unix_compile_flags(
    language: Literal["c", "cxx"],
) -> list[str]:
    return [
        "-Wall",
        "-Wextra",
        "-Wpedantic",
        "-O2",
        "-std=c17" if language == "c" else "-std=c++17",
    ]


def msvc_compile_flags(
    language: Literal["c", "cxx"],
) -> list[str]:
    flags = [
        "/nologo",
        "/W4",
        "/O2",
        "/D_CRT_SECURE_NO_WARNINGS",
    ]

    if language == "c":
        flags += [
            "/std:c17",
            "/TC",
        ]
    else:
        flags += [
            "/std:c++17",
            "/EHsc",
            "/TP",
        ]

    return flags


def compile_object(
    source: Path,
    output: Path,
    toolchain: Toolchain,
    include_dirs: list[Path],
    defines: list[str],
    extra_flags: list[str],
) -> tuple[bool, str]:
    language = source_language(source)
    compiler = get_compiler(toolchain, language)

    if compiler.style == "msvc":
        command = [
            compiler.executable,
            *msvc_compile_flags(language),
            "/c",
            str(source),
            f"/Fo:{output}",
        ]

        for include_dir in include_dirs:
            command.append(f"/I{include_dir}")

        for define in defines:
            command.append(f"/D{define}")

        command += extra_flags

    else:
        command = [
            compiler.executable,
            *unix_compile_flags(language),
            "-c",
            str(source),
            "-o",
            str(output),
        ]

        for include_dir in include_dirs:
            command += ["-I", str(include_dir)]

        for define in defines:
            command.append(f"-D{define}")

        command += extra_flags

    proc = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    return (
        proc.returncode == 0,
        proc.stdout + proc.stderr,
    )


def link_objects(
    objects: list[Path],
    output: Path,
    toolchain: Toolchain,
    use_cxx: bool,
    extra_flags: list[str],
) -> tuple[bool, str]:
    language: Literal["c", "cxx"] = "cxx" if use_cxx else "c"

    compiler = get_compiler(
        toolchain,
        language,
    )

    if compiler.style == "msvc":
        command = [
            compiler.executable,
            "/nologo",
        ]

        if use_cxx:
            command.append("/EHsc")

        command += [str(obj) for obj in objects]

        command += [
            f"/Fe:{output}",
            *extra_flags,
        ]

    else:
        command = [
            compiler.executable,
            *[str(obj) for obj in objects],
            "-o",
            str(output),
            *extra_flags,
        ]

    proc = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    return (
        proc.returncode == 0,
        proc.stdout + proc.stderr,
    )


def compile_problem(
    assignment: Path,
    problem: str,
    config: dict[str, Any],
    output: Path,
    build_dir: Path,
    toolchain: Toolchain,
) -> tuple[bool, str]:
    raw_sources = config.get("sources")

    if not isinstance(raw_sources, list) or not raw_sources:
        raise RuntimeError(f"{problem}: sources must be a non-empty list")

    sources: list[Path] = []

    for raw in raw_sources:
        source = assignment / str(raw)

        if not source.is_file():
            raise RuntimeError(f"{problem}: source not found: {raw}")

        if source.suffix.lower() not in COMPILE_EXTENSIONS:
            raise RuntimeError(f"{problem}: unsupported source: {raw}")

        sources.append(source)

    raw_includes = config.get(
        "include_dirs",
        ["src"],
    )

    if not isinstance(raw_includes, list):
        raise RuntimeError(f"{problem}: include_dirs must be a list")

    include_dirs = [assignment / str(path) for path in raw_includes]

    defines = config.get(
        "defines",
        [],
    )

    compile_flags = config.get(
        "compile_flags",
        [],
    )

    link_flags = config.get(
        "link_flags",
        [],
    )

    if not all(
        isinstance(value, list)
        for value in (
            defines,
            compile_flags,
            link_flags,
        )
    ):
        raise RuntimeError(f"{problem}: defines/flags must be lists")

    objects: list[Path] = []

    use_cxx = False
    logs: list[str] = []

    for index, source in enumerate(sources):
        language = source_language(source)

        if language == "cxx":
            use_cxx = True

        extension = ".obj" if toolchain == "msvc" else ".o"

        obj = build_dir / f"{problem}_{index}{extension}"

        ok, output_text = compile_object(
            source=source,
            output=obj,
            toolchain=toolchain,
            include_dirs=include_dirs,
            defines=[str(x) for x in defines],
            extra_flags=[str(x) for x in compile_flags],
        )

        if output_text.strip():
            logs.append(output_text.rstrip())

        if not ok:
            return False, "\n".join(logs)

        objects.append(obj)

    ok, output_text = link_objects(
        objects=objects,
        output=output,
        toolchain=toolchain,
        use_cxx=use_cxx,
        extra_flags=[str(x) for x in link_flags],
    )

    if output_text.strip():
        logs.append(output_text.rstrip())

    return ok, "\n".join(logs)
