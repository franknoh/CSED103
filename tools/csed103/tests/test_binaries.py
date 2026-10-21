"""Real shared-library builds and build-only target orchestration."""

import contextlib
import ctypes
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from csed103.binaries import binary_path, build_binaries, supported_platform
from csed103.cli import main
from csed103.testing import test_assignment


class BinaryTests(unittest.TestCase):
    def test_names_and_platforms_are_validated(self):
        for name in ("..", "../escape", "nested/file", "nested\\file"):
            with self.assertRaises(RuntimeError):
                binary_path(Path("out"), name, {}, "gcc")
        with self.assertRaises(RuntimeError):
            supported_platform({"platforms": "windows"})
        self.assertFalse(supported_platform({"platforms": []}))

    def test_build_only_target_is_not_run_as_an_io_test(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "manifest.yaml").write_text(
                "problems:\n  gui:\n    sources: [main.c]\n    test: false\n"
            )
            with (
                patch("csed103.testing.compile_problem") as compile_,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(test_assignment(root, compiler="gcc"), 0)
                compile_.assert_not_called()

    def test_cli_binary_target_forwards_compiler(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "pyproject.toml").write_text('[project]\nname="csed103"\n')
            assignment = root / "assign1"
            assignment.mkdir()
            (assignment / "manifest.yaml").write_text("{}")
            with patch("csed103.cli.build_binaries") as build:
                self.assertEqual(
                    main(
                        [
                            "--root",
                            str(root),
                            "build",
                            "binaries",
                            "assign1",
                            "--compiler",
                            "msvc",
                        ]
                    ),
                    0,
                )
                build.assert_called_once_with(assignment, compiler="msvc")

    @unittest.skipUnless(
        os.name != "nt" and shutil.which("gcc"), "GCC integration test"
    )
    def test_shared_library_loads_without_running_it_as_executable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "sample.c").write_text(
                "int triple(int value) { return value * 3; }\n"
            )
            (root / "manifest.yaml").write_text(
                "problems:\n  sample:\n    kind: shared\n    sources: [sample.c]\n"
                "    exports: [triple]\n    test: false\n"
            )
            with contextlib.redirect_stdout(io.StringIO()):
                result = build_binaries(root, compiler="gcc")
            lib = ctypes.CDLL(str(result["sample"]))
            lib.triple.argtypes = [ctypes.c_int]
            lib.triple.restype = ctypes.c_int
            self.assertEqual(lib.triple(7), 21)
            self.assertTrue((root / "out/compiler-build-log.txt").is_file())


if __name__ == "__main__":
    unittest.main()
