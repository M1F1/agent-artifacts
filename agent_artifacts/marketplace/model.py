"""Frozen runtime marketplace, source, trust, query, and result values."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from agent_artifacts.compiler.graph import MarketplaceArtifact, MarketplaceCollection
from agent_artifacts.configuration.model import ConfiguredSource, SourceKind
from agent_artifacts.domain.diagnostics import Diagnostic, sort_diagnostics
from agent_artifacts.domain.identifiers import (
    ArtifactCoordinate,
    ArtifactIdentity,
    ObjectDigest,
    SourceAlias,
    SourceId,
)
from agent_artifacts.domain.result import Err
from agent_artifacts.protocol.semver import parse_semver
from agent_artifacts.sources.model import HealthStatus, SourceHealth, source_instance_id

_HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_KINDS = frozenset({"skill", "guideline", "mcp", "hook", "memory"})
_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def _valid_digest(digest: ObjectDigest) -> bool:
    return digest.algorithm == "sha256" and _HEX_64_RE.fullmatch(digest.value) is not None


class TrustClass(str, Enum):
    UNVERIFIED = "unverified"
    LOCAL = "local"
    DIRECT_SOURCE = "direct-source"
    REGISTRY_REVIEWED = "registry-reviewed"
    COMPANY_REVIEWED = "company-reviewed"


@dataclass(frozen=True, slots=True)
class MarketplaceSourceState:
    configured: ConfiguredSource
    health: SourceHealth
    display_order: int

    def __post_init__(self) -> None:
        if not self.configured.enabled:
            raise ValueError("marketplace source state must be enabled")
        if (
            not isinstance(self.health, SourceHealth)
            or not isinstance(self.display_order, int)
            or isinstance(self.display_order, bool)
            or self.display_order < 0
        ):
            raise ValueError("marketplace source state is invalid")
        current = self.health.current
        if (
            (self.health.status is HealthStatus.MISSING and current is not None)
            or (
                self.health.status
                in {
                    HealthStatus.HEALTHY,
                    HealthStatus.STALE,
                    HealthStatus.NOT_SYNCHRONIZED,
                }
                and current is None
            )
            or (current is None and self.health.age_seconds is not None)
            or (current is not None and self.health.age_seconds is None)
        ):
            raise ValueError("marketplace source health/current state is inconsistent")
        if current is not None and (
            current.candidate.alias != self.configured.alias
            or current.candidate.instance_id != source_instance_id(self.configured)
        ):
            raise ValueError("marketplace current source does not match its configuration")


@dataclass(frozen=True, slots=True)
class MarketplaceSourceView:
    alias: SourceAlias
    kind: SourceKind
    source_id: SourceId | None
    origin: str
    resolved_revision: str | None
    snapshot_digest: ObjectDigest | None
    health: HealthStatus
    age_seconds: int | None
    display_order: int
    is_default: bool
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        current_values = (self.source_id, self.resolved_revision, self.snapshot_digest)
        has_current = all(value is not None for value in current_values)
        has_no_current = all(value is None for value in current_values)
        if (
            _SLUG_RE.fullmatch(self.alias.value) is None
            or not isinstance(self.kind, SourceKind)
            or not self.origin
            or "\n" in self.origin
            or "\r" in self.origin
            or (self.source_id is not None and _SLUG_RE.fullmatch(self.source_id.value) is None)
            or not isinstance(self.health, HealthStatus)
            or not isinstance(self.display_order, int)
            or isinstance(self.display_order, bool)
            or self.display_order < 0
            or not isinstance(self.is_default, bool)
            or (
                self.age_seconds is not None
                and (
                    not isinstance(self.age_seconds, int)
                    or isinstance(self.age_seconds, bool)
                    or self.age_seconds < 0
                )
            )
            or not (has_current or has_no_current)
            or (self.health is HealthStatus.MISSING and has_current)
            or (
                self.health
                in {
                    HealthStatus.HEALTHY,
                    HealthStatus.STALE,
                    HealthStatus.NOT_SYNCHRONIZED,
                }
                and has_no_current
            )
            or (has_current != (self.age_seconds is not None))
            or (self.snapshot_digest is not None and not _valid_digest(self.snapshot_digest))
        ):
            raise ValueError("marketplace source view is invalid")
        object.__setattr__(self, "diagnostics", sort_diagnostics(self.diagnostics))

    @property
    def rank(self) -> tuple[int, int, str]:
        return (0 if self.is_default else 1, self.display_order, self.alias.value)


@dataclass(frozen=True, slots=True)
class TrustDecision:
    kind: TrustClass
    evidence_digest: ObjectDigest
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.kind, TrustClass)
            or not _valid_digest(self.evidence_digest)
            or not self.reasons
            or any(
                not isinstance(reason, str) or not reason or "\n" in reason or "\r" in reason
                for reason in self.reasons
            )
        ):
            raise ValueError("marketplace trust decision is invalid")
        object.__setattr__(self, "reasons", tuple(sorted(set(self.reasons))))


@dataclass(frozen=True, slots=True)
class MarketplaceItem:
    artifact: MarketplaceArtifact
    source: MarketplaceSourceView
    trust: TrustDecision

    def __post_init__(self) -> None:
        if (
            self.artifact.source_alias != self.source.alias
            or self.source.source_id is None
            or self.artifact.source_id != self.source.source_id
        ):
            raise ValueError("marketplace item source identity is inconsistent")

    @property
    def coordinate(self) -> ArtifactCoordinate:
        return self.artifact.coordinate


def _item_key(
    item: MarketplaceItem,
) -> tuple[int, int, str, str, str, str]:
    source_rank = item.source.rank
    coordinate = item.coordinate
    return (
        source_rank[0],
        source_rank[1],
        source_rank[2],
        coordinate.artifact.kind,
        coordinate.artifact.name,
        coordinate.version or "",
    )


@dataclass(frozen=True, slots=True)
class MarketplaceCatalog:
    sources: tuple[MarketplaceSourceView, ...]
    items: tuple[MarketplaceItem, ...]
    collections: tuple[MarketplaceCollection, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        sources = tuple(sorted(self.sources, key=lambda source: source.rank))
        aliases = tuple(source.alias for source in sources)
        if len(set(aliases)) != len(aliases):
            raise ValueError("marketplace catalog source aliases must be unique")
        by_alias = {source.alias: source for source in sources}
        items = tuple(sorted(self.items, key=_item_key))
        keys = tuple((item.coordinate.source, item.coordinate.artifact) for item in items)
        if len(set(keys)) != len(keys) or any(
            by_alias.get(item.source.alias) != item.source for item in items
        ):
            raise ValueError("marketplace catalog items must be qualified and source-bound")
        collections = tuple(sorted(self.collections, key=lambda item: item.coordinate))
        collection_keys = tuple(collection.coordinate for collection in collections)
        item_coordinates = frozenset(item.coordinate for item in items)
        if (
            len(set(collection_keys)) != len(collection_keys)
            or any(collection.coordinate.source not in by_alias for collection in collections)
            or any(
                member not in item_coordinates
                for collection in collections
                for member in collection.members
            )
        ):
            raise ValueError("marketplace catalog collections must be source-bound")
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "collections", collections)
        object.__setattr__(self, "diagnostics", sort_diagnostics(self.diagnostics))


@dataclass(frozen=True, slots=True)
class ArtifactQuery:
    identity: ArtifactIdentity
    source: SourceAlias | None = None
    version: str | None = None

    def __post_init__(self) -> None:
        if (
            self.identity.kind not in _ARTIFACT_KINDS
            or _SLUG_RE.fullmatch(self.identity.name) is None
            or (self.source is not None and _SLUG_RE.fullmatch(self.source.value) is None)
            or (self.version is not None and isinstance(parse_semver(self.version), Err))
        ):
            raise ValueError("marketplace artifact query is invalid")


@dataclass(frozen=True, slots=True)
class MarketplaceQuery:
    text: str = ""
    kinds: tuple[str, ...] = ()
    sources: tuple[SourceAlias, ...] = ()
    include_removed: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.text, str)
            or len(self.text) > 512
            or any(kind not in _ARTIFACT_KINDS for kind in self.kinds)
            or any(_SLUG_RE.fullmatch(source.value) is None for source in self.sources)
            or not isinstance(self.include_removed, bool)
        ):
            raise ValueError("marketplace search query is invalid")
        object.__setattr__(self, "kinds", tuple(sorted(set(self.kinds))))
        object.__setattr__(self, "sources", tuple(sorted(set(self.sources))))
