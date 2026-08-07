from __future__ import annotations

import unittest
from dataclasses import replace
from typing import cast

from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Ok
from agent_artifacts.importers.model import ImportApplyPlan
from agent_artifacts.protocol.hashing import sha256_bytes
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.registry_maintenance.model import (
    MaterializedUpstreamCheck,
    NativeReferenceAcquisition,
    NativeUpstreamCheck,
    RegistryApplyCommand,
    RegistryApplyReceipt,
    RegistryChangeKind,
    RegistryFileChange,
    RegistryMutationPlan,
    UpstreamDisposition,
)
from agent_artifacts.registry_maintenance.planning import plan_registry_entry_add
from tests.registry_maintenance_fixtures import (
    empty_registry_snapshot,
    native_snapshot,
    registry_entry,
)


class RegistryMaintenanceModelTest(unittest.TestCase):
    def test_plan_rejects_a_forged_review_digest(self) -> None:
        planned = plan_registry_entry_add(empty_registry_snapshot(), registry_entry())
        assert isinstance(planned, Ok)
        with self.assertRaises(ValueError):
            replace(
                planned.value,
                review_digest=ObjectDigest("sha256", "f" * 64),
            )

    def test_file_change_requires_kind_consistent_exact_digests(self) -> None:
        path = parse_relative_path("entries/skill/code-review.json")
        assert isinstance(path, Ok)
        digest = sha256_bytes(b"{}")
        with self.assertRaises(ValueError):
            RegistryFileChange(
                path.value,
                RegistryChangeKind.ADDED,
                b"{}",
                digest,
                digest,
            )
        with self.assertRaises(ValueError):
            RegistryFileChange(
                path.value,
                RegistryChangeKind.UNCHANGED,
                b"{}",
                None,
                digest,
            )
        with self.assertRaises(ValueError):
            RegistryFileChange(
                path.value,
                RegistryChangeKind.CHANGED,
                b"{}",
                digest,
                digest,
            )

    def test_invalid_or_inconsistent_maintenance_values_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            NativeReferenceAcquisition("url", "main", "short", native_snapshot())
        with self.assertRaises(ValueError):
            NativeReferenceAcquisition(
                "url",
                "main",
                cast(str, None),
                native_snapshot(),
            )
        with self.assertRaises(ValueError):
            RegistryFileChange(
                cast(object, "not-a-path"),
                RegistryChangeKind.ADDED,
                b"{}",
                None,
                sha256_bytes(b"different"),
            )

        planned = plan_registry_entry_add(empty_registry_snapshot(), registry_entry())
        assert isinstance(planned, Ok)
        with self.assertRaises(ValueError):
            NativeUpstreamCheck(UpstreamDisposition.UP_TO_DATE, planned.value)
        with self.assertRaises(ValueError):
            NativeUpstreamCheck(
                UpstreamDisposition.CHANGED,
                cast(RegistryMutationPlan, object()),
            )
        with self.assertRaises(ValueError):
            MaterializedUpstreamCheck(
                UpstreamDisposition.CHANGED,
                cast(ImportApplyPlan, object()),
            )
        with self.assertRaises(ValueError):
            RegistryApplyCommand(cast(RegistryMutationPlan, object()))
        with self.assertRaises(ValueError):
            RegistryApplyReceipt(
                planned.value.review_digest,
                planned.value.next_inputs_digest,
                -1,
            )


if __name__ == "__main__":
    unittest.main()
