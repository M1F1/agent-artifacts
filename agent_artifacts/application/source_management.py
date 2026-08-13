"""Finalize a reviewed TUI source-management request through one injected write port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, Sized

from agent_artifacts.configuration.model import OrganizationPolicy, UserConfiguration
from agent_artifacts.configuration.policy import (
    RuntimeOverrides,
    apply_configuration,
    apply_configuration_for_source_management,
)
from agent_artifacts.domain.result import Err, Ok, Result


class ReviewedSourceManagement(Protocol):
    """Application-facing value contract; the interface owns the concrete request type."""

    @property
    def after(self) -> UserConfiguration: ...

    @property
    def policy(self) -> OrganizationPolicy: ...

    @property
    def operations(self) -> Sized: ...


class ReviewedSourceAddition(Protocol):
    """Application-facing contract for one separately reviewed source-origin addition."""

    @property
    def after(self) -> UserConfiguration: ...

    @property
    def policy(self) -> OrganizationPolicy: ...


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


def finalize_source_removal(
    request: ReviewedSourceAddition,
    save: SaveSourceConfigurationPort,
) -> Result[SourceManagementReceipt]:
    """Persist one reviewed unsubscribe after its managed snapshot has already been discarded.

    Store discard belongs to the runtime boundary before this function is called, and in that
    order deliberately: a failure here leaves a configured source whose snapshot is gone, which
    ``source sync`` repairs, rather than an unsubscribed origin whose store still binds the old
    declared identity — the state that has no command to name.
    """

    checked = apply_configuration_for_source_management(request.after, request.policy)
    if isinstance(checked, Err):
        return checked
    saved = save(request.after, request.policy)
    if isinstance(saved, Err):
        return saved
    return Ok(SourceManagementReceipt(True, 1))


def finalize_source_addition(
    request: ReviewedSourceAddition,
    save: SaveSourceConfigurationPort,
) -> Result[SourceManagementReceipt]:
    """Persist a source already synchronized and explicitly approved by first-use onboarding.

    Synchronization belongs to the runtime boundary before this function is called.  This function
    only rechecks policy and crosses the single durable user-configuration write boundary.
    """

    checked = apply_configuration_for_source_management(request.after, request.policy)
    if isinstance(checked, Err):
        return checked
    saved = save(request.after, request.policy)
    if isinstance(saved, Err):
        return saved
    return Ok(SourceManagementReceipt(True, 1))
