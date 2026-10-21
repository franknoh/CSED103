"""Discover MSVC without requiring a Developer Command Prompt."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path


def environment_path(environment: dict[str, str]) -> str:
    return next((v for k, v in environment.items() if k.lower() == "path"), "")


@lru_cache(maxsize=None)
def msvc_environment(toolset: str | None = None) -> dict[str, str]:
    """Return a private x64 environment, never change the calling shell.

    An already configured compiler is honored unless a toolset was requested.
    Failed discovery is not cached. Captured environment values are never logged.
    """
    if os.name != "nt":
        raise RuntimeError("MSVC requires Windows; use gcc or clang on this host")
    if toolset is not None and not re.fullmatch(r"\d+(?:\.\d+)*", toolset):
        raise RuntimeError("MSVC toolset must be a numeric version such as 14.44")
    if toolset is None and shutil.which("cl"):
        return dict(os.environ)
    installer = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
    vswhere = installer / "Microsoft Visual Studio/Installer/vswhere.exe"
    if not vswhere.is_file():
        raise RuntimeError(
            "Visual Studio Installer/vswhere.exe not found; install C++ Build Tools"
        )
    result = subprocess.run(
        [
            str(vswhere),
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    installation = result.stdout.strip()
    if result.returncode or not installation:
        raise RuntimeError("No Visual Studio installation with C++ tools was found")
    vcvars = Path(installation) / "VC/Auxiliary/Build/vcvars64.bat"
    if not vcvars.is_file():
        raise RuntimeError("Visual Studio vcvars64.bat not found")
    # cmd.exe cannot start in a UNC working directory. Use a local temporary
    # batch file, not a shell-quoted command assembled from assignment paths.
    with tempfile.TemporaryDirectory(prefix="csed103-msvc-") as directory:
        script = Path(directory) / "environment.cmd"
        flag = f" -vcvars_ver={toolset}" if toolset else ""
        script.write_text(
            f'@echo off\ncall "{vcvars}"{flag} >nul\nif errorlevel 1 exit /b 1\nset\n',
            encoding="utf-8",
        )
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", str(script)],
            cwd=directory,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
    if result.returncode:
        raise RuntimeError(f"Cannot initialize MSVC toolset {toolset or 'default'}")
    environment = {
        k: v
        for line in result.stdout.splitlines()
        if "=" in line and not line.startswith("=")
        for k, v in [line.split("=", 1)]
    }
    if not shutil.which("cl", path=environment_path(environment)):
        raise RuntimeError("MSVC environment does not contain cl.exe")
    return environment
