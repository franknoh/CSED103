"""Exercise real terminal echo, failures, and capture/report orchestration."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pyte
import yaml
from csed103.cli import main
from csed103.examples import (
    build_examples,
    capture_terminal,
    render_terminal,
    terminal_text,
)
from PIL import Image


class ExampleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="examples-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "pyproject.toml").write_text('[project]\nname="csed103"\n')
        self.assignment = self.root / "assign1"
        self.assignment.mkdir()
        self.manifest = self.assignment / "manifest.yaml"
        self.manifest.write_text("{}")

    def configure(self):
        (self.assignment / "sample.in").write_text("21\n")
        self.manifest.write_text(
            yaml.safe_dump(
                {
                    "problems": {"sample": {"sources": ["main.c"]}},
                    "examples": {
                        "sample": {"input": "sample.in", "prompt": "Number: "}
                    },
                }
            )
        )

    def test_absent_examples_do_not_build_anything(self):
        with patch("csed103.examples.build_binaries") as build:
            self.assertEqual(build_examples(self.assignment), [])
        build.assert_not_called()

    def test_invalid_paths_and_prompts_fail_before_build(self):
        for setting, value in (
            ("input", "../outside.in"),
            ("prompt", "["),
            ("prompt", ".*"),
            ("problem", "missing"),
        ):
            self.configure()
            config = yaml.safe_load(self.manifest.read_text())
            config["examples"]["sample"][setting] = value
            self.manifest.write_text(yaml.safe_dump(config))
            with (
                self.subTest(setting=setting),
                patch("csed103.examples.build_binaries") as build,
            ):
                with self.assertRaises(RuntimeError):
                    build_examples(self.assignment)
                build.assert_not_called()

    def test_terminal_control_sequences_are_interpreted(self):
        screen = pyte.Screen(40, 10)
        pyte.Stream(screen).feed("wrong\r\x1b[2KNumber: 21\r\n42\r\n")
        self.assertEqual(terminal_text(screen), "Number: 21\n42\n")

    def test_invalid_key_configuration_fails_before_build(self):
        for settings in (
            {"keys": ["left"], "input": "sample.in", "exit_key": "q"},
            {"keys": "left", "exit_key": "q"},
            {"keys": ["unknown"], "exit_key": "q"},
            {"keys": ["left"]},
            {"keys": [], "exit_key": "q", "capture": "["},
            {"keys": [], "exit_key": "q", "capture": ".*"},
        ):
            self.configure()
            config = yaml.safe_load(self.manifest.read_text())
            config["examples"]["sample"] = {"prompt": "Ready", **settings}
            self.manifest.write_text(yaml.safe_dump(config))
            with (
                self.subTest(settings=settings),
                patch("csed103.examples.build_binaries") as build,
            ):
                with self.assertRaises(RuntimeError):
                    build_examples(self.assignment)
                build.assert_not_called()

    @unittest.skipUnless(
        os.name != "nt" and shutil.which("gcc"), "Unix PTY integration"
    )
    def test_key_input_scroll_and_capture_before_quit(self):
        source = self.root / "keys.c"
        source.write_text(r"""
#include <stdio.h>
#include <termios.h>
#include <unistd.h>
int main(void) {
    struct termios old, raw;
    tcgetattr(0, &old); raw = old;
    raw.c_lflag &= ~(ICANON | ECHO);
    tcsetattr(0, TCSANOW, &raw);
    int frame = 0, key;
    for (;;) {
        printf("Frame %d\n", frame);
        for (int i = 0; i < 20; ++i) puts("board row");
        puts("Ready"); fflush(stdout);
        key = getchar();
        if (key == 'q') break;
        if (key != 27 || getchar() != '[' || getchar() != 'D') return 2;
        ++frame;
    }
    puts("QUIT");
    tcsetattr(0, TCSANOW, &old);
    return 0;
}
""")
        executable = self.root / "keys"
        subprocess.run(["gcc", str(source), "-o", str(executable)], check=True)
        raw, text = capture_terminal(
            executable,
            ["left"] * 6,
            "Ready",
            3,
            exit_key="q",
            capture=r"Frame \d+\n(?:board row\n){20}Ready",
        )
        self.assertIn("QUIT", raw)
        self.assertEqual(text, "Frame 6\n" + "board row\n" * 20 + "Ready\n")
        with self.assertRaisesRegex(RuntimeError, "capture pattern"):
            capture_terminal(
                executable, [], "Ready", 2, exit_key="q", capture="missing"
            )
        with self.assertRaisesRegex(RuntimeError, "final capture prompt"):
            capture_terminal(executable, ["q"], "Ready", 2, exit_key="q")

    def test_png_is_sized_for_long_output(self):
        output = self.root / "terminal.png"
        render_terminal("x" * 90 + "\n" + "line\n" * 20, "sample.exe", output)
        with Image.open(output) as picture:
            self.assertEqual(picture.format, "PNG")
            self.assertGreater(picture.width, 1000)
            self.assertGreater(picture.height, 600)

    def test_failed_capture_preserves_existing_image(self):
        self.configure()
        directory = self.assignment / "out/examples"
        directory.mkdir(parents=True)
        image = directory / "sample.png"
        image.write_bytes(b"old image")
        with (
            patch(
                "csed103.examples.build_binaries",
                return_value={"sample": Path("unused")},
            ),
            patch(
                "csed103.examples.capture_terminal", side_effect=RuntimeError("timeout")
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "timeout"):
                build_examples(self.assignment)
        self.assertEqual(image.read_bytes(), b"old image")

    def test_cli_forwards_example_options(self):
        with patch("csed103.cli.build_examples") as examples:
            self.assertEqual(
                main(
                    [
                        "--root",
                        str(self.root),
                        "build",
                        "examples",
                        "assign1",
                        "--compiler",
                        "msvc",
                        "--timeout",
                        "3",
                    ]
                ),
                0,
            )
        examples.assert_called_once_with(self.assignment, compiler="msvc", timeout=3)

    def test_full_build_captures_before_rendering_report(self):
        events = []
        with (
            patch("csed103.cli.test_assignment", return_value=0),
            patch(
                "csed103.cli.build_examples",
                side_effect=lambda *a, **k: events.append("examples"),
            ),
            patch(
                "csed103.cli.build_report",
                side_effect=lambda *a, **k: events.append("report"),
            ),
            patch(
                "csed103.cli.build_submission",
                side_effect=lambda *a, **k: events.append("zip"),
            ),
        ):
            self.assertEqual(
                main(["--root", str(self.root), "build", "all", "assign1"]), 0
            )
        self.assertEqual(events, ["examples", "report", "zip"])

    @unittest.skipUnless(
        os.name != "nt" and shutil.which("gcc"), "Unix PTY integration"
    )
    def test_real_prompt_echo_timeout_and_exit_failure(self):
        source = self.root / "dialogue.c"
        source.write_text(
            '#include <stdio.h>\nint main(void) { int n; printf("Number: "); fflush(stdout); if(scanf("%d", &n)!=1) return 1; printf("Answer: %d\\n", n*2); return n < 0; }\n'
        )
        executable = self.root / "dialogue"
        subprocess.run(["gcc", str(source), "-o", str(executable)], check=True)
        raw, text = capture_terminal(executable, ["21"], "Number: ", 2)
        self.assertIn("21", raw)
        self.assertEqual(text, "Number: 21\nAnswer: 42\n")
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            capture_terminal(executable, ["21"], "Wrong prompt: ", 0.2)
        with self.assertRaisesRegex(RuntimeError, "exit code 1"):
            capture_terminal(executable, ["-1"], "Number: ", 2)
        with self.assertRaisesRegex(RuntimeError, "all input"):
            capture_terminal(executable, ["21", "22"], "Number: ", 2)


if __name__ == "__main__":
    unittest.main()
