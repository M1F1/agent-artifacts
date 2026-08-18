#!/usr/bin/env python3
"""Fail-closed AART release checklist and schema-freeze generator."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
# The release series this checklist governs.  REL01's `1.0.0` evidence is immutable: its
# schema freeze, checklist, and release notes are never regenerated or edited.  A new release
# series adds its own contract here and its own versioned documents beside the frozen ones.
EXPECTED_VERSION = "2.7.1"
RELEASE_CONTRACT_VERSION = 17
REFERENCE_REGISTRY_ORIGIN = "https://github.com/M1F1/agent-artifacts-registry"
SCHEMA_FREEZE_PATH = f"docs/release/schema-freeze-v{RELEASE_CONTRACT_VERSION}.json"
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SCHEMA_INPUTS = (
    "agent_artifacts/configuration/schema.py",
    "agent_artifacts/domain/outcomes.py",
    "agent_artifacts/install_state/schema.py",
    "agent_artifacts/protocol/capabilities.py",
    "agent_artifacts/protocol/native_models.py",
    "agent_artifacts/protocol/native_schema.py",
    "agent_artifacts/protocol/registry_models.py",
    "agent_artifacts/protocol/registry_schema.py",
    "agent_artifacts/reporting/schema.py",
    "agent_artifacts/security/analyzers.py",
    "agent_artifacts/security/attestation_schema.py",
    "agent_artifacts/security/schema.py",
    "agent_artifacts/setup.py",
    "docs/protocol/native-source-v1.md",
    "docs/protocol/registry-v1.md",
)
# Documents that must exist *and* name this exact release.
REQUIRED_RELEASE_DOCS = (
    "CHANGELOG.md",
    f"docs/release/compatibility-v{RELEASE_CONTRACT_VERSION}.md",
    f"docs/release/release-checklist-v{RELEASE_CONTRACT_VERSION}.md",
    f"docs/release/github-release-v{EXPECTED_VERSION}.md",
)
# Documents that stay shipped and referenced across release series.  They are still gated — a
# release must not silently drop the 0.1.x migration guide or the onboarding tutorials — but they
# describe an earlier boundary and are not expected to name the current version.
REQUIRED_PERSISTENT_DOCS = (
    "docs/release/migration-v1.md",
    "docs/tutorials/direct-source-v1.md",
    "docs/tutorials/company-registry-v1.md",
    "docs/tutorials/vendoring-v1.md",
)
RELEASE_CHECKS = (
    "repository",
    "schema-freeze",
    "system-matrix",
    "package",
    "registry-origin",
    "registry-format",
    "registry-validate",
    "registry-lock",
    "registry-build",
    "registry-audit",
    "registry-compatibility",
)
REGISTRY_CONTENT_CHECKS = RELEASE_CHECKS[5:]
PROTOCOL_VERSIONS = {
    "artifact_manifest": 1,
    "configuration": 1,
    "installation_state": 2,
    "native_source": 1,
    "registry": 1,
    "reporting": 1,
    "security_assessment": 1,
    # Raised for the 2.0.0 series: revision 1 is rejected at parse time rather than carried behind
    # a compatibility branch, so the single supported revision is the one recorded here.
    "setup_recipe": 2,
}

ProcessRunner = Callable[
    [tuple[str, ...], Path, Mapping[str, str], int], subprocess.CompletedProcess[str]
]


@dataclass(frozen=True, order=True)
class ReleaseDiagnostic:
    check: str
    code: str
    message: str

    def to_json(self) -> dict[str, str]:
        return {"check": self.check, "code": self.code, "message": self.message}


@dataclass(frozen=True)
class RegistryEvidence:
    diagnostics: tuple[ReleaseDiagnostic, ...]
    commit: str | None
    content_checks_ran: bool


def _versioning():
    path = ROOT / "scripts" / "version.py"
    spec = importlib.util.spec_from_file_location("_aart_release_version", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load scripts/version.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def schema_freeze_bytes(root: Path = ROOT) -> bytes:
    inputs = [
        {"path": relative, "sha256": _sha256((root / relative).read_bytes())}
        for relative in SCHEMA_INPUTS
    ]
    document = {
        "protocol_versions": PROTOCOL_VERSIONS,
        "release_version": EXPECTED_VERSION,
        "schema_inputs": inputs,
        "schema_version": 1,
    }
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_aart_release_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def wheel_digest(root: Path = ROOT, *, output_dir: Path | None = None) -> tuple[str, str]:
    """Build this commit's wheel in a throwaway copy and return ``(filename, digest)``.

    The published wheel is dated from the commit it was built at, so its digest is a property of
    the tag and cannot be recorded inside the tag: writing it into a tracked file would change the
    commit that determines it.  This command is how the digest reaches the release evidence — run
    it at the tag and publish what it prints beside the artifact
    (``docs/release/wheel-reproducibility-v1.md``).

    ``output_dir`` receives that artifact, and the digest is then read back from the written file:
    what the caller is handed is the file the printed digest describes.  `LAF-75`: the wheel used
    to live in a temporary directory removed before this returned, which left the publisher to
    build a second wheel by another route and attach that one — a *different* file, because a
    build from the checkout carries no commit stamp.  `2.6.0` came within one ``curl`` of
    publishing a digest line that did not describe its own attachment.
    """

    inject = _script("inject_commit")
    packaging = _script("packaging_check")
    with tempfile.TemporaryDirectory(prefix="aart-wheel-digest-") as raw:
        temp_root = Path(raw)
        source_copy = temp_root / "source"
        source_copy.mkdir()
        packaging._copy_project(root, source_copy)
        # The copy has no ``.git``, so the stamp is taken from the real checkout and written in —
        # otherwise this would hash a wheel no release ever publishes.
        (source_copy / "agent_artifacts" / "_commit.py").write_text(
            inject.render(inject.current_commit(), inject.current_commit_epoch()),
            encoding="utf-8",
        )
        subprocess.run(
            [PYTHON, "scripts/build_wheel.py"],
            cwd=source_copy,
            check=True,
            capture_output=True,
        )
        built = tuple((source_copy / "dist").glob("agent_artifacts-*-py3-none-any.whl"))
        if len(built) != 1:
            raise ValueError(f"expected one built wheel, found {built}")
        if output_dir is None:
            return built[0].name, _sha256(built[0].read_bytes())
        output_dir.mkdir(parents=True, exist_ok=True)
        destination = output_dir / built[0].name
        shutil.copyfile(built[0], destination)
        # Hashed from the destination rather than from the source, so a copy that arrived short
        # cannot be described by the digest of the file it was copied from.
        return destination.name, _sha256(destination.read_bytes())


def _environment() -> dict[str, str]:
    environment = {
        "PATH": os.environ.get("PATH", os.defpath),
        "LANG": "C",
        "LC_ALL": "C",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
    }
    for name in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TMPDIR"):
        if name in os.environ:
            environment[name] = os.environ[name]
    return environment


def _run_process(
    command: tuple[str, ...],
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=dict(environment),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def _run(
    runner: ProcessRunner,
    command: tuple[str, ...],
    cwd: Path,
    timeout_seconds: int = 120,
) -> subprocess.CompletedProcess[str] | None:
    try:
        return runner(command, cwd, _environment(), timeout_seconds)
    except (OSError, subprocess.SubprocessError):
        return None


def _diagnostic(check: str, code: str, message: str) -> ReleaseDiagnostic:
    return ReleaseDiagnostic(check, code, message)


def _repository_diagnostics(
    root: Path,
    *,
    process_runner: ProcessRunner,
    require_clean: bool,
    require_main: bool,
) -> tuple[ReleaseDiagnostic, ...]:
    diagnostics: list[ReleaseDiagnostic] = []
    versioning = _versioning()
    try:
        version = versioning.read_version(root)
        if str(version) != EXPECTED_VERSION or not version.stable:
            diagnostics.append(
                _diagnostic(
                    "repository",
                    "version-not-stable",
                    f"release source must be exactly stable {EXPECTED_VERSION}",
                )
            )
    except (OSError, ValueError) as error:
        diagnostics.append(_diagnostic("repository", "version-invalid", str(error)))
    try:
        progress = (root / "PROGRESS.md").read_text(encoding="utf-8")
        incomplete = tuple(
            task for task, status in versioning.task_states(progress) if status != "complete"
        )
        if incomplete:
            diagnostics.append(
                _diagnostic(
                    "repository",
                    "progress-incomplete",
                    "incomplete release tasks: " + ", ".join(incomplete),
                )
            )
    except (OSError, ValueError) as error:
        diagnostics.append(_diagnostic("repository", "progress-invalid", str(error)))
    for relative in REQUIRED_RELEASE_DOCS:
        path = root / relative
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        if EXPECTED_VERSION not in text:
            diagnostics.append(
                _diagnostic(
                    "repository",
                    "release-doc-missing",
                    f"required {EXPECTED_VERSION} release document is missing "
                    f"or incomplete: {relative}",
                )
            )
    for relative in REQUIRED_PERSISTENT_DOCS:
        try:
            carried = (root / relative).read_text(encoding="utf-8").strip()
        except OSError:
            carried = ""
        if not carried:
            diagnostics.append(
                _diagnostic(
                    "repository",
                    "release-doc-missing",
                    f"carried-forward release document is missing or empty: {relative}",
                )
            )
    if require_clean:
        status = _run(
            process_runner,
            ("git", "status", "--porcelain=v1", "--untracked-files=all"),
            root,
            30,
        )
        if status is None or status.returncode != 0:
            diagnostics.append(
                _diagnostic(
                    "repository",
                    "repository-state-unavailable",
                    "cannot prove the release worktree is clean",
                )
            )
        elif status.stdout:
            diagnostics.append(
                _diagnostic(
                    "repository",
                    "repository-dirty",
                    "release worktree contains changed or generated output",
                )
            )
    if require_main:
        main_membership = _run(
            process_runner,
            ("git", "merge-base", "--is-ancestor", "HEAD", "origin/main"),
            root,
            30,
        )
        if main_membership is None or main_membership.returncode != 0:
            diagnostics.append(
                _diagnostic(
                    "repository",
                    "source-not-merged-into-main",
                    "release source commit is not proven to be merged into origin/main",
                )
            )
    return tuple(diagnostics)


def _schema_diagnostics(root: Path) -> tuple[ReleaseDiagnostic, ...]:
    try:
        expected = schema_freeze_bytes(root)
        actual = (root / SCHEMA_FREEZE_PATH).read_bytes()
    except OSError:
        return (
            _diagnostic(
                "schema-freeze",
                "schema-freeze-missing",
                "schema freeze or one of its declared inputs is missing",
            ),
        )
    if actual != expected:
        return (
            _diagnostic(
                "schema-freeze",
                "schema-freeze-stale",
                "schema freeze does not match the normative schema inputs",
            ),
        )
    return ()


def _tool_diagnostics(
    root: Path,
    process_runner: ProcessRunner,
) -> tuple[ReleaseDiagnostic, ...]:
    commands = (
        (
            "system-matrix",
            "system-matrix-failed",
            (PYTHON, "scripts/system_matrix.py", "--json"),
        ),
        (
            "package",
            "release-package-invalid",
            (PYTHON, "scripts/packaging_check.py"),
        ),
    )
    diagnostics: list[ReleaseDiagnostic] = []
    for check, code, command in commands:
        outcome = _run(process_runner, command, root, 180)
        if outcome is None or outcome.returncode != 0:
            diagnostics.append(_diagnostic(check, code, f"{check} release evidence did not pass"))
    return tuple(diagnostics)


def _normalize_origin(raw: str) -> str:
    return raw.strip().removesuffix(".git").removesuffix("/")


def _remote_head_commit(result: subprocess.CompletedProcess[str] | None) -> str | None:
    if result is None or result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] == "HEAD" and GIT_SHA_RE.fullmatch(fields[0]):
            return fields[0]
    return None


def _registry_diagnostics(
    root: Path,
    registry: Path,
    process_runner: ProcessRunner,
) -> RegistryEvidence:
    if registry.is_symlink() or not registry.is_dir():
        return RegistryEvidence(
            (
                _diagnostic(
                    "registry-origin",
                    "registry-path-invalid",
                    "reference registry must be an existing real directory",
                ),
            ),
            None,
            False,
        )
    origin = _run(
        process_runner,
        ("git", "remote", "get-url", "origin"),
        registry,
        30,
    )
    if (
        origin is None
        or origin.returncode != 0
        or _normalize_origin(origin.stdout) != REFERENCE_REGISTRY_ORIGIN
    ):
        return RegistryEvidence(
            (
                _diagnostic(
                    "registry-origin",
                    "registry-origin-invalid",
                    "release registry is not the approved public reference repository",
                ),
            ),
            None,
            False,
        )
    status = _run(
        process_runner,
        ("git", "status", "--porcelain=v1", "--untracked-files=all"),
        registry,
        30,
    )
    if status is None or status.returncode != 0:
        return RegistryEvidence(
            (
                _diagnostic(
                    "registry-origin",
                    "registry-state-unavailable",
                    "cannot prove the reference registry worktree is clean",
                ),
            ),
            None,
            False,
        )
    if status.stdout:
        return RegistryEvidence(
            (
                _diagnostic(
                    "registry-origin",
                    "registry-dirty",
                    "reference registry contains changed or generated output",
                ),
            ),
            None,
            False,
        )
    head = _run(process_runner, ("git", "rev-parse", "HEAD"), registry, 30)
    origin_head = _run(process_runner, ("git", "rev-parse", "origin/HEAD"), registry, 30)
    advertised_head = _remote_head_commit(
        _run(process_runner, ("git", "ls-remote", "--symref", "origin", "HEAD"), registry, 30)
    )
    commit = head.stdout.strip() if head is not None and head.returncode == 0 else None
    expected_commit = (
        origin_head.stdout.strip()
        if origin_head is not None and origin_head.returncode == 0
        else None
    )
    if (
        commit is None
        or expected_commit is None
        or GIT_SHA_RE.fullmatch(commit) is None
        or commit != expected_commit
    ):
        return RegistryEvidence(
            (
                _diagnostic(
                    "registry-origin",
                    "registry-revision-not-current",
                    "reference registry HEAD is not the clean fetched origin/HEAD revision",
                ),
            ),
            commit if commit is not None and GIT_SHA_RE.fullmatch(commit) else None,
            False,
        )
    if advertised_head != commit:
        return RegistryEvidence(
            (
                _diagnostic(
                    "registry-origin",
                    "registry-remote-revision-mismatch",
                    "reference registry HEAD does not match the origin-advertised default revision",
                ),
            ),
            commit,
            False,
        )
    diagnostics: list[ReleaseDiagnostic] = []
    base = (PYTHON, "-m", "agent_artifacts", "registry")
    source = ("--source", str(registry), "--json")
    commands = (
        ("registry-format", "registry-format-stale", (*base, "format", *source, "--check")),
        (
            "registry-validate",
            "registry-incompatible",
            (*base, "validate", *source, "--strict", "--frozen"),
        ),
        ("registry-lock", "registry-lock-stale", (*base, "lock", *source, "--check")),
        ("registry-build", "registry-index-stale", (*base, "build", *source, "--check")),
        ("registry-audit", "registry-audit-failed", (*base, "audit", *source)),
        (
            "registry-compatibility",
            "registry-compatibility-failed",
            (
                *base,
                "test",
                *source,
                "--compatibility",
                "all",
                "--latest-version",
                EXPECTED_VERSION,
            ),
        ),
    )
    for check, code, command in commands:
        outcome = _run(process_runner, command, root, 180)
        if outcome is None or outcome.returncode != 0:
            diagnostics.append(_diagnostic(check, code, f"{check} release evidence did not pass"))
    final_status = _run(
        process_runner,
        ("git", "status", "--porcelain=v1", "--untracked-files=all"),
        registry,
        30,
    )
    if final_status is None or final_status.returncode != 0:
        diagnostics.append(
            _diagnostic(
                "registry-origin",
                "registry-state-unavailable",
                "cannot prove the reference registry worktree stayed clean",
            )
        )
    elif final_status.stdout:
        diagnostics.append(
            _diagnostic(
                "registry-origin",
                "registry-dirty",
                "reference registry changed while release checks ran",
            )
        )
    final_head = _run(process_runner, ("git", "rev-parse", "HEAD"), registry, 30)
    final_origin_head = _run(process_runner, ("git", "rev-parse", "origin/HEAD"), registry, 30)
    final_advertised_head = _remote_head_commit(
        _run(process_runner, ("git", "ls-remote", "--symref", "origin", "HEAD"), registry, 30)
    )
    if (
        final_head is None
        or final_origin_head is None
        or final_head.returncode != 0
        or final_origin_head.returncode != 0
        or final_head.stdout.strip() != commit
        or final_origin_head.stdout.strip() != commit
        or final_advertised_head != commit
    ):
        diagnostics.append(
            _diagnostic(
                "registry-origin",
                "registry-revision-changed",
                "reference registry revision changed while release checks ran",
            )
        )
    return RegistryEvidence(tuple(diagnostics), commit, True)


def check_release(
    root: Path,
    registry: Path,
    *,
    process_runner: ProcessRunner = _run_process,
    require_clean: bool = True,
    require_main: bool = True,
) -> dict[str, Any]:
    before = _repository_diagnostics(
        root,
        process_runner=process_runner,
        require_clean=require_clean,
        require_main=require_main,
    )
    registry_evidence = _registry_diagnostics(root, registry, process_runner)
    after = _repository_diagnostics(
        root,
        process_runner=process_runner,
        require_clean=require_clean,
        require_main=require_main,
    )
    diagnostics = tuple(
        sorted(
            set(
                (
                    *before,
                    *_schema_diagnostics(root),
                    *_tool_diagnostics(root, process_runner),
                    *registry_evidence.diagnostics,
                    *after,
                )
            )
        )
    )
    failed_checks = {item.check for item in diagnostics}
    if not registry_evidence.content_checks_ran:
        failed_checks.update(REGISTRY_CONTENT_CHECKS)
    try:
        version = str(_versioning().read_version(root))
    except (OSError, ValueError):
        version = "unknown"
    return {
        "schema_version": 1,
        "status": "passed" if not diagnostics else "failed",
        "version": version,
        "registry_commit": registry_evidence.commit,
        "checks": [{"name": name, "passed": name not in failed_checks} for name in RELEASE_CHECKS],
        "diagnostics": [item.to_json() for item in diagnostics],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze", help="write exact schema-freeze evidence")
    freeze.add_argument("--write", action="store_true", help="required write acknowledgement")
    digest = commands.add_parser(
        "wheel-digest", help="build the wheel this commit publishes and print its digest"
    )
    digest.add_argument(
        "--output",
        type=Path,
        default=None,
        help="directory the wheel is written into (default: dist/)",
    )
    check = commands.add_parser("check", help="run the complete stable-release checklist")
    check.add_argument("--registry", required=True, type=Path)
    check.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT) -> int:
    args = _parser().parse_args(argv)
    if args.command == "freeze":
        if not args.write:
            print("release error: refusing to write schema freeze without --write", file=sys.stderr)
            return 1
        try:
            content = schema_freeze_bytes(root)
            destination = root / SCHEMA_FREEZE_PATH
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        except OSError as error:
            print(f"release error: cannot write schema freeze: {error}", file=sys.stderr)
            return 1
        print(f"schema freeze written: {SCHEMA_FREEZE_PATH}")
        return 0
    if args.command == "wheel-digest":
        output_dir = args.output if args.output is not None else root / "dist"
        try:
            name, digest = wheel_digest(root, output_dir=output_dir)
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            print(f"release error: cannot build the wheel to digest: {error}", file=sys.stderr)
            return 1
        print(f"{digest}  {name}")
        print(f"wrote {output_dir / name}")
        return 0
    receipt = check_release(root, args.registry)
    if args.json:
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    else:
        for check in receipt["checks"]:
            print(f"{check['name']}: {'passed' if check['passed'] else 'failed'}")
        for diagnostic in receipt["diagnostics"]:
            print(f"{diagnostic['code']}: {diagnostic['message']}", file=sys.stderr)
        print(f"release checklist {receipt['status']}: {receipt['version']}")
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
