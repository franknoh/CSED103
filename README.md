# CSED103

Coursework for CSED103. Build, test, and package assignments with `csed103`.

## Setup

Requires uv and GCC, Clang, or MSVC. PDF reports also require Pandoc and XeLaTeX.

```sh
uv sync --locked
```

Set student information and the MSVC toolset in `config.yaml`.
MSVC is initialized automatically on Windows.

## Usage

```sh
uv run csed103 build ppy assign1       # Generate C from PPY
uv run csed103 build binaries assign1 # Build programs
uv run csed103 test assign1           # Run tests
uv run csed103 build all assign1      # Test, build report, package ZIP
uv run csed103 clean assign1          # Remove generated outputs
uv run csed103 --help
```

Replace `assign1` with the assignment name. Use `--compiler msvc`, `gcc`, or
`clang` for builds and tests. `build report` and `build submission` can run
separately. Generate C before running `build all`.

## Structure

```text
assign*/
  README.md       # Report source
  manifest.yaml   # Generation, build, test, and submission settings
  assets/         # Provided files and report images
  ppy/            # PPY sources
  src/            # C/C++ sources
  tests/          # Test cases and drivers
  out/            # Generated files; only report.pdf is tracked
tools/csed103/   # Shared CLI and tests
```

See each assignment's manifest for its configuration and required submission files.
