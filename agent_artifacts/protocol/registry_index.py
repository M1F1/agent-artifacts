"""Deterministic registry index projection and collection graph validation."""

from __future__ import annotations

from dataclasses import replace

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ArtifactIdentity, ObjectDigest, SourceId
from agent_artifacts.domain.result import Err, Ok, Result

from .codes import REGISTRY_GRAPH_INVALID, REGISTRY_INDEX_INVALID
from .native_models import CollectionManifest
from .native_tree import NativeArtifactPackage
from .registry_models import (
    IndexArtifact,
    IndexProvenance,
    IndexSetup,
    RegistryIndex,
    RegistryManifest,
    ReviewRecord,
)


def _error(code: DiagnosticCode, message: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message),))


def index_artifact_from_package(
    package: NativeArtifactPackage,
    *,
    source_id: SourceId,
    object_digest: ObjectDigest,
    review: ReviewRecord | None = None,
    collections: tuple[str, ...] = (),
) -> IndexArtifact:
    """Project a canonical owned or acquired package without copying payload bytes."""

    setup = None
    if package.manifest.setup is not None:
        setup = IndexSetup(
            package.manifest.setup.recipe,
            package.manifest.setup.platforms,
        )
    provenance = None
    if package.provenance is not None:
        provenance = IndexProvenance(
            package.provenance.origin.url,
            package.provenance.origin.resolved_commit,
            package.provenance.origin.path,
        )
    return IndexArtifact(
        source_id,
        package.manifest.identity,
        package.manifest.version,
        package.manifest.summary,
        package.manifest_digest,
        package.payload_digest,
        object_digest,
        package.manifest.compatibility,
        package.manifest.install,
        setup,
        review,
        provenance,
        tuple(sorted(set(collections))),
    )


def _collection_members(
    collection_name: str,
    collections: dict[str, CollectionManifest],
    artifacts: dict[ArtifactIdentity, IndexArtifact],
    memo: dict[str, frozenset[ArtifactIdentity]],
    visiting: tuple[str, ...],
) -> Result[frozenset[ArtifactIdentity]]:
    if collection_name in memo:
        return Ok(memo[collection_name])
    if collection_name in visiting:
        cycle = " -> ".join((*visiting, collection_name))
        return _error(REGISTRY_GRAPH_INVALID, f"collection cycle: {cycle}")
    collection = collections.get(collection_name)
    if collection is None:
        return _error(
            REGISTRY_GRAPH_INVALID,
            f"dangling collection reference: {collection_name}",
        )
    members: set[ArtifactIdentity] = set()
    for selector in collection.artifacts:
        artifact = artifacts.get(selector.identity)
        if artifact is None:
            return _error(
                REGISTRY_GRAPH_INVALID,
                f"collection {collection_name} references missing {selector.identity}",
            )
        if selector.version is not None and not selector.version.allows(artifact.version):
            return _error(
                REGISTRY_GRAPH_INVALID,
                f"collection {collection_name} excludes available version of {selector.identity}",
            )
        members.add(selector.identity)
    next_visiting = (*visiting, collection_name)
    for nested_name in collection.collections:
        nested = _collection_members(
            nested_name,
            collections,
            artifacts,
            memo,
            next_visiting,
        )
        if isinstance(nested, Err):
            return nested
        members.update(nested.value)
    frozen = frozenset(members)
    memo[collection_name] = frozen
    return Ok(frozen)


def validate_registry_graph(
    artifacts: tuple[IndexArtifact, ...],
    collections: tuple[CollectionManifest, ...],
) -> Result[tuple[IndexArtifact, ...]]:
    """Validate the collection graph and derive complete deterministic memberships."""

    artifact_map: dict[ArtifactIdentity, IndexArtifact] = {}
    qualified: set[tuple[SourceId, ArtifactIdentity]] = set()
    for artifact in artifacts:
        key = (artifact.source_id, artifact.identity)
        if key in qualified or artifact.identity in artifact_map:
            return _error(
                REGISTRY_INDEX_INVALID,
                f"duplicate or ambiguous index identity: {artifact.source_id}/{artifact.identity}",
            )
        qualified.add(key)
        artifact_map[artifact.identity] = artifact
    collection_map: dict[str, CollectionManifest] = {}
    for collection in collections:
        if collection.name in collection_map:
            return _error(
                REGISTRY_GRAPH_INVALID,
                f"duplicate collection identity: {collection.name}",
            )
        collection_map[collection.name] = collection
    memo: dict[str, frozenset[ArtifactIdentity]] = {}
    memberships: dict[ArtifactIdentity, set[str]] = {identity: set() for identity in artifact_map}
    for name in sorted(collection_map):
        members = _collection_members(name, collection_map, artifact_map, memo, ())
        if isinstance(members, Err):
            return members
        for identity in members.value:
            memberships[identity].add(name)
    return Ok(
        tuple(
            sorted(
                (
                    replace(artifact, collections=tuple(sorted(memberships[artifact.identity])))
                    for artifact in artifacts
                ),
                key=lambda item: (str(item.source_id), str(item.identity)),
            )
        )
    )


def build_registry_index(
    manifest: RegistryManifest,
    inputs_digest: ObjectDigest,
    artifacts: tuple[IndexArtifact, ...],
    collections: tuple[CollectionManifest, ...],
) -> Result[RegistryIndex]:
    """Build a sorted index only after the complete local collection graph validates."""

    indexed_artifacts = validate_registry_graph(artifacts, collections)
    if isinstance(indexed_artifacts, Err):
        return indexed_artifacts
    return Ok(
        RegistryIndex(
            1,
            manifest.protocol_version,
            manifest.registry_id,
            inputs_digest,
            indexed_artifacts.value,
            tuple(sorted(collections, key=lambda item: item.name)),
            manifest.services,
        )
    )
