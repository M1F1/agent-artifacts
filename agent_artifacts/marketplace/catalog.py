"""Pure source union, trust overlay, search, resolution, and presentation."""

from __future__ import annotations

from collections.abc import Iterable

from agent_artifacts.compiler.graph import ArtifactLifecycle, MarketplaceArtifact, MarketplaceGraph
from agent_artifacts.configuration.model import (
    CompanyReviewedSource,
    OrganizationPolicy,
    SourceKind,
    git_location_parts,
)
from agent_artifacts.configuration.policy import EffectiveConfiguration, redact_text
from agent_artifacts.configuration.schema import organization_policy_bytes
from agent_artifacts.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    Severity,
    SourceLocation,
    sort_diagnostics,
)
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.hashing import json_digest, sha256_bytes
from agent_artifacts.protocol.json import JsonArray, JsonObject, JsonValue, canonical_json_bytes

from .model import (
    ArtifactQuery,
    MarketplaceCatalog,
    MarketplaceItem,
    MarketplaceQuery,
    MarketplaceSourceState,
    MarketplaceSourceView,
    TrustClass,
    TrustDecision,
)

MARKETPLACE_INVALID = DiagnosticCode("marketplace-invalid")
ARTIFACT_AMBIGUOUS = DiagnosticCode("artifact-ambiguous")
ARTIFACT_NOT_FOUND = DiagnosticCode("artifact-not-found")
_MAX_SOURCES = 1_000
_MAX_ITEMS = 100_000


def _error(
    code: DiagnosticCode,
    message: str,
    *,
    alias: SourceAlias | None = None,
    details: tuple[tuple[str, str], ...] = (),
) -> Diagnostic:
    return Diagnostic(
        code,
        Severity.ERROR,
        redact_text(message),
        None if alias is None else SourceLocation(source=alias),
        details=details,
    )


def _origin(state: MarketplaceSourceState) -> str:
    configured = state.configured
    if configured.kind is SourceKind.SOURCE_LOCAL:
        return configured.location
    parts = git_location_parts(configured.location)
    if parts is None:
        raise ValueError("effective Git source location must already be valid")
    return f"{parts[0]}/{parts[1]}"


def _source_view(
    state: MarketplaceSourceState,
    effective: EffectiveConfiguration,
) -> MarketplaceSourceView:
    current = state.health.current
    return MarketplaceSourceView(
        state.configured.alias,
        state.configured.kind,
        None if current is None else current.declared_source_id,
        _origin(state),
        None if current is None else current.candidate.resolved_revision,
        None if current is None else current.candidate.snapshot_digest,
        state.health.status,
        state.health.age_seconds,
        state.display_order,
        effective.configuration.default_registry == state.configured.alias,
        state.health.diagnostics,
    )


def _company_identity(source: MarketplaceSourceView) -> CompanyReviewedSource | None:
    if source.kind is not SourceKind.REGISTRY_GIT or source.source_id is None:
        return None
    host, separator, repository = source.origin.partition("/")
    if not separator:
        return None
    try:
        return CompanyReviewedSource(source.source_id, host, repository)
    except ValueError:
        return None


def _review_json(item: MarketplaceArtifact) -> JsonValue:
    review = item.artifact.review
    if review is None:
        return None
    return JsonObject((("policy", review.policy), ("status", review.status)))


def _provenance_json(item: MarketplaceArtifact) -> JsonValue:
    provenance = item.artifact.provenance
    if provenance is None:
        return None
    return JsonObject(
        (
            ("origin_url", redact_text(provenance.origin_url)),
            ("path", str(provenance.path)),
            ("resolved_commit", provenance.resolved_commit),
        )
    )


def _trust(
    item: MarketplaceArtifact,
    source: MarketplaceSourceView,
    policy: OrganizationPolicy,
) -> TrustDecision:
    review = item.artifact.review
    approved = (
        review is not None
        and review.status == "approved"
        and bool(review.policy)
        and "\n" not in review.policy
        and "\r" not in review.policy
    )
    company_identity = _company_identity(source)
    reasons: tuple[str, ...]
    if source.kind is SourceKind.SOURCE_LOCAL:
        trust = TrustClass.LOCAL
        reasons = ("mutable local source",)
    elif source.kind is SourceKind.SOURCE_GIT:
        trust = TrustClass.DIRECT_SOURCE
        reasons = ("configured direct Git source",)
    elif approved and company_identity in policy.company_reviewed_sources:
        trust = TrustClass.COMPANY_REVIEWED
        reasons = ("approved registry entry", "exact organization source identity")
    elif approved:
        trust = TrustClass.REGISTRY_REVIEWED
        reasons = ("approved registry entry",)
    else:
        trust = TrustClass.UNVERIFIED
        reasons = ("registry review is absent, incomplete, or not approved",)
    evidence = JsonObject(
        (
            ("artifact_manifest_digest", str(item.artifact.manifest_digest)),
            ("artifact_object_digest", str(item.artifact.object_digest)),
            ("artifact_payload_digest", str(item.artifact.payload_digest)),
            ("policy_digest", str(sha256_bytes(organization_policy_bytes(policy)))),
            ("provenance", _provenance_json(item)),
            ("review", _review_json(item)),
            ("source_id", None if source.source_id is None else source.source_id.value),
            ("source_kind", source.kind.value),
            ("source_origin", source.origin),
            ("source_revision", source.resolved_revision),
            (
                "source_snapshot_digest",
                None if source.snapshot_digest is None else str(source.snapshot_digest),
            ),
        )
    )
    return TrustDecision(trust, json_digest(evidence), reasons)


def build_marketplace(
    graph: MarketplaceGraph,
    effective: EffectiveConfiguration,
    source_states: Iterable[MarketplaceSourceState],
) -> Result[MarketplaceCatalog]:
    """Overlay runtime source health and local trust without mutating the compiled graph."""

    enabled = {source.alias: source for source in effective.configuration.sources if source.enabled}
    states = tuple(source_states)
    if len(enabled) > _MAX_SOURCES or len(states) > _MAX_SOURCES:
        return Err(
            (
                _error(
                    MARKETPLACE_INVALID,
                    "marketplace exceeds the configured source bound",
                ),
            )
        )
    if len(graph.artifacts) > _MAX_ITEMS or len(graph.collections) > _MAX_ITEMS:
        return Err(
            (
                _error(
                    MARKETPLACE_INVALID,
                    "compiled marketplace exceeds the item bound",
                ),
            )
        )
    by_alias: dict[SourceAlias, MarketplaceSourceState] = {}
    diagnostics: list[Diagnostic] = []
    for state in states:
        alias = state.configured.alias
        if alias in by_alias:
            diagnostics.append(
                _error(
                    MARKETPLACE_INVALID,
                    f"duplicate runtime source state: {alias}",
                    alias=alias,
                )
            )
            continue
        configured = enabled.get(alias)
        if configured is None or configured != state.configured:
            diagnostics.append(
                _error(
                    MARKETPLACE_INVALID,
                    f"runtime source state does not match enabled configuration: {alias}",
                    alias=alias,
                )
            )
            continue
        by_alias[alias] = state
    for alias in sorted(set(enabled) - set(by_alias)):
        diagnostics.append(
            _error(
                MARKETPLACE_INVALID,
                f"enabled source has no runtime state: {alias}",
                alias=alias,
            )
        )
    views = {alias: _source_view(state, effective) for alias, state in by_alias.items()}
    items: list[MarketplaceItem] = []
    for artifact in graph.artifacts:
        source = views.get(artifact.source_alias)
        if source is None:
            diagnostics.append(
                _error(
                    MARKETPLACE_INVALID,
                    f"compiled artifact has no enabled runtime source: {artifact.coordinate}",
                    alias=artifact.source_alias,
                )
            )
            continue
        if source.source_id != artifact.source_id:
            diagnostics.append(
                _error(
                    MARKETPLACE_INVALID,
                    f"compiled source ID does not match current source for {artifact.coordinate}",
                    alias=artifact.source_alias,
                )
            )
            continue
        items.append(MarketplaceItem(artifact, source, _trust(artifact, source, effective.policy)))
    if diagnostics:
        return Err(sort_diagnostics(diagnostics))
    return Ok(
        MarketplaceCatalog(
            tuple(views.values()),
            tuple(items),
            graph.collections,
            graph.diagnostics,
        )
    )


def resolve_artifact(
    catalog: MarketplaceCatalog,
    query: ArtifactQuery,
) -> Result[MarketplaceItem]:
    matches = tuple(
        item
        for item in catalog.items
        if item.artifact.lifecycle is ArtifactLifecycle.AVAILABLE
        and item.coordinate.artifact == query.identity
        and (query.source is None or item.coordinate.source == query.source)
        and (query.version is None or item.coordinate.version == query.version)
    )
    if not matches:
        qualification = "" if query.source is None else f" in source {query.source}"
        return Err(
            (
                _error(
                    ARTIFACT_NOT_FOUND,
                    f"artifact {query.identity}{qualification} was not found",
                ),
            )
        )
    if len(matches) > 1:
        coordinates = tuple(sorted(str(item.coordinate) for item in matches))
        return Err(
            (
                _error(
                    ARTIFACT_AMBIGUOUS,
                    f"artifact {query.identity} is ambiguous; valid coordinates: "
                    + ", ".join(coordinates),
                    details=(("coordinates", ",".join(coordinates)),),
                ),
            )
        )
    return Ok(matches[0])


def search_marketplace(
    catalog: MarketplaceCatalog,
    query: MarketplaceQuery | None = None,
) -> tuple[MarketplaceItem, ...]:
    query = MarketplaceQuery() if query is None else query
    needle = query.text.casefold().strip()
    kinds = frozenset(query.kinds)
    sources = frozenset(query.sources)
    result: list[MarketplaceItem] = []
    for item in catalog.items:
        artifact = item.artifact.artifact
        if not query.include_removed and item.artifact.lifecycle is ArtifactLifecycle.REMOVED:
            continue
        if kinds and artifact.identity.kind not in kinds:
            continue
        if sources and item.source.alias not in sources:
            continue
        haystack = "\n".join(
            (
                str(item.coordinate),
                artifact.identity.name,
                artifact.summary,
                item.source.alias.value,
                "" if item.source.source_id is None else item.source.source_id.value,
                *artifact.collections,
            )
        ).casefold()
        if needle and needle not in haystack:
            continue
        result.append(item)
    return tuple(result)


def list_marketplace(
    catalog: MarketplaceCatalog,
    *,
    include_removed: bool = False,
) -> tuple[MarketplaceItem, ...]:
    if not isinstance(include_removed, bool):
        raise ValueError("marketplace list include_removed flag must be boolean")
    return tuple(
        item
        for item in catalog.items
        if include_removed or item.artifact.lifecycle is ArtifactLifecycle.AVAILABLE
    )


def _source_json(source: MarketplaceSourceView) -> JsonObject:
    return JsonObject(
        (
            ("age_seconds", source.age_seconds),
            ("alias", source.alias.value),
            ("diagnostics", JsonArray(tuple(item.code.value for item in source.diagnostics))),
            ("display_order", source.display_order),
            ("health", source.health.value),
            ("is_default", source.is_default),
            ("kind", source.kind.value),
            ("origin", redact_text(source.origin)),
            ("resolved_revision", source.resolved_revision),
            (
                "snapshot_digest",
                None if source.snapshot_digest is None else str(source.snapshot_digest),
            ),
            ("source_id", None if source.source_id is None else source.source_id.value),
        )
    )


def _item_json(item: MarketplaceItem) -> JsonObject:
    artifact = item.artifact.artifact
    return JsonObject(
        (
            ("collections", JsonArray(tuple(artifact.collections))),
            ("coordinate", str(item.coordinate)),
            ("lifecycle", item.artifact.lifecycle.value),
            ("manifest_digest", str(artifact.manifest_digest)),
            ("object_digest", str(artifact.object_digest)),
            ("payload_digest", str(artifact.payload_digest)),
            ("provenance", _provenance_json(item.artifact)),
            ("source", _source_json(item.source)),
            ("summary", redact_text(artifact.summary)),
            ("trust", item.trust.kind.value),
            ("trust_evidence_digest", str(item.trust.evidence_digest)),
        )
    )


def marketplace_catalog_bytes(catalog: MarketplaceCatalog) -> bytes:
    return canonical_json_bytes(
        JsonObject(
            (
                ("artifacts", JsonArray(tuple(_item_json(item) for item in catalog.items))),
                (
                    "collections",
                    JsonArray(
                        tuple(
                            JsonObject(
                                (
                                    ("coordinate", str(collection.coordinate)),
                                    (
                                        "members",
                                        JsonArray(tuple(str(item) for item in collection.members)),
                                    ),
                                    ("summary", redact_text(collection.summary)),
                                )
                            )
                            for collection in catalog.collections
                        )
                    ),
                ),
                (
                    "diagnostics",
                    JsonArray(tuple(item.code.value for item in catalog.diagnostics)),
                ),
                ("schema_version", 1),
                ("sources", JsonArray(tuple(_source_json(source) for source in catalog.sources))),
            )
        )
    )


def render_marketplace(catalog: MarketplaceCatalog) -> str:
    lines = [
        f"source {source.alias.value} [{source.health.value}] "
        f"{source.kind.value} {redact_text(source.origin)}"
        for source in catalog.sources
    ]
    for item in catalog.items:
        artifact = item.artifact.artifact
        provenance = artifact.provenance
        origin = (
            f"{redact_text(provenance.origin_url)}@{provenance.resolved_commit}:{provenance.path}"
            if provenance is not None
            else f"{redact_text(item.source.origin)}@{item.source.resolved_revision or 'missing'}"
        )
        lines.append(
            f"{item.coordinate} [{item.trust.kind.value}] [{item.source.health.value}] "
            f"{redact_text(artifact.summary)} object={artifact.object_digest} origin={origin}"
        )
    for collection in catalog.collections:
        lines.append(
            f"{collection.coordinate} [collection] {redact_text(collection.summary)} "
            f"members={','.join(map(str, collection.members))}"
        )
    return "\n".join(lines) + ("\n" if lines else "")
