"""Pure, source-qualified marketplace projection for the consumer TUI.

The terminal frontends consume these frozen values.  This module performs no IO and never parses
human command output: it projects the canonical marketplace, compatibility, lifecycle, and
security domains into rows that both text and curses can render.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

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
from agent_artifacts.tui_layout import (
    CONTENT_MEASURE,
    STAGE_PROJECTION,
    columns,
    field_block,
    measure,
    wrap,
)

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
    # ``None`` mirrors organization policy: no allowlist means every setup capability is
    # permitted. An explicit empty tuple means the organization permits none.
    setup_capabilities: tuple[Capability, ...] | None = None

    def __post_init__(self) -> None:
        profiles = tuple(sorted(set(self.profiles)))
        capabilities = (
            None if self.setup_capabilities is None else tuple(sorted(set(self.setup_capabilities)))
        )
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
        declared_setup = item.artifact.artifact.setup
        setup_capabilities = (
            declared_setup.capabilities
            if target.setup_capabilities is None and declared_setup is not None
            else (target.setup_capabilities or ())
        )
        decision: CompatibilityDecision = evaluate_compatibility(
            item.artifact,
            CompatibilityTarget(
                profile,
                target.platform,
                target.scope,
                target.mode,
                _AVAILABLE_EFFECTS,
                EXECUTABLE_VERSION,
                setup_capabilities,
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


_PANE_INDENT = 2
_FIELD_INDENT = 4


def _risk_text(security: MarketplaceSecurity) -> str:
    return (
        f"{security.installation_risk}, max severity {security.max_finding_severity}, "
        f"{security.assessment_status} coverage "
        f"{security.coverage_completed}/{security.coverage_expected}"
    )


def _harness_text(row: MarketplaceArtifactRow) -> str:
    return ", ".join(row.installed_statuses) if row.installed_statuses else "not installed"


def _status_text(row: MarketplaceArtifactRow) -> str:
    """The verdict, and — when it is a refusal — the first reason for it.

    D5 asks a disabled row to say why it is disabled wherever it is shown, so the reason travels
    with the verdict rather than living only in the detail record.
    """

    if row.compatible:
        return "compatible"
    reasons = row.reasons
    return f"unavailable: {reasons[0].message}" if reasons else "unavailable"


_REVISION_PREFIX = 7


def _short_revision(revision: str) -> str:
    """Abbreviate a revision for the pane; the detail record keeps it whole.

    A resolved revision is usually a full hash, and at pane width it wraps over three lines and
    pushes the ``status`` field — the one carrying the reason a row is unavailable — off the
    bottom. Seven characters is the length every git tool abbreviates to.
    """

    if len(revision) <= _REVISION_PREFIX:
        return revision
    return revision[:_REVISION_PREFIX] + STAGE_PROJECTION


def _one_line(text: str, *, indent: int, width: int) -> str:
    """One line bounded to the content measure, indented and truncated by the layout kernel."""

    return columns((((" " * indent) + text,),), width=width)[0]


def artifact_cells(row: MarketplaceArtifactRow) -> Tuple[str, ...]:
    """The unpadded cells of one list row, identity first (D6).

    The caller passes every row's cells through :func:`tui_layout.columns` at once, so one column
    layout serves the whole list and positions never drift between rows. Identity is the qualified
    key: it is the only cell that identifies the artifact, so it is the only one that must survive
    a narrow terminal intact.

    Cells are ordered by decreasing importance to a choice, so a narrow caller may pass a prefix
    of them. That is deliberate: below roughly fifty columns the kernel shrinks trailing cells to
    ``risk…``, which costs the same space as the whole word and conveys nothing, so a caller is
    better off dropping a column than showing its stump.
    """

    if not row.compatible:
        state = "unavailable"
    elif row.installed_statuses:
        state = ", ".join(row.installed_statuses)
    else:
        state = "available"
    return (row.key, state, f"risk {row.security.installation_risk}", row.trust)


def render_artifact_pane(row: MarketplaceArtifactRow, *, width: int) -> Tuple[str, ...]:
    """The pinned pane describing the cursor row: identity, summary, then the deciding evidence."""

    budget = measure(width, bound=CONTENT_MEASURE)
    lines = [_one_line(row.key, indent=_PANE_INDENT, width=budget)]
    for line in wrap(row.summary, width=budget - _PANE_INDENT):
        lines.append(_one_line(line, indent=_PANE_INDENT, width=budget))
    lines.extend(
        field_block(
            (
                (
                    "source",
                    f"{row.source_alias} ({row.trust}) at {_short_revision(row.source_revision)}, "
                    f"{row.source_health}",
                ),
                ("risk", _risk_text(row.security)),
                ("harness", _harness_text(row)),
                ("status", _status_text(row)),
            ),
            indent=_FIELD_INDENT,
            width=budget,
        )
    )
    return tuple(lines)


def _detail_section(heading: str, fields: Tuple[Tuple[str, str], ...]) -> Tuple[str, ...]:
    return ("", heading, *field_block(fields, indent=_PANE_INDENT, width=CONTENT_MEASURE))


def render_artifact_detail(row: MarketplaceArtifactRow) -> Tuple[str, ...]:
    """The full record behind ``?``: every stored evidence field as ``label   value`` (D8).

    Digests are emitted outside the field block and outside the measure. A wrapped hash cannot be
    read or copied, so it keeps its own line however narrow the terminal is.
    """

    security = row.security
    age = (
        "not recorded"
        if security.evidence_age_seconds is None
        else f"{security.evidence_age_seconds}s old"
    )
    harness = tuple(
        (item.profile, "compatible" if item.compatible else _harness_reason(item))
        for item in row.compatibility
    )
    remediation = security.remediation or ("none recorded",)
    lines = [row.key, *wrap(row.summary, width=CONTENT_MEASURE)]
    lines.extend(
        _detail_section(
            "source",
            (
                ("alias", str(row.source_alias)),
                ("origin", row.source_origin),
                ("revision", row.source_revision),
                ("health", row.source_health),
                ("trust", row.trust),
            ),
        )
    )
    lines.extend(
        _detail_section(
            "security",
            (
                ("risk", security.installation_risk),
                ("severity", security.max_finding_severity),
                ("assessment", security.assessment_status),
                ("coverage", f"{security.coverage_completed}/{security.coverage_expected}"),
                ("providers", ", ".join(security.provider_versions) or "none"),
                ("evidence", age),
                *(
                    (("remediation" if index == 0 else ""), text)
                    for index, text in enumerate(remediation)
                ),
            ),
        )
    )
    lines.extend(_detail_section("harness", harness))
    lines.extend(
        _detail_section(
            "install",
            (
                ("modes", ", ".join(row.actual_modes) or "none"),
                ("installed", _harness_text(row)),
                ("status", _status_text(row)),
            ),
        )
    )
    lines.extend(("", "digests"))
    digests = (
        ("manifest", row.manifest_digest),
        ("payload", row.payload_digest),
        ("object", row.object_digest),
        ("trust", row.trust_evidence_digest),
    )
    lines.extend(f"  {label.ljust(8)}  {value}" for label, value in digests if value)
    return tuple(lines)


def _harness_reason(item: HarnessCompatibility) -> str:
    if not item.reasons:
        return "unavailable"
    return "unavailable: " + "; ".join(reason.message for reason in item.reasons)


__all__ = [
    "BasketReconciliation",
    "HarnessCompatibility",
    "MarketplaceArtifactRow",
    "MarketplaceFilters",
    "MarketplaceSecurity",
    "MarketplaceTarget",
    "artifact_cells",
    "filter_marketplace_rows",
    "project_marketplace_rows",
    "reconcile_marketplace_basket",
    "render_artifact_detail",
    "render_artifact_pane",
]
