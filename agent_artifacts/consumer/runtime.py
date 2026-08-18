"""Local composition root for the canonical consumer marketplace and shared object store."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace

from agent_artifacts.application.configuration import (
    ConfigurationPorts,
    ConfigurationRequest,
    load_configuration,
)
from agent_artifacts.application.sources import SourceStatusRequest, source_status
from agent_artifacts.compiler.graph import GraphSource, compile_marketplace_graph
from agent_artifacts.configuration.model import ConfiguredSource, SourceKind, UserConfiguration
from agent_artifacts.configuration.paths import Platform, resolve_config_paths
from agent_artifacts.configuration.policy import (
    EffectiveConfiguration,
    RuntimeOverrides,
    apply_configuration,
)
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ArtifactCoordinate, SourceAlias
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.installation.model import InstallLocation
from agent_artifacts.io.config_store import (
    read_configuration,
    recover_configuration,
    write_configuration,
)
from agent_artifacts.io.object_store import publish_object
from agent_artifacts.io.source_store import (
    acquire_source_lock,
    read_current_source,
    release_source_lock,
)
from agent_artifacts.marketplace.catalog import build_marketplace, resolve_artifact
from agent_artifacts.marketplace.model import (
    ArtifactQuery,
    MarketplaceCatalog,
    MarketplaceSourceState,
)
from agent_artifacts.profiles.builtin import builtin
from agent_artifacts.protocol.native_schema import parse_source_manifest
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    load_native_source,
)
from agent_artifacts.protocol.paths import SafeRelativePath, parse_relative_path
from agent_artifacts.protocol.registry_index import index_artifact_from_package
from agent_artifacts.protocol.registry_models import IndexArtifact, LockedArtifact, RegistryEntry
from agent_artifacts.protocol.registry_schema import (
    parse_registry_entry,
    parse_registry_index,
    parse_registry_lock,
    parse_registry_manifest,
)
from agent_artifacts.protocol.registry_tree import (
    registry_inputs_digest,
    resolve_locked_references,
)
from agent_artifacts.registry_maintenance.model import NativeReferenceAcquisition
from agent_artifacts.registry_maintenance.planning import (
    registry_native_content,
    resolve_native_acquisition,
)
from agent_artifacts.runtime_contract import EXECUTABLE_CAPABILITIES, EXECUTABLE_VERSION
from agent_artifacts.security.aggregation import ArtifactSecurityEvidence
from agent_artifacts.security.application import verify_security_index
from agent_artifacts.security.attestation_schema import parse_security_index
from agent_artifacts.security.attestations import (
    AttestationTrust,
    AttestationTrustContext,
    ResolvedAttestation,
    resolve_attestation,
)
from agent_artifacts.security.model import (
    AssessmentCoverage,
    AssessmentStatus,
    FindingSeverity,
    SecurityAssessment,
    risk_from_evidence,
)
from agent_artifacts.sources.git import acquire_git_snapshot
from agent_artifacts.sources.model import (
    CurrentSource,
    CurrentSourceRequest,
    GitSnapshotRequest,
    SnapshotLimits,
    SourceHealth,
    SourceLockRequest,
    source_instance_id,
    source_store_paths,
)
from agent_artifacts.sources.runtime import observe_configured_source, sync_configured_source
from agent_artifacts.store.model import (
    ObjectPublishCommand,
    ObjectReadRequest,
    ObjectStorePaths,
    make_object_candidate,
    object_store_paths,
)

from .application import ConsumerApplicationService
from .io import LocalConsumerAdapter
from .model import ConsumerActionRequest, ConsumerContext

CONSUMER_RUNTIME_INVALID = DiagnosticCode("consumer-runtime-invalid")
# Compatibility aliases for existing internal callers.  New composition roots use the public
# executable contract instead of importing this module's private implementation details.
_VERSION = EXECUTABLE_VERSION
_CAPABILITIES = EXECUTABLE_CAPABILITIES
_ATTESTATION_TRUST_RANK = {
    AttestationTrust.UNVERIFIED: 0,
    AttestationTrust.LOCAL: 1,
    AttestationTrust.REGISTRY_REVIEWED: 2,
    AttestationTrust.COMPANY_REVIEWED: 3,
}


@dataclass(frozen=True, slots=True)
class _RegistryReferenceBinding:
    coordinate: ArtifactCoordinate
    entry: RegistryEntry
    locked: LockedArtifact
    indexed: IndexArtifact


@dataclass(frozen=True, slots=True)
class _GraphProjection:
    graph: GraphSource
    references: tuple[_RegistryReferenceBinding, ...] = ()


def _error(message: str) -> Err:
    return Err((Diagnostic(CONSUMER_RUNTIME_INVALID, Severity.ERROR, message),))


def _offline_object_missing(coordinate: ArtifactCoordinate) -> Err:
    return Err(
        (
            Diagnostic(
                DiagnosticCode("offline-object-missing"),
                Severity.ERROR,
                f"offline mode cannot fetch uncached registry content for {coordinate}",
                remediation=("retry without offline mode while the registry origin is reachable",),
            ),
        )
    )


def _entry(snapshot, path: str) -> SnapshotEntry | None:
    return next((item for item in snapshot.entries if str(item.path) == path), None)


def _package_entries(snapshot, root: SafeRelativePath) -> Result[tuple[SnapshotEntry, ...]]:
    prefix = f"{root}/"
    result = []
    for item in snapshot.entries:
        raw = str(item.path)
        if not raw.startswith(prefix):
            continue
        relative = parse_relative_path(raw.removeprefix(prefix))
        if isinstance(relative, Err):
            return relative
        result.append(SnapshotEntry(relative.value, item.kind, item.content, item.executable))
    if not result:
        return _error(f"canonical package is absent from its source snapshot: {root}")
    return Ok(tuple(result))


def _package_root(snapshot, native, identity) -> SafeRelativePath:
    matches = tuple(
        SafeRelativePath((*root.parts, identity.kind, identity.name))
        for root in native.manifest.artifact_roots
        if _entry(snapshot, f"{root}/{identity.kind}/{identity.name}/artifact.json") is not None
    )
    if len(matches) != 1:
        raise ValueError(f"canonical package root is ambiguous: {identity}")
    return matches[0]


def _index_native(
    snapshot,
    native,
    paths: ObjectStorePaths | None,
    expected_by_identity=None,
):
    """Validate native packages into graph index records, optionally publishing their objects."""

    indexed = []
    for package in native.artifacts:
        try:
            root = _package_root(snapshot, native, package.manifest.identity)
        except ValueError as error:
            return _error(str(error))
        entries = _package_entries(snapshot, root)
        if isinstance(entries, Err):
            return entries
        expected = (
            None
            if expected_by_identity is None
            else expected_by_identity.get(package.manifest.identity)
        )
        candidate = make_object_candidate(entries.value, expected_digest=expected)
        if isinstance(candidate, Err):
            return candidate
        if paths is not None:
            published = publish_object(ObjectPublishCommand(paths, candidate.value))
            if isinstance(published, Err):
                return published
        indexed.append(
            index_artifact_from_package(
                package,
                source_id=native.manifest.source_id,
                object_digest=candidate.value.digest,
            )
        )
    return Ok(tuple(indexed))


def _materialize_native(snapshot, native, paths, expected_by_identity=None):
    """Compatibility wrapper for the consumer service's object-materializing composition path."""

    return _index_native(snapshot, native, paths, expected_by_identity)


def _verify_registry_owned(
    snapshot,
    source,
    owned,
    paths: ObjectStorePaths | None,
) -> Result[None]:
    """Verify registry-owned packages and optionally materialize their immutable objects.

    Read-only discovery still has to bind each package to the digest committed in the registry
    index.  It may skip only the final object-store publication effect, never that verification.
    """

    for artifact in owned:
        roots = tuple(
            SafeRelativePath((*root.parts, artifact.identity.kind, artifact.identity.name))
            for root in source.artifact_roots
            if _entry(
                snapshot,
                f"{root}/{artifact.identity.kind}/{artifact.identity.name}/artifact.json",
            )
            is not None
        )
        if len(roots) != 1:
            return _error(f"registry-owned package path is ambiguous: {artifact.identity}")
        entries = _package_entries(snapshot, roots[0])
        if isinstance(entries, Err):
            return entries
        candidate = make_object_candidate(
            entries.value,
            expected_digest=artifact.object_digest,
        )
        if isinstance(candidate, Err):
            return candidate
        if paths is not None:
            published = publish_object(ObjectPublishCommand(paths, candidate.value))
            if isinstance(published, Err):
                return published
    return Ok(None)


def _materialize_registry_owned(snapshot, source, owned, paths) -> Result[None]:
    """Compatibility wrapper for the object-materializing consumer service path."""

    return _verify_registry_owned(snapshot, source, owned, paths)


def _registry_entries(snapshot) -> Result[tuple[RegistryEntry, ...]]:
    entries = []
    for item in snapshot.entries:
        raw = str(item.path)
        if not raw.startswith("entries/"):
            continue
        if item.kind is SnapshotEntryKind.DIRECTORY:
            continue
        if item.kind is not SnapshotEntryKind.FILE:
            return _error(f"registry entry must be a regular file: {raw}")
        parsed = parse_registry_entry(item.content, path=raw)
        if isinstance(parsed, Err):
            return parsed
        expected = f"entries/{parsed.value.identity.kind}/{parsed.value.identity.name}.json"
        if raw != expected:
            return _error(f"registry entry identity does not match its path: {raw}")
        entries.append(parsed.value)
    identities = tuple(item.identity for item in entries)
    if len(set(identities)) != len(identities):
        return _error("registry contains duplicate external-reference identities")
    return Ok(tuple(sorted(entries, key=lambda item: str(item.identity))))


def _locked_index_agrees(locked: LockedArtifact, indexed: IndexArtifact) -> bool:
    return (
        indexed.version == locked.artifact_version
        and indexed.manifest_digest == locked.manifest_digest
        and indexed.payload_digest == locked.payload_digest
        and indexed.object_digest == locked.object_digest
        and indexed.review == locked.review
        and (indexed.provenance is None) == (locked.provenance_digest is None)
    )


def _registry_references(
    configured,
    current,
    snapshot,
    source_id,
    index,
    owned: tuple[IndexArtifact, ...],
) -> Result[tuple[_RegistryReferenceBinding, ...]]:
    if source_id != current.declared_source_id or index.registry_id != current.declared_source_id:
        return _error(f"registry {configured.alias} compiled identity does not match its source")
    inputs = registry_inputs_digest(snapshot)
    if isinstance(inputs, Err):
        return inputs
    if index.registry_inputs_digest != inputs.value:
        return _error(f"registry {configured.alias} compiled index is stale")
    entries = _registry_entries(snapshot)
    if isinstance(entries, Err):
        return entries
    lock_entry = _entry(snapshot, "aart.lock.json")
    if lock_entry is None:
        if entries.value:
            return _error(f"registry {configured.alias} has no committed aart.lock.json")
        locked_by_identity = {}
    else:
        if lock_entry.kind is not SnapshotEntryKind.FILE:
            return _error(f"registry {configured.alias} lock must be a regular file")
        lock = parse_registry_lock(lock_entry.content)
        if isinstance(lock, Err):
            return lock
        resolved = resolve_locked_references(
            entries.value,
            lock.value,
            expected_inputs_digest=inputs.value,
            registry_origin_url=configured.location,
        )
        if isinstance(resolved, Err):
            return resolved
        locked_by_identity = dict(lock.value.entries)
        if set(locked_by_identity) != {item.identity for item in entries.value}:
            return _error(f"registry {configured.alias} lock identities are incomplete")

    indexed_by_identity = {item.identity: item for item in index.artifacts}
    if len(indexed_by_identity) != len(index.artifacts):
        return _error(f"registry {configured.alias} index contains duplicate identities")
    owned_by_identity = {item.identity: item for item in owned}
    expected_identities = set(owned_by_identity) | {item.identity for item in entries.value}
    if set(indexed_by_identity) != expected_identities:
        return _error(f"registry {configured.alias} index identities are incomplete")
    for identity, actual in owned_by_identity.items():
        if replace(indexed_by_identity[identity], collections=()) != actual:
            return _error(f"registry {configured.alias} index disagrees with owned {identity}")

    bindings = []
    for entry in entries.value:
        locked = locked_by_identity[entry.identity]
        indexed = indexed_by_identity[entry.identity]
        if not _locked_index_agrees(locked, indexed):
            return _error(f"registry {configured.alias} lock/index disagree for {entry.identity}")
        bindings.append(
            _RegistryReferenceBinding(
                ArtifactCoordinate(
                    configured.alias,
                    entry.identity,
                    str(indexed.version),
                ),
                entry,
                locked,
                indexed,
            )
        )
    return Ok(tuple(bindings))


def _project_graph_source(
    configured,
    current,
    paths: ObjectStorePaths,
    *,
    materialize_objects: bool = True,
) -> Result[_GraphProjection]:
    snapshot = current.candidate.snapshot
    if configured.kind is not SourceKind.REGISTRY_GIT:
        native = load_native_source(
            snapshot,
            executable_version=_VERSION,
            available_capabilities=_CAPABILITIES,
        )
        if isinstance(native, Err):
            return native
        indexed = _index_native(
            snapshot,
            native.value,
            paths if materialize_objects else None,
        )
        if isinstance(indexed, Err):
            return indexed
        return Ok(
            _GraphProjection(
                GraphSource(
                    configured.alias,
                    native.value.manifest.source_id,
                    native.value.manifest.required_capabilities,
                    indexed.value,
                    native.value.collections,
                )
            )
        )

    files = {str(item.path): item for item in snapshot.entries}
    source_entry = files.get("aart-source.json")
    registry_entry = files.get("aart-registry.json")
    if (
        source_entry is None
        or source_entry.kind is not SnapshotEntryKind.FILE
        or registry_entry is None
        or registry_entry.kind is not SnapshotEntryKind.FILE
    ):
        return _error(f"registry {configured.alias} has invalid root manifests")
    source = parse_source_manifest(source_entry.content)
    registry = parse_registry_manifest(registry_entry.content)
    if isinstance(source, Err):
        return source
    if isinstance(registry, Err):
        return registry
    owned = registry_native_content(
        snapshot,
        files,
        registry.value,
        executable_version=_VERSION,
        available_capabilities=_CAPABILITIES,
    )
    if isinstance(owned, Err):
        return owned
    compiled_entry = _entry(snapshot, "aart.index.json")
    if compiled_entry is None or compiled_entry.kind is not SnapshotEntryKind.FILE:
        return _error(f"registry {configured.alias} has no committed aart.index.json")
    parsed = parse_registry_index(compiled_entry.content)
    if isinstance(parsed, Err):
        return parsed
    index = parsed.value
    if (
        index.registry_id != registry.value.registry_id
        or index.protocol_version != registry.value.protocol_version
        or index.services != registry.value.services
        or index.collections != owned.value[1]
    ):
        return _error(f"registry {configured.alias} compiled index is stale")
    materialized = _verify_registry_owned(
        snapshot,
        source.value,
        owned.value[0],
        paths if materialize_objects else None,
    )
    if isinstance(materialized, Err):
        return materialized
    references = _registry_references(
        configured,
        current,
        snapshot,
        source.value.source_id,
        index,
        owned.value[0],
    )
    if isinstance(references, Err):
        return references
    # A registry coordinate is bound to the reviewed registry identity.  Upstream identity remains
    # in provenance/lock evidence; it must not make one registry source appear as several runtime
    # sources or bypass the registry trust overlay.
    artifacts = tuple(replace(item, source_id=index.registry_id) for item in index.artifacts)
    return Ok(
        _GraphProjection(
            GraphSource(
                configured.alias,
                index.registry_id,
                tuple(
                    sorted(
                        set(source.value.required_capabilities)
                        | set(registry.value.required_capabilities)
                    )
                ),
                artifacts,
                index.collections,
            ),
            references.value,
        )
    )


def _graph_source(configured, current, paths) -> Result[GraphSource]:
    projected = _project_graph_source(configured, current, paths)
    return projected if isinstance(projected, Err) else Ok(projected.value.graph)


def _acquire_registry_reference(
    binding: _RegistryReferenceBinding,
    store_paths,
) -> Result[None]:
    pinned_source = ConfiguredSource(
        binding.coordinate.source,
        SourceKind.SOURCE_GIT,
        binding.locked.origin_url,
        binding.locked.resolved_commit,
        True,
    )
    paths = source_store_paths(store_paths.root, source_instance_id(pinned_source))
    lease = acquire_source_lock(SourceLockRequest(paths.lock_directory, 30.0, 300))
    if isinstance(lease, Err):
        return lease
    acquired = acquire_git_snapshot(
        GitSnapshotRequest(
            source_instance_id(pinned_source),
            binding.coordinate.source,
            binding.locked.origin_url,
            binding.locked.resolved_commit,
            paths.mirror,
            paths.temporary_root,
            SnapshotLimits(),
            60,
        )
    )
    released = release_source_lock(lease.value)
    if isinstance(released, Err):
        if isinstance(acquired, Err):
            return Err((*acquired.diagnostics, *released.diagnostics))
        return released
    if isinstance(acquired, Err):
        return acquired
    resolved = resolve_native_acquisition(
        binding.entry,
        NativeReferenceAcquisition(
            binding.entry.source.url,
            binding.entry.source.ref,
            acquired.value.resolved_revision,
            acquired.value.snapshot,
        ),
        executable_version=_VERSION,
        available_capabilities=_CAPABILITIES,
    )
    if isinstance(resolved, Err):
        return resolved
    package, candidate, provenance_digest, source_id = resolved.value
    actual_lock = LockedArtifact(
        binding.entry.source.url,
        binding.entry.source.ref,
        acquired.value.resolved_revision,
        binding.entry.source.path,
        package.manifest_digest,
        package.payload_digest,
        candidate.digest,
        package.manifest.version,
        binding.entry.review,
        provenance_digest,
    )
    actual_index = index_artifact_from_package(
        package,
        source_id=source_id,
        object_digest=candidate.digest,
        review=binding.entry.review,
    )
    if actual_lock != binding.locked or actual_index != replace(
        binding.indexed,
        collections=(),
    ):
        return _error(
            f"pinned registry content does not match committed lock/index for {binding.coordinate}"
        )
    published = publish_object(ObjectPublishCommand(store_paths, candidate))
    return published if isinstance(published, Err) else Ok(None)


def _consumer_content_port(
    bindings: tuple[_RegistryReferenceBinding, ...],
    catalog: MarketplaceCatalog,
    adapter: LocalConsumerAdapter,
    store_paths,
):
    by_coordinate = {item.coordinate: item for item in bindings}

    def ensure(request: ConsumerActionRequest) -> Result[None]:
        if request.action not in {"install", "update"}:
            return Ok(None)
        selected = []
        requested = request.coordinates or tuple(sorted(by_coordinate, key=str))
        for coordinate in requested:
            exact = coordinate
            if request.action == "update":
                latest = resolve_artifact(
                    catalog,
                    ArtifactQuery(coordinate.artifact, coordinate.source),
                )
                if isinstance(latest, Err):
                    continue
                exact = latest.value.coordinate
            binding = by_coordinate.get(exact)
            if binding is not None:
                selected.append(binding)
        for binding in sorted(set(selected), key=lambda item: str(item.coordinate)):
            available = adapter.read_object(
                ObjectReadRequest(store_paths, binding.locked.object_digest)
            )
            if isinstance(available, Ok) and available.value is not None:
                continue
            if isinstance(available, Err) and any(
                item.code.value not in {"digest-mismatch", "store-invalid"}
                for item in available.diagnostics
            ):
                return available
            if request.offline:
                return _offline_object_missing(binding.coordinate)
            acquired = _acquire_registry_reference(binding, store_paths)
            if isinstance(acquired, Err):
                return acquired
        return Ok(None)

    return ensure


def _merged_security_evidence(
    coordinate: ArtifactCoordinate,
    resolved: tuple[ResolvedAttestation, ...],
    *,
    age_seconds: int,
) -> ArtifactSecurityEvidence | None:
    """Merge one current attestation per provider into explainable artifact evidence."""

    by_provider: dict[str, ResolvedAttestation] = {}
    for item in resolved:
        provider = item.assessment.providers[0]
        existing = by_provider.get(provider.id)
        if existing is None or provider.version > existing.assessment.providers[0].version:
            by_provider[provider.id] = item
    selected = tuple(by_provider[key] for key in sorted(by_provider))
    if not selected:
        return None
    providers = tuple(item.assessment.providers[0] for item in selected)
    statuses = {provider.status for provider in providers}
    if AssessmentStatus.STALE in statuses:
        status = AssessmentStatus.STALE
    elif AssessmentStatus.FAILED in statuses:
        status = AssessmentStatus.FAILED
    elif statuses == {AssessmentStatus.COMPLETE}:
        status = AssessmentStatus.COMPLETE
    elif statuses == {AssessmentStatus.NOT_SCANNED}:
        status = AssessmentStatus.NOT_SCANNED
    else:
        status = AssessmentStatus.PARTIAL
    coverage = (
        providers[0].coverage
        if len(providers) == 1
        else AssessmentCoverage(
            sum(provider.coverage.completed for provider in providers),
            sum(provider.coverage.expected for provider in providers),
            tuple(
                f"{provider.id}:{reason}"
                for provider in providers
                for reason in provider.coverage.skipped
            ),
        )
    )
    findings_by_fingerprint = {
        finding.fingerprint: finding for item in selected for finding in item.assessment.findings
    }
    findings = tuple(findings_by_fingerprint.values())
    maximum = max(
        (finding.severity for finding in findings),
        key=lambda severity: severity.rank,
        default=FindingSeverity.UNKNOWN,
    )
    try:
        assessment = SecurityAssessment(
            1,
            selected[0].assessment.object_digest,
            status,
            risk_from_evidence(status, maximum),
            maximum,
            coverage,
            findings,
            providers,
        )
    except ValueError:
        return None
    trust = min(
        (item.trust for item in selected),
        key=lambda item: _ATTESTATION_TRUST_RANK[item],
    )
    return ArtifactSecurityEvidence(coordinate, assessment, trust, age_seconds)


def _registry_security_evidence(
    catalog: MarketplaceCatalog,
    registry_sources: tuple[tuple[ConfiguredSource, CurrentSource], ...],
    *,
    now: int,
) -> tuple[ArtifactSecurityEvidence, ...]:
    """Verify optional committed registry attestations and bind them to exact coordinates."""

    evidence = []
    for configured, current in registry_sources:
        snapshot = current.candidate.snapshot
        security_entry = _entry(snapshot, "security/index.json")
        compiled_entry = _entry(snapshot, "aart.index.json")
        if security_entry is None or compiled_entry is None:
            continue
        security_index = parse_security_index(security_entry.content)
        compiled_index = parse_registry_index(compiled_entry.content)
        if isinstance(security_index, Err) or isinstance(compiled_index, Err):
            continue
        index = security_index.value
        if (
            index.registry_id != compiled_index.value.registry_id
            or index.registry_inputs_digest != compiled_index.value.registry_inputs_digest
            or index.registry_id != current.declared_source_id
        ):
            continue
        documents = []
        for index_entry in index.entries:
            document = _entry(snapshot, str(index_entry.path))
            if document is None:
                break
            documents.append((index_entry.path, document.content))
        else:
            verified = verify_security_index(index, tuple(documents))
            if isinstance(verified, Err):
                continue
            age = max(now - current.published_at_epoch_seconds, 0)
            for item in catalog.items:
                if item.source.alias != configured.alias:
                    continue
                matching = tuple(
                    resolve_attestation(
                        attestation,
                        attestation.cache_key,
                        trust_context=AttestationTrustContext(
                            index.registry_id,
                            index.registry_inputs_digest,
                            item.trust.kind,
                        ),
                    )
                    for attestation in verified.value.attestations
                    if attestation.cache_key.object_digest == item.artifact.artifact.object_digest
                )
                merged = _merged_security_evidence(item.coordinate, matching, age_seconds=age)
                if merged is not None:
                    evidence.append(merged)
    return tuple(evidence)


def load_read_only_marketplace(
    effective: EffectiveConfiguration,
    *,
    data_root: str,
    observe_freshness: bool = False,
) -> Result[MarketplaceCatalog]:
    """Build the configured marketplace from durable snapshots without object-store mutation.

    This is intentionally narrower than :func:`load_local_consumer_service`: it receives the
    already-resolved effective configuration from its caller, never rereads configuration, and
    validates packages into graph/index values without materializing immutable objects.  Object
    publication remains an install/update concern owned by the consumer service.
    """

    now = int(time.time())
    states = []
    graph_sources = []
    paths = object_store_paths(data_root)
    for order, configured in enumerate(
        source for source in effective.configuration.sources if source.enabled
    ):
        source_paths = source_store_paths(data_root, source_instance_id(configured))
        health: SourceHealth
        if observe_freshness:
            health = observe_configured_source(
                configured,
                data_root=data_root,
                mode=effective.configuration.sync.mode,
                observed_at_epoch_seconds=now,
            )
        else:
            health = source_status(
                SourceStatusRequest(
                    CurrentSourceRequest(source_paths, configured.alias),
                    now,
                    effective.configuration.sync.max_age_seconds,
                ),
                read_current_source,
            )
        states.append(MarketplaceSourceState(configured, health, order))
        if health.current is None:
            continue
        projected = _project_graph_source(
            configured,
            health.current,
            paths,
            materialize_objects=False,
        )
        if isinstance(projected, Err):
            return projected
        graph_sources.append(projected.value.graph)
    graph = compile_marketplace_graph(
        tuple(graph_sources),
        available_capabilities=_CAPABILITIES,
    )
    if isinstance(graph, Err):
        return graph
    return build_marketplace(graph.value, effective, tuple(states))


def load_local_consumer_service(
    *,
    project: str | None,
    user_home: str | None,
    configuration: UserConfiguration | None = None,
    refresh_sources: bool = False,
    observe_freshness: bool = False,
    offline: bool = False,
    content_required: bool = True,
) -> Result[ConsumerApplicationService]:
    """Load a consumer service, optionally refreshing every configured origin first.

    ``content_required`` is the canonical no-source contract: a content operation needs at least one
    enabled source, and every organization-required alias.  Uninstall is the one lifecycle operation
    that is not a content operation — it reads the manifest — so it passes ``False`` rather than
    refusing to remove what a project already has because the subscription it came from is gone.
    """

    platform = Platform.DARWIN if sys.platform == "darwin" else Platform.LINUX
    home = os.path.abspath(user_home or os.path.expanduser("~"))
    config_paths = resolve_config_paths(
        platform,
        home=home,
        xdg_config_home=os.environ.get("XDG_CONFIG_HOME"),
        xdg_data_home=os.environ.get("XDG_DATA_HOME"),
        xdg_cache_home=os.environ.get("XDG_CACHE_HOME"),
    )
    loaded = load_configuration(
        ConfigurationRequest(
            config_paths,
            RuntimeOverrides(),
            content_required=content_required and configuration is None,
        ),
        ConfigurationPorts(
            read_configuration,
            write_configuration,
            recover_configuration,
        ),
    )
    if isinstance(loaded, Err):
        return loaded
    if configuration is None:
        effective = loaded.value.effective
    else:
        prospective = apply_configuration(
            configuration,
            RuntimeOverrides(),
            loaded.value.effective.policy,
        )
        if isinstance(prospective, Err):
            return prospective
        effective = prospective.value
    observed_health: Mapping[SourceAlias, SourceHealth] = {}
    if observe_freshness and not offline:
        observed_health = {
            source.alias: observe_configured_source(
                source,
                data_root=config_paths.data_root,
                mode=effective.configuration.sync.mode,
            )
            for source in effective.configuration.sources
            if source.enabled
        }
    elif refresh_sources and not offline:
        for source in effective.configuration.sources:
            if not source.enabled:
                continue
            refreshed = sync_configured_source(source, data_root=config_paths.data_root)
            if isinstance(refreshed, Err):
                return refreshed
    now = int(time.time())
    states = []
    graph_sources = []
    registry_sources = []
    registry_references: list[_RegistryReferenceBinding] = []
    store_paths = object_store_paths(config_paths.data_root)
    for order, configured in enumerate(
        source for source in effective.configuration.sources if source.enabled
    ):
        paths = source_store_paths(config_paths.data_root, source_instance_id(configured))
        health = observed_health.get(configured.alias)
        if health is None:
            health = source_status(
                SourceStatusRequest(
                    CurrentSourceRequest(paths, configured.alias),
                    now,
                    effective.configuration.sync.max_age_seconds,
                ),
                read_current_source,
            )
        states.append(MarketplaceSourceState(configured, health, order))
        if health.current is None:
            continue
        if configured.kind is SourceKind.REGISTRY_GIT:
            registry_sources.append((configured, health.current))
        projected = _project_graph_source(configured, health.current, store_paths)
        if isinstance(projected, Err):
            return projected
        graph_sources.append(projected.value.graph)
        registry_references.extend(projected.value.references)
    graph = compile_marketplace_graph(
        tuple(graph_sources),
        available_capabilities=_CAPABILITIES,
    )
    if isinstance(graph, Err):
        return graph
    catalog = build_marketplace(graph.value, effective, tuple(states))
    if isinstance(catalog, Err):
        return catalog
    security = _registry_security_evidence(catalog.value, tuple(registry_sources), now=now)
    location = InstallLocation(
        os.path.abspath(project or os.getcwd()),
        home,
        config_paths.data_root,
    )
    context = ConsumerContext(
        catalog.value,
        effective,
        builtin(),
        location,
        store_paths,
        security,
    )
    adapter = LocalConsumerAdapter()
    return Ok(
        ConsumerApplicationService(
            context,
            adapter,
            _consumer_content_port(
                tuple(registry_references),
                catalog.value,
                adapter,
                store_paths,
            ),
        )
    )


__all__ = [
    "CONSUMER_RUNTIME_INVALID",
    "load_local_consumer_service",
    "load_read_only_marketplace",
]
