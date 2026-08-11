"""Shared imperative composition for commands over configured AART sources.

This module deliberately owns only process-environment path resolution and configuration IO.
Individual commands retain their own domain operation and output contracts.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from agent_artifacts.application.configuration import (
    ConfigurationPorts,
    ConfigurationRequest,
    LoadedConfiguration,
    load_configuration,
)
from agent_artifacts.configuration.paths import ConfigPaths, Platform, resolve_config_paths
from agent_artifacts.configuration.policy import RuntimeOverrides, redact_text
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.io.config_cas import checked_config_writer
from agent_artifacts.io.config_store import (
    read_configuration,
    recover_configuration,
    write_configuration,
)
from agent_artifacts.model import Request


@dataclass(frozen=True, slots=True)
class ConfiguredRuntime:
    """Resolved private paths, IO ports, and one configuration read for a command."""

    paths: ConfigPaths
    ports: ConfigurationPorts
    loaded: LoadedConfiguration


def load_runtime_configuration(
    request: Request,
    *,
    content_required: bool,
) -> Result[ConfiguredRuntime]:
    """Load the user configuration without making an implicit source or config mutation."""

    platform = Platform.DARWIN if sys.platform == "darwin" else Platform.LINUX
    home = os.path.abspath(request.user_home or os.path.expanduser("~"))
    try:
        paths = resolve_config_paths(
            platform,
            home=home,
            xdg_config_home=os.environ.get("XDG_CONFIG_HOME"),
            xdg_data_home=os.environ.get("XDG_DATA_HOME"),
            xdg_cache_home=os.environ.get("XDG_CACHE_HOME"),
        )
    except ValueError as error:
        return Err(
            (
                Diagnostic(
                    DiagnosticCode("config-invalid"),
                    Severity.ERROR,
                    redact_text(f"configuration path environment is invalid: {error}"),
                    remediation=("set XDG configuration paths to normalized absolute paths",),
                ),
            )
        )
    ports = ConfigurationPorts(
        read_configuration,
        write_configuration,
        recover_configuration,
        checked_config_writer,
    )
    loaded = load_configuration(
        ConfigurationRequest(paths, RuntimeOverrides(), content_required=content_required),
        ports,
    )
    if isinstance(loaded, Err):
        return loaded
    return Ok(ConfiguredRuntime(paths, ports, loaded.value))


__all__ = ["ConfiguredRuntime", "load_runtime_configuration"]
