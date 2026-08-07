"""Object-reference replacement and dry-run-first garbage collection orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypeVar

from agent_artifacts.domain.diagnostics import Diagnostic
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.store.model import (
    GcOutcome,
    GcPlan,
    GcRequest,
    ObjectDeleteCommand,
    ObjectInventory,
    ObjectReadRequest,
    ObjectReference,
    ObjectStatus,
    ObjectStatusKind,
    ObjectStorePaths,
    ReferenceIndex,
    ReferenceKind,
    ReferenceReadRequest,
    ReferenceWriteCommand,
    StoredObject,
    StoreLockLease,
    StoreLockRequest,
)

AcquireStoreLockPort = Callable[[StoreLockRequest], Result[StoreLockLease]]
ReleaseStoreLockPort = Callable[[StoreLockLease], Result[None]]
ReadReferencesPort = Callable[[ReferenceReadRequest], Result[ReferenceIndex]]
WriteReferencesPort = Callable[[ReferenceWriteCommand], Result[ReferenceIndex]]
InventoryObjectsPort = Callable[[ObjectStorePaths], Result[ObjectInventory]]
DeleteObjectPort = Callable[[ObjectDeleteCommand], Result[None]]
ReadObjectPort = Callable[[ObjectReadRequest], Result[StoredObject | None]]
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ReferenceUpdatePorts:
    acquire_lock: AcquireStoreLockPort
    release_lock: ReleaseStoreLockPort
    read_references: ReadReferencesPort
    write_references: WriteReferencesPort


@dataclass(frozen=True, slots=True)
class ReferenceUpdateRequest:
    paths: ObjectStorePaths
    kind: ReferenceKind
    owner: str
    digests: tuple[ObjectDigest, ...]

    def __post_init__(self) -> None:
        probes = tuple(ObjectReference(self.kind, self.owner, digest) for digest in self.digests)
        if len(set(probes)) != len(probes):
            raise ValueError("reference update digests must be unique")
        object.__setattr__(self, "digests", tuple(sorted(self.digests, key=str)))


@dataclass(frozen=True, slots=True)
class StoreGcPorts:
    acquire_lock: AcquireStoreLockPort
    release_lock: ReleaseStoreLockPort
    read_references: ReadReferencesPort
    inventory_objects: InventoryObjectsPort
    delete_object: DeleteObjectPort


def _release_result(
    outcome: Result[T],
    lease: StoreLockLease,
    release: ReleaseStoreLockPort,
) -> Result[T]:
    released = release(lease)
    if isinstance(released, Err):
        if isinstance(outcome, Err):
            return Err((*outcome.diagnostics, *released.diagnostics))
        return released
    return outcome


def replace_references(
    request: ReferenceUpdateRequest,
    ports: ReferenceUpdatePorts,
) -> Result[ReferenceIndex]:
    """Atomically replace one owner/kind reference set under the store/GC lease."""

    lease = ports.acquire_lock(StoreLockRequest(request.paths.lock_directory))
    if isinstance(lease, Err):
        return lease
    current = ports.read_references(ReferenceReadRequest(request.paths))
    if isinstance(current, Err):
        return _release_result(current, lease.value, ports.release_lock)
    retained = tuple(
        reference
        for reference in current.value.references
        if reference.kind is not request.kind or reference.owner != request.owner
    )
    replacements = tuple(
        ObjectReference(request.kind, request.owner, digest) for digest in request.digests
    )
    updated = ReferenceIndex(1, (*retained, *replacements))
    written = ports.write_references(ReferenceWriteCommand(request.paths, updated))
    return _release_result(written, lease.value, ports.release_lock)


def collect_garbage(
    request: GcRequest,
    ports: StoreGcPorts,
) -> Result[GcOutcome]:
    """Plan under a global lease and delete only the same unreferenced digest set."""

    lease = ports.acquire_lock(StoreLockRequest(request.paths.lock_directory))
    if isinstance(lease, Err):
        return lease
    references = ports.read_references(ReferenceReadRequest(request.paths))
    if isinstance(references, Err):
        return _release_result(references, lease.value, ports.release_lock)
    inventory = ports.inventory_objects(request.paths)
    if isinstance(inventory, Err):
        return _release_result(inventory, lease.value, ports.release_lock)
    referenced = tuple(
        sorted({reference.digest for reference in references.value.references}, key=str)
    )
    referenced_set = frozenset(referenced)
    candidates = tuple(digest for digest in inventory.value.digests if digest not in referenced_set)
    plan = GcPlan(referenced, candidates, inventory.value.diagnostics)
    if not request.execute:
        return _release_result(Ok(GcOutcome(plan, False)), lease.value, ports.release_lock)
    deleted: list[ObjectDigest] = []
    diagnostics: list[Diagnostic] = []
    for digest in candidates:
        result = ports.delete_object(ObjectDeleteCommand(request.paths, digest))
        if isinstance(result, Err):
            diagnostics.extend(result.diagnostics)
        else:
            deleted.append(digest)
    outcome: Result[GcOutcome] = (
        Err(tuple(diagnostics)) if diagnostics else Ok(GcOutcome(plan, True, tuple(deleted)))
    )
    return _release_result(outcome, lease.value, ports.release_lock)


def object_status(request: ObjectReadRequest, read_object: ReadObjectPort) -> ObjectStatus:
    """Project verified, absent, or corrupt durable object state without mutation."""

    loaded = read_object(request)
    if isinstance(loaded, Err):
        return ObjectStatus(
            ObjectStatusKind.DEGRADED,
            request.digest,
            diagnostics=loaded.diagnostics,
        )
    if loaded.value is None:
        return ObjectStatus(ObjectStatusKind.MISSING, request.digest)
    return ObjectStatus(ObjectStatusKind.VERIFIED, request.digest, loaded.value)
