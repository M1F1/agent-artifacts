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
from agent_artifacts.configuration.model import UserConfiguration
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

from .application import ReportingApplicationService, ReportingProvider
from .destination import configured_reporting_source, destination_from_services
from .io import GitHubIssueProvider, browser_provider
from .model import ReportingDestination

REPORTING_RUNTIME_INVALID = DiagnosticCode("reporting-runtime-invalid")
CurrentSourcePort = Callable[[CurrentSourceRequest], Result[CurrentSource | None]]


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
    return Ok(
        ReportingApplicationService(
            destination.value,
            browser or browser_provider(),
            authenticated or GitHubIssueProvider(),
        )
    )


__all__ = [
    "REPORTING_RUNTIME_INVALID",
    "load_local_reporting_service",
    "reporting_destination_from_current",
]
