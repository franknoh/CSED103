"""Generate the PPY source targets declared in an assignment manifest."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .project import load_yaml


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
    if "--unsafe" not in help_result.stdout:
        raise RuntimeError(
            "installed ppy does not support emit --unsafe; "
            "upgrade to ppy 0.3.4 or newer using "
            "uv sync --upgrade-package ppy-lang; existing targets were not changed"
        )
    # Stage every output first: an emitter failure must leave all existing sources intact.
    with tempfile.TemporaryDirectory(prefix=".ppy-", dir=assignment) as tmp:
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
                    "--standalone",
                    "--unsafe",
                    "-o",
                    str(output),
                ],
                cwd=assignment,
                check=True,
            )
            if not output.is_file() or not output.read_text(encoding="utf-8").strip():
                raise RuntimeError(f"ppy emitted no source for {target.name}")
            staged.append((output, target))
        for output, target in staged:
            target.parent.mkdir(parents=True, exist_ok=True)
            output.replace(target)
    print(f"[ppy] generated {len(pairs)} target(s) for {assignment.name}")
    return [target for _, target in pairs]
