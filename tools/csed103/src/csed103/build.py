"""Build manifest-defined PDF documents and submission archives."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile

from .project import load_yaml, output_dir


def local_file(assignment: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RuntimeError("file paths must be non-empty relative POSIX paths")
    relative = Path(value)
    path = assignment / relative
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not path.resolve().is_relative_to(assignment.resolve())
    ):
        raise RuntimeError(f"file must stay inside the assignment: {value}")
    return path


def report_sources(assignment: Path) -> dict[str, Path]:
    reports = load_yaml(assignment / "manifest.yaml").get(
        "reports", {"report.pdf": "README.md"}
    )
    if not isinstance(reports, dict) or "report.pdf" not in reports:
        raise RuntimeError(
            "reports must map PDF basenames to Markdown sources, including report.pdf"
        )
    result = {}
    for name, source in reports.items():
        if not isinstance(name, str) or not re.fullmatch(r"[\w.-]+\.pdf", name):
            raise RuntimeError("report output must be a PDF basename")
        path = local_file(assignment, source)
        if path.suffix != ".md":
            raise RuntimeError("report source must be Markdown")
        result[name] = path
    return result


def build_report(assignment: Path, *, pdf_engine: str | None = None) -> Path:
    for name, source in report_sources(assignment).items():
        render_report(assignment, source, name, pdf_engine=pdf_engine)
    return output_dir(assignment) / "report.pdf"


def render_report(
    assignment: Path, readme: Path, name: str, *, pdf_engine: str | None = None
) -> Path:
    if not readme.is_file():
        raise RuntimeError(f"README.md not found: {readme}")
    if not readme.read_text(encoding="utf-8").strip():
        raise RuntimeError(f"report source is empty: {readme}; write the report first")
    if not shutil.which("pandoc"):
        raise RuntimeError("required command not found: pandoc")
    engine = pdf_engine or os.environ.get("PDF_ENGINE") or "xelatex"
    out = output_dir(assignment)
    out.mkdir(parents=True, exist_ok=True)
    report = out / name
    print(f"[report] {assignment.name}/{name} (engine: {engine})", flush=True)
    with tempfile.TemporaryDirectory(prefix=".report-", dir=out) as tmp:
        temporary = Path(tmp) / "report.pdf"
        subprocess.run(
            [
                "pandoc",
                str(readme),
                "--from=gfm+attributes",
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
    if "files" in submission:
        if "include" in submission:
            raise RuntimeError("use either submission.files or submission.include")
        mapping = submission["files"]
        if not isinstance(mapping, dict) or not mapping:
            raise RuntimeError(
                "submission.files must be a non-empty archive-path to source mapping"
            )
        files = {}
        for name, source in mapping.items():
            if not isinstance(name, str) or not name or "\\" in name or ":" in name:
                raise RuntimeError("invalid submission archive path")
            relative = PurePosixPath(name)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or str(relative) != name
                or name == "."
            ):
                raise RuntimeError(f"invalid submission archive path: {name}")
            path = local_file(assignment, source)
            if not path.is_file():
                raise RuntimeError(f"submission file not found: {source}")
            files[name] = path
        return dict(sorted(files.items()))
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
    name = submission_name(root, assignment)
    out = output_dir(assignment)
    if any(not (out / name).is_file() for name in report_sources(assignment)):
        print("[submission] report not found; building")
        build_report(assignment, pdf_engine=pdf_engine)
    files = submission_files(assignment)
    if "files" not in load_yaml(assignment / "manifest.yaml")["submission"]:
        files["report.pdf"] = out / "report.pdf"
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
