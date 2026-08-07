from __future__ import annotations

from agent_artifacts.compiler.graph import GraphSource, MarketplaceGraph, compile_marketplace_graph
from agent_artifacts.configuration.model import (
    CompanyReviewedSource,
    ConfiguredSource,
    OrganizationPolicy,
    ReportingSettings,
    SourceKind,
    SyncSettings,
    UserConfiguration,
)
from agent_artifacts.configuration.policy import (
    EffectiveConfiguration,
    RuntimeOverrides,
    apply_configuration,
)
from agent_artifacts.domain.identifiers import (
    ArtifactIdentity,
    ObjectDigest,
    SourceAlias,
    SourceId,
)
from agent_artifacts.domain.result import Ok
from agent_artifacts.marketplace.model import MarketplaceSourceState
from agent_artifacts.protocol.native_models import (
    CollectionManifest,
    CompatibilitySpec,
    InstallSpec,
)
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import SafeRelativePath
from agent_artifacts.protocol.registry_models import (
    IndexArtifact,
    IndexProvenance,
    ReviewRecord,
)
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.sources.model import (
    CurrentSource,
    assess_source_health,
    make_source_candidate,
    source_instance_id,
)


def digest(character: str) -> ObjectDigest:
    return ObjectDigest("sha256", character * 64)


def configured_source(
    alias: str,
    kind: SourceKind,
    *,
    location: str | None = None,
    enabled: bool = True,
) -> ConfiguredSource:
    if location is None:
        location = (
            f"/work/{alias}"
            if kind is SourceKind.SOURCE_LOCAL
            else f"https://{alias}.example/agents/{alias}.git"
        )
    return ConfiguredSource(
        SourceAlias(alias),
        kind,
        location,
        None if kind is SourceKind.SOURCE_LOCAL else "main",
        enabled,
    )


def source_state(
    source: ConfiguredSource,
    source_id: str,
    *,
    display_order: int,
    published_at: int = 90,
    now: int = 100,
    max_age: int = 30,
    content: bytes = b"source",
    resolved_revision: str | None = None,
) -> MarketplaceSourceState:
    origin = (
        SnapshotOrigin.LOCAL
        if source.kind is SourceKind.SOURCE_LOCAL
        else SnapshotOrigin.IMMUTABLE_GIT
    )
    snapshot = SourceSnapshot(
        origin,
        (
            SnapshotEntry(
                SafeRelativePath(("aart-source.json",)),
                SnapshotEntryKind.FILE,
                content,
            ),
        ),
    )
    candidate = make_source_candidate(
        source_instance_id(source),
        source.alias,
        (
            "local"
            if source.kind is SourceKind.SOURCE_LOCAL
            else ("a" * 40 if resolved_revision is None else resolved_revision)
        ),
        snapshot,
    )
    assert isinstance(candidate, Ok), candidate
    current = CurrentSource(
        candidate.value,
        SourceId(source_id),
        published_at,
        f"/managed/{source.alias}/snapshot",
    )
    health = assess_source_health(current, now=now, max_age_seconds=max_age)
    return MarketplaceSourceState(source, health, display_order)


def missing_source_state(
    source: ConfiguredSource,
    *,
    display_order: int,
) -> MarketplaceSourceState:
    return MarketplaceSourceState(
        source,
        assess_source_health(None, now=100, max_age_seconds=30),
        display_order,
    )


def artifact(
    source_id: str,
    name: str,
    *,
    kind: str = "skill",
    version: SemVer | None = None,
    review: ReviewRecord | None = None,
    object_character: str = "3",
    provenance: IndexProvenance | None = None,
) -> IndexArtifact:
    return IndexArtifact(
        SourceId(source_id),
        ArtifactIdentity(kind, name),  # type: ignore[arg-type]
        SemVer(1, 0, 0) if version is None else version,
        f"Use {name} to improve agent work.",
        digest("1"),
        digest("2"),
        digest(object_character),
        CompatibilitySpec(("claude",), ("darwin",)),
        InstallSpec(("project",), ("copy",), ("copy-tree",)),
        review=review,
        provenance=provenance,
    )


def graph(
    *sources: tuple[ConfiguredSource, str, tuple[IndexArtifact, ...]],
    previous: MarketplaceGraph | None = None,
) -> MarketplaceGraph:
    compiled = compile_marketplace_graph(
        tuple(
            GraphSource(source.alias, SourceId(source_id), (), artifacts)
            for source, source_id, artifacts in sources
        ),
        available_capabilities=(),
        previous=previous,
    )
    assert isinstance(compiled, Ok), compiled
    return compiled.value


def graph_with_collections(
    source: ConfiguredSource,
    source_id: str,
    artifacts: tuple[IndexArtifact, ...],
    collections: tuple[CollectionManifest, ...],
) -> MarketplaceGraph:
    compiled = compile_marketplace_graph(
        (GraphSource(source.alias, SourceId(source_id), (), artifacts, collections),),
        available_capabilities=(),
    )
    assert isinstance(compiled, Ok), compiled
    return compiled.value


def effective_configuration(
    sources: tuple[ConfiguredSource, ...],
    *,
    default_registry: str | None = None,
    company_sources: tuple[CompanyReviewedSource, ...] = (),
) -> EffectiveConfiguration:
    user = UserConfiguration(
        1,
        sources,
        None if default_registry is None else SourceAlias(default_registry),
        SyncSettings(),
        ReportingSettings(),
    )
    policy = OrganizationPolicy(1, company_reviewed_sources=company_sources)
    effective = apply_configuration(user, RuntimeOverrides(), policy)
    assert isinstance(effective, Ok), effective
    return effective.value


def provenance(name: str) -> IndexProvenance:
    return IndexProvenance(
        f"https://upstream.example/{name}.git",
        "b" * 40,
        SafeRelativePath(("artifacts", "skill", name)),
    )
