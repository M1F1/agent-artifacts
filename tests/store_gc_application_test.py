from __future__ import annotations

import unittest

from agent_artifacts.application.store import (
    ReferenceUpdatePorts,
    ReferenceUpdateRequest,
    StoreGcPorts,
    collect_garbage,
    replace_references,
)
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.store.model import (
    GcRequest,
    ObjectInventory,
    ObjectReference,
    ReferenceIndex,
    ReferenceKind,
    StoreLockLease,
    object_store_paths,
)


class _GcPorts:
    def __init__(self, inventory: ObjectInventory, references: ReferenceIndex):
        self.inventory = inventory
        self.references = references
        self.deleted: list[ObjectDigest] = []
        self.events: list[str] = []

    def acquire(self, request):
        self.events.append("lock")
        return Ok(StoreLockLease(request.lock_directory, "token"))

    def release(self, _lease):
        self.events.append("release")
        return Ok(None)

    def read(self, _request):
        self.events.append("references")
        return Ok(self.references)

    def inventory_objects(self, _paths):
        self.events.append("inventory")
        return Ok(self.inventory)

    def delete(self, command):
        self.events.append("delete")
        self.deleted.append(command.digest)
        return Ok(None)

    def ports(self):
        return StoreGcPorts(
            self.acquire,
            self.release,
            self.read,
            self.inventory_objects,
            self.delete,
        )


class StoreGcApplicationTest(unittest.TestCase):
    def test_dry_run_is_default_and_every_reference_kind_is_retained(self) -> None:
        paths = object_store_paths("/managed")
        digests = tuple(ObjectDigest("sha256", character * 64) for character in "abcdef")
        references = ReferenceIndex(
            1,
            tuple(
                ObjectReference(kind, f"owner/{index}", digest)
                for index, (kind, digest) in enumerate(zip(ReferenceKind, digests, strict=True))
            ),
        )
        unreferenced = ObjectDigest("sha256", "0" * 64)
        fake = _GcPorts(ObjectInventory((*digests, unreferenced)), references)

        result = collect_garbage(GcRequest(paths), fake.ports())

        self.assertIsInstance(result, Ok)
        assert isinstance(result, Ok)
        self.assertFalse(result.value.executed)
        self.assertEqual(result.value.plan.candidates, (unreferenced,))
        self.assertEqual(fake.deleted, [])
        self.assertEqual(fake.events, ["lock", "references", "inventory", "release"])

    def test_execute_deletes_only_unreferenced_and_reports_partial_failure(self) -> None:
        paths = object_store_paths("/managed")
        retained = ObjectDigest("sha256", "a" * 64)
        first = ObjectDigest("sha256", "b" * 64)
        second = ObjectDigest("sha256", "c" * 64)
        references = ReferenceIndex(
            1, (ObjectReference(ReferenceKind.ROLLBACK, "rollback/one", retained),)
        )
        fake = _GcPorts(ObjectInventory((retained, first, second)), references)
        original_delete = fake.delete

        def delete(command):
            if command.digest == second:
                return Err(
                    (
                        Diagnostic(
                            DiagnosticCode("store-delete-failed"),
                            Severity.ERROR,
                            "delete failed",
                        ),
                    )
                )
            return original_delete(command)

        fake.delete = delete
        result = collect_garbage(GcRequest(paths, execute=True), fake.ports())

        self.assertIsInstance(result, Err)
        self.assertEqual(fake.deleted, [first])
        self.assertEqual(fake.events[-1], "release")

    def test_execute_success_reports_exact_deleted_partition(self) -> None:
        paths = object_store_paths("/managed")
        retained = ObjectDigest("sha256", "a" * 64)
        deleted = ObjectDigest("sha256", "b" * 64)
        references = ReferenceIndex(
            1, (ObjectReference(ReferenceKind.TRANSACTION, "tx/one", retained),)
        )
        fake = _GcPorts(ObjectInventory((retained, deleted)), references)

        result = collect_garbage(GcRequest(paths, execute=True), fake.ports())

        self.assertIsInstance(result, Ok)
        assert isinstance(result, Ok)
        self.assertTrue(result.value.executed)
        self.assertEqual(result.value.deleted, (deleted,))
        self.assertEqual(fake.deleted, [deleted])

    def test_lock_reference_inventory_and_release_failures_always_stop_safely(self) -> None:
        paths = object_store_paths("/managed")
        empty = ReferenceIndex(1, ())
        failure = Err(
            (Diagnostic(DiagnosticCode("store-unavailable"), Severity.ERROR, "port failed"),)
        )

        lock = _GcPorts(ObjectInventory(()), empty)
        lock.acquire = lambda _request: failure
        self.assertIsInstance(collect_garbage(GcRequest(paths), lock.ports()), Err)
        self.assertEqual(lock.events, [])

        references = _GcPorts(ObjectInventory(()), empty)

        def fail_references(_request):
            references.events.append("references")
            return failure

        references.read = fail_references
        self.assertIsInstance(collect_garbage(GcRequest(paths), references.ports()), Err)
        self.assertEqual(references.events[-1], "release")

        inventory = _GcPorts(ObjectInventory(()), empty)

        def fail_inventory(_paths):
            inventory.events.append("inventory")
            return failure

        inventory.inventory_objects = fail_inventory
        self.assertIsInstance(collect_garbage(GcRequest(paths), inventory.ports()), Err)
        self.assertEqual(inventory.events[-1], "release")

        release = _GcPorts(ObjectInventory(()), empty)
        release.release = lambda _lease: failure
        self.assertIsInstance(collect_garbage(GcRequest(paths), release.ports()), Err)

    def test_reference_update_rejects_duplicates_and_combines_operation_release_failures(
        self,
    ) -> None:
        paths = object_store_paths("/managed")
        digest = ObjectDigest("sha256", "a" * 64)
        first = Diagnostic(DiagnosticCode("read-failed"), Severity.ERROR, "read failed")
        second = Diagnostic(DiagnosticCode("release-failed"), Severity.ERROR, "release failed")
        with self.assertRaises(ValueError):
            ReferenceUpdateRequest(
                paths,
                ReferenceKind.INSTALLED,
                "project/demo",
                (digest, digest),
            )

        lock_failure = Err((first,))
        lock_ports = ReferenceUpdatePorts(
            lambda _request: lock_failure,
            lambda _lease: Ok(None),
            lambda _request: Ok(ReferenceIndex(1, ())),
            lambda command: Ok(command.index),
        )
        request = ReferenceUpdateRequest(
            paths,
            ReferenceKind.INSTALLED,
            "project/demo",
            (digest,),
        )
        self.assertEqual(replace_references(request, lock_ports), lock_failure)

        combined_ports = ReferenceUpdatePorts(
            lambda request: Ok(StoreLockLease(request.lock_directory, "token")),
            lambda _lease: Err((second,)),
            lambda _request: Err((first,)),
            lambda command: Ok(command.index),
        )
        combined = replace_references(request, combined_ports)
        self.assertIsInstance(combined, Err)
        assert isinstance(combined, Err)
        self.assertEqual(combined.diagnostics, (first, second))


if __name__ == "__main__":
    unittest.main()
