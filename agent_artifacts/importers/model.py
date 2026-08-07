"""Frozen values for deterministic, maintainer-only importer workflows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit

from agent_artifacts.domain.identifiers import ArtifactIdentity, ObjectDigest
from agent_artifacts.protocol.json import JsonObject, JsonValue
from agent_artifacts.protocol.native_models import CollectionManifest, OriginProvenance
from agent_artifacts.protocol.native_tree import NativeSource, SnapshotOrigin, SourceSnapshot
from agent_artifacts.protocol.paths import SafeRelativePath
from agent_artifacts.protocol.semver import SemVer

_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_TYPES = frozenset({"skill", "guideline", "mcp", "hook", "memory"})


def _valid_digest(value: ObjectDigest) -> bool:
    return value.algorithm == "sha256" and _DIGEST_RE.fullmatch(value.value) is not None


def _safe_git_url(raw: str) -> bool:
    if raw.startswith("git@"):
        match = re.fullmatch(r"git@[A-Za-z0-9.-]+:(?P<path>[^\s?#]+)", raw)
        if match is None:
            return False
        parts = match.group("path").split("/")
        return all(
            part not in {".", ".."} and re.fullmatch(r"[A-Za-z0-9._-]+", part) for part in parts
        )
    if any(character.isspace() or ord(character) < 32 for character in raw):
        return False
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return False
    parts = parsed.path.removeprefix("/").split("/")
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and len(parts) >= 2
        and all(
            part not in {".", ".."} and re.fullmatch(r"[A-Za-z0-9._-]+", part) for part in parts
        )
        and "\\" not in parsed.path
        and "%" not in parsed.path
    )


@dataclass(frozen=True, slots=True)
class ImporterDescriptor:
    id: str
    version: SemVer
    markers: tuple[str, ...]
    artifact_types: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            _SLUG_RE.fullmatch(self.id) is None
            or not isinstance(self.version, SemVer)
            or any(not marker or "\n" in marker or "\r" in marker for marker in self.markers)
            or not self.artifact_types
            or any(item not in _ARTIFACT_TYPES for item in self.artifact_types)
        ):
            raise ValueError("importer descriptor is invalid")
        object.__setattr__(self, "markers", tuple(sorted(set(self.markers))))
        object.__setattr__(self, "artifact_types", tuple(sorted(set(self.artifact_types))))


@dataclass(frozen=True, slots=True)
class ImportOrigin:
    url: str
    resolved_commit: str
    root: SafeRelativePath | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.url, str)
            or not _safe_git_url(self.url)
            or _COMMIT_RE.fullmatch(self.resolved_commit) is None
            or (self.root is not None and not isinstance(self.root, SafeRelativePath))
        ):
            raise ValueError("import origin must be pinned credential-free Git content")


@dataclass(frozen=True, slots=True)
class ImporterInput:
    origin: ImportOrigin
    snapshot: SourceSnapshot

    def __post_init__(self) -> None:
        if (
            not isinstance(self.origin, ImportOrigin)
            or not isinstance(self.snapshot, SourceSnapshot)
            or self.snapshot.origin is not SnapshotOrigin.IMMUTABLE_GIT
        ):
            raise ValueError("importer input must be an immutable acquired Git snapshot")


@dataclass(frozen=True, slots=True)
class LegacyArtifactCandidate:
    identity: ArtifactIdentity
    source_path: SafeRelativePath
    descriptor_path: SafeRelativePath
    summary: str
    profiles: tuple[str, ...] | None
    setup_recipe: SafeRelativePath | None
    setup_platforms: tuple[str, ...]
    provenance: OriginProvenance
    provenance_extensions: tuple[tuple[str, JsonValue], ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.identity.kind not in _ARTIFACT_TYPES
            or _SLUG_RE.fullmatch(self.identity.name) is None
            or not isinstance(self.source_path, SafeRelativePath)
            or not isinstance(self.descriptor_path, SafeRelativePath)
            or not self.summary
            or "\n" in self.summary
            or "\r" in self.summary
            or (
                self.profiles is not None
                and (
                    not self.profiles
                    or any(_SLUG_RE.fullmatch(profile) is None for profile in self.profiles)
                )
            )
            or not isinstance(self.provenance, OriginProvenance)
            or any(not warning or "\n" in warning or "\r" in warning for warning in self.warnings)
        ):
            raise ValueError("legacy artifact candidate is invalid")
        if self.setup_recipe is not None and self.setup_recipe.parts[:1] != ("setup",):
            raise ValueError("legacy setup recipe must be below setup/")
        if (self.setup_recipe is None) != (not self.setup_platforms) or any(
            _SLUG_RE.fullmatch(platform) is None for platform in self.setup_platforms
        ):
            raise ValueError("legacy setup metadata is inconsistent")
        if self.profiles is not None:
            object.__setattr__(self, "profiles", tuple(sorted(set(self.profiles))))
        object.__setattr__(self, "setup_platforms", tuple(sorted(set(self.setup_platforms))))
        extension_keys = tuple(key for key, _value in self.provenance_extensions)
        if len(set(extension_keys)) != len(extension_keys):
            raise ValueError("legacy provenance extension keys must be unique")
        object.__setattr__(self, "provenance_extensions", tuple(sorted(self.provenance_extensions)))
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))


@dataclass(frozen=True, slots=True)
class ImportScan:
    importer: ImporterDescriptor
    input_digest: ObjectDigest
    artifacts: tuple[LegacyArtifactCandidate, ...]
    collections: tuple[CollectionManifest, ...]
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        identities = tuple(item.identity for item in self.artifacts)
        collection_names = tuple(item.name for item in self.collections)
        if (
            not isinstance(self.importer, ImporterDescriptor)
            or not _valid_digest(self.input_digest)
            or not self.artifacts
            or len(set(identities)) != len(identities)
            or len(set(collection_names)) != len(collection_names)
            or any(not warning or "\n" in warning or "\r" in warning for warning in self.warnings)
        ):
            raise ValueError("import scan is invalid")
        object.__setattr__(
            self, "artifacts", tuple(sorted(self.artifacts, key=lambda x: str(x.identity)))
        )
        object.__setattr__(
            self, "collections", tuple(sorted(self.collections, key=lambda x: x.name))
        )
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))


@dataclass(frozen=True, slots=True)
class ImportPlan:
    scan: ImportScan
    options: JsonObject
    options_digest: ObjectDigest
    plan_digest: ObjectDigest

    def __post_init__(self) -> None:
        if (
            not isinstance(self.scan, ImportScan)
            or not isinstance(self.options, JsonObject)
            or not _valid_digest(self.options_digest)
            or not _valid_digest(self.plan_digest)
        ):
            raise ValueError("import plan is invalid")


@dataclass(frozen=True, slots=True)
class MaterializedImport:
    plan: ImportPlan
    snapshot: SourceSnapshot
    output_digest: ObjectDigest

    def __post_init__(self) -> None:
        if (
            not isinstance(self.plan, ImportPlan)
            or not isinstance(self.snapshot, SourceSnapshot)
            or self.snapshot.origin is not SnapshotOrigin.LOCAL
            or not _valid_digest(self.output_digest)
        ):
            raise ValueError("materialized import is invalid")


@dataclass(frozen=True, slots=True)
class ValidatedImport:
    materialized: MaterializedImport
    source: NativeSource

    def __post_init__(self) -> None:
        if not isinstance(self.materialized, MaterializedImport) or not isinstance(
            self.source, NativeSource
        ):
            raise ValueError("validated import is invalid")


class ImportChangeKind(str, Enum):
    ADDED = "added"
    CHANGED = "changed"
    REMOVED = "removed"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True, order=True)
class ImportChange:
    path: SafeRelativePath
    kind: ImportChangeKind

    def __post_init__(self) -> None:
        if not isinstance(self.path, SafeRelativePath) or not isinstance(
            self.kind, ImportChangeKind
        ):
            raise ValueError("import change is invalid")


@dataclass(frozen=True, slots=True)
class ImportDiff:
    before_digest: ObjectDigest | None
    after_digest: ObjectDigest
    changes: tuple[ImportChange, ...]

    def __post_init__(self) -> None:
        if (
            (self.before_digest is not None and not _valid_digest(self.before_digest))
            or not _valid_digest(self.after_digest)
            or not self.changes
        ):
            raise ValueError("import diff is invalid")
        object.__setattr__(self, "changes", tuple(sorted(set(self.changes))))


@dataclass(frozen=True, slots=True)
class ImportApplyPlan:
    materialized: MaterializedImport
    expected_destination_digest: ObjectDigest | None
    changes: tuple[ImportChange, ...]
    review_digest: ObjectDigest

    def __post_init__(self) -> None:
        if (
            not isinstance(self.materialized, MaterializedImport)
            or (
                self.expected_destination_digest is not None
                and not _valid_digest(self.expected_destination_digest)
            )
            or not self.changes
            or not _valid_digest(self.review_digest)
        ):
            raise ValueError("import apply plan is invalid")
        object.__setattr__(self, "changes", tuple(sorted(set(self.changes))))

    @property
    def output_digest(self) -> ObjectDigest:
        return self.materialized.output_digest


@dataclass(frozen=True, slots=True)
class StagedImport:
    stage_id: str
    output_digest: ObjectDigest

    def __post_init__(self) -> None:
        if (
            not isinstance(self.stage_id, str)
            or not self.stage_id
            or "\n" in self.stage_id
            or "\r" in self.stage_id
            or not _valid_digest(self.output_digest)
        ):
            raise ValueError("staged import receipt is invalid")


@dataclass(frozen=True, slots=True)
class PreparedImport:
    validated: ValidatedImport
    apply_plan: ImportApplyPlan
    staged: StagedImport

    def __post_init__(self) -> None:
        if (
            not isinstance(self.validated, ValidatedImport)
            or not isinstance(self.apply_plan, ImportApplyPlan)
            or not isinstance(self.staged, StagedImport)
            or self.apply_plan.materialized != self.validated.materialized
            or self.staged.output_digest != self.apply_plan.output_digest
        ):
            raise ValueError("prepared import is inconsistent")


@dataclass(frozen=True, slots=True)
class AppliedImport:
    output_digest: ObjectDigest
    changed_paths: int
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not _valid_digest(self.output_digest)
            or not isinstance(self.changed_paths, int)
            or isinstance(self.changed_paths, bool)
            or self.changed_paths < 0
            or any(not warning or "\n" in warning or "\r" in warning for warning in self.warnings)
        ):
            raise ValueError("applied import receipt is invalid")
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))
