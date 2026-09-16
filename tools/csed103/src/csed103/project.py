"""Project discovery, assignment paths, and shared configuration."""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(f"cannot load {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} must contain a YAML mapping")
    return data


def find_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    for directory in (start, *start.parents):
        path = directory / "pyproject.toml"
        if path.is_file():
            with path.open("rb") as stream:
                config = tomllib.load(stream)
            if config.get("project", {}).get("name") == "csed103":
                return directory
    raise RuntimeError(
        "CSED103 project not found; run from the repository or use --root PATH"
    )


def resolve_assignment(root: Path, name: str) -> Path:
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise RuntimeError(f"invalid assignment name: {name}")
    path = root / name
    if path.is_symlink() or path.resolve().parent != root.resolve():
        raise RuntimeError(f"assignment must be a directory inside the project: {name}")
    if not path.is_dir():
        raise RuntimeError(f"assignment not found: {name}")
    if not (path / "manifest.yaml").is_file():
        raise RuntimeError(f"manifest not found: {path / 'manifest.yaml'}")
    return path


def assignments(root: Path) -> list[Path]:
    names = sorted(
        path.name
        for path in root.glob("assign*")
        if path.is_dir() and (path / "manifest.yaml").is_file()
    )
    if not names:
        raise RuntimeError("no assignments found")
    return [resolve_assignment(root, name) for name in names]


def output_dir(assignment: Path) -> Path:
    path = assignment / "out"
    if path.is_symlink() or path.resolve().parent != assignment.resolve():
        raise RuntimeError(f"output directory must stay inside the assignment: {path}")
    return path


def clean_assignment(assignment: Path) -> None:
    path = output_dir(assignment)
    if path.exists():
        shutil.rmtree(path)
    print(f"[clean] {path}")
