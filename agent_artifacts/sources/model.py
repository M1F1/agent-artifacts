"""Frozen source acquisition, snapshot, health, and persistence values."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from enum import Enum

from agent_artifacts.configuration.model import ConfiguredSource, SourceKind
from agent_artifacts.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    Severity,
    sort_diagnostics,
)
from agent_artifacts.domain.identifiers import ObjectDigest, SourceAlias, SourceId
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.hashing import directory_entry, file_entry, json_digest, tree_digest
from agent_artifacts.protocol.json import JsonObject
from agent_artifacts.protocol.native_tree import (
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.protocol.semver import SemVer

_INSTANCE_RE = re.compile(r"^(?:git|local|registry)-[0-9a-f]{32}$")
_HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_SNAPSHOT_LIMITS = (10_000, 10 * 1024 * 1024, 100 * 1024 * 1024, 64)
SOURCE_INVALID = DiagnosticCode("source-invalid")


def _error(message: str) -> Err:
    return Err((Diagnostic(SOURCE_INVALID, Severity.ERROR, message),))


@dataclass(frozen=True, slots=True, order=True)
class SourceInstanceId:
    value: str

    def __post_init__(self) -> None:
        if _INSTANCE_RE.fullmatch(self.value) is None:
            raise ValueError("source instance ID must be a canonical kind/digest value")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SourceStorePaths:
    root: str
    mirror: str
    snapshots: str
    current_file: str
    lock_directory: str
    temporary_root: str

    def __post_init__(self) -> None:
        for value in (
            self.root,
            self.mirror,
            self.snapshots,
            self.current_file,
            self.lock_directory,
            self.temporary_root,
        ):
            if not posixpath.isabs(value) or posixpath.normpath(value) != value:
                raise ValueError("source store paths must be normalized and absolute")


@dataclass(frozen=True, slots=True)
class SnapshotLimits:
    max_files: int = 10_000
    max_file_bytes: int = 10 * 1024 * 1024
    max_total_bytes: int = 100 * 1024 * 1024
    max_depth: int = 64

    def __post_init__(self) -> None:
        values = (
            self.max_files,
            self.max_file_bytes,
            self.max_total_bytes,
            self.max_depth,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in values
        ) or any(
            value > maximum for value, maximum in zip(values, _MAX_SNAPSHOT_LIMITS, strict=True)
        ):
            raise ValueError("snapshot limits must be positive integers within hard safety bounds")


_INSTANCE_PREFIX = {
    SourceKind.REGISTRY_GIT: "registry",
    SourceKind.SOURCE_GIT: "git",
    SourceKind.SOURCE_LOCAL: "local",
}


def _instance_id(source: ConfiguredSource, fields: tuple[tuple[str, str], ...]) -> SourceInstanceId:
    digest = json_digest(JsonObject(fields))
    return SourceInstanceId(f"{_INSTANCE_PREFIX[source.kind]}-{digest.value[:32]}")


def source_instance_id(source: ConfiguredSource) -> SourceInstanceId:
    """Return the ref-aware store identity for one configured source.

    The ref participates in the identity so that two refs of one Git origin own separate mirrors,
    snapshots, and ``current.json`` pointers.  Without it a second ref would silently retarget the
    first source's installed content.  Local sources have no ref and keep their v1 identity.
    """

    if source.ref is None:
        return legacy_source_instance_id(source)
    return _instance_id(
        source,
        (
            ("kind", source.kind.value),
            ("location", source.location),
            ("ref", source.ref),
        ),
    )


def legacy_source_instance_id(source: ConfiguredSource) -> SourceInstanceId:
    """Return the v1 identity, which ignored ``ref``.

    Retained so the store migration can find directories written before ref-aware storage; it must
    not be used to resolve a source for reading or publishing.
    """

    return _instance_id(
        source,
        (
            ("kind", source.kind.value),
            ("location", source.location),
        ),
    )


def source_store_paths(data_root: str, instance_id: SourceInstanceId) -> SourceStorePaths:
    if not posixpath.isabs(data_root) or posixpath.normpath(data_root) != data_root:
        raise ValueError("source data root must be normalized and absolute")
    root = posixpath.join(data_root, "sources", instance_id.value)
    return SourceStorePaths(
        root,
        posixpath.join(root, "mirror.git"),
        posixpath.join(root, "snapshots"),
        posixpath.join(root, "current.json"),
        posixpath.join(root, "sync.lock"),
        posixpath.join(root, "tmp"),
    )


def source_snapshot_digest(snapshot: SourceSnapshot) -> Result[ObjectDigest]:
    if not isinstance(snapshot.origin, SnapshotOrigin):
        return _error("snapshot origin is invalid")
    entries = []
    seen: set[str] = set()
    for entry in snapshot.entries:
        raw_path = str(entry.path)
        parsed = parse_relative_path(raw_path)
        if isinstance(parsed, Err) or parsed.value != entry.path or raw_path in seen:
            return _error(f"snapshot path is invalid or duplicated: {raw_path!r}")
        seen.add(raw_path)
        if entry.kind is SnapshotEntryKind.DIRECTORY:
            if entry.content or entry.executable:
                return _error(f"snapshot directory has file metadata: {raw_path}")
            entries.append(directory_entry(entry.path))
        elif entry.kind is SnapshotEntryKind.FILE:
            if not isinstance(entry.content, bytes) or not isinstance(entry.executable, bool):
                return _error(f"snapshot file metadata is invalid: {raw_path}")
            entries.append(file_entry(entry.path, entry.content, executable=entry.executable))
        else:
            return _error(f"snapshot contains forbidden {entry.kind.value}: {raw_path}")
    return tree_digest(entries)


@dataclass(frozen=True, slots=True)
class SourceCandidate:
    instance_id: SourceInstanceId
    alias: SourceAlias
    resolved_revision: str
    snapshot_digest: ObjectDigest
    snapshot: SourceSnapshot

    def __post_init__(self) -> None:
        if (
            not self.alias.value
            or not self.resolved_revision
            or any(character in self.resolved_revision for character in "\r\n")
        ):
            raise ValueError("source candidate identity must be one non-empty line")
        if (
            self.snapshot_digest.algorithm != "sha256"
            or _HEX_64_RE.fullmatch(self.snapshot_digest.value) is None
        ):
            raise ValueError("source candidate digest must be canonical SHA-256")
        calculated = source_snapshot_digest(self.snapshot)
        if not isinstance(calculated, Ok) or calculated.value != self.snapshot_digest:
            raise ValueError("source candidate digest must bind the exact safe snapshot")


def make_source_candidate(
    instance_id: SourceInstanceId,
    alias: SourceAlias,
    resolved_revision: str,
    snapshot: SourceSnapshot,
) -> Result[SourceCandidate]:
    digest = source_snapshot_digest(snapshot)
    if isinstance(digest, Err):
        return digest
    try:
        return Ok(SourceCandidate(instance_id, alias, resolved_revision, digest.value, snapshot))
    except ValueError as error:
        return _error(str(error))


@dataclass(frozen=True, slots=True)
class ValidatedSourceCandidate:
    candidate: SourceCandidate
    declared_source_id: SourceId

    def __post_init__(self) -> None:
        if not self.declared_source_id.value:
            raise ValueError("validated source requires a declared source ID")


@dataclass(frozen=True, slots=True)
class CurrentSource:
    candidate: SourceCandidate
    declared_source_id: SourceId
    published_at_epoch_seconds: int
    snapshot_root: str

    def __post_init__(self) -> None:
        if not self.declared_source_id.value:
            raise ValueError("current source requires a declared source ID")
        if (
            not isinstance(self.published_at_epoch_seconds, int)
            or isinstance(self.published_at_epoch_seconds, bool)
            or self.published_at_epoch_seconds < 0
        ):
            raise ValueError("source publication time must be a non-negative integer")
        if (
            not posixpath.isabs(self.snapshot_root)
            or posixpath.normpath(self.snapshot_root) != self.snapshot_root
        ):
            raise ValueError("current snapshot root must be normalized and absolute")


class HealthStatus(str, Enum):
    MISSING = "missing"
    HEALTHY = "healthy"
    STALE = "stale"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class SourceHealth:
    status: HealthStatus
    age_seconds: int | None
    current: CurrentSource | None
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", sort_diagnostics(self.diagnostics))


def assess_source_health(
    current: CurrentSource | None,
    *,
    now: int,
    max_age_seconds: int,
    diagnostics: tuple[Diagnostic, ...] = (),
) -> SourceHealth:
    if (
        not isinstance(now, int)
        or isinstance(now, bool)
        or now < 0
        or not isinstance(max_age_seconds, int)
        or isinstance(max_age_seconds, bool)
        or max_age_seconds < 0
    ):
        raise ValueError("health clock and maximum age must be non-negative integers")
    if current is None and diagnostics:
        return SourceHealth(HealthStatus.DEGRADED, None, None, diagnostics)
    if current is None:
        return SourceHealth(HealthStatus.MISSING, None, None, diagnostics)
    age = max(0, now - current.published_at_epoch_seconds)
    if diagnostics:
        status = HealthStatus.DEGRADED
    elif age > max_age_seconds:
        status = HealthStatus.STALE
    else:
        status = HealthStatus.HEALTHY
    return SourceHealth(status, age, current, diagnostics)


class SyncFallback(str, Enum):
    REQUIRE_FRESH = "require-fresh"
    ALLOW_LAST_KNOWN_GOOD = "allow-last-known-good"


class SyncDisposition(str, Enum):
    PUBLISHED = "published"
    UNCHANGED = "unchanged"
    RETAINED = "retained"


@dataclass(frozen=True, slots=True)
class SourceSyncOutcome:
    disposition: SyncDisposition
    current: CurrentSource
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", sort_diagnostics(self.diagnostics))


@dataclass(frozen=True, slots=True)
class LocalSnapshotRequest:
    instance_id: SourceInstanceId
    alias: SourceAlias
    root: str
    limits: SnapshotLimits

    def __post_init__(self) -> None:
        if (
            not self.alias.value
            or not posixpath.isabs(self.root)
            or posixpath.normpath(self.root) != self.root
        ):
            raise ValueError(
                "local snapshot request requires an alias and normalized absolute root"
            )


@dataclass(frozen=True, slots=True)
class GitSnapshotRequest:
    instance_id: SourceInstanceId
    alias: SourceAlias
    location: str
    ref: str
    mirror_path: str
    temporary_root: str
    limits: SnapshotLimits
    timeout_seconds: int
    allow_local_transport: bool = False

    def __post_init__(self) -> None:
        if (
            not self.alias.value
            or not self.location
            or not self.ref
            or "\n" in self.ref
            or "\r" in self.ref
        ):
            raise ValueError("Git snapshot request identity is invalid")
        for value in (self.mirror_path, self.temporary_root):
            if not posixpath.isabs(value) or posixpath.normpath(value) != value:
                raise ValueError("Git snapshot paths must be normalized and absolute")
        if (
            not isinstance(self.timeout_seconds, int)
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
            or not isinstance(self.allow_local_transport, bool)
        ):
            raise ValueError("Git snapshot timeout/transport value is invalid")


@dataclass(frozen=True, slots=True)
class SourceValidationRequest:
    candidate: SourceCandidate
    executable_version: SemVer
    available_capabilities: tuple[Capability, ...]


@dataclass(frozen=True, slots=True)
class CurrentSourceRequest:
    paths: SourceStorePaths
    alias: SourceAlias


@dataclass(frozen=True, slots=True)
class SourcePublishCommand:
    paths: SourceStorePaths
    validated: ValidatedSourceCandidate
    observed_at_epoch_seconds: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.observed_at_epoch_seconds, int)
            or isinstance(self.observed_at_epoch_seconds, bool)
            or self.observed_at_epoch_seconds < 0
        ):
            raise ValueError("source publish time must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class SourcePublishReceipt:
    current: CurrentSource
    created: bool


@dataclass(frozen=True, slots=True)
class SourceLockRequest:
    lock_directory: str
    timeout_seconds: float
    stale_after_seconds: int

    def __post_init__(self) -> None:
        if (
            not posixpath.isabs(self.lock_directory)
            or posixpath.normpath(self.lock_directory) != self.lock_directory
            or not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
            or not isinstance(self.stale_after_seconds, int)
            or isinstance(self.stale_after_seconds, bool)
            or self.stale_after_seconds <= 0
        ):
            raise ValueError("source lock request is invalid")


@dataclass(frozen=True, slots=True)
class SourceLockLease:
    lock_directory: str
    token: str

    def __post_init__(self) -> None:
        if not posixpath.isabs(self.lock_directory) or not self.token:
            raise ValueError("source lock lease is invalid")
