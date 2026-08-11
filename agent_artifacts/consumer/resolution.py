"""Bind agent-supplied selectors to exact catalog coordinates.

Resolution is a pure function of the already-compiled catalog: it performs no source fetch, no
configuration write, and no object publication.  An unqualified selector that matches more than one
source is an error naming every valid coordinate — the lifecycle never picks a source for the
caller, because installing the wrong publisher's artifact is not a recoverable mistake.
"""

from __future__ import annotations

from agent_artifacts.domain.diagnostics import Diagnostic
from agent_artifacts.domain.identifiers import ArtifactCoordinate
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.marketplace.catalog import resolve_artifact
from agent_artifacts.marketplace.model import ArtifactQuery, MarketplaceCatalog

from .coordinates import ArtifactSelector


def resolve_selectors(
    catalog: MarketplaceCatalog,
    selectors: tuple[ArtifactSelector, ...],
) -> Result[tuple[ArtifactCoordinate, ...]]:
    """Resolve every selector, collecting all failures rather than stopping at the first."""

    coordinates: list[ArtifactCoordinate] = []
    diagnostics: list[Diagnostic] = []
    for selector in selectors:
        resolved = resolve_artifact(
            catalog,
            ArtifactQuery(selector.identity, selector.source, selector.version),
        )
        if isinstance(resolved, Err):
            diagnostics.extend(resolved.diagnostics)
            continue
        coordinates.append(resolved.value.coordinate)
    if diagnostics:
        return Err(tuple(diagnostics))
    return Ok(tuple(sorted(set(coordinates), key=str)))


__all__ = ["resolve_selectors"]
