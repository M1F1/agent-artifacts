#!/usr/bin/env python3
"""Build and import a wheel from a throwaway source copy without mutating the checkout."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
_RESOURCE_ROOTS = frozenset({"schemas", "profiles", "importers", "templates"})
_DIST_INFO_FILES = frozenset({"METADATA", "WHEEL", "entry_points.txt", "RECORD", "top_level.txt"})


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
            "--no-index",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
            ".",
        ],
        cwd=source_copy,
        check=True,
    )


def _safe_archive_name(name: str) -> bool:
    path = PurePosixPath(name)
    encoded_parts = tuple(name.split("/"))
    return (
        bool(name)
        and "\x00" not in name
        and "\\" not in name
        and not name.startswith("/")
        and not name.endswith("/")
        and tuple(path.parts) == encoded_parts
        and all(part not in {".", ".."} for part in path.parts)
    )


def _allowed_package_member(name: str) -> bool:
    parts = PurePosixPath(name).parts
    if len(parts) < 2 or parts[0] != "agent_artifacts":
        return False
    if name.endswith(".py"):
        return True
    return len(parts) >= 3 and parts[1] in _RESOURCE_ROOTS


def _allowed_dist_info_member(name: str, info: str) -> bool:
    parts = PurePosixPath(name).parts
    if len(parts) == 2 and parts[0] == info:
        return parts[1] in _DIST_INFO_FILES
    return len(parts) >= 3 and parts[0] == info and parts[1] == "licenses"


def _regular_archive_members(archive: zipfile.ZipFile) -> tuple[str, ...]:
    rejected = []
    for item in archive.infolist():
        file_type = stat.S_IFMT(item.external_attr >> 16)
        if file_type not in {0, stat.S_IFREG}:
            rejected.append(item.filename)
    return tuple(rejected)


def _validate_record(archive: zipfile.ZipFile, names: list[str], record_name: str) -> None:
    try:
        rows = tuple(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"))))
    except (KeyError, UnicodeDecodeError, csv.Error) as error:
        raise ValueError("wheel RECORD is unreadable") from error
    if any(len(row) != 3 for row in rows):
        raise ValueError("wheel RECORD rows must have three fields")
    recorded = tuple(row[0] for row in rows)
    if len(recorded) != len(set(recorded)) or set(recorded) != set(names):
        raise ValueError("wheel RECORD does not list every member exactly once")
    for name, digest, raw_size in rows:
        if name == record_name:
            if digest or raw_size:
                raise ValueError("wheel RECORD self-entry must omit digest and size")
            continue
        content = archive.read(name)
        expected = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        if digest != f"sha256={expected}" or raw_size != str(len(content)):
            raise ValueError(f"wheel RECORD evidence mismatch: {name}")


def _validate_wheel(wheel: Path, install_root: Path) -> None:
    if not zipfile.is_zipfile(wheel):
        raise ValueError(f"not a wheel zip: {wheel.name}")
    with zipfile.ZipFile(wheel) as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise ValueError(f"corrupt wheel member: {corrupt}")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("wheel contains duplicate archive members")
        unsafe = tuple(name for name in names if not _safe_archive_name(name))
        if unsafe:
            raise ValueError(f"wheel contains unsafe archive members: {unsafe}")
        special = _regular_archive_members(archive)
        if special:
            raise ValueError(f"wheel contains non-regular archive members: {special}")
        records = [name for name in names if name.endswith(".dist-info/RECORD")]
        if len(records) != 1:
            raise ValueError(f"expected one RECORD, found {records}")
        info = records[0].split("/")[0]
        expected_info = wheel.name.removesuffix("-py3-none-any.whl") + ".dist-info"
        if info != expected_info:
            raise ValueError(f"wheel filename and dist-info identity disagree: {info}")
        rejected = tuple(
            name
            for name in names
            if not _allowed_package_member(name) and not _allowed_dist_info_member(name, info)
        )
        if rejected:
            raise ValueError(f"wheel member allowlist rejects: {rejected}")
        _validate_record(archive, names, records[0])
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


_TYPED_BEHAVIOR_PROBE = """
import json
from agent_artifacts.install_state.schema import parse_install_state
from agent_artifacts.tui import InternalFailureContext, internal_failure_lines
from agent_artifacts.tui_failures import WizardStageFailure, render_wizard_stage_failure

LEGACY = json.dumps({"repo": "org/aart", "installed": []}).encode()
INVALID = b'{"schema_version": 2, "installations": '


def record(raw, path):
    parsed = parse_install_state(raw, path=path)
    return WizardStageFailure(
        stage="artifacts",
        operation="load",
        diagnostics=parsed.diagnostics,
        action="install",
        scope="project",
        project="/probe/project",
        recoverable=True,
        choices=("retry", "back", "quit"),
    )


for raw, path in (
    (LEGACY, "/probe/project/.agent-artifacts/manifest.json"),
    (INVALID, "/probe/project/.agent-artifacts/state.json"),
):
    for line in render_wizard_stage_failure(record(raw, path), width=80):
        print(line)

context = InternalFailureContext()
context.stage = "artifacts"
context.operation = "load"
for line in internal_failure_lines(ValueError("probe"), context):
    print(line)
"""


def run_typed_behavior_probe(
    interpreter: str,
    *,
    env: dict[str, str] | None,
    cwd: Path,
) -> str:
    """Render the track's typed diagnostics through one interpreter.

    Every path in the snippet is synthetic, so two interpreters that agree on the typed contract
    produce byte-identical output regardless of where they run from.
    """

    completed = subprocess.run(
        [interpreter, "-c", _TYPED_BEHAVIOR_PROBE],
        cwd=cwd,
        env=env,
        capture_output=True,
        check=True,
    )
    return completed.stdout.decode("utf-8")


def _compare_typed_behavior(checkout: str, wheel: str) -> None:
    if checkout != wheel:
        raise ValueError(
            "typed behavior differs between the checkout and the built wheel; "
            "the wheel does not reproduce the same diagnostics"
        )


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
        # Importability is not the contract users depend on: the typed diagnostics are. The wheel
        # is run from a directory that contains no checkout, so only the extracted package answers.
        checkout_environment = os.environ.copy()
        checkout_environment.pop("PYTHONPATH", None)
        checkout_environment["PYTHONDONTWRITEBYTECODE"] = "1"
        _compare_typed_behavior(
            run_typed_behavior_probe(sys.executable, env=checkout_environment, cwd=root),
            run_typed_behavior_probe(sys.executable, env=environment, cwd=temp_root),
        )
        return Path(wheel.name)


def main() -> int:
    wheel = check_packaging()
    print(f"packaging check OK: {wheel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
