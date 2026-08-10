"""Finalize a reviewed TUI source-management request through one injected write port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, Sized

from agent_artifacts.configuration.model import OrganizationPolicy, UserConfiguration
from agent_artifacts.configuration.policy import RuntimeOverrides, apply_configuration
from agent_artifacts.domain.result import Err, Ok, Result


class ReviewedSourceManagement(Protocol):
    """Application-facing value contract; the interface owns the concrete request type."""

    @property
    def after(self) -> UserConfiguration: ...

    @property
    def policy(self) -> OrganizationPolicy: ...

    @property
    def operations(self) -> Sized: ...


@dataclass(frozen=True, slots=True)
class SourceManagementReceipt:
    changed: bool
    operation_count: int


SaveSourceConfigurationPort = Callable[[UserConfiguration, OrganizationPolicy], Result[object]]


def finalize_source_management(
    request: ReviewedSourceManagement,
    save: SaveSourceConfigurationPort,
) -> Result[SourceManagementReceipt]:
    """Revalidate exact reviewed values, then cross the configuration mutation boundary once."""

    checked = apply_configuration(request.after, RuntimeOverrides(), request.policy)
    if isinstance(checked, Err):
        return checked
    if not request.operations:
        return Ok(SourceManagementReceipt(False, 0))
    saved = save(request.after, request.policy)
    if isinstance(saved, Err):
        return saved
    return Ok(SourceManagementReceipt(True, len(request.operations)))
