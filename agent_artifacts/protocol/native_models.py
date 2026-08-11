"""Frozen domain values for AART native source protocol v1."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping

from agent_artifacts.domain.identifiers import ArtifactIdentity, ObjectDigest, SourceId

from .capabilities import Capability
from .json import JsonValue
from .paths import SafeRelativePath
from .semver import SemVer, VersionBounds

CanonicalArtifactType = Literal["skill", "guideline", "mcp", "hook", "memory"]
InstallScope = Literal["project", "user"]
InstallMode = Literal["copy", "symlink"]
InstallEffect = Literal["copy-tree", "write-file", "merge-json", "managed-block"]

PAYLOAD_FORMATS: tuple[tuple[CanonicalArtifactType, str], ...] = (
    ("skill", "aart-skill-v1"),
    ("guideline", "aart-guideline-v1"),
    ("mcp", "aart-mcp-v1"),
    ("hook", "aart-hook-v1"),
    ("memory", "aart-memory-v1"),
)
PAYLOAD_FORMAT_BY_TYPE: Mapping[CanonicalArtifactType, str] = MappingProxyType(
    dict(PAYLOAD_FORMATS)
)
INSTALL_EFFECTS_BY_TYPE: Mapping[CanonicalArtifactType, frozenset[InstallEffect]] = (
    MappingProxyType(
        {
            "skill": frozenset({"copy-tree"}),
            "guideline": frozenset({"write-file"}),
            "mcp": frozenset({"merge-json"}),
            "hook": frozenset({"copy-tree", "merge-json"}),
            "memory": frozenset({"write-file", "managed-block"}),
        }
    )
)


@dataclass(frozen=True, slots=True)
class SourceManifest:
    schema_version: int
    protocol_version: int
    source_id: SourceId
    display_name: str
    requires_aart: VersionBounds
    required_capabilities: tuple[Capability, ...]
    artifact_roots: tuple[SafeRelativePath, ...]
    collection_roots: tuple[SafeRelativePath, ...] = ()
    extensions: tuple[tuple[str, JsonValue], ...] = ()


@dataclass(frozen=True, slots=True)
class PayloadSpec:
    root: SafeRelativePath
    format: str


@dataclass(frozen=True, slots=True)
class CompatibilitySpec:
    profiles: tuple[str, ...]
    platforms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InstallSpec:
    scopes: tuple[InstallScope, ...]
    modes: tuple[InstallMode, ...]
    effects: tuple[InstallEffect, ...]


@dataclass(frozen=True, slots=True)
class SetupReference:
    recipe: SafeRelativePath
    platforms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    schema_version: int
    identity: ArtifactIdentity
    version: SemVer
    summary: str
    payload: PayloadSpec
    compatibility: CompatibilitySpec
    install: InstallSpec
    setup: SetupReference | None = None
    authors: tuple[str, ...] = ()
    license: str | None = None
    homepage: str | None = None
    extensions: tuple[tuple[str, JsonValue], ...] = ()
    requires_aart: VersionBounds = VersionBounds()


@dataclass(frozen=True, slots=True)
class OriginProvenance:
    kind: Literal["git"]
    url: str
    resolved_commit: str
    path: SafeRelativePath
    input_digest: ObjectDigest


@dataclass(frozen=True, slots=True)
class ImporterProvenance:
    id: str
    version: SemVer
    options_digest: ObjectDigest


@dataclass(frozen=True, slots=True)
class Provenance:
    schema_version: int
    origin: OriginProvenance
    importer: ImporterProvenance
    warnings: tuple[str, ...]
    extensions: tuple[tuple[str, JsonValue], ...] = ()


@dataclass(frozen=True, slots=True)
class ArtifactSelector:
    identity: ArtifactIdentity
    version: VersionBounds | None = None


@dataclass(frozen=True, slots=True)
class CollectionManifest:
    schema_version: int
    name: str
    summary: str
    artifacts: tuple[ArtifactSelector, ...]
    collections: tuple[str, ...] = ()
    extensions: tuple[tuple[str, JsonValue], ...] = ()
