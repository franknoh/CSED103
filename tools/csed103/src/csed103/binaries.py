"""Build manifest-defined executables and shared libraries for any assignment."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from .compilers import Toolchain, compile_problem, detect_toolchain
from .project import build_output_dir, load_yaml


def supported_platform(config: dict) -> bool:
    platforms = config.get("platforms", ["windows", "linux", "macos"])
    if not isinstance(platforms, list) or any(
        p not in ("windows", "linux", "macos") for p in platforms
    ):
        raise RuntimeError("platforms must be a list of windows, linux, or macos")
    current = (
        "windows"
        if os.name == "nt"
        else "macos"
        if sys.platform == "darwin"
        else "linux"
    )
    return current in platforms


def binary_path(directory: Path, name: str, config: dict, toolchain: Toolchain) -> Path:
    if (
        not name
        or Path(name).name != name
        or "/" in name
        or "\\" in name
        or name in {".", ".."}
    ):
        raise RuntimeError("binary names must be simple filenames")
    shared = config.get("kind", "executable") == "shared"
    if os.name == "nt" or toolchain == "msvc":
        suffix = ".dll" if shared else ".exe"
    else:
        suffix = (".dylib" if sys.platform == "darwin" else ".so") if shared else ""
    return directory / (name + suffix)


def build_binaries(
    assignment: Path, *, compiler: Toolchain = "auto"
) -> dict[str, Path]:
    problems = load_yaml(assignment / "manifest.yaml").get("problems")
    if not isinstance(problems, dict) or not problems:
        raise RuntimeError("manifest must contain a non-empty problems mapping")
    toolchain = detect_toolchain(compiler, project_dir=assignment)
    out = build_output_dir(assignment)
    built = {}
    logs = []
    with tempfile.TemporaryDirectory(prefix=".objects-", dir=out) as temporary:
        for name, config in problems.items():
            if not isinstance(config, dict):
                raise RuntimeError(f"{name}: configuration must be a mapping")
            if not supported_platform(config):
                print(f"[skip] {name}: not supported on this platform")
                continue
            target = binary_path(out, name, config, toolchain)
            ok, log = compile_problem(
                assignment, name, config, target, Path(temporary), toolchain
            )
            logs.append(f"[{name}]\n{log}")
            (out / "compiler-build-log.txt").write_text(
                "\n".join(logs), encoding="utf-8"
            )
            if not ok:
                raise RuntimeError(f"{name}: compilation failed\n{log}")
            print(f"[build] {name}: {target.relative_to(assignment)} ({toolchain})")
            built[name] = target
    return built
