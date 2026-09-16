"""Regression tests for packaging, orchestration, and the real compiler runner."""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from csed103.build import build_report, build_submission, submission_files
from csed103.cli import main
from csed103.project import clean_assignment, find_root, resolve_assignment
from csed103.testing import run_case, test_assignment


class ToolingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="csed103-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "pyproject.toml").write_text('[project]\nname = "csed103"\n')
        (self.root / "config.yaml").write_text(
            'student_id: "123"\nname: "Test Student"\n'
        )
        self.assignment = self.root / "assign1"
        (self.assignment / "src").mkdir(parents=True)
        (self.assignment / "src/main.c").write_text(
            '#include <stdio.h>\nint main(void) { int n; if(scanf("%d", &n) != 1) return 1; printf("%d\\n", n * 2); return 0; }\n'
        )
        (self.assignment / "README.md").write_text("# Report\n")
        self.manifest = self.assignment / "manifest.yaml"
        self.manifest.write_text(
            "problems:\n  double:\n    sources: [src/main.c]\n"
            "submission:\n  include: [src/*.c]\n"
        )
        self.out = self.assignment / "out"
        self.out.mkdir()
        self.report = self.out / "report.pdf"
        self.report.write_bytes(b"existing report")
        self.output = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.output))
        self.enterContext(contextlib.redirect_stderr(self.output))

    def cli(self, *args):
        return main(["--root", str(self.root), *args])

    def test_project_discovery_from_assignment_subdirectory(self):
        self.assertEqual(find_root(self.assignment / "src"), self.root)
        self.assertEqual(resolve_assignment(self.root, "assign1"), self.assignment)

    def test_flat_archive_and_existing_report_reuse(self):
        with patch("csed103.build.build_report") as report:
            archive = build_submission(self.root, self.assignment)
        report.assert_not_called()
        self.assertEqual(archive.name, "assign1_123_Test_Student.zip")
        with ZipFile(archive) as zipped:
            self.assertEqual(zipped.namelist(), ["main.c", "report.pdf"])
            self.assertEqual(
                zipped.read("main.c"), (self.assignment / "src/main.c").read_bytes()
            )
            self.assertEqual(zipped.read("report.pdf"), b"existing report")

    def test_assignment_can_choose_submission_archive_prefix(self):
        self.manifest.write_text(
            "submission:\n  archive_prefix: assn1\n  include: [src/*.c]\n"
        )
        archive = build_submission(self.root, self.assignment)
        self.assertEqual(archive.name, "assn1_123_Test_Student.zip")

    def test_unsafe_submission_archive_prefix_is_rejected(self):
        self.manifest.write_text(
            "submission:\n  archive_prefix: ../outside\n  include: [src/*.c]\n"
        )
        with self.assertRaisesRegex(RuntimeError, "filename prefix"):
            build_submission(self.root, self.assignment)

    def test_missing_report_is_built_before_packaging(self):
        self.report.unlink()

        def render(assignment, **kwargs):
            self.report.write_bytes(b"new report")
            return self.report

        with patch("csed103.build.build_report", side_effect=render) as report:
            archive = build_submission(
                self.root, self.assignment, pdf_engine="tectonic"
            )
        report.assert_called_once_with(self.assignment, pdf_engine="tectonic")
        with ZipFile(archive) as zipped:
            self.assertEqual(zipped.read("report.pdf"), b"new report")

    def test_duplicate_submission_basenames_are_rejected(self):
        (self.assignment / "main.c").write_text("duplicate")
        self.manifest.write_text("submission:\n  include: [src/*.c, '*.c']\n")
        with self.assertRaisesRegex(RuntimeError, "duplicate submission basename"):
            submission_files(self.assignment)

    def test_invalid_submission_manifests(self):
        for contents in (
            "submission: []",
            "submission: {include: []}",
            "submission: {include: [missing.c]}",
            "submission: {include: [../outside.c]}",
            "submission: {include: [null]}",
        ):
            with self.subTest(contents=contents):
                self.manifest.write_text(contents)
                with self.assertRaises(RuntimeError):
                    submission_files(self.assignment)

    def test_report_name_is_reserved_in_archive(self):
        self.manifest.write_text("submission:\n  include: [out/report.pdf]\n")
        with self.assertRaisesRegex(RuntimeError, "duplicate submission basename"):
            submission_files(self.assignment)

    def test_failed_archive_write_preserves_previous_archive(self):
        archive = build_submission(self.root, self.assignment)
        before = archive.read_bytes()
        with patch("csed103.build.ZipFile.write", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                build_submission(self.root, self.assignment)
        self.assertEqual(archive.read_bytes(), before)
        self.assertFalse(list(self.out.glob(".submission-*")))

    def test_report_arguments_and_atomic_replacement(self):
        def render(command, **kwargs):
            self.assertEqual(kwargs["cwd"], self.assignment)
            self.assertIn("--pdf-engine=lualatex", command)
            self.assertIn(
                f"--resource-path={self.assignment}{os.pathsep}{self.assignment / 'assets'}",
                command,
            )
            Path(command[command.index("-o") + 1]).write_bytes(b"new report")

        with (
            patch("csed103.build.shutil.which", return_value="pandoc"),
            patch.dict(os.environ, {"PDF_ENGINE": "xelatex"}),
            patch("csed103.build.subprocess.run", side_effect=render),
        ):
            self.assertEqual(
                build_report(self.assignment, pdf_engine="lualatex"), self.report
            )
        self.assertEqual(self.report.read_bytes(), b"new report")
        self.assertFalse(list(self.out.glob(".report-*")))

    def test_empty_report_source_has_clear_error(self):
        (self.assignment / "README.md").write_text("   ")
        with patch("csed103.build.subprocess.run") as process:
            self.assertEqual(self.cli("build", "report", "assign1"), 1)
        process.assert_not_called()
        self.assertIn("report source is empty", self.output.getvalue())
        self.assertEqual(self.report.read_bytes(), b"existing report")

    def test_report_failure_preserves_previous_report(self):
        with (
            patch("csed103.build.shutil.which", return_value="pandoc"),
            patch(
                "csed103.build.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "pandoc"),
            ),
        ):
            self.assertEqual(self.cli("build", "report", "assign1"), 1)
        self.assertEqual(self.report.read_bytes(), b"existing report")
        self.assertFalse(list(self.out.glob(".report-*")))

    def test_build_all_skips_failed_assignment_and_continues(self):
        second = self.root / "assign2"
        second.mkdir()
        (second / "manifest.yaml").write_text("{}")
        events = []

        def test(assignment, **kwargs):
            events.append(("test", assignment.name))
            return int(assignment.name == "assign1")

        with (
            patch("csed103.cli.test_assignment", side_effect=test),
            patch(
                "csed103.cli.build_report",
                side_effect=lambda assignment, **kwargs: events.append(
                    ("report", assignment.name)
                ),
            ),
            patch(
                "csed103.cli.build_submission",
                side_effect=lambda root, assignment, **kwargs: events.append(
                    ("submission", assignment.name)
                ),
            ),
        ):
            self.assertEqual(self.cli("build", "all"), 1)
        self.assertEqual(
            events,
            [
                ("test", "assign1"),
                ("test", "assign2"),
                ("report", "assign2"),
                ("submission", "assign2"),
            ],
        )

    def test_test_options_are_forwarded(self):
        with patch("csed103.cli.test_assignment", return_value=0) as test:
            self.assertEqual(
                self.cli("test", "assign1", "--compiler", "clang", "--timeout", "0.5"),
                0,
            )
        test.assert_called_once_with(self.assignment, compiler="clang", timeout=0.5)

    def test_invalid_timeout_and_assignment_are_rejected(self):
        for timeout in ("0", "-1", "nan", "inf"):
            with self.subTest(timeout=timeout), self.assertRaises(SystemExit) as result:
                self.cli("test", "assign1", "--timeout", timeout)
            self.assertEqual(result.exception.code, 2)
        for assignment in ("..", "../assign1", "missing"):
            self.assertEqual(self.cli("clean", assignment), 2)
        self.assertTrue(self.report.is_file())

    def test_clean_only_removes_selected_output(self):
        second = self.root / "assign2"
        (second / "out").mkdir(parents=True)
        (second / "manifest.yaml").write_text("{}")
        self.assertEqual(self.cli("clean", "assign1"), 0)
        self.assertFalse(self.out.exists())
        self.assertTrue((self.assignment / "src/main.c").is_file())
        self.assertTrue((second / "out").is_dir())
        self.assertEqual(self.cli("clean"), 0)
        self.assertFalse((second / "out").exists())

    @unittest.skipIf(os.name == "nt", "symlinks require Windows developer privileges")
    def test_clean_refuses_symlink_output(self):
        shutil.rmtree(self.out)
        outside = self.root / "keep"
        outside.mkdir()
        marker = outside / "marker"
        marker.write_text("keep")
        self.out.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            clean_assignment(self.assignment)
        self.assertTrue(marker.exists())

    @unittest.skipUnless(
        any(shutil.which(name) for name in ("gcc", "clang", "cl")),
        "requires a compiler",
    )
    def test_real_compilation_pass_and_mismatch(self):
        cases = self.assignment / "tests/double"
        cases.mkdir(parents=True)
        (cases / "sample.in").write_text("21\n")
        expected = cases / "sample.out"
        expected.write_text("42  \n\n")
        self.assertEqual(test_assignment(self.assignment), 0)
        expected.write_text("43\n")
        self.assertEqual(test_assignment(self.assignment), 1)
        self.assertIn("output mismatch", self.output.getvalue())
        expected.unlink()
        self.assertEqual(test_assignment(self.assignment), 1)
        self.assertIn("missing expected output", self.output.getvalue())

    def test_process_timeout_is_reported(self):
        case = self.assignment / "case.in"
        expected = self.assignment / "case.out"
        case.write_text("import time; time.sleep(5)\n")
        expected.write_text("")
        result = run_case(Path(sys.executable), case, expected, 0.05, "slow")
        self.assertFalse(result.passed)
        self.assertIn("timeout", result.reason)


if __name__ == "__main__":
    unittest.main()
