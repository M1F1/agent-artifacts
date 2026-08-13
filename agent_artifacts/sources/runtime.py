"""Imperative local runtime composition for one configured source refresh."""

from __future__ import annotations

import time

from agent_artifacts.application.sources import (
    SourceAdoptionOutcome,
    SourceAdoptionPorts,
    SourceAdoptionRequest,
    SourceDiscardOutcome,
    SourceDiscardPorts,
    SourceDiscardRequest,
    SourceSyncPorts,
    SourceSyncRequest,
    adopt_source_identity,
    discard_source,
    sync_source,
)
from agent_artifacts.configuration.model import ConfiguredSource
from agent_artifacts.domain.result import Result
from agent_artifacts.io.source_store import (
    acquire_source_lock,
    discard_source_store,
    prune_source_store_root,
    prune_superseded_snapshots,
    publish_source_snapshot,
    read_current_source,
    release_source_lock,
)
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.runtime_contract import EXECUTABLE_CAPABILITIES, EXECUTABLE_VERSION

from .git import acquire_git_snapshot
from .local import read_local_snapshot
from .model import (
    SnapshotLimits,
    SourceIdentityTransition,
    SourceSyncOutcome,
    SourceValidationRequest,
    SyncFallback,
    ValidatedSourceCandidate,
)
from .validation import validate_configured_source_candidate

DEFAULT_SOURCE_SYNC_TIMEOUT_SECONDS = 60


def source_sync_ports(source: ConfiguredSource) -> SourceSyncPorts:
    """Compose the concrete source-store and acquisition adapters for one source value."""

    def validate(request: SourceValidationRequest) -> Result[ValidatedSourceCandidate]:
        return validate_configured_source_candidate(source, request)

    return SourceSyncPorts(
        acquire_source_lock,
        release_source_lock,
        read_current_source,
        read_local_snapshot,
        acquire_git_snapshot,
        validate,
        publish_source_snapshot,
    )


def discard_configured_source(
    source: ConfiguredSource,
    *,
    data_root: str,
    lock_timeout_seconds: float = 30.0,
    lock_stale_after_seconds: int = 300,
) -> Result[SourceDiscardOutcome]:
    """Remove one managed source instance from the local store; touches no configuration."""

    return discard_source(
        SourceDiscardRequest(source, data_root, lock_timeout_seconds, lock_stale_after_seconds),
        SourceDiscardPorts(
            acquire_source_lock,
            release_source_lock,
            read_current_source,
            discard_source_store,
            prune_source_store_root,
        ),
    )


def resubscribe_configured_source(
    source: ConfiguredSource,
    *,
    data_root: str,
    expected: SourceIdentityTransition | None = None,
    observed_at_epoch_seconds: int | None = None,
    timeout_seconds: int = DEFAULT_SOURCE_SYNC_TIMEOUT_SECONDS,
    limits: SnapshotLimits | None = None,
    lock_timeout_seconds: float = 30.0,
    lock_stale_after_seconds: int = 300,
    executable_version: SemVer = EXECUTABLE_VERSION,
    available_capabilities: tuple[Capability, ...] = EXECUTABLE_CAPABILITIES,
) -> Result[SourceAdoptionOutcome]:
    """Review one identity change, or apply the exact one already reviewed.

    Without ``expected`` this publishes nothing: it reports the transition so a caller can render
    it.  With ``expected`` it applies that transition and no other.  Configuration is never touched
    either way — resubscribing keeps alias, kind, location, ref, and the default flag by not having
    an opinion about any of them.
    """

    observed = int(time.time()) if observed_at_epoch_seconds is None else observed_at_epoch_seconds
    return adopt_source_identity(
        SourceAdoptionRequest(
            source,
            data_root,
            executable_version,
            available_capabilities,
            observed,
            expected,
            timeout_seconds,
            SnapshotLimits() if limits is None else limits,
            lock_timeout_seconds,
            lock_stale_after_seconds,
        ),
        SourceAdoptionPorts(source_sync_ports(source), prune_superseded_snapshots),
    )


def sync_configured_source(
    source: ConfiguredSource,
    *,
    data_root: str,
    observed_at_epoch_seconds: int | None = None,
    offline: bool = False,
    timeout_seconds: int = DEFAULT_SOURCE_SYNC_TIMEOUT_SECONDS,
    limits: SnapshotLimits | None = None,
    lock_timeout_seconds: float = 30.0,
    lock_stale_after_seconds: int = 300,
    executable_version: SemVer = EXECUTABLE_VERSION,
    available_capabilities: tuple[Capability, ...] = EXECUTABLE_CAPABILITIES,
) -> Result[SourceSyncOutcome]:
    """Synchronize one source with a fresh-snapshot requirement and no config mutation.

    The caller owns policy/configuration review and persistence.  This boundary only acquires,
    validates, and atomically publishes a source snapshot under ``data_root``.
    """

    observed = int(time.time()) if observed_at_epoch_seconds is None else observed_at_epoch_seconds
    return sync_source(
        SourceSyncRequest(
            source,
            data_root,
            executable_version,
            available_capabilities,
            observed,
            SyncFallback.REQUIRE_FRESH,
            offline,
            timeout_seconds,
            SnapshotLimits() if limits is None else limits,
            lock_timeout_seconds,
            lock_stale_after_seconds,
        ),
        source_sync_ports(source),
    )


__all__ = [
    "DEFAULT_SOURCE_SYNC_TIMEOUT_SECONDS",
    "discard_configured_source",
    "resubscribe_configured_source",
    "source_sync_ports",
    "sync_configured_source",
]
