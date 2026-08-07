"""Source synchronization orchestration through explicit acquisition/store ports."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field, replace
from typing import Callable

from agent_artifacts.configuration.model import ConfiguredSource, SourceKind
from agent_artifacts.configuration.policy import redact_text
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.sources.model import (
    CurrentSource,
    CurrentSourceRequest,
    GitSnapshotRequest,
    LocalSnapshotRequest,
    SnapshotLimits,
    SourceCandidate,
    SourceHealth,
    SourceLockLease,
    SourceLockRequest,
    SourcePublishCommand,
    SourcePublishReceipt,
    SourceSyncOutcome,
    SourceValidationRequest,
    SyncDisposition,
    SyncFallback,
    ValidatedSourceCandidate,
    assess_source_health,
    source_instance_id,
    source_store_paths,
)

AcquireLockPort = Callable[[SourceLockRequest], Result[SourceLockLease]]
ReleaseLockPort = Callable[[SourceLockLease], Result[None]]
ReadCurrentPort = Callable[[CurrentSourceRequest], Result[CurrentSource | None]]
AcquireLocalPort = Callable[[LocalSnapshotRequest], Result[SourceCandidate]]
AcquireGitPort = Callable[[GitSnapshotRequest], Result[SourceCandidate]]
ValidateSourcePort = Callable[[SourceValidationRequest], Result[ValidatedSourceCandidate]]
PublishSourcePort = Callable[[SourcePublishCommand], Result[SourcePublishReceipt]]


@dataclass(frozen=True, slots=True)
class SourceSyncPorts:
    acquire_lock: AcquireLockPort
    release_lock: ReleaseLockPort
    read_current: ReadCurrentPort
    acquire_local: AcquireLocalPort
    acquire_git: AcquireGitPort
    validate: ValidateSourcePort
    publish: PublishSourcePort


@dataclass(frozen=True, slots=True)
class SourceSyncRequest:
    source: ConfiguredSource
    data_root: str
    executable_version: SemVer
    available_capabilities: tuple[Capability, ...]
    observed_at_epoch_seconds: int
    fallback: SyncFallback
    offline: bool
    timeout_seconds: int
    limits: SnapshotLimits = field(default_factory=SnapshotLimits)
    lock_timeout_seconds: float = 30.0
    lock_stale_after_seconds: int = 300

    def __post_init__(self) -> None:
        if (
            not posixpath.isabs(self.data_root)
            or posixpath.normpath(self.data_root) != self.data_root
            or not isinstance(self.observed_at_epoch_seconds, int)
            or isinstance(self.observed_at_epoch_seconds, bool)
            or self.observed_at_epoch_seconds < 0
            or not isinstance(self.fallback, SyncFallback)
            or not isinstance(self.offline, bool)
            or not isinstance(self.timeout_seconds, int)
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("source sync request is invalid")


@dataclass(frozen=True, slots=True)
class SourceStatusRequest:
    current: CurrentSourceRequest
    now_epoch_seconds: int
    max_age_seconds: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.now_epoch_seconds, int)
            or isinstance(self.now_epoch_seconds, bool)
            or self.now_epoch_seconds < 0
            or not isinstance(self.max_age_seconds, int)
            or isinstance(self.max_age_seconds, bool)
            or self.max_age_seconds < 0
        ):
            raise ValueError("source status clock and maximum age must be non-negative integers")


def _failure(code: str, message: str, *remediation: str) -> Err:
    return Err(
        (
            Diagnostic(
                DiagnosticCode(code),
                Severity.ERROR,
                redact_text(message),
                remediation=tuple(remediation),
            ),
        )
    )


def _retained(
    result: Err,
    current: CurrentSource | None,
    fallback: SyncFallback,
) -> Result[SourceSyncOutcome]:
    if fallback is not SyncFallback.ALLOW_LAST_KNOWN_GOOD or current is None:
        return result
    warnings = tuple(
        replace(
            diagnostic,
            severity=Severity.WARNING,
            message=redact_text(diagnostic.message),
        )
        for diagnostic in result.diagnostics
    )
    return Ok(SourceSyncOutcome(SyncDisposition.RETAINED, current, warnings))


def _candidate(
    request: SourceSyncRequest,
    paths,
    ports: SourceSyncPorts,
) -> Result[SourceCandidate]:
    instance_id = source_instance_id(request.source)
    if request.source.kind is SourceKind.SOURCE_LOCAL:
        return ports.acquire_local(
            LocalSnapshotRequest(
                instance_id,
                request.source.alias,
                request.source.location,
                request.limits,
            )
        )
    assert request.source.ref is not None
    return ports.acquire_git(
        GitSnapshotRequest(
            instance_id,
            request.source.alias,
            request.source.location,
            request.source.ref,
            paths.mirror,
            paths.temporary_root,
            request.limits,
            request.timeout_seconds,
        )
    )


def _sync_locked(
    request: SourceSyncRequest,
    ports: SourceSyncPorts,
) -> Result[SourceSyncOutcome]:
    instance_id = source_instance_id(request.source)
    paths = source_store_paths(request.data_root, instance_id)
    current_result = ports.read_current(CurrentSourceRequest(paths, request.source.alias))
    if isinstance(current_result, Err):
        return current_result
    current = current_result.value
    if request.offline:
        offline = _failure(
            "source-unavailable",
            "source synchronization is disabled in offline mode",
            "retry without offline mode",
        )
        return _retained(offline, current, request.fallback)
    acquired = _candidate(request, paths, ports)
    if isinstance(acquired, Err):
        return _retained(acquired, current, request.fallback)
    validated = ports.validate(
        SourceValidationRequest(
            acquired.value,
            request.executable_version,
            request.available_capabilities,
        )
    )
    if isinstance(validated, Err):
        return _retained(validated, current, request.fallback)
    if validated.value.candidate != acquired.value:
        invalid_receipt = _failure(
            "source-invalid",
            "source validator returned a candidate different from its request",
        )
        return _retained(invalid_receipt, current, request.fallback)
    if current is not None and current.declared_source_id != validated.value.declared_source_id:
        changed_identity = _failure(
            "source-invalid",
            "resolved source changed its declared source identity",
            "review the configured origin before replacing this source",
        )
        return _retained(changed_identity, current, request.fallback)
    published = ports.publish(
        SourcePublishCommand(paths, validated.value, request.observed_at_epoch_seconds)
    )
    if isinstance(published, Err):
        return _retained(published, current, request.fallback)
    expected = validated.value.candidate
    if (
        published.value.current.candidate.snapshot_digest != expected.snapshot_digest
        or published.value.current.candidate.resolved_revision != expected.resolved_revision
        or published.value.current.declared_source_id != validated.value.declared_source_id
    ):
        return _failure(
            "source-invalid",
            "source publication receipt does not match the validated candidate",
        )
    unchanged = current is not None and (
        current.candidate.snapshot_digest == expected.snapshot_digest
        and current.candidate.resolved_revision == expected.resolved_revision
        and current.declared_source_id == validated.value.declared_source_id
    )
    disposition = SyncDisposition.UNCHANGED if unchanged else SyncDisposition.PUBLISHED
    return Ok(SourceSyncOutcome(disposition, published.value.current))


def sync_source(
    request: SourceSyncRequest,
    ports: SourceSyncPorts,
) -> Result[SourceSyncOutcome]:
    """Serialize acquisition and publish only a validated complete snapshot."""

    if not request.source.enabled:
        return _failure("source-invalid", "disabled source cannot be synchronized")
    paths = source_store_paths(request.data_root, source_instance_id(request.source))
    lease = ports.acquire_lock(
        SourceLockRequest(
            paths.lock_directory,
            request.lock_timeout_seconds,
            request.lock_stale_after_seconds,
        )
    )
    if isinstance(lease, Err):
        return lease
    outcome = _sync_locked(request, ports)
    released = ports.release_lock(lease.value)
    if isinstance(released, Err):
        if isinstance(outcome, Err):
            return Err((*outcome.diagnostics, *released.diagnostics))
        return released
    return outcome


def source_status(
    request: SourceStatusRequest,
    read_current: ReadCurrentPort,
) -> SourceHealth:
    """Project current durable state into a non-mutating doctor/status result."""

    loaded = read_current(request.current)
    if isinstance(loaded, Err):
        return assess_source_health(
            None,
            now=request.now_epoch_seconds,
            max_age_seconds=request.max_age_seconds,
            diagnostics=loaded.diagnostics,
        )
    return assess_source_health(
        loaded.value,
        now=request.now_epoch_seconds,
        max_age_seconds=request.max_age_seconds,
    )
