"""Pure compilation of source records into a deterministic marketplace graph."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable

from agent_artifacts.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    Severity,
    SourceLocation,
    sort_diagnostics,
)
from agent_artifacts.domain.identifiers import (
    ArtifactCoordinate,
    ArtifactIdentity,
    ObjectDigest,
    SourceAlias,
    SourceId,
)
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.hashing import json_digest
from agent_artifacts.protocol.json import JsonArray, JsonObject, JsonValue, canonical_json_bytes
from agent_artifacts.protocol.native_models import (
    CollectionManifest,
    CompatibilitySpec,
    InstallEffect,
    InstallMode,
    InstallScope,
    InstallSpec,
)
from agent_artifacts.protocol.registry_models import IndexArtifact, IndexSetup
from agent_artifacts.protocol.semver import SemVer, version_bounds_label

from .model import PhaseOutput, phase_output

MARKETPLACE_GRAPH_INVALID = DiagnosticCode("marketplace-graph-invalid")
SOURCE_INCOMPATIBLE = DiagnosticCode("source-incompatible")
ARTIFACT_INCOMPATIBLE = DiagnosticCode("artifact-incompatible")
ARTIFACT_NOT_FOUND = DiagnosticCode("artifact-not-found")
ARTIFACT_VERSION_UNCHANGED = DiagnosticCode("artifact-version-unchanged")
ARTIFACT_VERSION_REGRESSED = DiagnosticCode("artifact-version-regressed")
ARTIFACT_VERSION_WITHOUT_CONTENT = DiagnosticCode("artifact-version-without-content")


class ArtifactLifecycle(str, Enum):
    AVAILABLE = "available"
    REMOVED = "removed"


class SelectionMode(str, Enum):
    BROAD = "broad"
    EXPLICIT = "explicit"


@dataclass(frozen=True, slots=True, order=True)
class CollectionCoordinate:
    source: SourceAlias
    name: str

    def __post_init__(self) -> None:
        if not self.source.value or not self.name:
            raise ValueError("collection coordinate must be qualified and non-empty")

    def __str__(self) -> str:
        return f"{self.source}/collection/{self.name}"


def _artifact_sort_key(
    coordinate: ArtifactCoordinate,
) -> tuple[str, str, str, str]:
    return (
        coordinate.source.value,
        coordinate.artifact.kind,
        coordinate.artifact.name,
        coordinate.version or "",
    )


@dataclass(frozen=True, slots=True)
class GraphSource:
    alias: SourceAlias
    source_id: SourceId
    required_capabilities: tuple[Capability, ...]
    artifacts: tuple[IndexArtifact, ...]
    collections: tuple[CollectionManifest, ...] = ()

    def __post_init__(self) -> None:
        if not self.alias.value or not self.source_id.value:
            raise ValueError("graph source alias and source ID must be non-empty")
        object.__setattr__(
            self,
            "required_capabilities",
            tuple(sorted(set(self.required_capabilities))),
        )
        object.__setattr__(
            self,
            "artifacts",
            tuple(
                sorted(
                    self.artifacts,
                    key=lambda item: (
                        item.identity.kind,
                        item.identity.name,
                        str(item.version),
                        str(item.object_digest),
                    ),
                )
            ),
        )
        object.__setattr__(
            self,
            "collections",
            tuple(sorted(self.collections, key=lambda item: item.name)),
        )


@dataclass(frozen=True, slots=True, order=True)
class CompatibilityReason:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class CompatibilityTarget:
    profile: str
    platform: str
    scope: InstallScope
    mode: InstallMode
    effects: tuple[InstallEffect, ...]
    aart_version: SemVer
    setup_capabilities: tuple[Capability, ...] = ()
    require_setup: bool = True

    def __post_init__(self) -> None:
        if not self.profile or not self.platform:
            raise ValueError("compatibility target profile and platform must be non-empty")
        if self.scope not in {"project", "user"}:
            raise ValueError("compatibility target scope is invalid")
        if self.mode not in {"copy", "symlink"}:
            raise ValueError("compatibility target mode is invalid")
        if not set(self.effects) <= {
            "copy-tree",
            "write-file",
            "merge-json",
            "managed-block",
        }:
            raise ValueError("compatibility target effects are invalid")
        if not isinstance(self.require_setup, bool):
            raise ValueError("require_setup must be a boolean")
        if not isinstance(self.aart_version, SemVer):
            raise ValueError("aart_version must be a SemVer")
        object.__setattr__(self, "effects", tuple(sorted(set(self.effects))))
        object.__setattr__(
            self,
            "setup_capabilities",
            tuple(sorted(set(self.setup_capabilities))),
        )


@dataclass(frozen=True, slots=True)
class CompatibilityDecision:
    payload_reasons: tuple[CompatibilityReason, ...]
    setup_reasons: tuple[CompatibilityReason, ...]
    setup_required: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload_reasons", tuple(sorted(set(self.payload_reasons))))
        object.__setattr__(self, "setup_reasons", tuple(sorted(set(self.setup_reasons))))

    @property
    def reasons(self) -> tuple[CompatibilityReason, ...]:
        blocking_setup = self.setup_reasons if self.setup_required else ()
        return tuple(sorted((*self.payload_reasons, *blocking_setup)))

    @property
    def payload_compatible(self) -> bool:
        return not self.payload_reasons

    @property
    def setup_compatible(self) -> bool:
        return not self.setup_reasons

    @property
    def compatible(self) -> bool:
        return self.payload_compatible and (self.setup_compatible or not self.setup_required)


@dataclass(frozen=True, slots=True)
class MarketplaceArtifact:
    source_alias: SourceAlias
    source_id: SourceId
    artifact: IndexArtifact
    semantic_digest: ObjectDigest
    lifecycle: ArtifactLifecycle = ArtifactLifecycle.AVAILABLE

    def __post_init__(self) -> None:
        if not self.source_alias.value or self.source_id != self.artifact.source_id:
            raise ValueError("marketplace artifact must retain its qualified source identity")
        if not isinstance(self.lifecycle, ArtifactLifecycle):
            raise ValueError("marketplace artifact lifecycle is invalid")
        if self.semantic_digest != json_digest(_semantic_json(self.artifact)):
            raise ValueError("marketplace semantic digest must bind normalized artifact semantics")

    @property
    def coordinate(self) -> ArtifactCoordinate:
        return ArtifactCoordinate(
            self.source_alias,
            self.artifact.identity,
            str(self.artifact.version),
        )


@dataclass(frozen=True, slots=True)
class MarketplaceCollection:
    coordinate: CollectionCoordinate
    summary: str
    members: tuple[ArtifactCoordinate, ...]

    def __post_init__(self) -> None:
        if any(member.source != self.coordinate.source for member in self.members):
            raise ValueError("protocol v1 collections may reference only their qualified source")
        object.__setattr__(
            self,
            "members",
            tuple(sorted(set(self.members), key=_artifact_sort_key)),
        )


@dataclass(frozen=True, slots=True)
class MarketplaceGraph:
    artifacts: tuple[MarketplaceArtifact, ...]
    collections: tuple[MarketplaceCollection, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        artifact_keys = tuple(
            _artifact_key(item.source_alias, item.artifact.identity) for item in self.artifacts
        )
        collection_keys = tuple(item.coordinate for item in self.collections)
        if len(set(artifact_keys)) != len(artifact_keys):
            raise ValueError("marketplace graph artifacts must be qualified and unique")
        if len(set(collection_keys)) != len(collection_keys):
            raise ValueError("marketplace graph collections must be qualified and unique")
        object.__setattr__(
            self,
            "artifacts",
            tuple(sorted(self.artifacts, key=lambda item: _artifact_sort_key(item.coordinate))),
        )
        object.__setattr__(
            self,
            "collections",
            tuple(sorted(self.collections, key=lambda item: item.coordinate)),
        )
        object.__setattr__(self, "diagnostics", sort_diagnostics(self.diagnostics))


@dataclass(frozen=True, slots=True)
class SelectionSkip:
    coordinate: ArtifactCoordinate
    reasons: tuple[CompatibilityReason, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "reasons", tuple(sorted(set(self.reasons))))


@dataclass(frozen=True, slots=True)
class SelectionRequest:
    mode: SelectionMode
    target: CompatibilityTarget
    artifacts: tuple[ArtifactCoordinate, ...] = ()
    collections: tuple[CollectionCoordinate, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.mode, SelectionMode):
            raise ValueError("selection mode is invalid")
        object.__setattr__(
            self,
            "artifacts",
            tuple(sorted(set(self.artifacts), key=_artifact_sort_key)),
        )
        object.__setattr__(self, "collections", tuple(sorted(set(self.collections))))


@dataclass(frozen=True, slots=True)
class SelectionResult:
    selected: tuple[MarketplaceArtifact, ...]
    skipped: tuple[SelectionSkip, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "selected",
            tuple(sorted(self.selected, key=lambda item: _artifact_sort_key(item.coordinate))),
        )
        object.__setattr__(
            self,
            "skipped",
            tuple(sorted(self.skipped, key=lambda item: _artifact_sort_key(item.coordinate))),
        )


def _location(alias: SourceAlias) -> SourceLocation:
    return SourceLocation(source=alias)


def _diagnostic(
    code: DiagnosticCode,
    message: str,
    *,
    alias: SourceAlias | None = None,
    severity: Severity = Severity.ERROR,
    details: tuple[tuple[str, str], ...] = (),
) -> Diagnostic:
    return Diagnostic(
        code,
        severity,
        message,
        None if alias is None else _location(alias),
        details=details,
    )


def _strings(values: Iterable[object]) -> JsonArray:
    return JsonArray(tuple(str(item) for item in sorted(values, key=str)))


def _setup_json(setup: IndexSetup | None) -> JsonValue:
    if setup is None:
        return None
    return JsonObject(
        (
            ("capabilities", _strings(setup.capabilities)),
            ("platforms", _strings(setup.platforms)),
            ("recipe", str(setup.recipe)),
        )
    )


def _semantic_json(artifact: IndexArtifact) -> JsonObject:
    entries: list[tuple[str, JsonValue]] = list(
        (
            (
                "compatibility",
                JsonObject(
                    (
                        ("platforms", _strings(artifact.compatibility.platforms)),
                        ("profiles", _strings(artifact.compatibility.profiles)),
                    )
                ),
            ),
            (
                "install",
                JsonObject(
                    (
                        ("effects", _strings(artifact.install.effects)),
                        ("modes", _strings(artifact.install.modes)),
                        ("scopes", _strings(artifact.install.scopes)),
                    )
                ),
            ),
            ("payload_digest", str(artifact.payload_digest)),
            ("setup", _setup_json(artifact.setup)),
        )
    )
    bounds = artifact.requires_aart
    if bounds.min_inclusive is not None or bounds.max_exclusive is not None:
        entries.append(
            (
                "requires_aart",
                JsonObject(
                    tuple(
                        entry
                        for entry in (
                            (
                                "min_inclusive",
                                None if bounds.min_inclusive is None else str(bounds.min_inclusive),
                            ),
                            (
                                "max_exclusive",
                                None if bounds.max_exclusive is None else str(bounds.max_exclusive),
                            ),
                        )
                        if entry[1] is not None
                    )
                ),
            )
        )
    return JsonObject(tuple(entries))


def _normalize_artifact(artifact: IndexArtifact) -> IndexArtifact:
    setup = artifact.setup
    if setup is not None:
        setup = replace(
            setup,
            platforms=tuple(sorted(set(setup.platforms))),
            capabilities=tuple(sorted(set(setup.capabilities))),
        )
    return replace(
        artifact,
        compatibility=CompatibilitySpec(
            tuple(sorted(set(artifact.compatibility.profiles))),
            tuple(sorted(set(artifact.compatibility.platforms))),
        ),
        install=InstallSpec(
            tuple(sorted(set(artifact.install.scopes))),
            tuple(sorted(set(artifact.install.modes))),
            tuple(sorted(set(artifact.install.effects))),
        ),
        setup=setup,
        collections=tuple(sorted(set(artifact.collections))),
    )


def _marketplace_artifact(source: GraphSource, artifact: IndexArtifact) -> MarketplaceArtifact:
    normalized = _normalize_artifact(artifact)
    return MarketplaceArtifact(
        source.alias,
        source.source_id,
        normalized,
        json_digest(_semantic_json(normalized)),
    )


def _artifact_key(
    alias: SourceAlias,
    identity: ArtifactIdentity,
) -> tuple[SourceAlias, ArtifactIdentity]:
    return (alias, identity)


def _expand_collection_members(
    coordinate: CollectionCoordinate,
    manifests: dict[CollectionCoordinate, CollectionManifest],
    artifacts: dict[tuple[SourceAlias, ArtifactIdentity], MarketplaceArtifact],
    memo: dict[CollectionCoordinate, tuple[ArtifactCoordinate, ...]],
    visiting: tuple[CollectionCoordinate, ...],
) -> Result[tuple[ArtifactCoordinate, ...]]:
    cached = memo.get(coordinate)
    if cached is not None:
        return Ok(cached)
    if coordinate in visiting:
        cycle = " -> ".join(str(item) for item in (*visiting, coordinate))
        return Err(
            (
                _diagnostic(
                    MARKETPLACE_GRAPH_INVALID,
                    f"collection cycle: {cycle}",
                    alias=coordinate.source,
                ),
            )
        )
    manifest = manifests.get(coordinate)
    if manifest is None:
        return Err(
            (
                _diagnostic(
                    MARKETPLACE_GRAPH_INVALID,
                    f"missing collection: {coordinate}",
                    alias=coordinate.source,
                ),
            )
        )
    members: dict[tuple[SourceAlias, ArtifactIdentity], ArtifactCoordinate] = {}
    for selector in manifest.artifacts:
        key = _artifact_key(coordinate.source, selector.identity)
        artifact = artifacts.get(key)
        if artifact is None:
            return Err(
                (
                    _diagnostic(
                        MARKETPLACE_GRAPH_INVALID,
                        f"collection {coordinate} references missing {selector.identity}",
                        alias=coordinate.source,
                    ),
                )
            )
        if selector.version is not None and not selector.version.allows(artifact.artifact.version):
            return Err(
                (
                    _diagnostic(
                        MARKETPLACE_GRAPH_INVALID,
                        f"collection {coordinate} excludes available version of {selector.identity}",
                        alias=coordinate.source,
                    ),
                )
            )
        members[key] = artifact.coordinate
    next_visiting = (*visiting, coordinate)
    for nested_name in manifest.collections:
        nested_coordinate = CollectionCoordinate(coordinate.source, nested_name)
        nested = _expand_collection_members(
            nested_coordinate,
            manifests,
            artifacts,
            memo,
            next_visiting,
        )
        if isinstance(nested, Err):
            return nested
        for item in nested.value:
            members[_artifact_key(item.source, item.artifact)] = item
    expanded = tuple(sorted(members.values(), key=_artifact_sort_key))
    memo[coordinate] = expanded
    return Ok(expanded)


def _compile_collections(
    sources: tuple[GraphSource, ...],
    artifacts: dict[tuple[SourceAlias, ArtifactIdentity], MarketplaceArtifact],
) -> Result[tuple[MarketplaceCollection, ...]]:
    manifests: dict[CollectionCoordinate, CollectionManifest] = {}
    diagnostics: list[Diagnostic] = []
    for source in sources:
        for manifest in source.collections:
            coordinate = CollectionCoordinate(source.alias, manifest.name)
            if coordinate in manifests:
                diagnostics.append(
                    _diagnostic(
                        MARKETPLACE_GRAPH_INVALID,
                        f"duplicate collection: {coordinate}",
                        alias=source.alias,
                    )
                )
            else:
                manifests[coordinate] = manifest
    if diagnostics:
        return Err(sort_diagnostics(diagnostics))
    memo: dict[CollectionCoordinate, tuple[ArtifactCoordinate, ...]] = {}
    compiled: list[MarketplaceCollection] = []
    for coordinate in sorted(manifests):
        members = _expand_collection_members(coordinate, manifests, artifacts, memo, ())
        if isinstance(members, Err):
            return members
        compiled.append(
            MarketplaceCollection(
                coordinate,
                manifests[coordinate].summary,
                members.value,
            )
        )
    return Ok(tuple(compiled))


def _history(
    current: dict[tuple[SourceAlias, ArtifactIdentity], MarketplaceArtifact],
    previous: MarketplaceGraph | None,
) -> Result[tuple[tuple[MarketplaceArtifact, ...], tuple[Diagnostic, ...]]]:
    if previous is None:
        return Ok((tuple(current.values()), ()))
    prior = {
        _artifact_key(item.source_alias, item.artifact.identity): item
        for item in previous.artifacts
    }
    diagnostics: list[Diagnostic] = []
    errors: list[Diagnostic] = []
    for key, artifact in current.items():
        old = prior.get(key)
        if old is None:
            continue
        current_version = artifact.artifact.version
        old_version = old.artifact.version
        if current_version < old_version:
            errors.append(
                _diagnostic(
                    ARTIFACT_VERSION_REGRESSED,
                    f"{artifact.coordinate} regressed from {old_version} to {current_version}",
                    alias=artifact.source_alias,
                )
            )
        elif current_version.same_precedence(old_version):
            if (
                artifact.semantic_digest != old.semantic_digest
                or artifact.artifact.manifest_digest != old.artifact.manifest_digest
                or artifact.artifact.payload_digest != old.artifact.payload_digest
                or artifact.artifact.object_digest != old.artifact.object_digest
            ):
                errors.append(
                    _diagnostic(
                        ARTIFACT_VERSION_UNCHANGED,
                        f"content or install semantics changed without a version precedence "
                        f"change for "
                        f"{artifact.source_alias}/{artifact.artifact.identity}",
                        alias=artifact.source_alias,
                    )
                )
        elif artifact.semantic_digest == old.semantic_digest:
            diagnostics.append(
                _diagnostic(
                    ARTIFACT_VERSION_WITHOUT_CONTENT,
                    f"version changed without semantic content change for {artifact.coordinate}",
                    alias=artifact.source_alias,
                    severity=Severity.WARNING,
                )
            )
    if errors:
        return Err(sort_diagnostics(errors))
    merged = dict(current)
    for key, old in prior.items():
        if key not in current:
            merged[key] = replace(old, lifecycle=ArtifactLifecycle.REMOVED)
    return Ok((tuple(merged.values()), sort_diagnostics(diagnostics)))


def compile_marketplace_graph(
    sources: Iterable[GraphSource],
    *,
    available_capabilities: Iterable[Capability],
    previous: MarketplaceGraph | None = None,
) -> Result[MarketplaceGraph]:
    """Normalize and validate a qualified, deterministic source/collection graph."""

    ordered_sources = tuple(sorted(sources, key=lambda item: item.alias.value))
    available = frozenset(available_capabilities)
    diagnostics: list[Diagnostic] = []
    aliases: set[SourceAlias] = set()
    source_ids: set[SourceId] = set()
    artifacts: dict[tuple[SourceAlias, ArtifactIdentity], MarketplaceArtifact] = {}
    for source in ordered_sources:
        if source.alias in aliases:
            diagnostics.append(
                _diagnostic(
                    MARKETPLACE_GRAPH_INVALID,
                    f"duplicate source alias: {source.alias}",
                    alias=source.alias,
                )
            )
        aliases.add(source.alias)
        if source.source_id in source_ids:
            diagnostics.append(
                _diagnostic(
                    MARKETPLACE_GRAPH_INVALID,
                    f"duplicate source ID: {source.source_id}",
                    alias=source.alias,
                )
            )
        source_ids.add(source.source_id)
        missing = tuple(
            capability for capability in source.required_capabilities if capability not in available
        )
        if missing:
            diagnostics.append(
                _diagnostic(
                    SOURCE_INCOMPATIBLE,
                    f"source {source.alias} requires unavailable capabilities: "
                    + ", ".join(map(str, missing)),
                    alias=source.alias,
                )
            )
        for artifact in source.artifacts:
            if artifact.source_id != source.source_id:
                diagnostics.append(
                    _diagnostic(
                        MARKETPLACE_GRAPH_INVALID,
                        f"artifact {artifact.identity} declares source ID {artifact.source_id}, "
                        f"expected {source.source_id}",
                        alias=source.alias,
                    )
                )
                continue
            key = _artifact_key(source.alias, artifact.identity)
            if key in artifacts:
                diagnostics.append(
                    _diagnostic(
                        MARKETPLACE_GRAPH_INVALID,
                        f"duplicate qualified artifact: {source.alias}/{artifact.identity}",
                        alias=source.alias,
                    )
                )
                continue
            artifacts[key] = _marketplace_artifact(source, artifact)
    if diagnostics:
        return Err(sort_diagnostics(diagnostics))
    collections = _compile_collections(ordered_sources, artifacts)
    if isinstance(collections, Err):
        return collections
    historical = _history(artifacts, previous)
    if isinstance(historical, Err):
        return historical
    historical_artifacts, history_diagnostics = historical.value
    return Ok(
        MarketplaceGraph(
            historical_artifacts,
            collections.value,
            history_diagnostics,
        )
    )


def compile_marketplace_graph_phase(
    sources: Iterable[GraphSource],
    *,
    available_capabilities: Iterable[Capability],
    previous: MarketplaceGraph | None = None,
) -> Result[PhaseOutput[MarketplaceGraph]]:
    """Compile the graph as a canonical typed output for a C01 compiler phase."""

    compiled = compile_marketplace_graph(
        sources,
        available_capabilities=available_capabilities,
        previous=previous,
    )
    if isinstance(compiled, Err):
        return compiled
    encoded = marketplace_graph_bytes(compiled.value)
    return Ok(
        phase_output(
            compiled.value,
            encoded,
            diagnostics=compiled.value.diagnostics,
        )
    )


def evaluate_compatibility(
    artifact: MarketplaceArtifact,
    target: CompatibilityTarget,
) -> CompatibilityDecision:
    payload: list[CompatibilityReason] = []
    setup: list[CompatibilityReason] = []
    manifest = artifact.artifact
    if not manifest.requires_aart.allows(target.aart_version):
        required = version_bounds_label(manifest.requires_aart)
        payload.append(
            CompatibilityReason(
                "aart-version-unsupported",
                f"artifact requires AART {required}; running AART {target.aart_version} may not "
                "support behavior used by this artifact, so installation is disabled",
            )
        )
    if artifact.lifecycle is ArtifactLifecycle.REMOVED:
        payload.append(
            CompatibilityReason("artifact-removed", "artifact was removed from its source")
        )
    if target.profile not in manifest.compatibility.profiles:
        payload.append(
            CompatibilityReason(
                "profile-unsupported",
                f"profile {target.profile!r} is not supported",
            )
        )
    if target.platform not in manifest.compatibility.platforms:
        payload.append(
            CompatibilityReason(
                "platform-unsupported",
                f"platform {target.platform!r} is not supported",
            )
        )
    if target.scope not in manifest.install.scopes:
        payload.append(
            CompatibilityReason(
                "scope-unsupported",
                f"scope {target.scope!r} is not supported",
            )
        )
    if target.mode not in manifest.install.modes:
        payload.append(
            CompatibilityReason(
                "mode-unsupported",
                f"mode {target.mode!r} is not supported",
            )
        )
    available_effects = frozenset(target.effects)
    for effect in manifest.install.effects:
        if effect not in available_effects:
            payload.append(
                CompatibilityReason(
                    "effect-unsupported",
                    f"install effect {effect!r} is unavailable",
                )
            )
    if manifest.setup is not None:
        if target.platform not in manifest.setup.platforms:
            setup.append(
                CompatibilityReason(
                    "setup-platform-unsupported",
                    f"setup does not support platform {target.platform!r}",
                )
            )
        available_setup = frozenset(target.setup_capabilities)
        missing_setup = tuple(
            capability
            for capability in manifest.setup.capabilities
            if capability not in available_setup
        )
        if missing_setup:
            setup.append(
                CompatibilityReason(
                    "setup-capability-missing",
                    "setup capabilities are unavailable: " + ", ".join(map(str, missing_setup)),
                )
            )
    return CompatibilityDecision(tuple(payload), tuple(setup), target.require_setup)


def expand_collection(
    graph: MarketplaceGraph,
    coordinate: CollectionCoordinate,
) -> Result[tuple[ArtifactCoordinate, ...]]:
    for collection in graph.collections:
        if collection.coordinate == coordinate:
            return Ok(collection.members)
    return Err(
        (
            _diagnostic(
                ARTIFACT_NOT_FOUND,
                f"collection is not available: {coordinate}",
                alias=coordinate.source,
            ),
        )
    )


def _requested_artifacts(
    graph: MarketplaceGraph,
    request: SelectionRequest,
) -> Result[tuple[ArtifactCoordinate, ...]]:
    requested = list(request.artifacts)
    for collection in request.collections:
        expanded = expand_collection(graph, collection)
        if isinstance(expanded, Err):
            return expanded
        requested.extend(expanded.value)
    if not requested:
        if request.mode is SelectionMode.EXPLICIT:
            return Err(
                (
                    _diagnostic(
                        ARTIFACT_NOT_FOUND,
                        "explicit selection requires at least one artifact or collection",
                    ),
                )
            )
        requested.extend(item.coordinate for item in graph.artifacts)
    return Ok(tuple(sorted(set(requested), key=_artifact_sort_key)))


def select_artifacts(
    graph: MarketplaceGraph,
    request: SelectionRequest,
) -> Result[SelectionResult]:
    requested = _requested_artifacts(graph, request)
    if isinstance(requested, Err):
        return requested
    records = {
        _artifact_key(item.source_alias, item.artifact.identity): item for item in graph.artifacts
    }
    selected: dict[tuple[SourceAlias, ArtifactIdentity], MarketplaceArtifact] = {}
    skipped: list[SelectionSkip] = []
    diagnostics: list[Diagnostic] = []
    for coordinate in requested.value:
        artifact = records.get(_artifact_key(coordinate.source, coordinate.artifact))
        if artifact is None or (
            coordinate.version is not None and coordinate.version != str(artifact.artifact.version)
        ):
            reason = CompatibilityReason(
                "artifact-not-found",
                f"artifact is not available: {coordinate}",
            )
            if request.mode is SelectionMode.EXPLICIT:
                diagnostics.append(
                    _diagnostic(
                        ARTIFACT_NOT_FOUND,
                        reason.message,
                        alias=coordinate.source,
                    )
                )
            else:
                skipped.append(SelectionSkip(coordinate, (reason,)))
            continue
        decision = evaluate_compatibility(artifact, request.target)
        if decision.compatible:
            selected[_artifact_key(artifact.source_alias, artifact.artifact.identity)] = artifact
            continue
        if request.mode is SelectionMode.EXPLICIT:
            diagnostics.append(
                _diagnostic(
                    ARTIFACT_NOT_FOUND
                    if artifact.lifecycle is ArtifactLifecycle.REMOVED
                    else ARTIFACT_INCOMPATIBLE,
                    f"cannot select {artifact.coordinate}: "
                    + "; ".join(reason.message for reason in decision.reasons),
                    alias=artifact.source_alias,
                    details=(
                        (
                            "reasons",
                            ",".join(reason.code for reason in decision.reasons),
                        ),
                    ),
                )
            )
        else:
            skipped.append(SelectionSkip(artifact.coordinate, decision.reasons))
    if diagnostics:
        return Err(sort_diagnostics(diagnostics))
    return Ok(SelectionResult(tuple(selected.values()), tuple(skipped)))


def _artifact_json(item: MarketplaceArtifact) -> JsonObject:
    artifact = item.artifact
    semantic = _semantic_json(artifact)
    setup = _setup_json(artifact.setup)
    review: JsonValue = None
    if artifact.review is not None:
        review = JsonObject(
            (("policy", artifact.review.policy), ("status", artifact.review.status))
        )
    provenance: JsonValue = None
    if artifact.provenance is not None:
        provenance = JsonObject(
            (
                ("origin_url", artifact.provenance.origin_url),
                ("path", str(artifact.provenance.path)),
                ("resolved_commit", artifact.provenance.resolved_commit),
            )
        )
    entries: list[tuple[str, JsonValue]] = list(
        (
            ("compatibility", semantic.get("compatibility")),
            ("identity", str(artifact.identity)),
            ("install", semantic.get("install")),
            ("lifecycle", item.lifecycle.value),
            ("manifest_digest", str(artifact.manifest_digest)),
            ("object_digest", str(artifact.object_digest)),
            ("payload_digest", str(artifact.payload_digest)),
            ("provenance", provenance),
            ("review", review),
            ("semantic_digest", str(item.semantic_digest)),
            ("setup", setup),
            ("source_alias", item.source_alias.value),
            ("source_id", item.source_id.value),
            ("summary", artifact.summary),
            ("version", str(artifact.version)),
        )
    )
    requires_aart = semantic.get("requires_aart")
    if requires_aart is not None:
        entries.append(("requires_aart", requires_aart))
    return JsonObject(tuple(entries))


def marketplace_graph_bytes(graph: MarketplaceGraph) -> bytes:
    """Serialize the pure marketplace projection to canonical, payload-free JSON bytes."""

    artifacts = JsonArray(tuple(_artifact_json(item) for item in graph.artifacts))
    collections = JsonArray(
        tuple(
            JsonObject(
                (
                    ("coordinate", str(item.coordinate)),
                    ("members", _strings(item.members)),
                    ("summary", item.summary),
                )
            )
            for item in graph.collections
        )
    )
    diagnostics = JsonArray(
        tuple(
            JsonObject(
                (
                    ("code", item.code.value),
                    ("message", item.message),
                    ("severity", item.severity.value),
                    (
                        "source",
                        None
                        if item.location is None or item.location.source is None
                        else item.location.source.value,
                    ),
                )
            )
            for item in graph.diagnostics
        )
    )
    return canonical_json_bytes(
        JsonObject(
            (
                ("artifacts", artifacts),
                ("collections", collections),
                ("diagnostics", diagnostics),
                ("schema_version", 1),
            )
        )
    )
