#!/usr/bin/env python3
"""Build and import a wheel from a throwaway source copy without mutating the checkout."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _copy_project(source: Path, target: Path) -> None:
    shutil.copytree(
        source / "agent_artifacts",
        target / "agent_artifacts",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for name in ("pyproject.toml", "README.md"):
        shutil.copy2(source / name, target / name)
    scripts = target / "scripts"
    scripts.mkdir()
    shutil.copy2(source / "scripts" / "build_wheel.py", scripts / "build_wheel.py")


def _build_wheel(source_copy: Path, wheel_dir: Path) -> None:
    if sys.version_info >= (3, 11):
        subprocess.run(
            [sys.executable, "scripts/build_wheel.py"],
            cwd=source_copy,
            check=True,
        )
        built = tuple((source_copy / "dist").glob("agent_artifacts-*-py3-none-any.whl"))
        if len(built) != 1:
            raise ValueError(f"expected one stdlib-built wheel, found {built}")
        shutil.move(str(built[0]), wheel_dir / built[0].name)
        return
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--disable-pip-version-check",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
            ".",
        ],
        cwd=source_copy,
        check=True,
    )


def _validate_wheel(wheel: Path, install_root: Path) -> None:
    if not zipfile.is_zipfile(wheel):
        raise ValueError(f"not a wheel zip: {wheel.name}")
    with zipfile.ZipFile(wheel) as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise ValueError(f"corrupt wheel member: {corrupt}")
        names = archive.namelist()
        records = [name for name in names if name.endswith(".dist-info/RECORD")]
        if len(records) != 1:
            raise ValueError(f"expected one RECORD, found {records}")
        info = records[0].split("/")[0]
        metadata = archive.read(f"{info}/METADATA").decode("utf-8")
        requirements = tuple(
            line.removeprefix("Requires-Dist:").strip()
            for line in metadata.splitlines()
            if line.startswith("Requires-Dist:")
        )
        runtime_requirements = tuple(item for item in requirements if "extra ==" not in item)
        if runtime_requirements:
            raise ValueError(f"runtime dependency found in wheel metadata: {runtime_requirements}")
        for required in (
            "agent_artifacts/__init__.py",
            "agent_artifacts/cli.py",
            f"{info}/entry_points.txt",
        ):
            if required not in names:
                raise ValueError(f"wheel member missing: {required}")
        archive.extractall(install_root)


def check_packaging(root: Path = ROOT) -> Path:
    with tempfile.TemporaryDirectory(prefix="aart-packaging-") as raw:
        temp_root = Path(raw)
        source_copy = temp_root / "source"
        wheel_dir = temp_root / "wheel"
        install_root = temp_root / "installed"
        source_copy.mkdir()
        wheel_dir.mkdir()
        install_root.mkdir()
        _copy_project(root, source_copy)
        _build_wheel(source_copy, wheel_dir)
        wheels = tuple(wheel_dir.glob("agent_artifacts-*-py3-none-any.whl"))
        if len(wheels) != 1:
            raise ValueError(f"expected one wheel, found {wheels}")
        wheel = wheels[0]
        _validate_wheel(wheel, install_root)
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(install_root)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import agent_artifacts; from agent_artifacts.cli import main; assert callable(main)",
            ],
            cwd=temp_root,
            env=environment,
            check=True,
        )
        return Path(wheel.name)


def main() -> int:
    wheel = check_packaging()
    print(f"packaging check OK: {wheel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
