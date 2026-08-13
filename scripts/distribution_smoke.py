#!/usr/bin/env python3
"""Hermetic editable-to-wheel AART lifecycle smoke test.

The driver creates disposable Python environments, but keeps source snapshots, objects,
configuration, installation state, and harness targets in a separate shared tree.  Its phase
processes intentionally run outside the AART checkout and import only the installed distribution.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import venv
from pathlib import Path
from typing import Any


def _unwrap(result: Any) -> Any:
    from agent_artifacts.domain.result import Ok

    if not isinstance(result, Ok):
        raise RuntimeError(f"AART operation failed: {result!r}")
    return result.value


def _platform() -> str:
    return "darwin" if sys.platform == "darwin" else "linux"


def _config_paths(home: Path):
    from agent_artifacts.configuration.paths import Platform, resolve_config_paths

    platform = Platform.DARWIN if sys.platform == "darwin" else Platform.LINUX
    return resolve_config_paths(
        platform,
        home=str(home),
        xdg_config_home=os.environ.get("XDG_CONFIG_HOME"),
        xdg_data_home=os.environ.get("XDG_DATA_HOME"),
        xdg_cache_home=os.environ.get("XDG_CACHE_HOME"),
    )


def _assert_installed_origin(
    expected: str,
    *,
    source_root: Path,
    environment_root: Path,
) -> int:
    import agent_artifacts

    package_file = Path(agent_artifacts.__file__).resolve()
    if expected == "editable":
        if not package_file.is_relative_to(source_root):
            raise RuntimeError(f"editable phase imported unexpected package: {package_file}")
    elif not package_file.is_relative_to(environment_root) or package_file.is_relative_to(
        source_root
    ):
        raise RuntimeError(f"wheel phase imported unexpected package: {package_file}")
    requirements = importlib.metadata.requires("agent-artifacts") or []
    runtime = tuple(item for item in requirements if "extra ==" not in item)
    if runtime:
        raise RuntimeError(f"installed distribution has runtime dependencies: {runtime}")
    return len(runtime)


def _configure_and_sync(source_root: Path, home: Path) -> str:
    from agent_artifacts.application.configuration import ConfigDocument
    from agent_artifacts.application.sources import SourceSyncPorts, SourceSyncRequest, sync_source
    from agent_artifacts.configuration.model import (
        ConfiguredSource,
        ReportingSettings,
        SourceKind,
        SyncSettings,
        UserConfiguration,
    )
    from agent_artifacts.configuration.schema import user_configuration_bytes
    from agent_artifacts.domain.identifiers import SourceAlias
    from agent_artifacts.io.config_store import write_configuration
    from agent_artifacts.io.source_store import (
        acquire_source_lock,
        publish_source_snapshot,
        read_current_source,
        release_source_lock,
    )
    from agent_artifacts.protocol.capabilities import Capability
    from agent_artifacts.protocol.semver import SemVer
    from agent_artifacts.sources.git import acquire_git_snapshot
    from agent_artifacts.sources.local import read_local_snapshot
    from agent_artifacts.sources.model import SyncFallback
    from agent_artifacts.sources.validation import validate_source_candidate

    source = ConfiguredSource(
        SourceAlias("reference"),
        SourceKind.SOURCE_LOCAL,
        str(source_root),
        None,
        True,
    )
    configuration = UserConfiguration(
        1,
        (source,),
        None,
        SyncSettings(),
        ReportingSettings(),
    )
    paths = _config_paths(home)
    _unwrap(
        write_configuration(
            ConfigDocument(paths.user_config_file, user_configuration_bytes(configuration))
        )
    )
    ports = SourceSyncPorts(
        acquire_source_lock,
        release_source_lock,
        read_current_source,
        read_local_snapshot,
        acquire_git_snapshot,
        validate_source_candidate,
        publish_source_snapshot,
    )
    outcome = _unwrap(
        sync_source(
            SourceSyncRequest(
                source,
                paths.data_root,
                SemVer(1, 0, 0),
                (Capability("artifact-manifest-v1"),),
                int(time.time()),
                SyncFallback.REQUIRE_FRESH,
                False,
                30,
            ),
            ports,
        )
    )
    return outcome.disposition.value


def _load_service(project: Path, home: Path):
    from agent_artifacts.consumer.runtime import load_local_consumer_service

    return _unwrap(load_local_consumer_service(project=str(project), user_home=str(home)))


def _apply(service: Any, request: Any) -> Any:
    review = _unwrap(service.prepare(request))
    return _unwrap(service.finalize(review, review.review_digest))


def _state(service: Any) -> Any:
    from agent_artifacts.install_state.paths import install_state_paths
    from agent_artifacts.install_state.schema import parse_install_state

    location = service.context.location
    state_path = install_state_paths(
        "project",
        project_root=location.project_root,
        user_home=location.user_home,
        data_root=location.data_root,
    ).destination_path
    try:
        content = Path(state_path).read_bytes()
    except FileNotFoundError:
        raise RuntimeError("project installation state is missing") from None
    return _unwrap(parse_install_state(content, path=state_path))


def _symlink_receipt(service: Any) -> tuple[str, str]:
    records = tuple(
        item for item in _state(service).installations if item.requested_mode == "symlink"
    )
    if len(records) != 1:
        raise RuntimeError(f"expected one managed symlink record, found {len(records)}")
    effects = tuple(effect for effect in records[0].effects if effect.actual_mode == "symlink")
    if len(effects) != 1 or effects[0].link_semantics != "immutable-object":
        raise RuntimeError("managed symlink is not bound to one immutable object")
    effect = effects[0]
    destination = Path(service.context.location.project_root, effect.destination)
    if not destination.is_symlink() or effect.link_target is None:
        raise RuntimeError(f"managed symlink destination is invalid: {destination}")
    if not Path(effect.link_target).is_dir():
        raise RuntimeError(f"managed object target is unavailable: {effect.link_target}")
    return str(destination), effect.link_target


def _symlinkable_coordinate(service: Any) -> Any:
    """The one fixture artifact that declares the symlink mode.

    The smoke proves that a managed *symlink* survives environment recreation, so both phases must
    drive the same symlink-capable artifact; picking positionally would silently switch to
    whichever artifact the fixture happens to list first.
    """

    symlinkable = [
        item
        for item in service.context.catalog.items
        if "symlink" in item.artifact.artifact.install.modes
    ]
    if len(symlinkable) != 1:
        raise RuntimeError(
            "distribution fixture must expose exactly one symlink-capable marketplace artifact"
        )
    return symlinkable[0].coordinate


def _phase_seed(args: argparse.Namespace) -> dict[str, Any]:
    from agent_artifacts.consumer.model import ConsumerActionRequest

    source_root = Path(args.source_root).resolve()
    project = Path(args.project).resolve()
    home = Path(args.home).resolve()
    runtime_dependencies = _assert_installed_origin(
        args.expected_origin,
        source_root=Path(args.checkout).resolve(),
        environment_root=Path(args.environment_root).resolve(),
    )
    disposition = _configure_and_sync(source_root, home)
    service = _load_service(project, home)
    coordinate = _symlinkable_coordinate(service)
    copied = _apply(
        service,
        ConsumerActionRequest(
            "install", (coordinate,), ("claude",), mode="copy", platform=_platform()
        ),
    )
    linked = _apply(
        service,
        ConsumerActionRequest(
            "install", (coordinate,), ("tabnine",), mode="symlink", platform=_platform()
        ),
    )
    destination, target = _symlink_receipt(service)
    return {
        "source_sync": disposition,
        "initial_copy": sum(item.status == "changed" for item in copied.items),
        "initial_symlink": sum(item.status == "changed" for item in linked.items),
        "runtime_dependencies": runtime_dependencies,
        "symlink_destination": destination,
        "symlink_target": target,
    }


def _phase_resume(args: argparse.Namespace) -> dict[str, Any]:
    from agent_artifacts.consumer.model import ConsumerActionRequest
    from agent_artifacts.domain.identifiers import ArtifactCoordinate

    project = Path(args.project).resolve()
    home = Path(args.home).resolve()
    runtime_dependencies = _assert_installed_origin(
        args.expected_origin,
        source_root=Path(args.checkout).resolve(),
        environment_root=Path(args.environment_root).resolve(),
    )
    service = _load_service(project, home)
    coordinate = _symlinkable_coordinate(service)
    unversioned = ArtifactCoordinate(coordinate.source, coordinate.artifact)
    current = _apply(
        service,
        ConsumerActionRequest("status", (unversioned,), ("claude", "tabnine")),
    )
    removed = _apply(
        service,
        ConsumerActionRequest("uninstall", (unversioned,), ("claude", "tabnine")),
    )
    reinstalled = _apply(
        service,
        ConsumerActionRequest(
            "install", (coordinate,), ("tabnine",), mode="symlink", platform=_platform()
        ),
    )
    destination, target = _symlink_receipt(service)
    return {
        "resumed_current": sum(item.status == "current" for item in current.items),
        "removed": sum(item.status == "removed" for item in removed.items),
        "reinstalled_symlink": sum(item.status == "changed" for item in reinstalled.items),
        "runtime_dependencies": runtime_dependencies,
        "symlink_destination": destination,
        "symlink_target": target,
    }


def _run(
    argv: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {argv!r}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def _environment_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _environment_script(root: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return root / ("Scripts" if os.name == "nt" else "bin") / f"{name}{suffix}"


def _make_environment(root: Path) -> Path:
    venv.EnvBuilder(with_pip=True, system_site_packages=True).create(root)
    python = _environment_python(root)
    if not python.is_file():
        raise RuntimeError(f"virtual environment Python is missing: {python}")
    return python


def _load_packaging_check(source_root: Path):
    path = source_root / "scripts" / "packaging_check.py"
    spec = importlib.util.spec_from_file_location("_aart_distribution_packaging", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load packaging helper: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_local_wheel(source_root: Path, workspace: Path) -> Path:
    packaging = _load_packaging_check(source_root)
    source_copy = workspace / "build-source"
    wheel_dir = workspace / "wheel"
    source_copy.mkdir()
    wheel_dir.mkdir()
    packaging._copy_project(source_root, source_copy)
    packaging._build_wheel(source_copy, wheel_dir)
    wheels = tuple(wheel_dir.glob("agent_artifacts-*-py3-none-any.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected one local wheel, found {wheels}")
    packaging._validate_wheel(wheels[0], workspace / "wheel-inspection")
    return wheels[0]


def _phase_command(
    python: Path,
    script: Path,
    phase: str,
    *,
    source: Path,
    project: Path,
    home: Path,
    checkout: Path,
    environment_root: Path,
    expected_origin: str,
) -> list[str]:
    return [
        str(python),
        str(script),
        "--phase",
        phase,
        "--source-root",
        str(source),
        "--project",
        str(project),
        "--home",
        str(home),
        "--checkout",
        str(checkout),
        "--environment-root",
        str(environment_root),
        "--expected-origin",
        expected_origin,
    ]


def _parse_phase(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"distribution phase did not return JSON: {completed.stdout!r}"
        ) from error
    if not isinstance(value, dict):
        raise RuntimeError("distribution phase receipt must be an object")
    return value


def _survives_environment_removal(environment: Path, destination: str, target: str) -> bool:
    shutil.rmtree(environment)
    link = Path(destination)
    return link.is_symlink() and Path(target).is_dir() and link.resolve() == Path(target).resolve()


def run_smoke(source_root: Path) -> dict[str, Any]:
    """Run the complete local distribution lifecycle and return a stable receipt."""

    source_root = source_root.resolve()
    script = source_root / "scripts" / "distribution_smoke.py"
    fixture = source_root / "tests" / "fixtures" / "protocol" / "native-source-v1"
    with tempfile.TemporaryDirectory(prefix="aart-distribution-") as raw:
        workspace = Path(raw).resolve()
        outside = workspace / "outside-checkout"
        project = workspace / "consumer-project"
        home = workspace / "user-home"
        source = workspace / "native-source"
        editable_environment = workspace / "editable-environment"
        wheel_environment = workspace / "wheel-environment"
        for directory in (outside, project, home):
            directory.mkdir()
        shutil.copytree(fixture, source)
        wheel = _build_local_wheel(source_root, workspace)
        environment = os.environ.copy()
        environment.pop("PYTHONHOME", None)
        environment.pop("PYTHONPATH", None)
        environment.update(
            {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(workspace / "xdg-config"),
                "XDG_DATA_HOME": str(workspace / "xdg-data"),
                "XDG_CACHE_HOME": str(workspace / "xdg-cache"),
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PIP_NO_INDEX": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )

        editable_python = _make_environment(editable_environment)
        _run(
            [
                str(editable_python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                "--no-build-isolation",
                "--editable",
                str(source_root),
            ],
            cwd=outside,
            environment=environment,
        )
        _run(
            [str(_environment_script(editable_environment, "aart")), "--version"],
            cwd=outside,
            environment=environment,
        )
        seed = _parse_phase(
            _run(
                _phase_command(
                    editable_python,
                    script,
                    "seed",
                    source=source,
                    project=project,
                    home=home,
                    checkout=source_root,
                    environment_root=editable_environment,
                    expected_origin="editable",
                ),
                cwd=outside,
                environment=environment,
            )
        )
        survived_editable = _survives_environment_removal(
            editable_environment,
            seed["symlink_destination"],
            seed["symlink_target"],
        )

        wheel_python = _make_environment(wheel_environment)
        _run(
            [
                str(wheel_python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                str(wheel),
            ],
            cwd=outside,
            environment=environment,
        )
        aart = _environment_script(wheel_environment, "aart")
        _run([str(aart), "--version"], cwd=outside, environment=environment)
        upgrade = _run(
            [str(aart), "upgrade", "--wheel", str(wheel), "--dry-run"],
            cwd=outside,
            environment=environment,
        )
        upgrade_dry_run = (
            "--no-index" in upgrade.stdout
            and "--no-deps" in upgrade.stdout
            and str(wheel) in upgrade.stdout
            and "pypi" not in upgrade.stdout.casefold()
        )
        resumed = _parse_phase(
            _run(
                _phase_command(
                    wheel_python,
                    script,
                    "resume",
                    source=source,
                    project=project,
                    home=home,
                    checkout=source_root,
                    environment_root=wheel_environment,
                    expected_origin="wheel",
                ),
                cwd=outside,
                environment=environment,
            )
        )
        survived_wheel = _survives_environment_removal(
            wheel_environment,
            resumed["symlink_destination"],
            resumed["symlink_target"],
        )
        if seed["runtime_dependencies"] != resumed["runtime_dependencies"]:
            raise RuntimeError("editable and wheel dependency metadata disagree")
        return {
            "schema_version": 1,
            "source_sync": seed["source_sync"],
            "initial_copy": seed["initial_copy"],
            "initial_symlink": seed["initial_symlink"],
            "resumed_current": resumed["resumed_current"],
            "removed": resumed["removed"],
            "reinstalled_symlink": resumed["reinstalled_symlink"],
            "survived_editable_removal": survived_editable,
            "survived_wheel_removal": survived_wheel,
            "runtime_dependencies": seed["runtime_dependencies"],
            "upgrade_dry_run": upgrade_dry_run,
            "symlink_target": resumed["symlink_target"],
            "editable_environment": str(editable_environment),
            "wheel_environment": str(wheel_environment),
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("seed", "resume"))
    parser.add_argument("--source-root")
    parser.add_argument("--project")
    parser.add_argument("--home")
    parser.add_argument("--checkout")
    parser.add_argument("--environment-root")
    parser.add_argument("--expected-origin", choices=("editable", "wheel"))
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.phase is None:
        receipt = run_smoke(Path(__file__).resolve().parent.parent)
    else:
        required = (
            args.source_root,
            args.project,
            args.home,
            args.checkout,
            args.environment_root,
            args.expected_origin,
        )
        if any(value is None for value in required):
            raise SystemExit("phase mode requires all path and origin arguments")
        receipt = _phase_seed(args) if args.phase == "seed" else _phase_resume(args)
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
