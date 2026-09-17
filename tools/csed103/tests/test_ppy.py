"""PPY generation must honor requested backends and preserve existing sources on failure."""

from __future__ import annotations

import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from csed103.cli import main
from csed103.ppy import build_ppy, source_targets


class PPYBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="csed103-ppy-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "pyproject.toml").write_text('[project]\nname = "csed103"\n')
        self.assignment = self.root / "assign1"
        (self.assignment / "ppy").mkdir(parents=True)
        (self.assignment / "src").mkdir()
        self.write_targets({"ppy/problem.ppy": ["src/problem.c", "src/problem.cpp"]})
        (self.assignment / "ppy/problem.ppy").write_text("print(1)\n")
        for suffix in ("c", "cpp"):
            (self.assignment / f"src/problem.{suffix}").write_text(
                f"original {suffix}\n"
            )
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))
        self.enterContext(patch("csed103.ppy.shutil.which", return_value="ppy"))

    def write_targets(self, targets):
        (self.assignment / "manifest.yaml").write_text(
            yaml.safe_dump({"ppy": {"targets": targets}})
        )

    def emitter(self, command, **kwargs):
        if command[-1] == "--help":
            return subprocess.CompletedProcess(
                command, 0, stdout="--standalone --unsafe --int-width --format"
            )
        self.assertEqual(command[:2], ["ppy", "emit"])
        self.assertIn(command[2], ("c", "cpp"))
        self.assertTrue(command[3].endswith(".ppy"))
        self.assertEqual(
            command[4:10],
            ["--standalone", "--unsafe", "--int-width", "32", "--format", "-o"],
        )
        self.assertTrue(kwargs["check"])
        self.assertEqual(kwargs["cwd"], self.assignment)
        Path(command[10]).write_text(f"generated {command[2]}\n")
        return subprocess.CompletedProcess(command, 0)

    def assert_original_targets(self):
        for suffix in ("c", "cpp"):
            self.assertEqual(
                (self.assignment / f"src/problem.{suffix}").read_text(),
                f"original {suffix}\n",
            )
        self.assertFalse(list(self.assignment.glob(".ppy-*")))

    def test_cli_generates_both_declared_backends(self):
        with patch("csed103.ppy.subprocess.run", side_effect=self.emitter) as run:
            status = main(["--root", str(self.root), "build", "ppy", "assign1"])
        self.assertEqual(status, 0)
        self.assertEqual(run.call_count, 3)
        for suffix in ("c", "cpp"):
            self.assertEqual(
                (self.assignment / f"src/problem.{suffix}").read_text(),
                f"generated {suffix}\n",
            )
        self.assertFalse(list(self.assignment.glob(".ppy-*")))

    def test_only_declared_targets_are_generated(self):
        self.write_targets({"ppy/problem.ppy": ["src/problem.c"]})
        (self.assignment / "src/manual.c").write_text("handwritten")
        (self.assignment / "ppy/unused.ppy").write_text("print(2)")
        with patch("csed103.ppy.subprocess.run", side_effect=self.emitter):
            outputs = build_ppy(self.assignment)
        self.assertEqual(outputs, [self.assignment / "src/problem.c"])
        self.assertEqual((self.assignment / "src/manual.c").read_text(), "handwritten")
        self.assertEqual(
            (self.assignment / "src/problem.cpp").read_text(), "original cpp\n"
        )
        self.assertFalse((self.assignment / "src/unused.c").exists())

    def test_missing_output_files_and_directory_are_created(self):
        (self.assignment / "src/problem.c").unlink()
        (self.assignment / "src/problem.cpp").unlink()
        (self.assignment / "src").rmdir()
        with patch("csed103.ppy.subprocess.run", side_effect=self.emitter):
            outputs = build_ppy(self.assignment)
        self.assertEqual(len(outputs), 2)
        for suffix in ("c", "cpp"):
            self.assertEqual(
                (self.assignment / f"src/problem.{suffix}").read_text(),
                f"generated {suffix}\n",
            )

    def test_source_and_output_names_need_not_match(self):
        (self.assignment / "inputs").mkdir()
        source = self.assignment / "inputs/original.ppy"
        source.write_text("print(2)")
        target = self.assignment / "src/nested/different.cpp"
        self.write_targets({"inputs/original.ppy": ["src/nested/different.cpp"]})
        with patch("csed103.ppy.subprocess.run", side_effect=self.emitter) as run:
            outputs = build_ppy(self.assignment)
        self.assertEqual(outputs, [target])
        self.assertEqual(run.call_args.args[0][3], str(source))
        self.assertEqual(target.read_text(), "generated cpp\n")
        self.assert_original_targets()

    def test_old_ppy_exits_without_touching_targets(self):
        for supported_flags in ("--standalone", "--standalone --unsafe"):
            with (
                self.subTest(supported_flags=supported_flags),
                patch(
                    "csed103.ppy.subprocess.run",
                    return_value=subprocess.CompletedProcess(
                        [], 0, stdout=supported_flags
                    ),
                ) as run,
            ):
                with self.assertRaisesRegex(RuntimeError, "upgrade to ppy 0.3.5"):
                    build_ppy(self.assignment)
            self.assertEqual(run.call_count, 1)
            self.assert_original_targets()

    def test_failure_of_second_backend_preserves_first_target_too(self):
        def emit(command, **kwargs):
            if command[2] == "cpp":
                raise subprocess.CalledProcessError(1, command)
            return self.emitter(command, **kwargs)

        with patch("csed103.ppy.subprocess.run", side_effect=emit):
            with self.assertRaises(subprocess.CalledProcessError):
                build_ppy(self.assignment)
        self.assert_original_targets()

    def test_empty_output_is_rejected_without_replacing_targets(self):
        def emit(command, **kwargs):
            result = self.emitter(command, **kwargs)
            if command[2] == "cpp":
                Path(command[-1]).write_text("")
            return result

        with patch("csed103.ppy.subprocess.run", side_effect=emit):
            with self.assertRaisesRegex(RuntimeError, "emitted no source"):
                build_ppy(self.assignment)
        self.assert_original_targets()

    def test_invalid_manifest_targets_fail_before_running_emitter(self):
        invalid = [
            None,
            [],
            {},
            {"ppy/missing.ppy": ["src/result.c"]},
            {"ppy/problem.ppy": []},
            {"ppy/problem.ppy": "src/result.c"},
            {"ppy/problem.ppy": ["../escape.c"]},
            {"ppy/problem.ppy": [str(self.root / "outside.c")]},
            {"ppy/problem.ppy": ["src/result.py"]},
            {"ppy/problem.ppy": [None]},
            {"ppy/problem.ppy": ["src/result.c", "src/./result.c"]},
        ]
        for targets in invalid:
            with (
                self.subTest(targets=targets),
                patch("csed103.ppy.subprocess.run") as run,
            ):
                self.write_targets(targets)
                with self.assertRaises(RuntimeError):
                    build_ppy(self.assignment)
                run.assert_not_called()
                self.assert_original_targets()

    def test_two_sources_cannot_write_the_same_output(self):
        (self.assignment / "ppy/other.ppy").write_text("print(2)")
        self.write_targets(
            {"ppy/problem.ppy": ["src/problem.c"], "ppy/other.ppy": ["src/problem.c"]}
        )
        with self.assertRaisesRegex(RuntimeError, "duplicate PPY output"):
            source_targets(self.assignment)

    def test_missing_ppy_is_reported(self):
        with patch("csed103.ppy.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "ppy is not installed"):
                build_ppy(self.assignment)
        self.assert_original_targets()

    def test_all_assignments_uses_manifest_instead_of_ppy_directory(self):
        other = self.root / "assign2"
        (other / "ppy").mkdir(parents=True)
        (other / "ppy/unused.ppy").write_text("print(2)")
        (other / "manifest.yaml").write_text("{}")
        (self.assignment / "ppy/problem.ppy").rename(self.assignment / "input.ppy")
        (self.assignment / "ppy").rmdir()
        self.write_targets({"input.ppy": ["src/problem.c", "src/problem.cpp"]})
        with patch("csed103.ppy.subprocess.run", side_effect=self.emitter):
            self.assertEqual(main(["--root", str(self.root), "build", "ppy"]), 0)
        self.assertFalse((other / "src").exists())


if __name__ == "__main__":
    unittest.main()
