"""AART 1.0 strict protocol primitives."""

from .capabilities import Capability, CapabilityDecision, negotiate_capabilities, parse_capability
from .hashing import TreeEntry, json_digest, parse_sha256, sha256_bytes, tree_digest
from .json import JsonArray, JsonObject, JsonValue, canonical_json_bytes, parse_json
from .native_models import (
    ArtifactManifest,
    CollectionManifest,
    Provenance,
    SourceManifest,
)
from .native_schema import (
    parse_artifact_manifest,
    parse_collection_manifest,
    parse_provenance,
    parse_source_manifest,
)
from .native_tree import (
    NativeArtifactPackage,
    NativeSource,
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
    load_native_source,
)
from .paths import SafeRelativePath, parse_relative_path
from .semver import SemVer, VersionBounds, parse_semver, version_bounds

__all__ = [
    "ArtifactManifest",
    "Capability",
    "CapabilityDecision",
    "CollectionManifest",
    "JsonArray",
    "JsonObject",
    "JsonValue",
    "NativeArtifactPackage",
    "NativeSource",
    "Provenance",
    "SafeRelativePath",
    "SemVer",
    "SnapshotEntry",
    "SnapshotEntryKind",
    "SnapshotOrigin",
    "SourceManifest",
    "SourceSnapshot",
    "TreeEntry",
    "VersionBounds",
    "canonical_json_bytes",
    "json_digest",
    "load_native_source",
    "negotiate_capabilities",
    "parse_artifact_manifest",
    "parse_capability",
    "parse_collection_manifest",
    "parse_json",
    "parse_provenance",
    "parse_relative_path",
    "parse_semver",
    "parse_sha256",
    "parse_source_manifest",
    "sha256_bytes",
    "tree_digest",
    "version_bounds",
]
