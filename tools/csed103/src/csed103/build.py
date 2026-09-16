"""Build PDF reports and flat submission archives."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .project import load_yaml, output_dir


def build_report(assignment: Path, *, pdf_engine: str | None = None) -> Path:
    readme = assignment / "README.md"
    if not readme.is_file():
        raise RuntimeError(f"README.md not found: {readme}")
    if not readme.read_text(encoding="utf-8").strip():
        raise RuntimeError(f"report source is empty: {readme}; write the report first")
    if not shutil.which("pandoc"):
        raise RuntimeError("required command not found: pandoc")
    engine = pdf_engine or os.environ.get("PDF_ENGINE") or "xelatex"
    out = output_dir(assignment)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "report.pdf"
    print(f"[report] {assignment.name} (engine: {engine})", flush=True)
    with tempfile.TemporaryDirectory(prefix=".report-", dir=out) as tmp:
        temporary = Path(tmp) / "report.pdf"
        subprocess.run(
            [
                "pandoc",
                str(readme),
                "--from=gfm",
                "--standalone",
                f"--resource-path={assignment}{os.pathsep}{assignment / 'assets'}",
                f"--pdf-engine={engine}",
                "-V",
                "geometry:margin=1in",
                "-V",
                "fontsize=11pt",
                "-o",
                str(temporary),
            ],
            cwd=assignment,
            check=True,
        )
        temporary.replace(report)
    print(f"[report] created: {report}")
    return report


def submission_files(assignment: Path) -> dict[str, Path]:
    submission = load_yaml(assignment / "manifest.yaml").get("submission")
    if not isinstance(submission, dict):
        raise RuntimeError("manifest missing submission mapping")
    patterns = submission.get("include")
    if not isinstance(patterns, list) or not patterns:
        raise RuntimeError("submission.include must be a non-empty list")
    files: dict[str, Path] = {}
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern:
            raise RuntimeError("submission.include entries must be non-empty strings")
        relative = Path(pattern)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(
                f"submission pattern must stay inside the assignment: {pattern}"
            )
        for path in sorted(assignment.glob(pattern)):
            if not path.is_file():
                continue
            if not path.resolve().is_relative_to(assignment.resolve()):
                raise RuntimeError(f"submission file is outside the assignment: {path}")
            if path.name == "report.pdf" or path.name in files:
                raise RuntimeError(f"duplicate submission basename: {path.name}")
            files[path.name] = path
    if not files:
        raise RuntimeError("submission include patterns matched no files")
    return dict(sorted(files.items()))


def submission_name(root: Path, assignment: Path) -> str:
    config = load_yaml(root / "config.yaml")
    submission = load_yaml(assignment / "manifest.yaml").get("submission", {})
    if not isinstance(submission, dict):
        raise RuntimeError("manifest missing submission mapping")
    prefix = submission.get("archive_prefix", assignment.name)
    if not isinstance(prefix, str) or not re.fullmatch(
        r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", prefix
    ):
        raise RuntimeError("submission.archive_prefix must be a simple filename prefix")
    parts = [prefix]
    for key in ("student_id", "name"):
        value = config.get(key)
        if value is None:
            raise RuntimeError(f"missing config key: {key}")
        sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "", str(value).replace(" ", "_"))
        if not sanitized:
            raise RuntimeError(f"config key has no filename characters: {key}")
        parts.append(sanitized)
    return "_".join(parts) + ".zip"


def build_submission(
    root: Path, assignment: Path, *, pdf_engine: str | None = None
) -> Path:
    files = submission_files(assignment)
    name = submission_name(root, assignment)
    out = output_dir(assignment)
    report = out / "report.pdf"
    if not report.is_file():
        print("[submission] report not found; building")
        report = build_report(assignment, pdf_engine=pdf_engine)
    files["report.pdf"] = report
    archive = out / name
    with tempfile.TemporaryDirectory(prefix=".submission-", dir=out) as tmp:
        temporary = Path(tmp) / name
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as zipped:
            for basename, path in sorted(files.items()):
                zipped.write(path, arcname=basename)
        temporary.replace(archive)
    print(f"[submission] created: {archive}")
    for basename in sorted(files):
        print(f"  {basename}")
    return archive
