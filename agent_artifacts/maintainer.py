"""Pure domain values and projections for maintaining a local artifact catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .model import ArtifactType, Catalog
from .upstream_planner import UpstreamStatus
from .upstreams import UpstreamCatalog, UpstreamKey, format_upstream_key

_TYPE_ORDER: Tuple[ArtifactType, ...] = ("skill", "guideline", "mcp", "hook", "memory")


@dataclass(frozen=True, slots=True)
class MaintainerContext:
    """A parsed local catalog and its source-side tracking metadata."""

    root: str
    catalog: Catalog
    upstreams: UpstreamCatalog
    validation_errors: Tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CatalogHealth:
    """UI/JSON-neutral health projection for one maintainer catalog."""

    catalog_root: str
    counts_by_type: Tuple[Tuple[ArtifactType, int], ...]
    tracked: Tuple[str, ...]
    untracked: Tuple[str, ...]
    validation_errors: Tuple[str, ...]
    statuses: Tuple[UpstreamStatus, ...]
    needs_attention: Tuple[UpstreamStatus, ...]


def empty_upstreams() -> UpstreamCatalog:
    return UpstreamCatalog(version=1, entries={})


def build_catalog_health(
    context: MaintainerContext,
    statuses: Tuple[UpstreamStatus, ...] = (),
) -> CatalogHealth:
    """Derive deterministic counts/partitions without filesystem or network effects."""
    counts = tuple(
        (artifact_type, sum(1 for key in context.catalog.artifacts if key[0] == artifact_type))
        for artifact_type in _TYPE_ORDER
    )
    catalog_keys = {
        UpstreamKey(artifact_type, name) for artifact_type, name in context.catalog.artifacts
    }
    tracked_keys = catalog_keys.intersection(context.upstreams.entries)
    untracked_keys = catalog_keys.difference(context.upstreams.entries)
    attention = tuple(status for status in statuses if status.state != "up_to_date")
    return CatalogHealth(
        catalog_root=context.root,
        counts_by_type=counts,
        tracked=tuple(sorted(format_upstream_key(key) for key in tracked_keys)),
        untracked=tuple(sorted(format_upstream_key(key) for key in untracked_keys)),
        validation_errors=context.validation_errors,
        statuses=statuses,
        needs_attention=attention,
    )
