#!/usr/bin/env python3
"""Canonical, hermetic, non-mutating quality-gate runner for local use and CI."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
QUALITY_GATES = (
    "format-check",
    "lint",
    "typecheck",
    "unit",
    "integration",
    "e2e",
    "validate",
    "coverage",
    "packaging-check",
    "docs-check",
)


@dataclass(frozen=True)
class Gate:
    name: str
    commands: tuple[tuple[str, ...], ...]


def select_gates(requested: tuple[str, ...]) -> tuple[str, ...]:
    selected = QUALITY_GATES if not requested else requested
    unknown = tuple(name for name in selected if name not in QUALITY_GATES)
    if unknown:
        raise ValueError(f"unknown quality gate(s): {', '.join(unknown)}")
    if len(set(selected)) != len(selected):
        raise ValueError("quality gates must not be repeated")
    return selected


def snapshot_paths(paths: Iterable[Path]) -> tuple[tuple[str, int, str], ...]:
    snapshot: list[tuple[str, int, str]] = []
    for path in sorted(paths, key=lambda item: str(item)):
        if not path.exists() or not path.is_file():
            snapshot.append((str(path), -1, "missing"))
            continue
        stat = path.stat()
        snapshot.append(
            (str(path), stat.st_mode & 0o777, hashlib.sha256(path.read_bytes()).hexdigest())
        )
    return tuple(snapshot)


def workspace_paths(root: Path) -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return tuple(root / raw.decode("utf-8") for raw in result.stdout.split(b"\0") if raw)


def build_gates(temp_root: Path, python: str = sys.executable) -> tuple[Gate, ...]:
    coverage_data = temp_root / "coverage.data"
    paths = ("agent_artifacts", "tests", "scripts")
    return (
        Gate("format-check", ((python, "-m", "ruff", "format", "--check", *paths),)),
        Gate("lint", ((python, "-m", "ruff", "check", *paths),)),
        Gate("typecheck", ((python, "-m", "mypy", "--cache-dir", str(temp_root / "mypy")),)),
        Gate(
            "unit",
            ((python, "-m", "unittest", "discover", "-s", "tests", "-p", "*_test.py"),),
        ),
        Gate(
            "integration",
            ((python, "-m", "unittest", "discover", "-s", "tests", "-p", "*e2e_test.py"),),
        ),
        Gate("e2e", (("bash", "tests/e2e_test.sh"),)),
        Gate(
            "validate",
            ((python, "scripts/validate.py"), (python, "scripts/version.py", "check")),
        ),
        Gate(
            "coverage",
            (
                (
                    python,
                    "-m",
                    "coverage",
                    "run",
                    "--branch",
                    "--source=agent_artifacts",
                    f"--data-file={coverage_data}",
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tests",
                    "-p",
                    "*_test.py",
                ),
                (
                    python,
                    "-m",
                    "coverage",
                    "report",
                    f"--data-file={coverage_data}",
                ),
            ),
        ),
        Gate("packaging-check", ((python, "scripts/packaging_check.py"),)),
        Gate("docs-check", ((python, "scripts/docs_check.py"),)),
    )


def _run(selected: tuple[str, ...], temp_root: Path) -> int:
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "RUFF_CACHE_DIR": str(temp_root / "ruff"),
        }
    )
    by_name = {gate.name: gate for gate in build_gates(temp_root)}
    for name in selected:
        print(f"\n==> quality gate: {name}", flush=True)
        for command in by_name[name].commands:
            print("+ " + " ".join(command), flush=True)
            result = subprocess.run(command, cwd=ROOT, env=environment)
            if result.returncode:
                print(f"quality gate FAILED: {name} ({result.returncode})", file=sys.stderr)
                return result.returncode
    return 0


def main(argv: tuple[str, ...] | None = None) -> int:
    try:
        selected = select_gates(tuple(sys.argv[1:]) if argv is None else argv)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    before_paths = workspace_paths(ROOT)
    before = snapshot_paths(before_paths)
    with tempfile.TemporaryDirectory(prefix="aart-quality-") as raw:
        result = _run(selected, Path(raw))
    after_paths = workspace_paths(ROOT)
    after = snapshot_paths(after_paths)
    if before_paths != after_paths or before != after:
        print("quality gate mutated repository files", file=sys.stderr)
        return 3
    if result:
        return result
    print("\nquality gates OK: " + ", ".join(selected))
    return 0


if __name__ == "__main__":
    sys.exit(main())
