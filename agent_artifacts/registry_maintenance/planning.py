"""Pure registry entry, native promotion, and exact native-reference refresh planning."""

from __future__ import annotations

import re
from dataclasses import replace

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ArtifactIdentity, ObjectDigest, SourceId
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.capabilities import Capability, negotiate_capabilities
from agent_artifacts.protocol.hashing import json_digest, sha256_bytes
from agent_artifacts.protocol.json import canonical_json_bytes
from agent_artifacts.protocol.native_models import CollectionManifest, SourceManifest
from agent_artifacts.protocol.native_schema import (
    parse_collection_manifest,
    parse_source_manifest,
    provenance_to_json,
)
from agent_artifacts.protocol.native_tree import (
    NativeArtifactPackage,
    SnapshotEntry,
    SnapshotEntryKind,
    SourceSnapshot,
    load_native_source,
)
from agent_artifacts.protocol.paths import SafeRelativePath, parse_relative_path
from agent_artifacts.protocol.registry_index import (
    build_registry_index,
    index_artifact_from_package,
)
from agent_artifacts.protocol.registry_models import (
    IndexArtifact,
    LockedArtifact,
    RegistryEntry,
    RegistryIndex,
    RegistryLock,
    RegistryManifest,
)
from agent_artifacts.protocol.registry_schema import (
    parse_registry_entry,
    parse_registry_index,
    parse_registry_lock,
    parse_registry_manifest,
    registry_entry_to_json,
    registry_index_to_json,
    registry_lock_to_json,
)
from agent_artifacts.protocol.registry_tree import (
    registry_inputs_digest,
    resolve_locked_references,
)
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.sources.model import source_snapshot_digest
from agent_artifacts.store.model import ObjectCandidate, make_object_candidate

from .model import (
    NativeReferenceAcquisition,
    NativeReferenceCheck,
    NativeReferenceDisposition,
    RegistryChangeKind,
    RegistryFileChange,
    RegistryMutationPlan,
    registry_mutation_review_digest,
)

REGISTRY_MAINTENANCE_INVALID = DiagnosticCode("registry-maintenance-invalid")
REGISTRY_MAINTENANCE_STALE = DiagnosticCode("registry-maintenance-stale")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _error(message: str, *, stale: bool = False) -> Err:
    return Err(
        (
            Diagnostic(
                REGISTRY_MAINTENANCE_STALE if stale else REGISTRY_MAINTENANCE_INVALID,
                Severity.ERROR,
                message,
            ),
        )
    )


def _snapshot_files(snapshot: SourceSnapshot) -> Result[dict[str, SnapshotEntry]]:
    digest = source_snapshot_digest(snapshot)
    if isinstance(digest, Err):
        return _error("registry workspace must be one inert canonical snapshot")
    return Ok({str(entry.path): entry for entry in snapshot.entries})


def _required_file(files: dict[str, SnapshotEntry], path: str) -> Result[SnapshotEntry]:
    entry = files.get(path)
    if entry is None or entry.kind is not SnapshotEntryKind.FILE:
        return _error(f"registry workspace requires {path}")
    return Ok(entry)


def _registry_manifest(files: dict[str, SnapshotEntry]) -> Result[RegistryManifest]:
    marker = _required_file(files, "aart-registry.json")
    if isinstance(marker, Err):
        return marker
    return parse_registry_manifest(marker.value.content)


def _registry_source_manifest(
    files: dict[str, SnapshotEntry],
    registry: RegistryManifest,
) -> Result[SourceManifest]:
    marker = _required_file(files, "aart-source.json")
    if isinstance(marker, Err):
        return marker
    source = parse_source_manifest(marker.value.content)
    if isinstance(source, Err):
        return source
    if source.value.source_id != registry.registry_id:
        return _error("registry and native source identities must match")
    return source


def _entry_path(entry: RegistryEntry) -> str:
    return f"entries/{entry.identity.kind}/{entry.identity.name}.json"


def _current_entries(files: dict[str, SnapshotEntry]) -> Result[tuple[RegistryEntry, ...]]:
    entries: list[RegistryEntry] = []
    for path, item in sorted(files.items()):
        if not path.startswith("entries/") or item.kind is not SnapshotEntryKind.FILE:
            continue
        parsed = parse_registry_entry(item.content, path=path)
        if isinstance(parsed, Err):
            return parsed
        if path != _entry_path(parsed.value):
            return _error(f"registry entry identity does not match its path: {path}")
        entries.append(parsed.value)
    identities = tuple(item.identity for item in entries)
    if len(set(identities)) != len(identities):
        return _error("registry workspace contains duplicate entry identities")
    return Ok(tuple(entries))


def _optional_lock(files: dict[str, SnapshotEntry]) -> Result[RegistryLock | None]:
    item = files.get("aart.lock.json")
    if item is None:
        return Ok(None)
    if item.kind is not SnapshotEntryKind.FILE:
        return _error("aart.lock.json must be a regular file")
    return parse_registry_lock(item.content)


def _optional_index(files: dict[str, SnapshotEntry]) -> Result[RegistryIndex | None]:
    item = files.get("aart.index.json")
    if item is None:
        return Ok(None)
    if item.kind is not SnapshotEntryKind.FILE:
        return _error("aart.index.json must be a regular file")
    return parse_registry_index(item.content)


def _file_change(path: str, before: SnapshotEntry | None, content: bytes) -> RegistryFileChange:
    parsed = parse_relative_path(path)
    assert isinstance(parsed, Ok)
    after_digest = sha256_bytes(content)
    before_digest = None if before is None else sha256_bytes(before.content)
    if before is None:
        kind = RegistryChangeKind.ADDED
    elif before.content == content and before.kind is SnapshotEntryKind.FILE:
        kind = RegistryChangeKind.UNCHANGED
    else:
        kind = RegistryChangeKind.CHANGED
    return RegistryFileChange(parsed.value, kind, content, before_digest, after_digest)


def _project_changes(
    snapshot: SourceSnapshot,
    changes: tuple[RegistryFileChange, ...],
) -> Result[SourceSnapshot]:
    files = _snapshot_files(snapshot)
    if isinstance(files, Err):
        return files
    output = dict(files.value)
    for change in changes:
        raw = str(change.path)
        before = output.get(raw)
        actual_digest = None
        if before is not None:
            if before.kind is not SnapshotEntryKind.FILE:
                return _error(f"registry mutation target is not a file: {raw}")
            actual_digest = sha256_bytes(before.content)
        if actual_digest != change.before_digest:
            return _error(f"registry mutation precondition changed: {raw}", stale=True)
        output[raw] = SnapshotEntry(
            change.path,
            SnapshotEntryKind.FILE,
            change.content,
        )
        for length in range(1, len(change.path.parts)):
            parent = SafeRelativePath(change.path.parts[:length])
            prior = output.get(str(parent))
            if prior is not None and prior.kind is not SnapshotEntryKind.DIRECTORY:
                return _error(f"registry mutation parent is not a directory: {parent}")
            output.setdefault(
                str(parent),
                SnapshotEntry(parent, SnapshotEntryKind.DIRECTORY),
            )
    return Ok(SourceSnapshot(snapshot.origin, tuple(output.values())))


def _mutation_plan(
    snapshot: SourceSnapshot,
    desired_files: tuple[tuple[str, bytes], ...],
) -> Result[RegistryMutationPlan]:
    files = _snapshot_files(snapshot)
    if isinstance(files, Err):
        return files
    current_digest = registry_inputs_digest(snapshot)
    if isinstance(current_digest, Err):
        return current_digest
    changes = tuple(
        _file_change(path, files.value.get(path), content)
        for path, content in sorted(desired_files)
    )
    projected = _project_changes(snapshot, changes)
    if isinstance(projected, Err):
        return projected
    next_digest = registry_inputs_digest(projected.value)
    if isinstance(next_digest, Err):
        return next_digest
    return Ok(
        RegistryMutationPlan(
            current_digest.value,
            next_digest.value,
            changes,
            registry_mutation_review_digest(
                current_digest.value,
                next_digest.value,
                changes,
            ),
        )
    )


def project_registry_mutation(
    snapshot: SourceSnapshot,
    plan: RegistryMutationPlan,
) -> Result[SourceSnapshot]:
    current = registry_inputs_digest(snapshot)
    if isinstance(current, Err):
        return current
    if current.value != plan.expected_inputs_digest:
        return _error("registry inputs changed after review", stale=True)
    projected = _project_changes(snapshot, plan.changes)
    if isinstance(projected, Err):
        return projected
    next_digest = registry_inputs_digest(projected.value)
    if isinstance(next_digest, Err) or next_digest.value != plan.next_inputs_digest:
        return _error("registry mutation no longer produces the reviewed input digest", stale=True)
    return projected


def plan_registry_entry_add(
    snapshot: SourceSnapshot,
    entry: RegistryEntry,
) -> Result[RegistryMutationPlan]:
    files = _snapshot_files(snapshot)
    if isinstance(files, Err):
        return files
    manifest = _registry_manifest(files.value)
    if isinstance(manifest, Err):
        return manifest
    source = _registry_source_manifest(files.value, manifest.value)
    if isinstance(source, Err):
        return source
    owned_paths = {
        f"{root}/{entry.identity.kind}/{entry.identity.name}/artifact.json"
        for root in source.value.artifact_roots
    }
    if owned_paths & files.value.keys():
        return _error(f"registry already owns canonical package {entry.identity}")
    path = _entry_path(entry)
    current = files.value.get(path)
    content = canonical_json_bytes(registry_entry_to_json(entry))
    if current is not None:
        if current.kind is not SnapshotEntryKind.FILE:
            return _error(f"registry entry path is not a file: {entry.identity}")
        parsed_current = parse_registry_entry(current.content, path=path)
        if isinstance(parsed_current, Err):
            return parsed_current
        if (
            parsed_current.value.source != entry.source
            or parsed_current.value.extensions != entry.extensions
        ):
            return _error(
                f"registry entry already exists with different authored source: {entry.identity}"
            )
    return _mutation_plan(snapshot, ((path, content),))


def _package_object(
    snapshot: SourceSnapshot,
    path: SafeRelativePath,
) -> Result[ObjectCandidate]:
    prefix = f"{path}/"
    entries: list[SnapshotEntry] = []
    for item in snapshot.entries:
        raw = str(item.path)
        if not raw.startswith(prefix):
            continue
        relative = raw.removeprefix(prefix)
        parsed = parse_relative_path(relative)
        if isinstance(parsed, Err):
            return _error(f"native package contains an unsafe relative path: {raw}")
        entries.append(SnapshotEntry(parsed.value, item.kind, item.content, item.executable))
    candidate = make_object_candidate(entries)
    return candidate if isinstance(candidate, Err) else Ok(candidate.value)


def _acquired_package(
    entry: RegistryEntry,
    acquisition: NativeReferenceAcquisition,
    *,
    executable_version: SemVer,
    available_capabilities: tuple[Capability, ...],
) -> Result[tuple[NativeArtifactPackage, ObjectCandidate, ObjectDigest | None, SourceId]]:
    if (
        acquisition.url != entry.source.url
        or acquisition.requested_ref != entry.source.ref
        or _COMMIT_RE.fullmatch(acquisition.resolved_commit) is None
    ):
        return _error("acquired Git origin/ref does not match the registry entry")
    loaded = load_native_source(
        acquisition.snapshot,
        executable_version=executable_version,
        available_capabilities=available_capabilities,
    )
    if isinstance(loaded, Err):
        return loaded
    packages = tuple(
        package for package in loaded.value.artifacts if package.manifest.identity == entry.identity
    )
    expected_paths = {
        SafeRelativePath((*root.parts, entry.identity.kind, entry.identity.name))
        for root in loaded.value.manifest.artifact_roots
    }
    if len(packages) != 1 or entry.source.path not in expected_paths:
        return _error(f"acquired native source does not contain exact identity {entry.identity}")
    candidate = _package_object(acquisition.snapshot, entry.source.path)
    if isinstance(candidate, Err):
        return candidate
    provenance_digest = (
        None
        if packages[0].provenance is None
        else json_digest(provenance_to_json(packages[0].provenance))
    )
    return Ok((packages[0], candidate.value, provenance_digest, loaded.value.manifest.source_id))


def resolve_native_acquisition(
    entry: RegistryEntry,
    acquisition: NativeReferenceAcquisition,
    *,
    executable_version: SemVer,
    available_capabilities: tuple[Capability, ...],
) -> Result[tuple[NativeArtifactPackage, ObjectCandidate, ObjectDigest | None, SourceId]]:
    """Validate and resolve one immutable native acquisition for registry tooling."""

    return _acquired_package(
        entry,
        acquisition,
        executable_version=executable_version,
        available_capabilities=available_capabilities,
    )


def _collections_without_index(
    files: dict[str, SnapshotEntry],
) -> Result[tuple[CollectionManifest, ...]]:
    marker = _required_file(files, "aart-source.json")
    if isinstance(marker, Err):
        return marker
    source = parse_source_manifest(marker.value.content)
    if isinstance(source, Err):
        return source
    collections: list[CollectionManifest] = []
    for root in source.value.collection_roots:
        prefix = f"{root}/"
        for path, item in sorted(files.items()):
            if not path.startswith(prefix) or item.kind is not SnapshotEntryKind.FILE:
                continue
            relative = path.removeprefix(prefix)
            if "/" in relative or not relative.endswith(".json"):
                return _error(f"collection files must be direct JSON children of {root}: {path}")
            parsed = parse_collection_manifest(item.content, path=path)
            if isinstance(parsed, Err):
                return parsed
            if parsed.value.name != relative.removesuffix(".json"):
                return _error(f"collection identity does not match its path: {path}")
            collections.append(parsed.value)
    identities = tuple(item.name for item in collections)
    if len(set(identities)) != len(identities):
        return _error("registry workspace contains duplicate collection identities")
    return Ok(tuple(sorted(collections, key=lambda item: item.name)))


def _native_registry_content(
    snapshot: SourceSnapshot,
    files: dict[str, SnapshotEntry],
    manifest: RegistryManifest,
    *,
    executable_version: SemVer,
    available_capabilities: tuple[Capability, ...],
) -> Result[tuple[tuple[IndexArtifact, ...], tuple[CollectionManifest, ...]]]:
    source = _registry_source_manifest(files, manifest)
    if isinstance(source, Err):
        return source
    if not manifest.requires_aart.allows(
        executable_version
    ) or not source.value.requires_aart.allows(executable_version):
        return _error("registry workspace is incompatible with this AART version")
    decision = negotiate_capabilities(
        tuple(
            sorted(set(manifest.required_capabilities) | set(source.value.required_capabilities))
        ),
        (),
        available_capabilities,
    )
    if decision.missing_required:
        missing = ", ".join(str(item) for item in decision.missing_required)
        return _error(f"registry workspace requires unavailable capabilities: {missing}")
    has_owned_files = any(
        item.kind is SnapshotEntryKind.FILE
        and any(
            tuple(path.split("/")[: len(root.parts)]) == root.parts
            and len(path.split("/")) > len(root.parts)
            for root in source.value.artifact_roots
        )
        for path, item in files.items()
    )
    if not has_owned_files:
        collections = _collections_without_index(files)
        if isinstance(collections, Err):
            return collections
        return Ok(((), collections.value))
    loaded = load_native_source(
        snapshot,
        executable_version=executable_version,
        available_capabilities=available_capabilities,
    )
    if isinstance(loaded, Err):
        return loaded
    artifacts: list[IndexArtifact] = []
    for package in loaded.value.artifacts:
        matching_paths = tuple(
            SafeRelativePath(
                (*root.parts, package.manifest.identity.kind, package.manifest.identity.name)
            )
            for root in loaded.value.manifest.artifact_roots
            if f"{root}/{package.manifest.identity.kind}/{package.manifest.identity.name}/artifact.json"
            in files
        )
        if len(matching_paths) != 1:
            return _error(f"registry-owned package path is ambiguous: {package.manifest.identity}")
        candidate = _package_object(snapshot, matching_paths[0])
        if isinstance(candidate, Err):
            return candidate
        artifacts.append(
            index_artifact_from_package(
                package,
                source_id=manifest.registry_id,
                object_digest=candidate.value.digest,
            )
        )
    return Ok((tuple(artifacts), loaded.value.collections))


def registry_native_content(
    snapshot: SourceSnapshot,
    files: dict[str, SnapshotEntry],
    manifest: RegistryManifest,
    *,
    executable_version: SemVer,
    available_capabilities: tuple[Capability, ...],
) -> Result[tuple[tuple[IndexArtifact, ...], tuple[CollectionManifest, ...]]]:
    """Compile registry-owned native packages and collections for maintainer commands."""

    return _native_registry_content(
        snapshot,
        files,
        manifest,
        executable_version=executable_version,
        available_capabilities=available_capabilities,
    )


def _locked_index_agrees(
    identity: ArtifactIdentity,
    locked: LockedArtifact,
    indexed: IndexArtifact,
) -> bool:
    return (
        indexed.identity == identity
        and indexed.version == locked.artifact_version
        and indexed.manifest_digest == locked.manifest_digest
        and indexed.payload_digest == locked.payload_digest
        and indexed.object_digest == locked.object_digest
        and indexed.review == locked.review
        and (indexed.provenance is None) == (locked.provenance_digest is None)
    )


def _existing_reference_state(
    snapshot: SourceSnapshot,
    files: dict[str, SnapshotEntry],
    entries: tuple[RegistryEntry, ...],
    current_inputs: ObjectDigest,
    manifest: RegistryManifest,
    owned: tuple[IndexArtifact, ...],
    collections: tuple[CollectionManifest, ...],
    promoting_identity: ArtifactIdentity,
) -> Result[tuple[dict[ArtifactIdentity, LockedArtifact], tuple[IndexArtifact, ...]]]:
    lock = _optional_lock(files)
    index = _optional_index(files)
    if isinstance(lock, Err):
        return lock
    if isinstance(index, Err):
        return index
    locked = {} if lock.value is None else dict(lock.value.entries)
    entry_by_identity = {entry.identity: entry for entry in entries}
    if not set(locked) <= set(entry_by_identity):
        return _error("lock contains entries absent from the registry", stale=True)
    validation_inputs = current_inputs
    validation_entries = entries
    if promoting_identity in entry_by_identity and promoting_identity not in locked:
        without_target = SourceSnapshot(
            snapshot.origin,
            tuple(
                item
                for item in snapshot.entries
                if str(item.path) != _entry_path(entry_by_identity[promoting_identity])
            ),
        )
        prior_inputs = registry_inputs_digest(without_target)
        if isinstance(prior_inputs, Err):
            return prior_inputs
        validation_inputs = prior_inputs.value
        validation_entries = tuple(
            entry for entry in entries if entry.identity != promoting_identity
        )
    elif (
        promoting_identity in locked
        and entry_by_identity[promoting_identity].review != locked[promoting_identity].review
    ):
        prior_entry = replace(
            entry_by_identity[promoting_identity],
            review=locked[promoting_identity].review,
        )
        prior_content = canonical_json_bytes(registry_entry_to_json(prior_entry))
        prior_snapshot = SourceSnapshot(
            snapshot.origin,
            tuple(
                SnapshotEntry(item.path, item.kind, prior_content, item.executable)
                if str(item.path) == _entry_path(prior_entry)
                else item
                for item in snapshot.entries
            ),
        )
        prior_inputs = registry_inputs_digest(prior_snapshot)
        if isinstance(prior_inputs, Err):
            return prior_inputs
        validation_inputs = prior_inputs.value
        validation_entries = tuple(
            prior_entry if entry.identity == promoting_identity else entry for entry in entries
        )
    if lock.value is not None and lock.value.registry_inputs_digest != validation_inputs:
        return _error("existing registry lock is stale", stale=True)
    if validation_entries:
        if lock.value is None:
            return _error("existing registry references require committed lock and index")
        resolved = resolve_locked_references(
            validation_entries,
            lock.value,
            expected_inputs_digest=validation_inputs,
        )
        if isinstance(resolved, Err):
            return resolved
        if set(locked) != {entry.identity for entry in validation_entries}:
            return _error("existing lock identities do not match authored entries", stale=True)
    elif locked:
        return _error("lock contains entries absent from the registry", stale=True)
    if index.value is None:
        if validation_entries:
            return _error("existing registry references require committed lock and index")
        return Ok((locked, ()))
    if (
        index.value.registry_id != manifest.registry_id
        or index.value.protocol_version != manifest.protocol_version
        or index.value.registry_inputs_digest != validation_inputs
        or index.value.collections != collections
        or index.value.services != manifest.services
    ):
        return _error("existing compiled index is stale", stale=True)
    indexed_by_identity = {item.identity: item for item in index.value.artifacts}
    if len(indexed_by_identity) != len(index.value.artifacts):
        return _error("existing index contains duplicate artifact identities", stale=True)
    expected_identities = set(locked) | {item.identity for item in owned}
    if set(indexed_by_identity) != expected_identities:
        return _error("existing index identities do not match registry content", stale=True)
    for item in owned:
        indexed = indexed_by_identity[item.identity]
        if replace(indexed, collections=()) != item:
            return _error(
                f"existing index disagrees with registry-owned package {item.identity}",
                stale=True,
            )
    referenced: list[IndexArtifact] = []
    for identity, locked_artifact in sorted(locked.items(), key=lambda item: str(item[0])):
        indexed = indexed_by_identity[identity]
        if not _locked_index_agrees(identity, locked_artifact, indexed):
            return _error(f"existing lock and index disagree for {identity}", stale=True)
        referenced.append(indexed)
    return Ok((locked, tuple(referenced)))


def plan_native_promotion(
    snapshot: SourceSnapshot,
    entry: RegistryEntry,
    acquisition: NativeReferenceAcquisition,
    *,
    executable_version: SemVer,
    available_capabilities: tuple[Capability, ...],
) -> Result[RegistryMutationPlan]:
    files = _snapshot_files(snapshot)
    if isinstance(files, Err):
        return files
    manifest = _registry_manifest(files.value)
    entries = _current_entries(files.value)
    current_inputs = registry_inputs_digest(snapshot)
    for result in (manifest, entries, current_inputs):
        if isinstance(result, Err):
            return result
    assert isinstance(manifest, Ok)
    assert isinstance(entries, Ok)
    assert isinstance(current_inputs, Ok)
    if entry.review.status != "approved":
        return _error("native promotion requires an approved review record")
    existing_by_identity = {item.identity: item for item in entries.value}
    prior = existing_by_identity.get(entry.identity)
    if prior is not None and (prior.source != entry.source or prior.extensions != entry.extensions):
        return _error(f"registry entry {entry.identity} changes its reviewed authored source")
    added = plan_registry_entry_add(snapshot, entry)
    if isinstance(added, Err):
        return added
    acquired = _acquired_package(
        entry,
        acquisition,
        executable_version=executable_version,
        available_capabilities=available_capabilities,
    )
    if isinstance(acquired, Err):
        return acquired
    package, object_candidate, provenance_digest, acquired_source_id = acquired.value
    native_content = _native_registry_content(
        snapshot,
        files.value,
        manifest.value,
        executable_version=executable_version,
        available_capabilities=available_capabilities,
    )
    if isinstance(native_content, Err):
        return native_content
    owned, collections = native_content.value
    state = _existing_reference_state(
        snapshot,
        files.value,
        entries.value,
        current_inputs.value,
        manifest.value,
        owned,
        collections,
        entry.identity,
    )
    if isinstance(state, Err):
        return state
    locked, indexed = state.value
    previous_index = next((item for item in indexed if item.identity == entry.identity), None)
    if previous_index is not None and previous_index.source_id != acquired_source_id:
        return _error(f"native reference source identity changed for {entry.identity}")
    prospective = project_registry_mutation(snapshot, added.value)
    if isinstance(prospective, Err):
        return prospective
    next_inputs = registry_inputs_digest(prospective.value)
    if isinstance(next_inputs, Err):
        return next_inputs
    locked[entry.identity] = LockedArtifact(
        acquisition.url,
        acquisition.requested_ref,
        acquisition.resolved_commit,
        entry.source.path,
        package.manifest_digest,
        package.payload_digest,
        object_candidate.digest,
        package.manifest.version,
        entry.review,
        provenance_digest,
    )
    lock = RegistryLock(
        1,
        next_inputs.value,
        tuple(sorted(locked.items(), key=lambda item: str(item[0]))),
    )
    next_artifact = index_artifact_from_package(
        package,
        source_id=acquired_source_id,
        object_digest=object_candidate.digest,
        review=entry.review,
    )
    artifacts = (
        owned
        + tuple(item for item in indexed if item.identity != entry.identity)
        + (next_artifact,)
    )
    index = build_registry_index(
        manifest.value,
        next_inputs.value,
        artifacts,
        collections,
    )
    if isinstance(index, Err):
        return index
    return _mutation_plan(
        snapshot,
        (
            (_entry_path(entry), canonical_json_bytes(registry_entry_to_json(entry))),
            ("aart.lock.json", canonical_json_bytes(registry_lock_to_json(lock))),
            ("aart.index.json", canonical_json_bytes(registry_index_to_json(index.value))),
        ),
    )


def check_native_reference(
    snapshot: SourceSnapshot,
    entry: RegistryEntry,
    acquisition: NativeReferenceAcquisition,
    *,
    executable_version: SemVer,
    available_capabilities: tuple[Capability, ...],
) -> Result[NativeReferenceCheck]:
    plan = plan_native_promotion(
        snapshot,
        entry,
        acquisition,
        executable_version=executable_version,
        available_capabilities=available_capabilities,
    )
    if isinstance(plan, Err):
        return plan
    disposition = (
        NativeReferenceDisposition.UP_TO_DATE
        if plan.value.changed_paths == 0
        else NativeReferenceDisposition.CHANGED
    )
    return Ok(NativeReferenceCheck(disposition, plan.value))
