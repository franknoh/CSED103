"""Run line-input examples in a real PTY and render their terminal output."""

from __future__ import annotations

import math
import os
import re
import select
import tempfile
import time
from pathlib import Path

import pyte
from PIL import Image, ImageDraw, ImageFont

from .binaries import build_binaries, supported_platform
from .build import local_file
from .compilers import Toolchain
from .project import build_output_dir, load_yaml, output_dir


def terminal_text(screen: pyte.Screen) -> str:
    return "\n".join(line.rstrip() for line in screen.display).rstrip() + "\n"


def capture_terminal(
    executable: Path, inputs: list[str], prompt: str, timeout: float
) -> tuple[str, str]:
    """Capture a finite, line-oriented example, including the terminal's input echo."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise RuntimeError("example timeout must be finite and positive")
    expression = re.compile(prompt)
    if expression.search(""):
        raise RuntimeError("example prompt must not match empty text")
    if os.name == "nt":
        from winpty import PtyProcess
    else:
        from ptyprocess import PtyProcessUnicode as PtyProcess

    screen = pyte.Screen(100, 80)
    stream = pyte.Stream(screen)
    process = PtyProcess.spawn(
        [str(executable)], cwd=str(executable.parent), dimensions=(80, 100)
    )
    deadline = time.monotonic() + timeout
    raw = ""
    sent = 0
    search_from = 0
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    f"example timed out after {timeout:g}s (sent {sent}/{len(inputs)} input lines)"
                )
            if not select.select([process.fd], [], [], remaining)[0]:
                raise RuntimeError(
                    f"example timed out waiting for output (sent {sent}/{len(inputs)} input lines)"
                )
            try:
                chunk = process.read(4096)
            except EOFError:
                break
            raw += chunk
            if len(raw) > 1_000_000:
                raise RuntimeError("example terminal output exceeds 1 MB")
            stream.feed(chunk)
            if sent < len(inputs):
                visible = "\n".join(screen.display)
                match = expression.search(visible, search_from)
                if match:
                    search_from = match.end()
                    process.write(inputs[sent] + ("\r\n" if os.name == "nt" else "\n"))
                    sent += 1
        # Reap the process before reading exitstatus (required by Unix PTYs).
        if os.name != "nt":
            process.isalive()
        if sent != len(inputs):
            raise RuntimeError(
                f"example exited before consuming all input ({sent}/{len(inputs)})"
            )
        if process.exitstatus != 0:
            raise RuntimeError(f"example failed with exit code {process.exitstatus}")
        return raw, terminal_text(screen)
    finally:
        process.close(force=True)


def terminal_font(size: int) -> ImageFont.FreeTypeFont:
    for name in (
        "C:/Windows/Fonts/consola.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
    ):
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    raise RuntimeError(
        "install Consolas, DejaVu Sans Mono, or Menlo to render examples"
    )


def render_terminal(
    text: str, title: str, destination: Path, *, prompt: str | None = None
) -> None:
    """Style the launch command and captured text without window decorations."""
    font = terminal_font(22)
    lines = text.rstrip("\n").expandtabs(8).splitlines() or [""]
    padding, top, line_height = 28, 70, 30
    command = f"./{title}"
    width = max(
        640,
        math.ceil(max(font.getlength(line) for line in lines)) + padding * 2,
        math.ceil(font.getlength(command)) + padding * 2 + 28,
    )
    height = top + max(3, len(lines)) * line_height + padding
    image = Image.new("RGB", (width, height), "#1a1b26")
    draw = ImageDraw.Draw(image)
    # Draw the shell chevron directly so it needs no Nerd Font glyphs.
    draw.line(
        ((padding + 3, 32), (padding + 10, 39), (padding + 3, 46)),
        fill="#9ece6a",
        width=3,
    )
    draw.text((padding + 28, 26), command, font=font, fill="#7dcfff")
    expression = re.compile(prompt) if prompt else None
    for number, line in enumerate(lines):
        position = (padding, top + number * line_height)
        draw.text(
            position,
            line,
            font=font,
            fill="#bb9af7" if number == 0 else "#c0caf5",
        )
        match = expression.search(line) if expression else None
        if match:
            draw.text(
                (padding + font.getlength(line[: match.end()]), position[1]),
                line[match.end() :],
                font=font,
                fill="#9ece6a",
            )
    image.save(destination, dpi=(160, 160))


def build_examples(
    assignment: Path, *, compiler: Toolchain = "auto", timeout: float = 10
) -> list[Path]:
    manifest = load_yaml(assignment / "manifest.yaml")
    examples = manifest.get("examples", {})
    if not isinstance(examples, dict):
        raise RuntimeError("examples must map names to problem/input/prompt settings")
    if not examples:
        return []
    problems = manifest.get("problems")
    if not isinstance(problems, dict):
        raise RuntimeError("examples require a problems mapping")
    if not math.isfinite(timeout) or timeout <= 0:
        raise RuntimeError("example timeout must be finite and positive")
    prepared = []
    for name, config in examples.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise RuntimeError("example names must be simple identifiers")
        if not isinstance(config, dict):
            raise RuntimeError(f"{name}: example must be a mapping")
        problem = config.get("problem", name)
        if not isinstance(problem, str):
            raise RuntimeError(f"{name}: problem must be a name")
        target = problems.get(problem)
        if (
            not isinstance(target, dict)
            or target.get("kind", "executable") != "executable"
        ):
            raise RuntimeError(f"{name}: example must name an executable problem")
        if not supported_platform(target):
            raise RuntimeError(f"{name}: example is not supported on this platform")
        source = local_file(assignment, config.get("input"))
        inputs = source.read_text(encoding="utf-8").splitlines()
        prompt = config.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise RuntimeError(f"{name}: prompt must be a non-empty regular expression")
        try:
            expression = re.compile(prompt)
        except re.error as exc:
            raise RuntimeError(f"{name}: invalid prompt expression: {exc}") from exc
        if expression.search(""):
            raise RuntimeError(f"{name}: prompt must not match empty text")
        prepared.append((name, problem, inputs, prompt))
    binaries = build_binaries(assignment, compiler=compiler)
    out = output_dir(assignment)
    directory = out / "examples"
    if directory.is_symlink():
        raise RuntimeError("example output directory must not be a symlink")
    directory.mkdir(exist_ok=True)
    paths = []
    # Stage all captures first; a failing example must not replace earlier images.
    with tempfile.TemporaryDirectory(
        prefix=".examples-", dir=build_output_dir(assignment)
    ) as temporary:
        staged = Path(temporary)
        for name, problem, inputs, prompt in prepared:
            raw, text = capture_terminal(binaries[problem], inputs, prompt, timeout)
            (staged / f"{name}.ansi").write_text(raw, encoding="utf-8", newline="")
            (staged / f"{name}.txt").write_text(text, encoding="utf-8")
            render_terminal(
                text, binaries[problem].name, staged / f"{name}.png", prompt=prompt
            )
            paths.append(directory / f"{name}.png")
        for file in staged.iterdir():
            file.replace(directory / file.name)
    for path in paths:
        print(f"[example] {path.relative_to(assignment)}")
    return paths
