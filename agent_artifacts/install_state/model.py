"""Frozen installation-state v2 and reviewed migration values."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, replace
from typing import Literal

from agent_artifacts.configuration.model import SourceKind, git_location_parts
from agent_artifacts.domain.identifiers import (
    ArtifactCoordinate,
    ArtifactIdentity,
    ObjectDigest,
    SourceAlias,
    SourceId,
)
from agent_artifacts.domain.result import Ok
from agent_artifacts.protocol.hashing import json_digest, sha256_bytes
from agent_artifacts.protocol.json import JsonObject, JsonValue, canonical_json_bytes
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.protocol.semver import SemVer

InstallScope = Literal["project", "user"]
InstallMode = Literal["copy", "symlink"]
EffectKind = Literal[
    "copy-tree",
    "write-file",
    "merge-json",
    "managed-block",
    "symlink-file",
    "symlink-tree",
]
MergeMode = Literal["key", "list"]
MemoryMode = Literal["replace", "prepend", "append", "skip"]

_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_SETUP_REF_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,255}$")
_ARTIFACT_KINDS = frozenset({"skill", "guideline", "mcp", "hook", "memory"})
_LEGACY_SOURCE_RE = re.compile(r"^(?:main|pin):[A-Za-z0-9._-]+$")
_MAX_STATE_BYTES = 10 * 1024 * 1024
_EFFECT_KINDS = frozenset(
    {
        "copy-tree",
        "write-file",
        "merge-json",
        "managed-block",
        "symlink-file",
        "symlink-tree",
    }
)


def _valid_digest(value: ObjectDigest) -> bool:
    return (
        isinstance(value, ObjectDigest)
        and value.algorithm == "sha256"
        and _HEX_RE.fullmatch(value.value) is not None
    )


def _one_line(value: str) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and "\r" not in value
        and "\n" not in value
    )


def _identity_evidence_matches(evidence: JsonValue, digest: ObjectDigest) -> bool:
    try:
        return json_digest(evidence) == digest
    except (TypeError, ValueError, UnicodeError):
        return False


def _safe_git_ref(value: str) -> bool:
    return (
        _one_line(value)
        and not value.startswith("-")
        and value not in {".", ".."}
        and not value.endswith((".", "/", ".lock"))
        and not any(part in {"", ".", ".."} for part in value.split("/"))
        and not any(
            token in value for token in ("..", "@{", "\\", " ", "~", "^", ":", "?", "*", "[")
        )
    )


def _safe_git_identity(value: str) -> bool:
    """Accept the marketplace's credential-free ``host/repository`` identity."""

    if not _one_line(value) or "://" in value or "@" in value:
        return False
    parts = value.split("/")
    return (
        len(parts) >= 2
        and "." in parts[0]
        and all(part not in {"", ".", ".."} for part in parts)
        and not any(character in value for character in "\\?#%")
    )


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    alias: SourceAlias
    declared_id: SourceId
    kind: SourceKind
    origin: str
    resolved_commit: str
    subscription_ref: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.alias, SourceAlias)
            or _SLUG_RE.fullmatch(self.alias.value) is None
            or not isinstance(self.declared_id, SourceId)
            or _SLUG_RE.fullmatch(self.declared_id.value) is None
            or not isinstance(self.kind, SourceKind)
            or not _one_line(self.origin)
        ):
            raise ValueError("installation source evidence is invalid")
        if self.kind is SourceKind.SOURCE_LOCAL:
            if (
                not posixpath.isabs(self.origin)
                or posixpath.normpath(self.origin) != self.origin
                or self.resolved_commit != "local"
                or self.subscription_ref is not None
            ):
                raise ValueError("local source origin must be a normalized absolute path")
        elif (
            _COMMIT_RE.fullmatch(self.resolved_commit) is None
            or (git_location_parts(self.origin) is None and not _safe_git_identity(self.origin))
            or not _safe_git_ref(self.subscription_ref or "")
        ):
            raise ValueError(
                "Git source origin/ref must be a credential-free Git location and safe subscription"
            )


@dataclass(frozen=True, slots=True)
class ArtifactEvidence:
    identity: ArtifactIdentity
    version: SemVer
    manifest_digest: ObjectDigest
    payload_digest: ObjectDigest
    object_digest: ObjectDigest

    def __post_init__(self) -> None:
        if (
            not isinstance(self.identity, ArtifactIdentity)
            or self.identity.kind not in _ARTIFACT_KINDS
            or _SLUG_RE.fullmatch(self.identity.name) is None
            or not isinstance(self.version, SemVer)
            or not all(
                _valid_digest(value)
                for value in (self.manifest_digest, self.payload_digest, self.object_digest)
            )
        ):
            raise ValueError("installation artifact evidence is invalid")


@dataclass(frozen=True, slots=True)
class EffectProof:
    kind: EffectKind
    destination: str
    actual_mode: InstallMode
    installed_digest: ObjectDigest
    source_path: str | None = None
    json_path: str | None = None
    merge_mode: MergeMode | None = None
    identity_digest: ObjectDigest | None = None
    identity_evidence: JsonValue | None = None
    link_target: str | None = None
    link_semantics: Literal["immutable-object", "mutable-local"] | None = None
    created_destination: bool = False
    overwrote: bool = False

    def __post_init__(self) -> None:
        if (
            self.kind not in _EFFECT_KINDS
            or not _one_line(self.destination)
            or self.actual_mode not in {"copy", "symlink"}
            or not _valid_digest(self.installed_digest)
            or not isinstance(self.created_destination, bool)
            or not isinstance(self.overwrote, bool)
        ):
            raise ValueError("installation effect proof is invalid")
        if self.source_path is not None:
            parsed_source = parse_relative_path(self.source_path)
            if not isinstance(parsed_source, Ok):
                raise ValueError("effect source path must be a safe relative path")
        merge_fields = (
            self.json_path,
            self.merge_mode,
            self.identity_digest,
            self.identity_evidence,
        )
        if self.kind == "merge-json":
            if (
                not _one_line(self.json_path or "")
                or self.merge_mode not in {"key", "list"}
                or not isinstance(self.identity_digest, ObjectDigest)
                or not _valid_digest(self.identity_digest)
                or (
                    self.identity_evidence is not None
                    and not _identity_evidence_matches(self.identity_evidence, self.identity_digest)
                )
                or self.source_path is not None
                or self.actual_mode != "copy"
            ):
                raise ValueError("merge-json effect proof is incomplete")
        elif any(value is not None for value in merge_fields):
            raise ValueError("non-merge effect proof cannot contain merge fields")
        elif (
            self.kind
            in {
                "copy-tree",
                "write-file",
                "symlink-file",
                "symlink-tree",
            }
            and self.source_path is None
        ):
            raise ValueError("file/tree effect proof requires a source path")
        if self.kind in {"symlink-file", "symlink-tree"}:
            if (
                self.actual_mode != "symlink"
                or self.link_target is None
                or not _one_line(self.link_target)
                or not posixpath.isabs(self.link_target)
                or posixpath.normpath(self.link_target) != self.link_target
                or self.link_target == "/"
                or self.link_semantics not in {"immutable-object", "mutable-local"}
            ):
                raise ValueError("symlink effect must record an absolute target and semantics")
        elif self.link_target is not None or self.link_semantics is not None:
            raise ValueError("non-symlink effect proof cannot contain link fields")
        if self.kind not in {"symlink-file", "symlink-tree"} and self.actual_mode != "copy":
            raise ValueError("non-symlink effects must record copy mode")

    @property
    def locator(self) -> tuple[str, str, str]:
        return (
            self.destination,
            self.json_path or "",
            "" if self.identity_digest is None else str(self.identity_digest),
        )


@dataclass(frozen=True, slots=True)
class InstallationRecord:
    coordinate: ArtifactCoordinate
    source: SourceEvidence
    artifact: ArtifactEvidence
    profile: str
    profile_version: int
    scope: InstallScope
    requested_mode: InstallMode
    effects: tuple[EffectProof, ...]
    memory_mode: MemoryMode | None = None
    setup_state_ref: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.coordinate, ArtifactCoordinate)
            or self.coordinate.version is not None
            or self.coordinate.source != self.source.alias
            or self.coordinate.artifact != self.artifact.identity
            or _SLUG_RE.fullmatch(self.profile) is None
            or not isinstance(self.profile_version, int)
            or isinstance(self.profile_version, bool)
            or self.profile_version < 1
            or self.profile_version > 2**63 - 1
            or self.scope not in {"project", "user"}
            or self.requested_mode not in {"copy", "symlink"}
            or not self.effects
            or any(not isinstance(effect, EffectProof) for effect in self.effects)
            or (
                self.artifact.identity.kind == "memory"
                and self.memory_mode not in {None, "replace", "prepend", "append", "skip"}
            )
            or (self.artifact.identity.kind != "memory" and self.memory_mode is not None)
            or (
                self.setup_state_ref is not None
                and _SETUP_REF_RE.fullmatch(self.setup_state_ref) is None
            )
        ):
            raise ValueError("installation record is invalid")
        locators = tuple(effect.locator for effect in self.effects)
        if len(set(locators)) != len(locators):
            raise ValueError("installation effect locators must be unique")
        for destination in (effect.destination for effect in self.effects):
            if self.scope == "project":
                parsed = parse_relative_path(destination)
                if not isinstance(parsed, Ok):
                    raise ValueError("project effect destination must be a safe relative path")
            elif not posixpath.isabs(destination) or posixpath.normpath(destination) != destination:
                raise ValueError("user effect destination must be a normalized absolute path")

    @property
    def key(self) -> tuple[str, str, str]:
        return (str(self.coordinate), self.profile, self.scope)


@dataclass(frozen=True, slots=True)
class InstallState:
    schema_version: int
    installations: tuple[InstallationRecord, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 2 or any(
            not isinstance(item, InstallationRecord) for item in self.installations
        ):
            raise ValueError("installation manifest schema version must be 2")
        ordered = tuple(sorted(self.installations, key=lambda item: item.key))
        if len({item.key for item in ordered}) != len(ordered):
            raise ValueError("installation identities must be unique")
        effect_owners = tuple(
            (item.scope, *effect.locator) for item in ordered for effect in item.effects
        )
        if len(set(effect_owners)) != len(effect_owners):
            raise ValueError("installation effect ownership must be unique across the manifest")
        object.__setattr__(self, "installations", ordered)


@dataclass(frozen=True, slots=True)
class LegacyMigrationCandidate:
    legacy_artifact: str
    legacy_type: str
    legacy_profile: str
    legacy_source: str
    source: SourceEvidence
    artifact: ArtifactEvidence
    profile_version: int
    effects: tuple[EffectProof, ...]
    setup_state_ref: str | None = None

    def __post_init__(self) -> None:
        if (
            _SLUG_RE.fullmatch(self.legacy_artifact) is None
            or self.legacy_type not in _ARTIFACT_KINDS
            or _SLUG_RE.fullmatch(self.legacy_profile) is None
            or _LEGACY_SOURCE_RE.fullmatch(self.legacy_source) is None
            or self.artifact.identity.kind != self.legacy_type
            or self.artifact.identity.name != self.legacy_artifact
            or not isinstance(self.profile_version, int)
            or isinstance(self.profile_version, bool)
            or self.profile_version < 1
            or self.profile_version > 2**63 - 1
            or any(not isinstance(effect, EffectProof) for effect in self.effects)
            or (
                self.setup_state_ref is not None
                and _SETUP_REF_RE.fullmatch(self.setup_state_ref) is None
            )
        ):
            raise ValueError("legacy migration candidate is invalid")

    @property
    def legacy_key(self) -> tuple[str, str, str, str]:
        return (
            self.legacy_type,
            self.legacy_artifact,
            self.legacy_profile,
            self.legacy_source,
        )


@dataclass(frozen=True, slots=True)
class InstallStatePaths:
    scope: InstallScope
    legacy_path: str
    destination_path: str
    backup_directory: str
    journal_directory: str
    lock_path: str

    def __post_init__(self) -> None:
        if self.scope not in {"project", "user"}:
            raise ValueError("state scope is invalid")
        for path in (
            self.legacy_path,
            self.destination_path,
            self.backup_directory,
            self.journal_directory,
            self.lock_path,
        ):
            if not posixpath.isabs(path) or posixpath.normpath(path) != path:
                raise ValueError("state paths must be normalized absolute paths")
        if (self.scope == "project") != (self.legacy_path == self.destination_path):
            raise ValueError("project state stays in place; user state must move to the data root")
        if (
            len(
                {
                    self.destination_path,
                    self.backup_directory,
                    self.journal_directory,
                    self.lock_path,
                }
            )
            != 4
        ):
            raise ValueError("state data, backup, journal, and lock paths must be distinct")


@dataclass(frozen=True, slots=True)
class StateMigrationPlan:
    scope: InstallScope
    legacy_path: str
    destination_path: str
    backup_path: str
    journal_path: str
    lock_path: str
    expected_legacy_digest: ObjectDigest
    replacement_digest: ObjectDigest
    legacy_content: bytes
    replacement: bytes
    journal_content: bytes
    review_digest: ObjectDigest

    def __post_init__(self) -> None:
        paths = (
            self.legacy_path,
            self.destination_path,
            self.backup_path,
            self.journal_path,
            self.lock_path,
        )
        if (
            self.scope not in {"project", "user"}
            or any(not posixpath.isabs(path) or posixpath.normpath(path) != path for path in paths)
            or not all(
                _valid_digest(value)
                for value in (
                    self.expected_legacy_digest,
                    self.replacement_digest,
                    self.review_digest,
                )
            )
        ):
            raise ValueError("state migration plan is invalid")
        if (self.scope == "project") != (self.legacy_path == self.destination_path):
            raise ValueError("state migration scope/path relationship is invalid")
        if len({self.destination_path, self.backup_path, self.journal_path, self.lock_path}) != 4:
            raise ValueError(
                "state migration data, backup, journal, and lock paths must be distinct"
            )
        if (
            max(len(self.legacy_content), len(self.replacement), len(self.journal_content))
            > _MAX_STATE_BYTES
        ):
            raise ValueError("state migration content exceeds the maximum supported size")
        if (
            sha256_bytes(self.legacy_content) != self.expected_legacy_digest
            or sha256_bytes(self.replacement) != self.replacement_digest
        ):
            raise ValueError("state migration content does not match its reviewed digests")
        review = JsonObject(
            (
                ("schema_version", 1),
                ("scope", self.scope),
                ("legacy_path", self.legacy_path),
                ("destination_path", self.destination_path),
                ("backup_path", self.backup_path),
                ("journal_path", self.journal_path),
                ("legacy_digest", str(self.expected_legacy_digest)),
                ("replacement_digest", str(self.replacement_digest)),
            )
        )
        if json_digest(review) != self.review_digest:
            raise ValueError("state migration review digest does not bind the plan")
        expected_journal = canonical_json_bytes(
            JsonObject(
                (
                    ("schema_version", 1),
                    ("review_digest", str(self.review_digest)),
                    ("scope", self.scope),
                    ("legacy_path", self.legacy_path),
                    ("destination_path", self.destination_path),
                    ("backup_path", self.backup_path),
                    ("legacy_digest", str(self.expected_legacy_digest)),
                    ("replacement_digest", str(self.replacement_digest)),
                )
            )
        )
        if self.journal_content != expected_journal:
            raise ValueError("state migration journal does not bind the reviewed plan")


@dataclass(frozen=True, slots=True)
class MigrationReceipt:
    plan: StateMigrationPlan
    changed: bool

    def current(self) -> MigrationReceipt:
        return replace(self, changed=False)


@dataclass(frozen=True, slots=True)
class RollbackReceipt:
    review_digest: ObjectDigest
    changed: bool
