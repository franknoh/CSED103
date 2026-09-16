# CSED103

Coursework for CSED103.

## Setup

Requires uv and GCC, Clang, or MSVC. PDF reports require Pandoc and XeLaTeX.
Python is managed through `.python-version`.

```sh
uv sync --locked
source .venv/bin/activate
```

On PowerShell, activate with `.venv\Scripts\Activate.ps1`.
Set your `student_id` and `name` in `config.yaml`.

## Structure

```text
assign*/
  README.md          # Report source
  manifest.yaml      # Build, test, and submission configuration
  assets/            # Assignment materials and report images
  ppy/               # Optional PPY sources
  src/               # C/C++ sources
  tests/<problem>/   # Matching .in / .out files
  out/               # Generated PDF and ZIP
tools/csed103/        # CLI source and its tests
config.yaml          # Student information
pyproject.toml       # uv workspace and dependencies
uv.lock              # Dependency lockfile
.python-version      # Python version
```

## Usage

```sh
csed103 build ppy assign1         # Generate manifest-defined C/C++ targets
csed103 test assign1
csed103 build report assign1
csed103 build submission assign1
csed103 build all assign1         # Test, report, then ZIP
csed103 clean assign1             # Remove out/
csed103 --help
```

Omit `assign1` from `test`, `build all`, or `clean` to process all assignments;
`build ppy` processes those with a `ppy` section in `manifest.yaml`.

- `test`, `build all`: `--compiler auto|gcc|clang|msvc`, `--timeout SECONDS`.
- PDF builds: `--pdf-engine ENGINE` (default: `PDF_ENGINE` or `xelatex`).
- `build submission` reuses an existing PDF; `build all` rebuilds it.
- `build ppy` uses `emit --standalone --unsafe` and requires PPY 0.3.4 or newer.

Declare PPY inputs and outputs in each assignment's `manifest.yaml`:

```yaml
ppy:
  targets:
    ppy/problem1.ppy: [src/problem1.c, src/problem1.cpp]
```

Only declared outputs are generated, including files that do not exist yet.
