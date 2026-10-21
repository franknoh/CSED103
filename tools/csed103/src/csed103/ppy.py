"""Generate the PPY source targets declared in an assignment manifest."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .project import build_output_dir, load_yaml


def declared_path(assignment: Path, value: object, suffixes: set[str]) -> Path:
    if not isinstance(value, str) or not value:
        raise RuntimeError("PPY source and output paths must be non-empty strings")
    relative = Path(value)
    path = assignment / relative
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not path.resolve().is_relative_to(assignment.resolve())
    ):
        raise RuntimeError(f"PPY path must stay inside the assignment: {value}")
    if path.suffix not in suffixes:
        raise RuntimeError(f"unsupported PPY path extension: {value}")
    return path


def source_targets(assignment: Path) -> list[tuple[Path, Path]]:
    config = load_yaml(assignment / "manifest.yaml").get("ppy")
    if not isinstance(config, dict):
        raise RuntimeError("manifest must contain a ppy mapping")
    targets = config.get("targets")
    if not isinstance(targets, dict) or not targets:
        raise RuntimeError("ppy.targets must be a non-empty source-to-outputs mapping")
    pairs = []
    seen = set()
    for raw_source, outputs in targets.items():
        source = declared_path(assignment, raw_source, {".ppy"})
        if not source.is_file():
            raise RuntimeError(f"PPY source not found: {raw_source}")
        if not isinstance(outputs, list) or not outputs:
            raise RuntimeError(f"PPY outputs must be a non-empty list: {raw_source}")
        for raw_target in outputs:
            target = declared_path(assignment, raw_target, {".c", ".cpp"})
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise RuntimeError(f"PPY output must be a regular file: {raw_target}")
            if target.resolve() in seen:
                raise RuntimeError(f"duplicate PPY output: {raw_target}")
            seen.add(target.resolve())
            pairs.append((source, target))
    return pairs


def build_ppy(assignment: Path) -> list[Path]:
    pairs = source_targets(assignment)
    config = load_yaml(assignment / "manifest.yaml")["ppy"]
    mode = config.get("mode", "standalone")
    if mode not in {"standalone", "library"}:
        raise RuntimeError("ppy.mode must be standalone or library")
    defines = config.get("defines", [])
    if not isinstance(defines, list) or any(
        not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
        for name in defines
    ):
        raise RuntimeError("ppy.defines must be a list of C macro identifiers")
    preamble = "".join(
        f"#ifndef {name}\n#define {name}\n#endif\n" for name in dict.fromkeys(defines)
    )
    # A library can ship its public C adapters in the same translation unit.
    # Concatenate authored files verbatim; never rewrite the compiler's output.
    append = config.get("append", {})
    if not isinstance(append, dict):
        raise RuntimeError("ppy.append must map declared outputs to C source lists")
    targets = {target for _, target in pairs}
    additions = {}
    for raw_target, inputs in append.items():
        target = declared_path(assignment, raw_target, {".c", ".cpp"})
        if target not in targets or not isinstance(inputs, list) or not inputs:
            raise RuntimeError(
                "ppy.append must name a declared output and non-empty source list"
            )
        additions[target] = []
        for value in inputs:
            path = declared_path(assignment, value, {".c", ".cpp", ".h"})
            if not path.is_file() or path in targets:
                raise RuntimeError(
                    f"PPY adapter must be an existing authored source: {value}"
                )
            additions[target].append(path.read_text(encoding="utf-8"))
    executable = shutil.which("ppy", path=str(Path(sys.executable).parent))
    if not executable:
        raise RuntimeError(
            "ppy is not installed in this environment; run uv sync in the repository"
        )
    command = [executable, "emit"]
    help_result = subprocess.run(
        [*command, "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    if help_result.returncode:
        raise RuntimeError("cannot run ppy emit; run uv sync in the repository")
    required = (
        ("--unsafe", "--int-width")
        if mode == "standalone"
        else ("--unsafe", "--format")
    )
    if any(flag not in help_result.stdout for flag in required):
        raise RuntimeError(
            "installed ppy does not support emit --unsafe --int-width; "
            "upgrade to ppy 0.3.6 or newer using "
            "uv sync --upgrade-package ppy-lang; existing targets were not changed"
        )
    # Stage every output first: an emitter failure must leave all existing sources intact.
    with tempfile.TemporaryDirectory(
        prefix=".ppy-", dir=build_output_dir(assignment)
    ) as tmp:
        staged = []
        for source, target in pairs:
            output = Path(tmp) / target.relative_to(assignment)
            output.parent.mkdir(parents=True, exist_ok=True)
            kind = target.suffix[1:]
            print(
                f"[ppy] {source.relative_to(assignment)} -> {target.relative_to(assignment)}",
                flush=True,
            )
            subprocess.run(
                [
                    *command,
                    kind,
                    str(source),
                    *(
                        ["--standalone", "--unsafe", "--int-width", "32"]
                        if mode == "standalone"
                        else ["--unsafe"]
                    ),
                    "--format",
                    "-o",
                    str(output),
                ],
                cwd=assignment,
                check=True,
            )
            if not output.is_file() or not output.read_text(encoding="utf-8").strip():
                raise RuntimeError(f"ppy emitted no source for {target.name}")
            if preamble:
                output.write_text(
                    preamble + "\n" + output.read_text(encoding="utf-8"),
                    encoding="utf-8",
                    newline="\n",
                )
            if target in additions:
                with output.open("a", encoding="utf-8", newline="\n") as stream:
                    for source_text in additions[target]:
                        stream.write("\n" + source_text + "\n")
            staged.append((output, target))
        for output, target in staged:
            target.parent.mkdir(parents=True, exist_ok=True)
            output.replace(target)
    print(f"[ppy] generated {len(pairs)} target(s) for {assignment.name}")
    return [target for _, target in pairs]
