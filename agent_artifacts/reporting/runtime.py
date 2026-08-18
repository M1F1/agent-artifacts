"""Local composition root for destination-bound, optional usage reporting."""

from __future__ import annotations

import os
import sys
from typing import Callable

from agent_artifacts.application.configuration import (
    ConfigurationPorts,
    ConfigurationRequest,
    load_configuration,
)
from agent_artifacts.configuration.model import (
    ReportingMode,
    SourceKind,
    UserConfiguration,
    git_location_parts,
)
from agent_artifacts.configuration.paths import Platform, resolve_config_paths
from agent_artifacts.configuration.policy import (
    EffectiveConfiguration,
    RuntimeOverrides,
    apply_configuration,
)
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.io.config_store import (
    read_configuration,
    recover_configuration,
    write_configuration,
)
from agent_artifacts.io.source_store import read_current_source
from agent_artifacts.protocol.native_tree import SnapshotEntryKind
from agent_artifacts.protocol.registry_schema import (
    parse_registry_index,
    parse_registry_manifest,
)
from agent_artifacts.sources.model import (
    CurrentSource,
    CurrentSourceRequest,
    source_instance_id,
    source_store_paths,
)

from .application import (
    RegistryReportingNotice,
    RegistryReportingRoute,
    ReportingApplicationService,
    ReportingProvider,
)
from .destination import configured_reporting_source, destination_from_services
from .io import GitHubIssueProvider, browser_provider
from .model import ReportingDestination

REPORTING_RUNTIME_INVALID = DiagnosticCode("reporting-runtime-invalid")
CurrentSourcePort = Callable[[CurrentSourceRequest], Result[CurrentSource | None]]
_PUBLIC_GIT_HOSTS = frozenset({"github.com", "gitlab.com", "bitbucket.org"})


def _error(message: str) -> Err:
    return Err((Diagnostic(REPORTING_RUNTIME_INVALID, Severity.ERROR, message),))


def _snapshot_file(current: CurrentSource, path: str) -> Result[bytes]:
    matches = tuple(item for item in current.candidate.snapshot.entries if str(item.path) == path)
    if len(matches) != 1 or matches[0].kind is not SnapshotEntryKind.FILE:
        return _error(f"reporting registry snapshot has no unique regular {path}")
    return Ok(matches[0].content)


def _coherent_services(current: CurrentSource):
    manifest_bytes = _snapshot_file(current, "aart-registry.json")
    if isinstance(manifest_bytes, Err):
        return manifest_bytes
    index_bytes = _snapshot_file(current, "aart.index.json")
    if isinstance(index_bytes, Err):
        return index_bytes
    manifest = parse_registry_manifest(manifest_bytes.value)
    if isinstance(manifest, Err):
        return manifest
    index = parse_registry_index(index_bytes.value)
    if isinstance(index, Err):
        return index
    if (
        manifest.value.registry_id != current.declared_source_id
        or index.value.registry_id != current.declared_source_id
        or index.value.services != manifest.value.services
    ):
        return _error("reporting registry manifest and compiled index do not agree")
    return Ok(manifest.value.services)


def reporting_destination_from_current(
    effective: EffectiveConfiguration,
    data_root: str,
    read_current: CurrentSourcePort = read_current_source,
) -> Result[ReportingDestination | None]:
    """Resolve the configured endpoint from its committed current snapshot without syncing."""

    selected = configured_reporting_source(effective)
    if isinstance(selected, Err):
        return selected
    if selected.value is None:
        return Ok(None)
    source = selected.value
    current = read_current(
        CurrentSourceRequest(
            source_store_paths(data_root, source_instance_id(source)),
            source.alias,
        )
    )
    if isinstance(current, Err):
        return current
    if current.value is None:
        return _error("configured reporting registry has no current local snapshot")
    services = _coherent_services(current.value)
    if isinstance(services, Err):
        return services
    return destination_from_services(
        effective.configuration.reporting.mode,
        source,
        services.value,
    )


def reporting_routes_from_current(
    effective: EffectiveConfiguration,
    data_root: str,
    read_current: CurrentSourcePort = read_current_source,
) -> tuple[RegistryReportingRoute, ...]:
    """Discover prompt-only routes from enabled registry snapshots without fetching.

    Missing, stale, or non-reporting registries are simply omitted: analytics availability never
    changes an artifact outcome.  Source aliases remain local routing keys and are never serialized.
    """

    return _reporting_route_resolution_from_current(effective, data_root, read_current)[0]


def _reporting_route_resolution_from_current(
    effective: EffectiveConfiguration,
    data_root: str,
    read_current: CurrentSourcePort = read_current_source,
) -> tuple[tuple[RegistryReportingRoute, ...], tuple[RegistryReportingNotice, ...]]:
    """Discover eligible routes and retain a visible local reason for each rejected registry."""

    settings = effective.configuration.reporting
    if settings.mode is not ReportingMode.PROMPT or settings.destination is not None:
        return (), ()
    routes = []
    notices = []
    for source in effective.configuration.sources:
        if not source.enabled or source.kind is not SourceKind.REGISTRY_GIT:
            continue
        location = git_location_parts(source.location)
        if location is None:
            notices.append(
                RegistryReportingNotice(source.alias, "its configured Git location is invalid")
            )
            continue
        if effective.policy.reporting.deny_public_destinations and location[0] in _PUBLIC_GIT_HOSTS:
            notices.append(
                RegistryReportingNotice(
                    source.alias,
                    "organization policy denies reporting to its public Git host",
                )
            )
            continue
        current = read_current(
            CurrentSourceRequest(
                source_store_paths(data_root, source_instance_id(source)),
                source.alias,
            )
        )
        if isinstance(current, Err):
            notices.append(
                RegistryReportingNotice(
                    source.alias, "its local registry snapshot could not be read"
                )
            )
            continue
        if current.value is None:
            notices.append(
                RegistryReportingNotice(source.alias, "it has no synchronized local snapshot")
            )
            continue
        services = _coherent_services(current.value)
        if isinstance(services, Err):
            notices.append(
                RegistryReportingNotice(
                    source.alias,
                    "its published manifest and index do not provide coherent services",
                )
            )
            continue
        if not any(service.name == "usage_reporting" for service in services.value):
            notices.append(
                RegistryReportingNotice(
                    source.alias,
                    "it does not advertise a usage_reporting service; maintainers can set one "
                    "with registry init --usage-reporting-repository OWNER/REPOSITORY",
                )
            )
            continue
        destination = destination_from_services(ReportingMode.PROMPT, source, services.value)
        if isinstance(destination, Err):
            notices.append(
                RegistryReportingNotice(
                    source.alias, "its usage_reporting advertisement is invalid"
                )
            )
            continue
        routes.append(RegistryReportingRoute(source.alias, destination.value))
    return (
        tuple(sorted(routes, key=lambda route: route.source_alias.value)),
        tuple(sorted(notices, key=lambda notice: notice.source_alias.value)),
    )


def load_local_reporting_service(
    *,
    user_home: str | None,
    configuration: UserConfiguration | None = None,
    browser: ReportingProvider | None = None,
    authenticated: ReportingProvider | None = None,
) -> Result[ReportingApplicationService]:
    """Load policy/config and the selected registry's already-published local advertisement."""

    platform = Platform.DARWIN if sys.platform == "darwin" else Platform.LINUX
    home = os.path.abspath(user_home or os.path.expanduser("~"))
    paths = resolve_config_paths(
        platform,
        home=home,
        xdg_config_home=os.environ.get("XDG_CONFIG_HOME"),
        xdg_data_home=os.environ.get("XDG_DATA_HOME"),
        xdg_cache_home=os.environ.get("XDG_CACHE_HOME"),
    )
    loaded = load_configuration(
        ConfigurationRequest(
            paths,
            RuntimeOverrides(),
            content_required=configuration is None,
        ),
        ConfigurationPorts(read_configuration, write_configuration, recover_configuration),
    )
    if isinstance(loaded, Err):
        return loaded
    effective = loaded.value.effective
    if configuration is not None:
        prospective = apply_configuration(
            configuration,
            RuntimeOverrides(),
            loaded.value.effective.policy,
        )
        if isinstance(prospective, Err):
            return prospective
        effective = prospective.value
    destination = reporting_destination_from_current(effective, paths.data_root)
    if isinstance(destination, Err):
        return destination
    routes, notices = _reporting_route_resolution_from_current(effective, paths.data_root)
    return Ok(
        ReportingApplicationService(
            destination.value,
            browser or browser_provider(),
            authenticated or GitHubIssueProvider(),
            routes,
            notices,
        )
    )


__all__ = [
    "REPORTING_RUNTIME_INVALID",
    "load_local_reporting_service",
    "reporting_destination_from_current",
    "reporting_routes_from_current",
]
