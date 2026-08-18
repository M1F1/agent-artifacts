"""Source synchronization orchestration through explicit acquisition/store ports."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field, replace
from typing import Callable, Protocol

from agent_artifacts.configuration.model import ConfiguredSource, SourceKind
from agent_artifacts.configuration.policy import redact_text
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.sources.model import (
    CurrentSource,
    CurrentSourceRequest,
    GitSnapshotRequest,
    HealthStatus,
    LocalSnapshotRequest,
    SnapshotLimits,
    SourceCandidate,
    SourceHealth,
    SourceIdentityTransition,
    SourceLockLease,
    SourceLockRequest,
    SourcePublishCommand,
    SourcePublishReceipt,
    SourceStorePaths,
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
DiscardSourcePort = Callable[[SourceStorePaths], Result[bool]]
PruneSourceRootPort = Callable[[SourceStorePaths], None]
PruneSupersededSnapshotsPort = Callable[[SourceStorePaths, ObjectDigest], None]


class _AcquisitionInputs(Protocol):
    """What acquiring a candidate needs, shared by synchronization and adoption."""

    @property
    def source(self) -> ConfiguredSource: ...

    @property
    def limits(self) -> SnapshotLimits: ...

    @property
    def timeout_seconds(self) -> int: ...


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
class SourceDiscardPorts:
    acquire_lock: AcquireLockPort
    release_lock: ReleaseLockPort
    read_current: ReadCurrentPort
    discard: DiscardSourcePort
    prune_root: PruneSourceRootPort


@dataclass(frozen=True, slots=True)
class SourceDiscardRequest:
    """One managed source instance to remove; carries no configuration decision of its own."""

    source: ConfiguredSource
    data_root: str
    lock_timeout_seconds: float = 30.0
    lock_stale_after_seconds: int = 300

    def __post_init__(self) -> None:
        if not posixpath.isabs(self.data_root) or posixpath.normpath(self.data_root) != (
            self.data_root
        ):
            raise ValueError("source discard request is invalid")


@dataclass(frozen=True, slots=True)
class SourceDiscardOutcome:
    """What the discard actually removed, for the command receipt."""

    existed: bool
    discarded: CurrentSource | None


@dataclass(frozen=True, slots=True)
class SourceAdoptionPorts:
    """Adoption acquires and publishes exactly as synchronization does, and then tidies up."""

    sync: SourceSyncPorts
    prune_snapshots: PruneSupersededSnapshotsPort


@dataclass(frozen=True, slots=True)
class SourceAdoptionRequest:
    """Adopt the identity an unchanged origin now declares, under an unchanged alias.

    ``expected`` is the whole review contract.  Left unset, this plans and publishes nothing, so
    the caller can render the transition; set, it is the only transition that may be applied, and
    an upstream that moved again between review and finalize is refused rather than absorbed.
    """

    source: ConfiguredSource
    data_root: str
    executable_version: SemVer
    available_capabilities: tuple[Capability, ...]
    observed_at_epoch_seconds: int
    expected: SourceIdentityTransition | None = None
    timeout_seconds: int = 60
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
            or not isinstance(self.timeout_seconds, int)
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("source adoption request is invalid")


@dataclass(frozen=True, slots=True)
class SourceAdoptionOutcome:
    """The reviewed or applied transition, and the snapshot the alias is bound to afterwards."""

    transition: SourceIdentityTransition
    finalized: bool
    current: CurrentSource


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


@dataclass(frozen=True, slots=True)
class SourceFreshnessRequest:
    """One read-only comparison between a published snapshot and its configured origin."""

    source: ConfiguredSource
    data_root: str
    executable_version: SemVer
    available_capabilities: tuple[Capability, ...]
    observed_at_epoch_seconds: int
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
            or not isinstance(self.timeout_seconds, int)
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("source freshness request is invalid")


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
    request: _AcquisitionInputs,
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
            f"review both identities with `aart source resubscribe --alias "
            f"{request.source.alias.value}`, then re-run it with --yes to adopt the change",
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


def discard_source(
    request: SourceDiscardRequest,
    ports: SourceDiscardPorts,
) -> Result[SourceDiscardOutcome]:
    """Serialize discard against synchronization and report what was actually removed.

    Ending a subscription owns the managed store as well as the configuration.  Leaving the store
    behind would keep the origin bound to its old declared identity, so a later subscription to the
    same origin would be refused by the identity check with nothing left to name in remediation.
    """

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
    current = ports.read_current(CurrentSourceRequest(paths, request.source.alias))
    discarded = ports.discard(paths)
    released = ports.release_lock(lease.value)
    if isinstance(discarded, Err):
        if isinstance(released, Err):
            return Err((*discarded.diagnostics, *released.diagnostics))
        return discarded
    if isinstance(released, Err):
        return released
    ports.prune_root(paths)
    return Ok(
        SourceDiscardOutcome(
            discarded.value,
            None if isinstance(current, Err) else current.value,
        )
    )


def _adopt_locked(
    request: SourceAdoptionRequest,
    ports: SourceAdoptionPorts,
) -> Result[SourceAdoptionOutcome]:
    alias = request.source.alias.value
    paths = source_store_paths(request.data_root, source_instance_id(request.source))
    current_result = ports.sync.read_current(CurrentSourceRequest(paths, request.source.alias))
    if isinstance(current_result, Err):
        return current_result
    current = current_result.value
    if current is None:
        return _failure(
            "source-invalid",
            "no managed snapshot is subscribed at this origin",
            f"run `aart source sync --alias {alias}` to publish one first",
        )
    acquired = _candidate(request, paths, ports.sync)
    if isinstance(acquired, Err):
        return acquired
    validated = ports.sync.validate(
        SourceValidationRequest(
            acquired.value,
            request.executable_version,
            request.available_capabilities,
        )
    )
    if isinstance(validated, Err):
        return validated
    if validated.value.candidate != acquired.value:
        return _failure(
            "source-invalid",
            "source validator returned a candidate different from its request",
        )
    if current.declared_source_id == validated.value.declared_source_id:
        # Adoption is never a quiet alias for refresh.  One operation, one meaning: if there is no
        # identity to adopt, the operator wanted the operation that republishes a snapshot.
        return _failure(
            "source-invalid",
            "source still declares the identity this alias is already subscribed to",
            f"run `aart source sync --alias {alias}` to refresh the snapshot instead",
        )
    try:
        observed = SourceIdentityTransition(
            current.declared_source_id,
            validated.value.declared_source_id,
            current.candidate.resolved_revision,
            validated.value.candidate.resolved_revision,
            current.candidate.snapshot_digest,
            validated.value.candidate.snapshot_digest,
        )
    except ValueError as error:
        return _failure("source-invalid", str(error))
    if request.expected is None:
        return Ok(SourceAdoptionOutcome(observed, False, current))
    if request.expected != observed:
        return _failure(
            "source-invalid",
            "source no longer declares the identity that was reviewed",
            f"run `aart source resubscribe --alias {alias}` again to review the current transition",
        )
    published = ports.sync.publish(
        SourcePublishCommand(paths, validated.value, request.observed_at_epoch_seconds)
    )
    if isinstance(published, Err):
        return published
    expected_candidate = validated.value.candidate
    if (
        published.value.current.candidate.snapshot_digest != expected_candidate.snapshot_digest
        or published.value.current.candidate.resolved_revision
        != expected_candidate.resolved_revision
        or published.value.current.declared_source_id != validated.value.declared_source_id
    ):
        return _failure(
            "source-invalid",
            "source publication receipt does not match the validated candidate",
        )
    # The pointer swap above is the rebinding; this drops the tree the old identity left behind, so
    # the store holds one snapshot per subscription rather than one per identity ever adopted.
    ports.prune_snapshots(paths, expected_candidate.snapshot_digest)
    return Ok(SourceAdoptionOutcome(observed, True, published.value.current))


def adopt_source_identity(
    request: SourceAdoptionRequest,
    ports: SourceAdoptionPorts,
) -> Result[SourceAdoptionOutcome]:
    """Review or apply one identity change at an origin and ref that did not move.

    Serialized against synchronization by the same lease, because the two operations disagree
    about exactly one thing — whether a changed declared identity is a refusal or the point — and
    interleaving them would let a plain `sync` republish between review and finalize.
    """

    if not request.source.enabled:
        return _failure("source-invalid", "disabled source cannot be resubscribed")
    paths = source_store_paths(request.data_root, source_instance_id(request.source))
    lease = ports.sync.acquire_lock(
        SourceLockRequest(
            paths.lock_directory,
            request.lock_timeout_seconds,
            request.lock_stale_after_seconds,
        )
    )
    if isinstance(lease, Err):
        return lease
    outcome = _adopt_locked(request, ports)
    released = ports.sync.release_lock(lease.value)
    if isinstance(released, Err):
        if isinstance(outcome, Err):
            return Err((*outcome.diagnostics, *released.diagnostics))
        return released
    return outcome


def _freshness_age(current: CurrentSource, observed_at_epoch_seconds: int) -> int:
    return max(0, observed_at_epoch_seconds - current.published_at_epoch_seconds)


def _check_freshness_locked(
    request: SourceFreshnessRequest,
    ports: SourceSyncPorts,
) -> SourceHealth:
    """Compare exact validated origin evidence without publishing it."""

    paths = source_store_paths(request.data_root, source_instance_id(request.source))
    loaded = ports.read_current(CurrentSourceRequest(paths, request.source.alias))
    if isinstance(loaded, Err):
        return SourceHealth(HealthStatus.DEGRADED, None, None, loaded.diagnostics)
    current = loaded.value
    if current is None:
        return SourceHealth(HealthStatus.MISSING, None, None)
    age = _freshness_age(current, request.observed_at_epoch_seconds)
    acquired = _candidate(request, paths, ports)
    if isinstance(acquired, Err):
        return SourceHealth(
            HealthStatus.CHECK_UNAVAILABLE,
            age,
            current,
            acquired.diagnostics,
        )
    validated = ports.validate(
        SourceValidationRequest(
            acquired.value,
            request.executable_version,
            request.available_capabilities,
        )
    )
    if isinstance(validated, Err):
        return SourceHealth(HealthStatus.DEGRADED, age, current, validated.diagnostics)
    if validated.value.candidate != acquired.value:
        return SourceHealth(
            HealthStatus.DEGRADED,
            age,
            current,
            _failure(
                "source-invalid",
                "source validator returned a candidate different from its request",
            ).diagnostics,
        )
    observed = validated.value
    synchronized = (
        current.declared_source_id == observed.declared_source_id
        and current.candidate.resolved_revision == observed.candidate.resolved_revision
        and current.candidate.snapshot_digest == observed.candidate.snapshot_digest
    )
    return SourceHealth(
        HealthStatus.HEALTHY if synchronized else HealthStatus.NOT_SYNCHRONIZED,
        age,
        current,
    )


def check_source_freshness(
    request: SourceFreshnessRequest,
    ports: SourceSyncPorts,
) -> SourceHealth:
    """Inspect origin freshness under the source lease, without moving the current pointer."""

    if not request.source.enabled:
        paths = source_store_paths(request.data_root, source_instance_id(request.source))
        return source_status(
            SourceStatusRequest(
                CurrentSourceRequest(paths, request.source.alias),
                request.observed_at_epoch_seconds,
                0,
            ),
            ports.read_current,
        )
    paths = source_store_paths(request.data_root, source_instance_id(request.source))
    lease = ports.acquire_lock(
        SourceLockRequest(
            paths.lock_directory,
            request.lock_timeout_seconds,
            request.lock_stale_after_seconds,
        )
    )
    if isinstance(lease, Err):
        loaded = ports.read_current(CurrentSourceRequest(paths, request.source.alias))
        current = None if isinstance(loaded, Err) else loaded.value
        age = (
            None if current is None else _freshness_age(current, request.observed_at_epoch_seconds)
        )
        diagnostics = (
            lease.diagnostics
            if isinstance(loaded, Ok)
            else (*loaded.diagnostics, *lease.diagnostics)
        )
        return SourceHealth(HealthStatus.CHECK_UNAVAILABLE, age, current, diagnostics)
    health = _check_freshness_locked(request, ports)
    released = ports.release_lock(lease.value)
    if isinstance(released, Err):
        return SourceHealth(
            HealthStatus.CHECK_UNAVAILABLE,
            health.age_seconds,
            health.current,
            (*health.diagnostics, *released.diagnostics),
        )
    return health


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
