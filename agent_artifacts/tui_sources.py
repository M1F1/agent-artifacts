"""Pure source-stage projections and deferred configuration requests for the TUI.

This module is the functional core of TUI01.  It translates configured source, organization-policy,
and health facts into immutable rows, then plans the exact configuration change selected by a user.
It deliberately owns no filesystem, Git, clock, terminal, or configuration-write effects.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Mapping

from agent_artifacts.configuration.model import (
    CompanyReviewedSource,
    ConfiguredSource,
    OrganizationPolicy,
    SourceKind,
    UserConfiguration,
    git_location_parts,
    git_origin_key,
)
from agent_artifacts.configuration.policy import (
    RuntimeOverrides,
    apply_configuration,
    apply_configuration_for_source_management,
)
from agent_artifacts.configuration.schema import validate_configured_source
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest, SourceAlias
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.sources.model import (
    HealthStatus,
    SourceHealth,
    SourceIdentityTransition,
    SourceSyncOutcome,
    SyncDisposition,
)

SOURCE_SELECTION_INVALID = DiagnosticCode("source-selection-invalid")


class SourceDisplayHealth(str, Enum):
    """Health states the interface promises to distinguish without relying on color."""

    CURRENT = "current"
    STALE = "stale"
    OFFLINE = "offline"
    INVALID = "invalid"
    INCOMPATIBLE = "incompatible"
    MISSING = "missing"
    DISABLED = "disabled"


class SourceOperationKind(str, Enum):
    """One explicit configuration effect, applied only after a reviewed Finalize."""

    DISABLE = "disable"
    ENABLE = "enable"
    USE_DEFAULT = "use-default"
    CLEAR_DEFAULT = "clear-default"


@dataclass(frozen=True, slots=True)
class SourceOperation:
    kind: SourceOperationKind
    alias: SourceAlias | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SourceOperationKind):
            raise ValueError("source operation kind is invalid")
        if self.kind is not SourceOperationKind.CLEAR_DEFAULT and self.alias is None:
            raise ValueError("source operation requires an alias")
        if self.kind is SourceOperationKind.CLEAR_DEFAULT and self.alias is not None:
            raise ValueError("clear-default does not accept an alias")


@dataclass(frozen=True, slots=True)
class SourceStageRow:
    source: ConfiguredSource
    origin: str
    health: SourceDisplayHealth
    age_seconds: int | None
    recommended: bool
    required: bool
    company_reviewed: bool
    is_default: bool
    selectable: bool
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.health, SourceDisplayHealth) or not self.origin:
            raise ValueError("source-stage row is invalid")
        if self.selectable == bool(self.reason):
            raise ValueError("source-stage availability and reason are inconsistent")

    @property
    def rank(self) -> tuple[int, int, int, str]:
        return (
            0 if self.required else 1,
            0 if self.recommended else 1,
            0 if self.source.enabled else 1,
            self.source.alias.value,
        )


@dataclass(frozen=True, slots=True)
class SourceStageView:
    configuration: UserConfiguration
    policy: OrganizationPolicy
    rows: tuple[SourceStageRow, ...]
    allow_no_source: bool
    allow_direct_sources: bool
    first_run: bool

    def __post_init__(self) -> None:
        rows = tuple(sorted(self.rows, key=lambda row: row.rank))
        aliases = tuple(row.source.alias for row in rows)
        if len(set(aliases)) != len(aliases):
            raise ValueError("source-stage aliases must be unique")
        if set(aliases) != {source.alias for source in self.configuration.sources}:
            raise ValueError("source-stage rows must represent the exact configuration")
        if self.allow_no_source != (not self.policy.required_sources):
            raise ValueError("source-stage no-source option must follow organization policy")
        if self.allow_direct_sources != (self.policy.allow_direct_sources is not False):
            raise ValueError("source-stage direct-source option must follow organization policy")
        object.__setattr__(self, "rows", rows)

    @property
    def unconfigured_recommended(self) -> tuple[SourceAlias, ...]:
        configured = {row.source.alias for row in self.rows}
        return tuple(alias for alias in self.policy.recommended_sources if alias not in configured)

    @property
    def unconfigured_required(self) -> tuple[SourceAlias, ...]:
        configured = {row.source.alias for row in self.rows}
        return tuple(alias for alias in self.policy.required_sources if alias not in configured)


def _configuration_operations(
    before: UserConfiguration,
    after: UserConfiguration,
) -> tuple[SourceOperation, ...]:
    if (
        before.schema_version != after.schema_version
        or before.sync != after.sync
        or before.reporting != after.reporting
        or tuple(source.alias for source in before.sources)
        != tuple(source.alias for source in after.sources)
    ):
        raise ValueError("source-management request may change only enabled/default source fields")
    operations = []
    for previous, desired in zip(before.sources, after.sources, strict=True):
        if replace(previous, enabled=desired.enabled) != desired:
            raise ValueError("source-management request changed source identity or origin")
        if previous.enabled and not desired.enabled:
            operations.append(SourceOperation(SourceOperationKind.DISABLE, previous.alias))
    for previous, desired in zip(before.sources, after.sources, strict=True):
        if not previous.enabled and desired.enabled:
            operations.append(SourceOperation(SourceOperationKind.ENABLE, previous.alias))
    if before.default_registry != after.default_registry:
        operations.append(
            SourceOperation(SourceOperationKind.CLEAR_DEFAULT)
            if after.default_registry is None
            else SourceOperation(SourceOperationKind.USE_DEFAULT, after.default_registry)
        )
    return tuple(operations)


@dataclass(frozen=True, slots=True)
class SourceManagementRequest:
    """Reviewed before/after value and its user-facing effects; still entirely inert."""

    before: UserConfiguration
    after: UserConfiguration
    policy: OrganizationPolicy
    operations: tuple[SourceOperation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.before, UserConfiguration) or not isinstance(
            self.after, UserConfiguration
        ):
            raise ValueError("source-management request configuration is invalid")
        if not isinstance(self.policy, OrganizationPolicy) or not all(
            isinstance(operation, SourceOperation) for operation in self.operations
        ):
            raise ValueError("source-management request is invalid")
        if self.operations != _configuration_operations(self.before, self.after):
            raise ValueError("source-management operations do not match the reviewed values")


@dataclass(frozen=True, slots=True)
class SourceAdditionRequest:
    """One reviewed first-use source addition, kept separate from toggle-only management.

    ``SourceManagementRequest`` deliberately permits only enabled/default changes to already
    configured sources.  Adding an origin is a different trust boundary: it has its own immutable
    request, explicit source value, synchronization step, and confirmation in the TUI.
    """

    before: UserConfiguration
    after: UserConfiguration
    policy: OrganizationPolicy
    source: ConfiguredSource
    make_default: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.before, UserConfiguration)
            or not isinstance(self.after, UserConfiguration)
            or not isinstance(self.policy, OrganizationPolicy)
            or not isinstance(self.source, ConfiguredSource)
            or not isinstance(self.make_default, bool)
        ):
            raise ValueError("source-addition request is invalid")
        validated = validate_configured_source(self.source)
        if isinstance(validated, Err) or validated.value != self.source:
            raise ValueError("source addition source is not schema-safe")
        if (
            self.before.schema_version != self.after.schema_version
            or self.before.sync != self.after.sync
            or self.before.reporting != self.after.reporting
        ):
            raise ValueError("source addition may not change unrelated configuration")
        before_by_alias = {item.alias: item for item in self.before.sources}
        after_by_alias = {item.alias: item for item in self.after.sources}
        if (
            self.source.alias in before_by_alias
            or after_by_alias.get(self.source.alias) != self.source
        ):
            raise ValueError("source addition must add its exact new source once")
        if any(
            existing.kind is self.source.kind
            and existing.location == self.source.location
            and existing.ref == self.source.ref
            for existing in self.before.sources
        ):
            # SRC02: identity is (kind, location, ref), so only an exact repeat is a duplicate.
            raise ValueError("source addition may not duplicate a configured source origin and ref")
        if set(after_by_alias) != set(before_by_alias) | {self.source.alias}:
            raise ValueError("source addition may not remove or replace configured sources")
        if any(after_by_alias[alias] != source for alias, source in before_by_alias.items()):
            raise ValueError("source addition may not change existing configured sources")
        expected_default = self.source.alias if self.make_default else self.before.default_registry
        if self.after.default_registry != expected_default:
            raise ValueError("source addition default registry is inconsistent")
        if self.make_default and not self.source.is_registry:
            raise ValueError("only a new registry may become the default registry")
        if not self.source.enabled:
            raise ValueError("a newly added source must be enabled")


@dataclass(frozen=True, slots=True)
class SourceRemovalRequest:
    """One reviewed unsubscribe, kept separate from toggle-only management.

    Removal ends a subscription: it deletes the configuration entry and, at the runtime boundary,
    the managed snapshot for that origin.  Disabling a source is a different thing entirely — it
    stops reads while keeping both — so the two never share a request value.
    """

    before: UserConfiguration
    after: UserConfiguration
    policy: OrganizationPolicy
    source: ConfiguredSource
    cleared_default: bool

    def __post_init__(self) -> None:
        if not isinstance(self.before, UserConfiguration) or not isinstance(
            self.after, UserConfiguration
        ):
            raise ValueError("source removal request configuration is invalid")
        if not isinstance(self.policy, OrganizationPolicy) or not isinstance(
            self.source, ConfiguredSource
        ):
            raise ValueError("source removal request is invalid")
        remaining = tuple(
            source for source in self.before.sources if source.alias != self.source.alias
        )
        if self.after.sources != remaining:
            raise ValueError("source removal must drop exactly the reviewed alias")
        if len(remaining) == len(self.before.sources):
            raise ValueError("source removal request names an unconfigured alias")
        cleared = self.before.default_registry == self.source.alias
        if cleared != self.cleared_default:
            raise ValueError("source removal default-registry effect is inconsistent")
        expected_default = None if cleared else self.before.default_registry
        if self.after.default_registry != expected_default:
            raise ValueError("source removal may only clear a default registry it owned")


@dataclass(frozen=True, slots=True)
class SourceSelection:
    """Source filter plus its deferred configuration request and captured health evidence."""

    enabled_aliases: tuple[SourceAlias, ...]
    default_registry: SourceAlias | None
    no_source: bool
    request: SourceManagementRequest
    health_snapshot: tuple[tuple[SourceAlias, SourceDisplayHealth], ...]

    def __post_init__(self) -> None:
        aliases = tuple(sorted(set(self.enabled_aliases)))
        if aliases != self.enabled_aliases:
            raise ValueError("source selection aliases must be sorted and unique")
        if self.no_source == bool(aliases):
            raise ValueError("source selection must choose sources or the no-source path")
        if self.default_registry is not None and self.default_registry not in aliases:
            raise ValueError("default registry must be selected")
        enabled_after = tuple(
            source.alias for source in self.request.after.sources if source.enabled
        )
        if enabled_after != aliases or self.request.after.default_registry != self.default_registry:
            raise ValueError("source selection does not match its deferred configuration")
        snapshot = tuple(sorted(self.health_snapshot, key=lambda item: item[0].value))
        if len({alias for alias, _health in snapshot}) != len(snapshot):
            raise ValueError("source health snapshot aliases must be unique")
        if {alias for alias, _health in snapshot} != {
            source.alias for source in self.request.before.sources
        }:
            raise ValueError("source selection health must cover the reviewed configuration")
        object.__setattr__(self, "health_snapshot", snapshot)


def _error(message: str, *remediation: str) -> Err:
    return Err(
        (
            Diagnostic(
                SOURCE_SELECTION_INVALID,
                Severity.ERROR,
                message,
                remediation=tuple(remediation),
            ),
        )
    )


def _origin(source: ConfiguredSource) -> str:
    if source.kind is SourceKind.SOURCE_LOCAL:
        return source.location
    parsed = git_location_parts(source.location)
    return "invalid Git origin" if parsed is None else f"{parsed[0]}/{parsed[1]}"


def _display_health(
    source: ConfiguredSource,
    health: SourceHealth | None,
) -> SourceDisplayHealth:
    if not source.enabled:
        return SourceDisplayHealth.DISABLED
    if health is None or health.status is HealthStatus.MISSING:
        return SourceDisplayHealth.MISSING
    if health.status is HealthStatus.HEALTHY:
        return SourceDisplayHealth.CURRENT
    if health.status is HealthStatus.STALE:
        return SourceDisplayHealth.STALE
    codes = {diagnostic.code.value for diagnostic in health.diagnostics}
    if "source-incompatible" in codes:
        return SourceDisplayHealth.INCOMPATIBLE
    if "source-unavailable" in codes or "source-auth-failed" in codes:
        return SourceDisplayHealth.OFFLINE
    return SourceDisplayHealth.INVALID


def _company_reviewed(
    source: ConfiguredSource,
    health: SourceHealth | None,
    policy: OrganizationPolicy,
) -> bool:
    if source.kind is not SourceKind.REGISTRY_GIT or health is None or health.current is None:
        return False
    parts = git_location_parts(source.location)
    if parts is None:
        return False
    identity = CompanyReviewedSource(health.current.declared_source_id, parts[0], parts[1])
    return identity in policy.company_reviewed_sources


def _availability_reason(
    source: ConfiguredSource,
    display_health: SourceDisplayHealth,
    policy: OrganizationPolicy,
) -> str:
    if source.kind is not SourceKind.REGISTRY_GIT and policy.allow_direct_sources is False:
        return "direct sources are disabled by organization policy"
    if display_health is SourceDisplayHealth.INCOMPATIBLE:
        return "source is incompatible with this AART version"
    if display_health is SourceDisplayHealth.INVALID:
        return "source state is invalid; run source doctor before enabling it"
    if source.kind is not SourceKind.SOURCE_LOCAL and git_location_parts(source.location) is None:
        return "source has an invalid Git origin"
    return ""


def build_source_stage(
    configuration: UserConfiguration,
    policy: OrganizationPolicy,
    health_by_alias: Mapping[SourceAlias, SourceHealth],
    *,
    first_run: bool = False,
) -> Result[SourceStageView]:
    """Project exact local configuration/policy/health facts into deterministic TUI rows."""

    configured_aliases = {source.alias for source in configuration.sources}
    unknown_health = tuple(sorted(set(health_by_alias) - configured_aliases))
    if unknown_health:
        return _error(
            "source health contains aliases absent from the effective configuration: "
            + ", ".join(alias.value for alias in unknown_health)
        )
    rows = []
    for source in configuration.sources:
        health = health_by_alias.get(source.alias)
        display_health = _display_health(source, health)
        reason = _availability_reason(source, display_health, policy)
        rows.append(
            SourceStageRow(
                source,
                _origin(source),
                display_health,
                None if health is None else health.age_seconds,
                source.alias in policy.recommended_sources,
                source.alias in policy.required_sources,
                _company_reviewed(source, health, policy),
                configuration.default_registry == source.alias,
                not reason,
                reason,
            )
        )
    return Ok(
        SourceStageView(
            configuration,
            policy,
            tuple(rows),
            not policy.required_sources,
            policy.allow_direct_sources is not False,
            first_run,
        )
    )


def _default_registry(
    view: SourceStageView,
    selected: tuple[SourceAlias, ...],
    requested: SourceAlias | None,
) -> SourceAlias | None:
    if requested is not None:
        return requested
    current = view.configuration.default_registry
    if current is not None and current in selected:
        return current
    registries = tuple(
        row.source.alias
        for row in view.rows
        if row.source.alias in selected and row.source.kind is SourceKind.REGISTRY_GIT
    )
    return registries[0] if registries else None


def plan_source_management(
    view: SourceStageView,
    enabled_aliases: tuple[SourceAlias, ...],
    *,
    default_registry: SourceAlias | None = None,
    no_source: bool = False,
) -> Result[SourceSelection]:
    """Validate one source-screen choice and return an inert, policy-checked change request."""

    aliases = tuple(sorted(set(enabled_aliases)))
    if len(aliases) != len(enabled_aliases):
        return _error("source selection contains duplicate aliases")
    if no_source and aliases:
        return _error("continue-without-sources cannot be combined with selected sources")
    if no_source and not view.allow_no_source:
        return _error("organization policy requires at least one configured source")
    if not no_source and not aliases:
        return _error("select at least one source or explicitly continue without sources")
    rows = {row.source.alias: row for row in view.rows}
    unknown = tuple(alias for alias in aliases if alias not in rows)
    if unknown:
        return _error("unknown source selection: " + ", ".join(alias.value for alias in unknown))
    unavailable = tuple(rows[alias] for alias in aliases if not rows[alias].selectable)
    if unavailable:
        return _error(
            "; ".join(f"{row.source.alias}: {row.reason}" for row in unavailable),
            "choose a policy-approved compatible source",
        )
    required = set(view.policy.required_sources)
    missing_required = tuple(sorted(required - set(aliases)))
    if missing_required:
        return _error(
            "required sources are not selected: "
            + ", ".join(alias.value for alias in missing_required)
        )
    default = None if no_source else _default_registry(view, aliases, default_registry)
    if default is not None:
        row = rows.get(default)
        if row is None or default not in aliases or row.source.kind is not SourceKind.REGISTRY_GIT:
            return _error("default registry must name one selected registry source")

    selected = set(aliases)
    desired_sources = tuple(
        replace(source, enabled=source.alias in selected) for source in view.configuration.sources
    )
    desired = replace(view.configuration, sources=desired_sources, default_registry=default)
    allowed = apply_configuration(desired, RuntimeOverrides(), view.policy)
    if isinstance(allowed, Err):
        return allowed

    operations = _configuration_operations(view.configuration, desired)
    request = SourceManagementRequest(
        view.configuration,
        desired,
        view.policy,
        operations,
    )
    snapshot = tuple((row.source.alias, row.health) for row in view.rows)
    return Ok(SourceSelection(aliases, default, no_source, request, snapshot))


def plan_source_addition(
    view: SourceStageView,
    source: ConfiguredSource,
    *,
    make_default: bool | None = None,
) -> Result[SourceAdditionRequest]:
    """Plan one explicit source-onboarding write without synchronizing or saving anything.

    The caller must use the schema parser for raw terminal input.  This pure planner owns the
    configuration and organization-policy boundary, while the runtime later acquires a validated
    snapshot before atomically persisting the reviewed value.
    """

    if not isinstance(source, ConfiguredSource):
        return _error("source addition requires a configured source value")
    validated = validate_configured_source(source)
    if isinstance(validated, Err):
        return validated
    source = validated.value
    if not source.enabled:
        return _error("new source must be enabled")
    if any(existing.alias == source.alias for existing in view.configuration.sources):
        return _error(
            f"source alias is already configured: {source.alias}",
            f"run `aart source sync --alias {source.alias}` to refresh it, "
            f"`aart source resubscribe --alias {source.alias}` if its declared identity changed, "
            f"or `aart source remove --alias {source.alias}` to subscribe to a different origin",
        )
    # SRC02: the store is keyed by (origin, ref), so a second ref of a configured origin is a
    # legitimate new source.  The same origin at the same ref would still resolve to one mirror
    # and one pointer, so it stays refused.
    same_origin_and_ref = tuple(
        existing.alias
        for existing in view.configuration.sources
        if existing.is_git
        and source.is_git
        and existing.ref == source.ref
        and git_origin_key(existing.kind, existing.location)
        == git_origin_key(source.kind, source.location)
    )
    if same_origin_and_ref:
        held = ", ".join(alias.value for alias in same_origin_and_ref)
        return _error(
            "source origin and ref are already configured as " + held,
            f"run `aart source sync --alias {same_origin_and_ref[0].value}` to refresh it, "
            f"`aart source resubscribe --alias {same_origin_and_ref[0].value}` if its declared "
            f"identity changed, `aart source remove --alias {same_origin_and_ref[0].value}` to "
            "free the origin, or add this origin at a different ref",
        )
    if source.kind is not SourceKind.REGISTRY_GIT and not view.allow_direct_sources:
        return _error("direct sources are disabled by organization policy")
    if source.is_git and git_location_parts(source.location) is None:
        return _error("source has an invalid Git origin")
    chosen_default = (
        source.is_registry and not any(row.source.is_registry for row in view.rows)
        if make_default is None
        else make_default
    )
    if chosen_default and not source.is_registry:
        return _error("only a registry source can become the default registry")
    desired = replace(
        view.configuration,
        sources=(*view.configuration.sources, source),
        default_registry=source.alias if chosen_default else view.configuration.default_registry,
    )
    allowed = apply_configuration_for_source_management(desired, view.policy)
    if isinstance(allowed, Err):
        return allowed
    try:
        return Ok(
            SourceAdditionRequest(
                view.configuration,
                desired,
                view.policy,
                source,
                chosen_default,
            )
        )
    except ValueError as error:
        return _error(str(error))


def plan_source_removal(view: SourceStageView, alias: SourceAlias) -> Result[SourceRemovalRequest]:
    """Plan one explicit unsubscribe without touching the store or saving anything.

    Organization policy owns whether an alias may leave: a required source is not removable, and a
    configuration that policy would reject after the removal is refused here rather than written.
    """

    if not isinstance(alias, SourceAlias):
        return _error("source removal requires a configured source alias")
    selected = tuple(source for source in view.configuration.sources if source.alias == alias)
    if not selected:
        return _error(
            f"no configured source has alias {alias}",
            "run `aart source list` to see configured aliases",
        )
    if alias in view.policy.required_sources:
        return _error(
            f"organization policy requires source {alias}",
            "ask the policy owner to drop the requirement before removing this source",
        )
    source = selected[0]
    cleared_default = view.configuration.default_registry == alias
    desired = replace(
        view.configuration,
        sources=tuple(
            existing for existing in view.configuration.sources if existing.alias != alias
        ),
        default_registry=None if cleared_default else view.configuration.default_registry,
    )
    allowed = apply_configuration_for_source_management(desired, view.policy)
    if isinstance(allowed, Err):
        return allowed
    try:
        return Ok(
            SourceRemovalRequest(
                view.configuration,
                desired,
                view.policy,
                source,
                cleared_default,
            )
        )
    except ValueError as error:
        return _error(str(error))


def _source_kind(source: ConfiguredSource) -> str:
    if source.kind is SourceKind.REGISTRY_GIT:
        return "registry"
    if source.kind is SourceKind.SOURCE_GIT:
        return "direct Git source"
    return "mutable local source"


def render_source_row(row: SourceStageRow) -> str:
    """Render one bounded, credential-free source choice with explicit local trust facts."""

    flags = []
    if row.required:
        flags.append("organization required")
    elif row.recommended:
        flags.append("organization recommended")
    if row.company_reviewed:
        flags.append("company reviewed")
    if row.source.enabled:
        flags.append("enabled")
    if row.is_default:
        flags.append("default")
    details = ", ".join(flags)
    detail_text = f"; {details}" if details else ""
    reason = f"; unavailable: {row.reason}" if row.reason else ""
    age = f", age {row.age_seconds}s" if row.age_seconds is not None else ""
    return (
        f"{row.source.alias} — {_source_kind(row.source)} at {row.origin}; "
        f"health: {row.health.value}{age}{detail_text}{reason}"
    )


def render_source_stage(view: SourceStageView) -> tuple[str, ...]:
    """Render source setup guidance and rows shared by text and curses frontends."""

    heading = (
        "Choose enabled artifact sources. Registries are optional unless organization policy "
        "marks one as required."
    )
    lines: tuple[str, ...] = (heading,)
    if not view.rows:
        lines += ("No sources are configured. In the Sources stage, choose Add to configure one.",)
    if view.unconfigured_recommended:
        lines += (
            "Organization-recommended source aliases still need configuration: "
            + ", ".join(alias.value for alias in view.unconfigured_recommended),
        )
    if view.unconfigured_required:
        lines += (
            "Organization-required source aliases still need configuration: "
            + ", ".join(alias.value for alias in view.unconfigured_required),
        )
    lines += tuple(render_source_row(row) for row in view.rows)
    if view.allow_no_source:
        lines += ("Continue without sources — exit cleanly without installing artifacts.",)
    else:
        lines += ("Organization policy requires the listed required source(s).",)
    return lines


def render_source_addition_review(request: SourceAdditionRequest) -> tuple[str, ...]:
    """Render the bounded, credential-free review surface before source acquisition/write."""

    source = request.source
    origin = _origin(source)
    ref = "" if source.ref is None else f"; ref: {source.ref}"
    default = "; becomes the default registry" if request.make_default else ""
    return (
        "Source setup review:",
        f"  alias: {source.alias}",
        f"  kind: {_source_kind(source)}",
        f"  origin: {origin}{ref}",
        "  next: download and validate one immutable source snapshot, then save this source",
        f"  effect: enable {source.alias}{default}",
    )


def render_source_sync_review(row: SourceStageRow) -> tuple[str, ...]:
    """Render the bounded review before one already-configured origin is fetched again.

    Synchronizing changes what the marketplace offers, never what a project already installed, so
    the review says both: the effect is on availability, and installed files stay untouched.
    """

    source = row.source
    ref = "" if source.ref is None else f"; ref: {source.ref}"
    return (
        "Source sync review:",
        f"  alias: {source.alias}",
        f"  kind: {_source_kind(source)}",
        f"  origin: {row.origin}{ref}",
        f"  health now: {row.health.value}",
        "  next: download and validate one immutable snapshot, then replace the managed snapshot",
        "  effect: artifacts added upstream become installable, and artifacts dropped upstream "
        "stop being offered",
        "  keeps: every installed artifact, until you install or update it from the new snapshot",
    )


def render_source_sync_outcome(alias: SourceAlias, outcome: SourceSyncOutcome) -> tuple[str, ...]:
    """Say which of the three synchronization results happened, in the user's own terms."""

    revision = outcome.current.candidate.resolved_revision
    if outcome.disposition is SyncDisposition.PUBLISHED:
        headline = f"{alias}: snapshot updated to {revision}; its artifacts are available now"
    elif outcome.disposition is SyncDisposition.UNCHANGED:
        headline = f"{alias}: already current at {revision}; nothing changed"
    else:
        headline = f"{alias}: could not refresh; keeping the last good snapshot at {revision}"
    warnings = tuple(
        f"  {diagnostic.severity.value}: {diagnostic.message}" for diagnostic in outcome.diagnostics
    )
    return (headline, *warnings)


def plan_source_resubscription(
    view: SourceStageView, alias: SourceAlias
) -> Result[ConfiguredSource]:
    """Select the subscription whose identity may be adopted, changing nothing.

    Resubscription writes no configuration at all, so there is no desired configuration to plan —
    only the question of whether this alias is one AART may act on.  The transition itself comes
    from the runtime, which is the only layer that can see what the origin declares today.
    """

    if not isinstance(alias, SourceAlias):
        return _error("source resubscription requires a configured source alias")
    selected = tuple(source for source in view.configuration.sources if source.alias == alias)
    if not selected:
        return _error(
            f"no configured source has alias {alias}",
            "run `aart source list` to see configured aliases",
        )
    source = selected[0]
    if not source.enabled:
        return _error(
            f"source {alias} is disabled",
            f"enable {alias} in the TUI Sources stage before adopting a new identity",
        )
    return Ok(source)


@dataclass(frozen=True, slots=True)
class SourceResubscriptionRequest:
    """One reviewed identity adoption, dispatched identically by both front-ends.

    It carries no configuration at all — that is the operation's whole point.  Alias, kind,
    location, ref, and the default-registry flag survive because nothing here can express a change
    to them, which is the difference between adopting an identity and re-subscribing by hand.
    """

    source: ConfiguredSource
    transition: SourceIdentityTransition

    def __post_init__(self) -> None:
        if not isinstance(self.source, ConfiguredSource) or not isinstance(
            self.transition, SourceIdentityTransition
        ):
            raise ValueError("source resubscription request is invalid")
        if not self.source.enabled:
            raise ValueError("a disabled source cannot be resubscribed")


def _short(digest: ObjectDigest) -> str:
    return digest.value[:12]


def render_source_resubscription_review(request: SourceResubscriptionRequest) -> tuple[str, ...]:
    """Render both identities, so the operator approves a transition rather than a destination."""

    source = request.source
    ref = "" if source.ref is None else f"; ref: {source.ref}"
    transition = request.transition
    return (
        "Source resubscription review:",
        f"  alias: {source.alias}",
        f"  kind: {_source_kind(source)}",
        f"  origin: {_origin(source)}{ref}",
        f"  identity: {transition.from_source_id.value} -> {transition.to_source_id.value}",
        f"  revision: {transition.from_revision} -> {transition.to_revision}",
        f"  snapshot: {_short(transition.from_digest)} -> {_short(transition.to_digest)}",
        f"  preserves: alias, kind, origin{ref and ', ref'}, and the default-registry flag",
        "  effect: publish the new snapshot and bind this alias to it",
        "  keeps: every installed artifact and every file in every project",
        "  note: installed artifacts are not re-installed; they surface as update-available or "
        "removed-upstream through the normal reconciliation",
    )


def render_source_removal_review(request: SourceRemovalRequest) -> tuple[str, ...]:
    """Render the bounded review before a subscription and its managed snapshot are dropped."""

    source = request.source
    ref = "" if source.ref is None else f"; ref: {source.ref}"
    default = (
        ("  effect: clear the default registry; no source becomes default in its place",)
        if request.cleared_default
        else ()
    )
    return (
        "Source removal review:",
        f"  alias: {source.alias}",
        f"  kind: {_source_kind(source)}",
        f"  origin: {_origin(source)}{ref}",
        f"  effect: forget {source.alias} and delete its managed snapshot",
        *default,
        "  keeps: every installed artifact and every file in every project",
        "  note: AART cannot see installation records in other project directories; a project "
        "still naming this alias reports an unconfigured source until it is re-added or "
        "uninstalled",
    )
