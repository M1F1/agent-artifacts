"""Fail-closed public boundary for deterministic reference-registry exports."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ArtifactIdentity, ObjectDigest, SourceId
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.native_schema import (
    parse_artifact_manifest,
    parse_collection_manifest,
    parse_provenance,
    parse_source_manifest,
)
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.protocol.registry_schema import (
    parse_registry_index,
    parse_registry_lock,
    parse_registry_manifest,
)
from agent_artifacts.registry_commands.templates import (
    REGISTRY_CI_WORKFLOW,
    REPORTING_TEMPLATES,
)
from agent_artifacts.sources.model import source_snapshot_digest

PUBLICATION_INVALID = DiagnosticCode("public-registry-invalid")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SPDX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+() -]{0,99}$")
_PUBLIC_GITHUB_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git$")
_MAX_FILES = 100_000
_MAX_FILE_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_BYTES = 256 * 1024 * 1024
_FORBIDDEN_PARTS = frozenset(
    {
        ".DS_Store",
        ".coverage",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "usage-dashboard",
    }
)
_SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"ASIA[0-9A-Z]{16}"),
    re.compile(rb"xox[baprs]-[A-Za-z0-9-]{16,}"),
)
_PRIVATE_PATTERNS = (
    re.compile(rb"/(?:Users|home)/[A-Za-z0-9._-]+/"),
    re.compile(rb"[A-Za-z]:\\Users\\[A-Za-z0-9._-]+\\"),
    re.compile(rb"file:///"),
    re.compile(rb"https?://(?:localhost|127\.0\.0\.1)(?=[:/\s\"'])", re.IGNORECASE),
    re.compile(rb"https?://[^/\s\"']+\.(?:internal|corp)(?=[:/\s\"'])", re.IGNORECASE),
)

LICENSE_TEXT = b"""MIT License

Copyright (c) 2026 Michal

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the \"Software\"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


def _error(message: str) -> Err:
    return Err((Diagnostic(PUBLICATION_INVALID, Severity.ERROR, message),))


def _source_web_url(repository: str) -> str:
    return repository.removesuffix(".git")


@dataclass(frozen=True, slots=True)
class PublicRegistryPolicy:
    """Exact, reviewable facts allowed to cross the public-repository boundary."""

    registry_id: SourceId
    target_repository: str
    source_repository: str
    source_commit: str
    artifacts: tuple[ArtifactIdentity, ...]
    collections: tuple[str, ...]
    accepted_licenses: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.registry_id, SourceId)
            or _REPOSITORY_RE.fullmatch(self.target_repository) is None
            or _PUBLIC_GITHUB_RE.fullmatch(self.source_repository) is None
            or _COMMIT_RE.fullmatch(self.source_commit) is None
            or not self.artifacts
            or len(set(self.artifacts)) != len(self.artifacts)
            or len(set(self.collections)) != len(self.collections)
            or any(not name or "/" in name or name != name.strip() for name in self.collections)
            or not self.accepted_licenses
            or any(_SPDX_RE.fullmatch(value) is None for value in self.accepted_licenses)
        ):
            raise ValueError("public registry policy is invalid")
        object.__setattr__(self, "artifacts", tuple(sorted(self.artifacts, key=str)))
        object.__setattr__(self, "collections", tuple(sorted(self.collections)))
        object.__setattr__(self, "accepted_licenses", tuple(sorted(set(self.accepted_licenses))))

    @property
    def repository_files(self) -> tuple[tuple[str, bytes, bool], ...]:
        source_web = _source_web_url(self.source_repository)
        target_web = f"https://github.com/{self.target_repository}"
        readme = f"""# AART Reference Registry

Public, version-independent [`{self.target_repository}`]({target_web}) registry compiled by
[AART]({source_web}) from the reviewed source commit
[`{self.source_commit}`]({source_web}/commit/{self.source_commit}).

Install or subscribe to this registry with AART. Treat its manifests, provenance, lock, and
compiled index as the source of truth; do not edit generated lock/index files by hand.

Every artifact declares its own license. Security evidence describes installation risk and never
constitutes a guarantee that an artifact is safe.
""".encode()
        security = b"""# Security

Do not report credentials, private repository locations, user paths, logs, or confidential
artifacts in public issues. Report vulnerabilities through GitHub's private security-advisory
channel for this repository.

AART's deterministic checks and optional analyzers provide bounded evidence, not a safety
certificate. Review artifact content, provenance, setup effects, and policy before installation.
"""
        ignored = b""".coverage
.mypy_cache/
.pytest_cache/
.ruff_cache/
__pycache__/
build/
dist/
htmlcov/
usage-dashboard/
"""
        files = (
            (".gitignore", ignored, False),
            ("LICENSE", LICENSE_TEXT, False),
            ("README.md", readme, False),
            ("SECURITY.md", security, False),
            (".github/workflows/aart-registry.yml", REGISTRY_CI_WORKFLOW, False),
            *((path, content, False) for path, content in REPORTING_TEMPLATES),
        )
        return tuple(sorted(files, key=lambda item: item[0]))


@dataclass(frozen=True, slots=True)
class PublicRegistryAudit:
    tree_digest: ObjectDigest
    file_count: int
    artifact_count: int
    collection_count: int
    source_commit: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.tree_digest, ObjectDigest)
            or self.file_count <= 0
            or self.artifact_count <= 0
            or self.collection_count < 0
            or _COMMIT_RE.fullmatch(self.source_commit) is None
        ):
            raise ValueError("public registry audit receipt is invalid")


def _legacy_origin_path(identity: ArtifactIdentity) -> str:
    if identity.kind == "guideline":
        return f"guidelines/{identity.name}.md"
    if identity.kind == "memory":
        return f"memory/{identity.name}.md"
    if identity.kind == "mcp":
        return f"mcp/{identity.name}"
    return f"{identity.kind}s/{identity.name}"


def _allowed_file(path: str, policy: PublicRegistryPolicy) -> bool:
    metadata = {item[0] for item in policy.repository_files}
    if path in metadata | {
        "aart-registry.json",
        "aart-source.json",
        "aart.lock.json",
        "aart.index.json",
    }:
        return True
    if path.startswith("collections/") and path.endswith(".json"):
        return path.removeprefix("collections/").removesuffix(".json") in policy.collections
    for identity in policy.artifacts:
        base = f"artifacts/{identity.kind}/{identity.name}/"
        if not path.startswith(base):
            continue
        relative = path.removeprefix(base)
        return relative in {"artifact.json", "provenance.json"} or relative.startswith(
            ("payload/", "setup/")
        )
    return False


def _file_map(snapshot: SourceSnapshot) -> Result[dict[str, SnapshotEntry]]:
    digest = source_snapshot_digest(snapshot)
    if isinstance(digest, Err):
        return _error("public tree contains a link, special file, duplicate, or unsafe path")
    files: dict[str, SnapshotEntry] = {}
    total = 0
    for entry in snapshot.entries:
        if entry.kind is SnapshotEntryKind.DIRECTORY:
            continue
        if entry.kind is not SnapshotEntryKind.FILE:
            return _error(f"public tree contains forbidden {entry.kind.value}: {entry.path}")
        if len(entry.content) > _MAX_FILE_BYTES:
            return _error(f"public file exceeds size bound: {entry.path}")
        total += len(entry.content)
        if total > _MAX_TOTAL_BYTES:
            return _error("public tree exceeds total-size bound")
        files[str(entry.path)] = entry
    if not files or len(files) > _MAX_FILES:
        return _error("public tree file count is outside the safety bound")
    return Ok(files)


def _required_file(files: dict[str, SnapshotEntry], path: str) -> Result[bytes]:
    entry = files.get(path)
    if entry is None:
        return _error(f"public tree is missing required file: {path}")
    return Ok(entry.content)


def _scan_content(path: str, content: bytes) -> Result[None]:
    if b"\0" in content:
        return _error(f"public tree contains non-text content: {path}")
    try:
        content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return _error(f"public tree contains non-UTF-8 content: {path}")
    if any(pattern.search(content) is not None for pattern in _SECRET_PATTERNS):
        return _error(f"public tree contains credential-like content: {path}")
    if any(pattern.search(content) is not None for pattern in _PRIVATE_PATTERNS):
        return _error(f"public tree contains a private path or endpoint: {path}")
    return Ok(None)


def _parse_roots(files: dict[str, SnapshotEntry], policy: PublicRegistryPolicy) -> Result[None]:
    registry_bytes = _required_file(files, "aart-registry.json")
    source_bytes = _required_file(files, "aart-source.json")
    lock_bytes = _required_file(files, "aart.lock.json")
    index_bytes = _required_file(files, "aart.index.json")
    if isinstance(registry_bytes, Err):
        return registry_bytes
    if isinstance(source_bytes, Err):
        return source_bytes
    if isinstance(lock_bytes, Err):
        return lock_bytes
    if isinstance(index_bytes, Err):
        return index_bytes
    registry = parse_registry_manifest(registry_bytes.value)
    source = parse_source_manifest(source_bytes.value)
    lock = parse_registry_lock(lock_bytes.value)
    index = parse_registry_index(index_bytes.value)
    if (
        isinstance(registry, Err)
        or isinstance(source, Err)
        or isinstance(lock, Err)
        or isinstance(index, Err)
    ):
        return _error("public tree contains an invalid registry root document")
    if (
        registry.value.registry_id != policy.registry_id
        or source.value.source_id != policy.registry_id
        or index.value.registry_id != policy.registry_id
        or registry.value.display_name != "AART Reference Registry"
        or source.value.display_name != "AART Reference Registry"
        or registry.value.default_channel != "main"
        or registry.value.services
        or source.value.required_capabilities
        or tuple(str(item) for item in source.value.artifact_roots) != ("artifacts",)
        or tuple(str(item) for item in source.value.collection_roots) != ("collections",)
    ):
        return _error("public tree registry identity differs from the approved policy")
    return Ok(None)


def _audit_artifacts(files: dict[str, SnapshotEntry], policy: PublicRegistryPolicy) -> Result[int]:
    found: list[ArtifactIdentity] = []
    for path in sorted(files):
        if not path.startswith("artifacts/") or not path.endswith("/artifact.json"):
            continue
        manifest = parse_artifact_manifest(files[path].content, path=path)
        if isinstance(manifest, Err):
            return _error(f"public tree contains an invalid artifact manifest: {path}")
        identity = manifest.value.identity
        found.append(identity)
        if manifest.value.license not in policy.accepted_licenses:
            return _error(f"artifact license is absent or not approved: {identity}")
        base = path.removesuffix("/artifact.json")
        provenance_path = f"{base}/provenance.json"
        provenance_entry = files.get(provenance_path)
        if provenance_entry is None:
            return _error(f"artifact provenance is missing: {identity}")
        provenance = parse_provenance(provenance_entry.content, path=provenance_path)
        if isinstance(provenance, Err):
            return _error(f"artifact provenance is invalid: {identity}")
        if provenance.value.origin.url != policy.source_repository:
            return _error(f"artifact provenance source repository is not approved: {identity}")
        if provenance.value.origin.resolved_commit != policy.source_commit:
            return _error(f"artifact provenance source commit is not approved: {identity}")
        if str(provenance.value.origin.path) != _legacy_origin_path(identity):
            return _error(f"artifact provenance source path is not approved: {identity}")
        payload_prefix = f"{base}/{manifest.value.payload.root}/"
        if not any(candidate.startswith(payload_prefix) for candidate in files):
            return _error(f"artifact payload is empty: {identity}")
    if tuple(sorted(found, key=str)) != policy.artifacts:
        return _error("public tree artifact identities differ from the approved allowlist")
    return Ok(len(found))


def _audit_collections(
    files: dict[str, SnapshotEntry], policy: PublicRegistryPolicy
) -> Result[int]:
    found: list[str] = []
    expected_artifacts = set(policy.artifacts)
    expected_collections = set(policy.collections)
    for path in sorted(files):
        if not path.startswith("collections/") or not path.endswith(".json"):
            continue
        collection = parse_collection_manifest(files[path].content, path=path)
        if isinstance(collection, Err):
            return _error(f"public tree contains an invalid collection manifest: {path}")
        expected_name = path.removeprefix("collections/").removesuffix(".json")
        if collection.value.name != expected_name:
            return _error(f"collection identity differs from its path: {path}")
        if any(
            item.identity not in expected_artifacts for item in collection.value.artifacts
        ) or any(item not in expected_collections for item in collection.value.collections):
            return _error(f"collection contains a non-allowlisted reference: {expected_name}")
        found.append(collection.value.name)
    if tuple(sorted(found)) != policy.collections:
        return _error("public tree collection identities differ from the approved allowlist")
    return Ok(len(found))


def audit_public_registry_tree(
    snapshot: SourceSnapshot, policy: PublicRegistryPolicy
) -> Result[PublicRegistryAudit]:
    """Audit every publishable byte against an exact public policy."""

    files_result = _file_map(snapshot)
    if isinstance(files_result, Err):
        return files_result
    files = files_result.value
    for path, entry in sorted(files.items()):
        if any(part in _FORBIDDEN_PARTS or part.endswith(".pyc") for part in path.split("/")):
            return _error(f"public tree contains a generated/cache path: {path}")
        if not _allowed_file(path, policy):
            return _error(f"public tree path is not allowlisted: {path}")
        scanned = _scan_content(path, entry.content)
        if isinstance(scanned, Err):
            return scanned
    for path, expected, executable in policy.repository_files:
        actual = files.get(path)
        if actual is None or actual.content != expected or actual.executable != executable:
            return _error(
                f"public repository metadata or CI differs from the approved bytes: {path}"
            )
    roots = _parse_roots(files, policy)
    if isinstance(roots, Err):
        return roots
    artifacts = _audit_artifacts(files, policy)
    if isinstance(artifacts, Err):
        return artifacts
    collections = _audit_collections(files, policy)
    if isinstance(collections, Err):
        return collections
    digest = source_snapshot_digest(snapshot)
    assert isinstance(digest, Ok)
    return Ok(
        PublicRegistryAudit(
            digest.value,
            len(files),
            artifacts.value,
            collections.value,
            policy.source_commit,
        )
    )


def read_public_registry_tree(root: str) -> Result[SourceSnapshot]:
    """Read a complete candidate tree without following links; omit only Git metadata."""

    if not os.path.isabs(root) or os.path.normpath(root) != root:
        return _error("public tree root must be normalized and absolute")
    root_path = Path(root)
    try:
        root_status = os.stat(root_path, follow_symlinks=False)
    except OSError as error:
        return _error(f"cannot inspect public tree root: {error}")
    if not stat.S_ISDIR(root_status.st_mode) or root_path.is_symlink():
        return _error("public tree root must be a real directory")
    entries: list[SnapshotEntry] = []
    total = 0
    try:
        for directory, children, filenames in os.walk(root_path, topdown=True, followlinks=False):
            relative_directory = Path(directory).relative_to(root_path).as_posix()
            relative_directory = "" if relative_directory == "." else relative_directory
            children[:] = sorted(child for child in children if child != ".git")
            for child in children:
                relative = child if not relative_directory else f"{relative_directory}/{child}"
                parsed = parse_relative_path(relative)
                if isinstance(parsed, Err):
                    return _error(f"public tree path is unsafe: {relative!r}")
                mode = os.stat(Path(directory) / child, follow_symlinks=False).st_mode
                kind = (
                    SnapshotEntryKind.SYMLINK
                    if stat.S_ISLNK(mode)
                    else SnapshotEntryKind.DIRECTORY
                    if stat.S_ISDIR(mode)
                    else SnapshotEntryKind.SPECIAL
                )
                entries.append(SnapshotEntry(parsed.value, kind))
            for filename in sorted(filenames):
                relative = (
                    filename if not relative_directory else f"{relative_directory}/{filename}"
                )
                parsed = parse_relative_path(relative)
                if isinstance(parsed, Err):
                    return _error(f"public tree path is unsafe: {relative!r}")
                target = Path(directory) / filename
                status = os.stat(target, follow_symlinks=False)
                if stat.S_ISLNK(status.st_mode):
                    entries.append(SnapshotEntry(parsed.value, SnapshotEntryKind.SYMLINK))
                    continue
                if not stat.S_ISREG(status.st_mode):
                    entries.append(SnapshotEntry(parsed.value, SnapshotEntryKind.SPECIAL))
                    continue
                if status.st_size > _MAX_FILE_BYTES:
                    return _error(f"public file exceeds size bound: {relative}")
                descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                with os.fdopen(descriptor, "rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if (
                        not stat.S_ISREG(opened.st_mode)
                        or opened.st_dev != status.st_dev
                        or opened.st_ino != status.st_ino
                        or opened.st_size != status.st_size
                        or opened.st_mtime_ns != status.st_mtime_ns
                    ):
                        return _error(f"public file changed while being opened: {relative}")
                    content = stream.read(_MAX_FILE_BYTES + 1)
                    completed = os.fstat(stream.fileno())
                if (
                    len(content) != opened.st_size
                    or completed.st_size != opened.st_size
                    or completed.st_mtime_ns != opened.st_mtime_ns
                ):
                    return _error(f"public file changed while being read: {relative}")
                total += len(content)
                if total > _MAX_TOTAL_BYTES:
                    return _error("public tree exceeds total-size bound")
                entries.append(
                    SnapshotEntry(
                        parsed.value,
                        SnapshotEntryKind.FILE,
                        content,
                        bool(opened.st_mode & 0o111),
                    )
                )
                if len(entries) > _MAX_FILES:
                    return _error("public tree exceeds entry-count bound")
    except OSError as error:
        return _error(f"cannot read public tree safely: {error}")
    return Ok(SourceSnapshot(SnapshotOrigin.LOCAL, tuple(entries)))
