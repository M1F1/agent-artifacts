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
DEPENDENCY_UNAVAILABLE = DiagnosticCode("dependency-unavailable")


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
    return _dependency_closure(catalog, tuple(sorted(set(coordinates), key=str)))


def _dependency_closure(
    catalog: MarketplaceCatalog,
    requested: tuple[ArtifactCoordinate, ...],
) -> Result[tuple[ArtifactCoordinate, ...]]:
    """Expand same-registry declared dependencies before any installation review.

    Registry compilation normally proves every dependency.  The consumer nevertheless repeats
    the lookup against its exact validated snapshot, so a corrupt or partial marketplace cannot
    turn a direct artifact selection into a partial runtime installation.
    """

    records = {(item.coordinate.source, item.coordinate.artifact): item for item in catalog.items}
    closure: dict[tuple[object, object], ArtifactCoordinate] = {}
    diagnostics: list[Diagnostic] = []

    def include(coordinate: ArtifactCoordinate, trail: tuple[ArtifactCoordinate, ...]) -> None:
        key = (coordinate.source, coordinate.artifact)
        if coordinate in trail:
            diagnostics.append(
                Diagnostic(
                    DEPENDENCY_UNAVAILABLE,
                    Severity.ERROR,
                    "artifact dependency cycle: "
                    + " -> ".join(str(item) for item in (*trail, coordinate)),
                )
            )
            return
        if key in closure:
            return
        item = records.get(key)
        if item is None:
            diagnostics.append(
                Diagnostic(
                    DEPENDENCY_UNAVAILABLE,
                    Severity.ERROR,
                    f"required artifact is unavailable: {coordinate}",
                )
            )
            return
        if coordinate.version is not None and coordinate.version != str(
            item.artifact.artifact.version
        ):
            diagnostics.append(
                Diagnostic(
                    DEPENDENCY_UNAVAILABLE,
                    Severity.ERROR,
                    f"required artifact version is unavailable: {coordinate}",
                )
            )
            return
        closure[key] = item.coordinate
        for selector in item.artifact.artifact.requires:
            dependency = records.get((item.coordinate.source, selector.identity))
            if dependency is None or (
                selector.version is not None
                and not selector.version.allows(dependency.artifact.artifact.version)
            ):
                rendered = f"{item.coordinate.source}/{selector.identity}"
                diagnostics.append(
                    Diagnostic(
                        DEPENDENCY_UNAVAILABLE,
                        Severity.ERROR,
                        f"{item.coordinate} requires unavailable dependency {rendered}",
                    )
                )
                continue
            include(dependency.coordinate, (*trail, coordinate))

    for coordinate in requested:
        include(coordinate, ())
    if diagnostics:
        return Err(tuple(sorted(diagnostics, key=lambda item: item.message)))
    return Ok(tuple(sorted(closure.values(), key=str)))


__all__ = ["resolve_selectors"]
