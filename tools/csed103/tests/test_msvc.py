"""Exercise discovery without a VS install, and compiler environment forwarding."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from csed103.compilers import (
    Compiler,
    compile_object,
    configured_msvc_environment,
    link_objects,
)
from csed103.msvc import msvc_environment


class MSVCTests(unittest.TestCase):
    def setUp(self):
        msvc_environment.cache_clear()
        self.addCleanup(msvc_environment.cache_clear)
        temp = tempfile.TemporaryDirectory(prefix="msvc-test-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        vswhere = self.root / "Microsoft Visual Studio/Installer/vswhere.exe"
        vswhere.parent.mkdir(parents=True)
        vswhere.touch()
        self.install = self.root / "Visual Studio With Spaces"
        vcvars = self.install / "VC/Auxiliary/Build/vcvars64.bat"
        vcvars.parent.mkdir(parents=True)
        vcvars.touch()
        self.enterContext(
            patch(
                "csed103.msvc.os",
                SimpleNamespace(
                    name="nt", environ={"ProgramFiles(x86)": str(self.root)}
                ),
            )
        )

    def test_discovery_caches_private_environment_and_preserves_equals(self):
        def run(command, **kwargs):
            if command[0].endswith("vswhere.exe"):
                self.assertIn("-requires", command)
                return subprocess.CompletedProcess(command, 0, stdout=str(self.install))
            script = Path(command[-1]).read_text()
            self.assertIn("-vcvars_ver=14.44", script)
            self.assertIn("if errorlevel 1 exit /b 1", script)
            self.assertEqual(Path(kwargs["cwd"]), Path(command[-1]).parent)
            return subprocess.CompletedProcess(
                command, 0, stdout="Path=tool/bin\nINCLUDE=a=b\n=C:=ignored\n"
            )

        with (
            patch("csed103.msvc.subprocess.run", side_effect=run) as invoked,
            patch("csed103.msvc.shutil.which", return_value="tool/bin/cl.exe"),
        ):
            env = msvc_environment("14.44")
            self.assertEqual(env, {"Path": "tool/bin", "INCLUDE": "a=b"})
            self.assertIs(msvc_environment("14.44"), env)
            self.assertEqual(invoked.call_count, 2)

    def test_existing_developer_environment_needs_no_discovery(self):
        with (
            patch("csed103.msvc.shutil.which", return_value="cl.exe"),
            patch("csed103.msvc.subprocess.run") as run,
        ):
            self.assertIn("ProgramFiles(x86)", msvc_environment())
            run.assert_not_called()

    def test_toolset_comes_from_selected_project_not_working_directory(self):
        (self.root / "pyproject.toml").write_text('[project]\nname = "csed103"\n')
        (self.root / "config.yaml").write_text('msvc:\n  toolset: "14.44"\n')
        assignment = self.root / "assign2"
        assignment.mkdir()
        with patch("csed103.compilers.msvc_environment", return_value={}) as setup:
            configured_msvc_environment(assignment)
        setup.assert_called_once_with("14.44")

    def test_invalid_version_is_rejected_before_shell(self):
        with patch("csed103.msvc.subprocess.run") as run:
            for version in ("14.44 & set", "latest", "14.44\nset"):
                with self.assertRaisesRegex(RuntimeError, "numeric"):
                    msvc_environment(version)
            run.assert_not_called()

    def test_failed_setup_does_not_expose_environment(self):
        results = [
            subprocess.CompletedProcess([], 0, stdout=str(self.install)),
            subprocess.CompletedProcess([], 1, stdout="PRIVATE=value", stderr="detail"),
        ]
        with patch("csed103.msvc.subprocess.run", side_effect=results):
            with self.assertRaisesRegex(
                RuntimeError, "Cannot initialize MSVC"
            ) as failure:
                msvc_environment("14.44")
            self.assertNotIn("PRIVATE", str(failure.exception))

    def test_compile_and_link_receive_the_discovered_environment(self):
        env = {"Path": "compiler", "LIB": "libraries", "INCLUDE": "headers"}
        compiler = Compiler("cl.exe", "msvc", "c", env)
        with (
            patch("csed103.compilers.get_compiler", return_value=compiler),
            patch(
                "csed103.compilers.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
            ) as run,
        ):
            self.assertTrue(
                compile_object(
                    self.root / "test.c", self.root / "test.obj", "msvc", [], [], []
                )[0]
            )
            self.assertEqual(run.call_args.kwargs["env"], env)
            self.assertIn("/utf-8", run.call_args.args[0])
            self.assertTrue(
                link_objects(
                    [self.root / "test.obj"], self.root / "test.exe", "msvc", False, []
                )[0]
            )
            self.assertEqual(run.call_args.kwargs["env"], env)
            self.assertEqual(run.call_args.kwargs["cwd"], self.root)


if __name__ == "__main__":
    unittest.main()
