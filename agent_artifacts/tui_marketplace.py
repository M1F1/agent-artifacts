"""Pure, source-qualified marketplace projection for the consumer TUI.

The terminal frontends consume these frozen values.  This module performs no IO and never parses
human command output: it projects the canonical marketplace, compatibility, lifecycle, and
security domains into rows that both text and curses can render.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_artifacts.compiler.graph import (
    CompatibilityDecision,
    CompatibilityReason,
    CompatibilityTarget,
    evaluate_compatibility,
)
from agent_artifacts.domain.identifiers import ArtifactCoordinate, ArtifactIdentity, SourceAlias
from agent_artifacts.install_state.model import InstallScope
from agent_artifacts.installation.model import InstallMode
from agent_artifacts.lifecycle.model import LifecycleItem
from agent_artifacts.marketplace.model import MarketplaceCatalog, MarketplaceItem
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.native_models import InstallEffect
from agent_artifacts.runtime_contract import EXECUTABLE_VERSION
from agent_artifacts.security.aggregation import ArtifactSecurityEvidence

_KINDS = frozenset({"skill", "guideline", "mcp", "hook", "memory"})
_TRUSTS = frozenset(
    {"unverified", "local", "direct-source", "registry-reviewed", "company-reviewed"}
)
_SCOPES = frozenset({"project", "user"})
_MODES = frozenset({"copy", "symlink"})
_AVAILABLE_EFFECTS: tuple[InstallEffect, ...] = (
    "copy-tree",
    "managed-block",
    "merge-json",
    "write-file",
)


@dataclass(frozen=True, slots=True)
class MarketplaceTarget:
    """Complete compatibility target selected in earlier wizard stages."""

    profiles: tuple[str, ...]
    platform: str
    scope: InstallScope
    mode: InstallMode
    setup_capabilities: tuple[Capability, ...] = ()

    def __post_init__(self) -> None:
        profiles = tuple(sorted(set(self.profiles)))
        capabilities = tuple(sorted(set(self.setup_capabilities)))
        if (
            not profiles
            or profiles != self.profiles
            or any(not profile or "\r" in profile or "\n" in profile for profile in profiles)
            or not self.platform
            or "\r" in self.platform
            or "\n" in self.platform
            or self.scope not in _SCOPES
            or self.mode not in _MODES
            or capabilities != self.setup_capabilities
        ):
            raise ValueError("TUI marketplace target is invalid")


@dataclass(frozen=True, slots=True)
class HarnessCompatibility:
    profile: str
    compatible: bool
    payload_compatible: bool
    setup_compatible: bool
    reasons: tuple[CompatibilityReason, ...] = ()

    def __post_init__(self) -> None:
        if (
            not self.profile
            or not isinstance(self.compatible, bool)
            or not isinstance(self.payload_compatible, bool)
            or not isinstance(self.setup_compatible, bool)
            or tuple(sorted(set(self.reasons))) != self.reasons
        ):
            raise ValueError("TUI harness compatibility is invalid")


@dataclass(frozen=True, slots=True)
class MarketplaceSecurity:
    assessment_status: str = "not-scanned"
    installation_risk: str = "unknown"
    max_finding_severity: str = "unknown"
    coverage_completed: int = 0
    coverage_expected: int = 0
    provider_versions: tuple[str, ...] = ()
    evidence_age_seconds: int | None = None
    remediation: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not self.assessment_status
            or not self.installation_risk
            or not self.max_finding_severity
            or not 0 <= self.coverage_completed <= self.coverage_expected
            or tuple(sorted(set(self.provider_versions))) != self.provider_versions
            or (
                self.evidence_age_seconds is not None
                and (
                    not isinstance(self.evidence_age_seconds, int)
                    or isinstance(self.evidence_age_seconds, bool)
                    or self.evidence_age_seconds < 0
                )
            )
            or tuple(sorted(set(self.remediation))) != self.remediation
        ):
            raise ValueError("TUI marketplace security evidence is invalid")


@dataclass(frozen=True, slots=True)
class MarketplaceArtifactRow:
    key: str
    identity: ArtifactIdentity
    version: str
    summary: str
    source_alias: SourceAlias
    source_origin: str
    source_revision: str
    source_health: str
    trust: str
    trust_evidence_digest: str
    manifest_digest: str
    payload_digest: str
    object_digest: str
    compatibility: tuple[HarnessCompatibility, ...]
    actual_modes: tuple[str, ...]
    installed_statuses: tuple[str, ...]
    security: MarketplaceSecurity

    def __post_init__(self) -> None:
        if (
            self.key != f"{self.source_alias}/{self.identity}@{self.version}"
            or self.identity.kind not in _KINDS
            or not self.summary
            or "\r" in self.summary
            or "\n" in self.summary
            or not self.source_origin
            or not self.source_revision
            or self.trust not in _TRUSTS
            or not self.compatibility
            or tuple(sorted(set(self.actual_modes))) != self.actual_modes
            or tuple(sorted(set(self.installed_statuses))) != self.installed_statuses
        ):
            raise ValueError("TUI marketplace artifact row is invalid")

    @property
    def compatible(self) -> bool:
        return all(item.compatible for item in self.compatibility)

    @property
    def coordinate(self) -> ArtifactCoordinate:
        return ArtifactCoordinate(self.source_alias, self.identity, self.version)

    @property
    def reasons(self) -> tuple[CompatibilityReason, ...]:
        return tuple(
            sorted({reason for decision in self.compatibility for reason in decision.reasons})
        )

    @property
    def installed(self) -> bool:
        return bool(self.installed_statuses)


@dataclass(frozen=True, slots=True)
class MarketplaceFilters:
    text: str = ""
    kinds: tuple[str, ...] = ()
    sources: tuple[SourceAlias, ...] = ()
    trusts: tuple[str, ...] = ()
    compatible_only: bool = False
    installed_only: bool = False

    def __post_init__(self) -> None:
        kinds = tuple(sorted(set(self.kinds)))
        sources = tuple(sorted(set(self.sources)))
        trusts = tuple(sorted(set(self.trusts)))
        if (
            not isinstance(self.text, str)
            or len(self.text) > 512
            or kinds != self.kinds
            or not set(kinds) <= _KINDS
            or sources != self.sources
            or trusts != self.trusts
            or not set(trusts) <= _TRUSTS
            or not isinstance(self.compatible_only, bool)
            or not isinstance(self.installed_only, bool)
        ):
            raise ValueError("TUI marketplace filters are invalid")


@dataclass(frozen=True, slots=True)
class BasketReconciliation:
    retained: tuple[str, ...]
    invalidated: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(set((*self.retained, *self.invalidated))) != len(
            (*self.retained, *self.invalidated)
        ):
            raise ValueError("TUI marketplace basket reconciliation is invalid")


def _compatibility(
    item: MarketplaceItem,
    target: MarketplaceTarget,
) -> tuple[HarnessCompatibility, ...]:
    result = []
    for profile in target.profiles:
        decision: CompatibilityDecision = evaluate_compatibility(
            item.artifact,
            CompatibilityTarget(
                profile,
                target.platform,
                target.scope,
                target.mode,
                _AVAILABLE_EFFECTS,
                EXECUTABLE_VERSION,
                target.setup_capabilities,
                require_setup=True,
            ),
        )
        result.append(
            HarnessCompatibility(
                profile,
                decision.compatible,
                decision.payload_compatible,
                decision.setup_compatible,
                decision.reasons,
            )
        )
    return tuple(result)


def _actual_modes(
    item: MarketplaceItem, target: MarketplaceTarget, compatible: bool
) -> tuple[str, ...]:
    if not compatible:
        return ()
    if target.mode == "copy":
        return ("copy",)
    effects = item.artifact.artifact.install.effects
    modes = {
        "copy" if effect in {"merge-json", "managed-block"} else "symlink" for effect in effects
    }
    return tuple(sorted(modes))


def _security(
    item: MarketplaceItem,
    evidence: dict[str, ArtifactSecurityEvidence],
) -> MarketplaceSecurity:
    found = evidence.get(str(item.coordinate))
    if found is None:
        return MarketplaceSecurity()
    assessment = found.assessment
    return MarketplaceSecurity(
        assessment.status.value,
        assessment.installation_risk.value,
        assessment.max_finding_severity.value,
        assessment.coverage.completed,
        assessment.coverage.expected,
        tuple(sorted(f"{provider.id}@{provider.version}" for provider in assessment.providers)),
        found.evidence_age_seconds,
        tuple(sorted({finding.remediation for finding in assessment.findings})),
    )


def _installed_statuses(
    item: MarketplaceItem,
    target: MarketplaceTarget,
    lifecycle: tuple[LifecycleItem, ...],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                f"{outcome.key.profile}:{outcome.status.value}"
                for outcome in lifecycle
                if outcome.key.coordinate.source == item.coordinate.source
                and outcome.key.coordinate.artifact == item.coordinate.artifact
                and outcome.key.scope == target.scope
                and outcome.key.profile in target.profiles
            }
        )
    )


def project_marketplace_rows(
    catalog: MarketplaceCatalog,
    target: MarketplaceTarget,
    *,
    security: tuple[ArtifactSecurityEvidence, ...] = (),
    lifecycle: tuple[LifecycleItem, ...] = (),
) -> tuple[MarketplaceArtifactRow, ...]:
    """Project every available qualified artifact without shadowing collisions."""

    evidence = {str(item.coordinate): item for item in security}
    rows = []
    for item in catalog.items:
        if item.artifact.lifecycle.value != "available":
            continue
        artifact = item.artifact.artifact
        compatibility = _compatibility(item, target)
        compatible = all(decision.compatible for decision in compatibility)
        assert item.source.resolved_revision is not None
        rows.append(
            MarketplaceArtifactRow(
                str(item.coordinate),
                artifact.identity,
                str(artifact.version),
                artifact.summary,
                item.source.alias,
                item.source.origin,
                item.source.resolved_revision,
                item.source.health.value,
                item.trust.kind.value,
                str(item.trust.evidence_digest),
                str(artifact.manifest_digest),
                str(artifact.payload_digest),
                str(artifact.object_digest),
                compatibility,
                _actual_modes(item, target, compatible),
                _installed_statuses(item, target, lifecycle),
                _security(item, evidence),
            )
        )
    return tuple(rows)


def filter_marketplace_rows(
    rows: tuple[MarketplaceArtifactRow, ...],
    filters: MarketplaceFilters,
) -> tuple[MarketplaceArtifactRow, ...]:
    """Apply deterministic local filters to an already projected snapshot."""

    needle = filters.text.casefold().strip()
    kinds = frozenset(filters.kinds)
    sources = frozenset(filters.sources)
    trusts = frozenset(filters.trusts)
    result = []
    for row in rows:
        haystack = "\n".join(
            (row.key, row.identity.name, row.summary, row.source_origin)
        ).casefold()
        if needle and needle not in haystack:
            continue
        if kinds and row.identity.kind not in kinds:
            continue
        if sources and row.source_alias not in sources:
            continue
        if trusts and row.trust not in trusts:
            continue
        if filters.compatible_only and not row.compatible:
            continue
        if filters.installed_only and not row.installed:
            continue
        result.append(row)
    return tuple(result)


def reconcile_marketplace_basket(
    keys: tuple[str, ...],
    rows: tuple[MarketplaceArtifactRow, ...],
) -> BasketReconciliation:
    """Retain exact qualified keys and report only entries lost from the new view."""

    available = {row.key for row in rows if row.compatible}
    retained = tuple(key for key in keys if key in available)
    invalidated = tuple(key for key in keys if key not in available)
    return BasketReconciliation(retained, invalidated)


def render_marketplace_row(row: MarketplaceArtifactRow) -> str:
    """Render one concise row; detail views can expose every stored evidence field."""

    compatibility = "compatible" if row.compatible else "unavailable"
    installed = "" if not row.installed_statuses else " · " + ", ".join(row.installed_statuses)
    return (
        f"{row.key} — {row.summary} · source {row.source_alias} · {row.trust} · "
        f"risk {row.security.installation_risk}, max {row.security.max_finding_severity} "
        f"({row.security.assessment_status}, "
        f"coverage {row.security.coverage_completed}/{row.security.coverage_expected}) · "
        f"{compatibility}{installed}"
    )


__all__ = [
    "BasketReconciliation",
    "HarnessCompatibility",
    "MarketplaceArtifactRow",
    "MarketplaceFilters",
    "MarketplaceSecurity",
    "MarketplaceTarget",
    "filter_marketplace_rows",
    "project_marketplace_rows",
    "reconcile_marketplace_basket",
    "render_marketplace_row",
]
