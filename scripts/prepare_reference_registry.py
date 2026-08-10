#!/usr/bin/env python3
"""Create a fresh, audited reference-registry tree from one committed AART revision."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_artifacts import cli  # noqa: E402
from agent_artifacts.domain.identifiers import ArtifactIdentity, SourceId  # noqa: E402
from agent_artifacts.domain.result import Err  # noqa: E402
from agent_artifacts.registry_publication import (  # noqa: E402
    PublicRegistryPolicy,
    audit_public_registry_tree,
    read_public_registry_tree,
)

SOURCE_REPOSITORY = "https://github.com/M1F1/agent-artifacts.git"
TARGET_REPOSITORY = "M1F1/agent-artifacts-registry"
EXPECTED_ARTIFACTS = (
    ArtifactIdentity("guideline", "python-style"),
    ArtifactIdentity("hook", "block-secrets"),
    ArtifactIdentity("mcp", "atlassian"),
    ArtifactIdentity("mcp", "postgres"),
    ArtifactIdentity("mcp", "tabnine-postgres"),
    ArtifactIdentity("memory", "house"),
    ArtifactIdentity("memory", "superpowers"),
    ArtifactIdentity("skill", "agent-artifacts"),
    ArtifactIdentity("skill", "author-aart-installer"),
    ArtifactIdentity("skill", "code-review"),
)
EXPECTED_COLLECTIONS = ("backend", "base")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compile only one committed AART catalog revision into an audited fresh public "
            "reference-registry tree. This command never creates or pushes a remote."
        )
    )
    parser.add_argument("--source-checkout", required=True, metavar="DIR")
    parser.add_argument("--source-commit", required=True, metavar="40-HEX")
    parser.add_argument("--destination", required=True, metavar="EMPTY-DIR")
    parser.add_argument("--json", action="store_true")
    return parser


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *arguments),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _resolved_commit(source: Path, requested: str) -> str:
    if len(requested) != 40 or any(character not in "0123456789abcdef" for character in requested):
        raise ValueError("--source-commit must be exactly 40 lowercase hexadecimal characters")
    remote = _git(source, "remote", "get-url", "origin")
    if remote.returncode or remote.stdout.strip().removesuffix(
        ".git"
    ) != SOURCE_REPOSITORY.removesuffix(".git"):
        raise ValueError("--source-checkout origin is not the approved public AART repository")
    result = _git(source, "rev-parse", "--verify", f"{requested}^{{commit}}")
    if result.returncode or result.stdout.strip() != requested:
        raise ValueError("--source-commit is not an exact commit in --source-checkout")
    return requested


def _prepare_destination(source: Path, destination: Path) -> None:
    source_real = source.resolve(strict=True)
    destination_parent = destination.parent.resolve(strict=True)
    destination_real = destination_parent / destination.name
    if destination_real == source_real or source_real in destination_real.parents:
        raise ValueError("--destination must be outside the source checkout")
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir() or any(destination.iterdir()):
            raise ValueError("--destination must not exist or must be an empty real directory")
    else:
        destination.mkdir(mode=0o700)
    initialized = subprocess.run(
        ("git", "-c", "core.hooksPath=/dev/null", "init", "-q", "-b", "main", str(destination)),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if initialized.returncode:
        raise ValueError("cannot initialize the fresh destination Git repository")


def _aart(*arguments: str) -> None:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = cli.main(list(arguments))
    if code:
        detail = output.getvalue().strip()
        raise ValueError(detail or f"AART command failed: {' '.join(arguments[:2])}")


def _write_repository_files(destination: Path, policy: PublicRegistryPolicy) -> None:
    for relative, content, executable in policy.repository_files:
        target = destination.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(content)
        target.chmod(0o700 if executable else 0o600)


def _export(source: Path, commit: str, destination: Path) -> dict[str, object]:
    policy = PublicRegistryPolicy(
        SourceId("reference-registry"),
        TARGET_REPOSITORY,
        SOURCE_REPOSITORY,
        commit,
        EXPECTED_ARTIFACTS,
        EXPECTED_COLLECTIONS,
        ("MIT",),
    )
    migration = (
        "registry",
        "migrate",
        "--legacy-source",
        str(source),
        "--origin-url",
        SOURCE_REPOSITORY,
        "--ref",
        commit,
        "--source",
        str(destination),
        "--source-id",
        policy.registry_id.value,
        "--display-name",
        "AART Reference Registry",
        "--artifact-version",
        "1.0.0",
        "--license",
        "MIT",
        "--profile",
        "claude",
        "--profile",
        "opencode",
        "--profile",
        "tabnine",
        "--profile",
        "vibe",
        "--platform",
        "darwin",
        "--platform",
        "linux",
        "--apply",
        "--json",
    )
    _aart(*migration)
    _write_repository_files(destination, policy)
    _aart("registry", "format", "--source", str(destination), "--json")
    _aart("registry", "lock", "--source", str(destination), "--json")
    _aart("registry", "build", "--source", str(destination), "--json")
    for arguments in (
        ("registry", "format", "--source", str(destination), "--check", "--json"),
        (
            "registry",
            "validate",
            "--source",
            str(destination),
            "--strict",
            "--frozen",
            "--json",
        ),
        ("registry", "lock", "--source", str(destination), "--check", "--json"),
        ("registry", "build", "--source", str(destination), "--check", "--json"),
        ("registry", "audit", "--source", str(destination), "--json"),
        ("registry", "test", "--source", str(destination), "--json"),
    ):
        _aart(*arguments)
    snapshot = read_public_registry_tree(str(destination))
    if isinstance(snapshot, Err):
        raise ValueError(snapshot.diagnostics[0].message)
    audited = audit_public_registry_tree(snapshot.value, policy)
    if isinstance(audited, Err):
        raise ValueError(audited.diagnostics[0].message)
    receipt = audited.value
    return {
        "artifact_count": receipt.artifact_count,
        "collection_count": receipt.collection_count,
        "file_count": receipt.file_count,
        "source_commit": receipt.source_commit,
        "target_repository": TARGET_REPOSITORY,
        "tree_digest": str(receipt.tree_digest),
    }


def main(argv: tuple[str, ...] | None = None) -> int:
    arguments = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        source = Path(os.path.abspath(arguments.source_checkout))
        destination = Path(os.path.abspath(arguments.destination))
        commit = _resolved_commit(source, arguments.source_commit)
        _prepare_destination(source, destination)
        receipt = _export(source, commit, destination)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        print(f"reference-registry export failed: {error}", file=sys.stderr)
        return 1
    if arguments.json:
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    else:
        print(
            "reference-registry export passed: "
            f"{receipt['artifact_count']} artifacts, {receipt['collection_count']} collections, "
            f"{receipt['tree_digest']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
