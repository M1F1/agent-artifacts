"""Pure selection of an explicitly configured registry-owned report destination."""

from __future__ import annotations

from agent_artifacts.configuration.model import (
    ConfiguredSource,
    ReportingMode,
    SourceKind,
    git_location_parts,
)
from agent_artifacts.configuration.policy import EffectiveConfiguration
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.registry_models import ServiceAdvertisement

from .model import ReportingDestination

REPORTING_DESTINATION_INVALID = DiagnosticCode("reporting-destination-invalid")


def _error(message: str) -> Err:
    return Err((Diagnostic(REPORTING_DESTINATION_INVALID, Severity.ERROR, message),))


def configured_reporting_source(
    effective: EffectiveConfiguration,
) -> Result[ConfiguredSource | None]:
    """Select an explicit central destination; ``prompt`` without one routes per registry."""

    settings = effective.configuration.reporting
    if settings.mode is ReportingMode.DISABLED:
        return Ok(None)
    if settings.destination is None:
        if settings.mode is ReportingMode.PROMPT:
            return Ok(None)
        return _error("automatic reporting has no explicit destination")
    matches = tuple(
        source
        for source in effective.configuration.sources
        if source.enabled and source.alias == settings.destination
    )
    if len(matches) != 1 or matches[0].kind is not SourceKind.REGISTRY_GIT:
        return _error("reporting destination must identify one enabled registry source")
    return Ok(matches[0])


def destination_from_services(
    mode: ReportingMode,
    source: ConfiguredSource,
    services: tuple[ServiceAdvertisement, ...],
) -> Result[ReportingDestination]:
    """Bind a registry advertisement to the host of that exact configured registry."""

    if mode not in {ReportingMode.PROMPT, ReportingMode.AUTOMATIC}:
        return _error("disabled reporting has no destination")
    if source.kind is not SourceKind.REGISTRY_GIT or not source.enabled:
        return _error("reporting service source must be an enabled registry")
    location = git_location_parts(source.location)
    if location is None:
        return _error("reporting registry has an invalid Git location")
    advertised = tuple(service for service in services if service.name == "usage_reporting")
    if len(advertised) != 1:
        return _error("reporting registry must advertise exactly one usage_reporting service")
    service = advertised[0]
    if service.kind != "github-issues" or service.repository is None:
        return _error("usage_reporting service must use github-issues with a repository")
    try:
        return Ok(ReportingDestination(mode, location[0], service.repository))
    except ValueError as error:
        return _error(str(error))


__all__ = [
    "REPORTING_DESTINATION_INVALID",
    "configured_reporting_source",
    "destination_from_services",
]
