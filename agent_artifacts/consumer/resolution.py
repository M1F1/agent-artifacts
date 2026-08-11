"""Bind agent-supplied selectors to exact catalog coordinates.

Resolution is a pure function of the already-compiled catalog: it performs no source fetch, no
configuration write, and no object publication.  An unqualified selector that matches more than one
source is an error naming every valid coordinate — the lifecycle never picks a source for the
caller, because installing the wrong publisher's artifact is not a recoverable mistake.
"""

from __future__ import annotations

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ArtifactCoordinate
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.marketplace.catalog import resolve_artifact
from agent_artifacts.marketplace.model import ArtifactQuery, MarketplaceCatalog

from .coordinates import ArtifactSelector

COLLECTION_NOT_FOUND = DiagnosticCode("collection-not-found")
COLLECTION_AMBIGUOUS = DiagnosticCode("collection-ambiguous")


def _resolve_collection(
    catalog: MarketplaceCatalog,
    selector: ArtifactSelector,
) -> Result[tuple[ArtifactCoordinate, ...]]:
    matches = tuple(
        collection
        for collection in catalog.collections
        if collection.coordinate.name == selector.identity.name
        and (selector.source is None or collection.coordinate.source == selector.source)
    )
    if not matches:
        qualification = "" if selector.source is None else f" in source {selector.source}"
        return Err(
            (
                Diagnostic(
                    COLLECTION_NOT_FOUND,
                    Severity.ERROR,
                    f"collection {selector.identity.name}{qualification} was not found",
                ),
            )
        )
    if len(matches) > 1:
        coordinates = tuple(sorted(str(item.coordinate) for item in matches))
        return Err(
            (
                Diagnostic(
                    COLLECTION_AMBIGUOUS,
                    Severity.ERROR,
                    f"collection {selector.identity.name} is ambiguous; valid coordinates: "
                    + ", ".join(coordinates),
                    details=(("coordinates", ",".join(coordinates)),),
                ),
            )
        )
    return Ok(matches[0].members)


def resolve_selectors(
    catalog: MarketplaceCatalog,
    selectors: tuple[ArtifactSelector, ...],
) -> Result[tuple[ArtifactCoordinate, ...]]:
    """Resolve every selector, collecting all failures rather than stopping at the first."""

    coordinates: list[ArtifactCoordinate] = []
    diagnostics: list[Diagnostic] = []
    for selector in selectors:
        if selector.identity.kind == "collection":
            resolved = _resolve_collection(catalog, selector)
        else:
            artifact = resolve_artifact(
                catalog,
                ArtifactQuery(selector.identity, selector.source, selector.version),
            )
            resolved = artifact if isinstance(artifact, Err) else Ok((artifact.value.coordinate,))
        if isinstance(resolved, Err):
            diagnostics.extend(resolved.diagnostics)
            continue
        coordinates.extend(resolved.value)
    if diagnostics:
        return Err(tuple(diagnostics))
    return Ok(tuple(sorted(set(coordinates), key=str)))


__all__ = ["resolve_selectors"]
