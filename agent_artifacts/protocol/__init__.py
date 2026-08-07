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
from .registry_index import (
    build_registry_index,
    index_artifact_from_package,
    validate_registry_graph,
)
from .registry_models import (
    GitArtifactReference,
    IndexArtifact,
    LockedArtifact,
    RegistryEntry,
    RegistryIndex,
    RegistryLock,
    RegistryManifest,
    ResolvedRegistryReference,
    ReviewRecord,
    ServiceAdvertisement,
)
from .registry_schema import (
    parse_registry_entry,
    parse_registry_index,
    parse_registry_lock,
    parse_registry_manifest,
    registry_entry_to_json,
    registry_index_to_json,
    registry_lock_to_json,
    registry_manifest_to_json,
)
from .registry_tree import registry_inputs_digest, resolve_locked_references
from .semver import SemVer, VersionBounds, parse_semver, version_bounds

__all__ = [
    "ArtifactManifest",
    "Capability",
    "CapabilityDecision",
    "CollectionManifest",
    "GitArtifactReference",
    "IndexArtifact",
    "JsonArray",
    "JsonObject",
    "JsonValue",
    "LockedArtifact",
    "NativeArtifactPackage",
    "NativeSource",
    "Provenance",
    "RegistryEntry",
    "RegistryIndex",
    "RegistryLock",
    "RegistryManifest",
    "ResolvedRegistryReference",
    "ReviewRecord",
    "SafeRelativePath",
    "SemVer",
    "ServiceAdvertisement",
    "SnapshotEntry",
    "SnapshotEntryKind",
    "SnapshotOrigin",
    "SourceManifest",
    "SourceSnapshot",
    "TreeEntry",
    "VersionBounds",
    "build_registry_index",
    "canonical_json_bytes",
    "index_artifact_from_package",
    "json_digest",
    "load_native_source",
    "negotiate_capabilities",
    "parse_artifact_manifest",
    "parse_capability",
    "parse_collection_manifest",
    "parse_json",
    "parse_provenance",
    "parse_relative_path",
    "parse_registry_entry",
    "parse_registry_index",
    "parse_registry_lock",
    "parse_registry_manifest",
    "parse_semver",
    "parse_sha256",
    "parse_source_manifest",
    "registry_entry_to_json",
    "registry_index_to_json",
    "registry_inputs_digest",
    "registry_lock_to_json",
    "registry_manifest_to_json",
    "resolve_locked_references",
    "sha256_bytes",
    "tree_digest",
    "validate_registry_graph",
    "version_bounds",
]
