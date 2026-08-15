"""Pure configuration precedence, organization-policy checks, and redaction."""

from __future__ import annotations

from dataclasses import dataclass, replace

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Err, Ok, Result

from ..redaction import redact_text
from .model import (
    OrganizationPolicy,
    ReportingMode,
    ReportingSettings,
    SourceKind,
    SyncMode,
    SyncSettings,
    UserConfiguration,
    git_location_parts,
)

SOURCE_POLICY_DENIED = DiagnosticCode("source-policy-denied")
CONFIG_INVALID = DiagnosticCode("config-invalid")
_PUBLIC_GIT_HOSTS = frozenset({"github.com", "gitlab.com", "bitbucket.org"})


@dataclass(frozen=True, slots=True)
class RuntimeOverrides:
    default_registry: SourceAlias | None = None
    sync_mode: SyncMode | None = None
    max_age_seconds: int | None = None
    reporting_mode: ReportingMode | None = None
    reporting_destination: SourceAlias | None = None


@dataclass(frozen=True, slots=True)
class EffectiveConfiguration:
    configuration: UserConfiguration
    policy: OrganizationPolicy
    locked_fields: tuple[str, ...]


def _denied(message: str) -> Diagnostic:
    return Diagnostic(SOURCE_POLICY_DENIED, Severity.ERROR, redact_text(message))


def _invalid(message: str) -> Err:
    return Err((Diagnostic(CONFIG_INVALID, Severity.ERROR, redact_text(message)),))


def _locked_override_diagnostics(
    overrides: RuntimeOverrides, policy: OrganizationPolicy
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    reporting = policy.reporting
    if (
        reporting.mode is not None
        and overrides.reporting_mode is not None
        and overrides.reporting_mode is not reporting.mode
    ):
        diagnostics.append(_denied("runtime override of policy-locked reporting.mode is denied"))
    if (
        reporting.destination is not None
        and overrides.reporting_destination is not None
        and overrides.reporting_destination != reporting.destination
    ):
        diagnostics.append(
            _denied("runtime override of policy-locked reporting.destination is denied")
        )
    return tuple(diagnostics)


def _policy_diagnostics(
    configuration: UserConfiguration,
    policy: OrganizationPolicy,
    *,
    allow_missing_required_sources: bool = False,
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    enabled = {source.alias: source for source in configuration.sources if source.enabled}
    if not allow_missing_required_sources:
        for required in policy.required_sources:
            if required not in enabled:
                diagnostics.append(
                    _denied(f"required source {required} is not configured and enabled")
                )
    for source in enabled.values():
        if policy.allow_direct_sources is False and source.kind is not SourceKind.REGISTRY_GIT:
            diagnostics.append(
                _denied(f"direct source {source.alias} is denied by organization policy")
            )
        if not source.is_git:
            continue
        location = git_location_parts(source.location)
        if location is None:
            diagnostics.append(_denied(f"source {source.alias} has an invalid Git location"))
            continue
        host, repository = location
        if policy.allowed_git_hosts is not None and host not in policy.allowed_git_hosts:
            diagnostics.append(_denied(f"Git host for source {source.alias} is not allowed"))
        if policy.allowed_repository_prefixes is not None and not any(
            repository.startswith(prefix) for prefix in policy.allowed_repository_prefixes
        ):
            diagnostics.append(_denied(f"repository path for source {source.alias} is not allowed"))
    destination = configuration.reporting.destination
    if destination is not None:
        target = enabled.get(destination)
        if target is None or not target.is_registry:
            diagnostics.append(_denied("reporting destination must be an enabled registry source"))
        elif policy.reporting.deny_public_destinations:
            location = git_location_parts(target.location)
            if location is not None and location[0] in _PUBLIC_GIT_HOSTS:
                diagnostics.append(_denied("public reporting destinations are denied by policy"))
    return tuple(diagnostics)


def _apply_configuration(
    user: UserConfiguration,
    overrides: RuntimeOverrides,
    policy: OrganizationPolicy,
    *,
    allow_missing_required_sources: bool,
) -> Result[EffectiveConfiguration]:
    """Apply precedence and policy, with a narrowly scoped source-onboarding exception."""

    locked_diagnostics = _locked_override_diagnostics(overrides, policy)
    if locked_diagnostics:
        return Err(locked_diagnostics)
    try:
        sync = SyncSettings(
            user.sync.mode if overrides.sync_mode is None else overrides.sync_mode,
            (
                user.sync.max_age_seconds
                if overrides.max_age_seconds is None
                else overrides.max_age_seconds
            ),
        )
        runtime_reporting_mode = (
            user.reporting.mode if overrides.reporting_mode is None else overrides.reporting_mode
        )
        runtime_reporting_destination = (
            user.reporting.destination
            if overrides.reporting_destination is None
            else overrides.reporting_destination
        )
        reporting = ReportingSettings(
            (runtime_reporting_mode if policy.reporting.mode is None else policy.reporting.mode),
            (
                runtime_reporting_destination
                if policy.reporting.destination is None
                else policy.reporting.destination
            ),
        )
        effective = replace(
            user,
            default_registry=(
                user.default_registry
                if overrides.default_registry is None
                else overrides.default_registry
            ),
            sync=sync,
            reporting=reporting,
        )
    except ValueError as error:
        return _invalid(str(error))
    sources = {source.alias: source for source in effective.sources if source.enabled}
    if effective.default_registry is not None:
        default = sources.get(effective.default_registry)
        if default is None or not default.is_registry:
            return _invalid("effective default registry must name an enabled registry")
    diagnostics = _policy_diagnostics(
        effective,
        policy,
        allow_missing_required_sources=allow_missing_required_sources,
    )
    if diagnostics:
        return Err(diagnostics)
    locked_fields = tuple(
        sorted(
            name
            for name, value in (
                ("reporting.destination", policy.reporting.destination),
                ("reporting.mode", policy.reporting.mode),
            )
            if value is not None
        )
    )
    return Ok(EffectiveConfiguration(effective, policy, locked_fields))


def apply_configuration(
    user: UserConfiguration,
    overrides: RuntimeOverrides,
    policy: OrganizationPolicy,
) -> Result[EffectiveConfiguration]:
    """Apply built-in/user/runtime/policy precedence for a content-capable operation."""

    return _apply_configuration(
        user,
        overrides,
        policy,
        allow_missing_required_sources=False,
    )


def apply_configuration_for_source_management(
    user: UserConfiguration,
    policy: OrganizationPolicy,
    overrides: RuntimeOverrides | None = None,
) -> Result[EffectiveConfiguration]:
    """Validate a source-management state without authorizing marketplace content.

    Organizations may require several source aliases.  A user must be able to synchronize and
    persist each allowed alias one at a time, but the ordinary content configuration path remains
    fail-closed until all required aliases are enabled.  This helper bypasses *only* that missing
    alias check; all origin, direct-source, reporting, and default-registry constraints remain in
    force.
    """

    return _apply_configuration(
        user,
        RuntimeOverrides() if overrides is None else overrides,
        policy,
        allow_missing_required_sources=True,
    )
