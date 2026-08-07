from __future__ import annotations

import json
import unittest

from agent_artifacts.application.registry_maintenance import (
    finalize_registry_mutation,
    prepare_native_promotion,
)
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.registry_maintenance.model import (
    NativeReferenceAcquisition,
    RegistryApplyReceipt,
)
from agent_artifacts.registry_maintenance.planning import project_registry_mutation
from tests.registry_maintenance_fixtures import (
    empty_registry_snapshot,
    native_snapshot,
    registry_entry,
    replace_snapshot_file,
    snapshot_file,
)


class FakeRegistryOutput:
    def __init__(self):
        self.snapshot = empty_registry_snapshot()
        self.apply_calls = 0

    def current(self):
        return Ok(self.snapshot)

    def apply(self, command):
        self.apply_calls += 1
        projected = project_registry_mutation(self.snapshot, command.plan)
        assert isinstance(projected, Ok)
        self.snapshot = projected.value
        return Ok(
            RegistryApplyReceipt(
                command.plan.review_digest,
                command.plan.next_inputs_digest,
                command.plan.changed_paths,
            )
        )


class BadReceiptOutput(FakeRegistryOutput):
    def apply(self, command):
        self.apply_calls += 1
        return Ok(
            RegistryApplyReceipt(
                command.plan.review_digest,
                command.plan.next_inputs_digest,
                command.plan.changed_paths + 1,
            )
        )


FAILURE = Err((Diagnostic(DiagnosticCode("test-failure"), Severity.ERROR, "failure"),))


class FailingCurrentOutput(FakeRegistryOutput):
    def current(self):
        return FAILURE


class FailingApplyOutput(FakeRegistryOutput):
    def apply(self, command):
        self.apply_calls += 1
        return FAILURE


class RegistryMaintenanceApplicationTest(unittest.TestCase):
    def test_port_errors_are_propagated_without_fabricating_success(self) -> None:
        acquisition = NativeReferenceAcquisition(
            "https://github.com/example/reference-skills.git",
            "main",
            "a" * 40,
            native_snapshot(),
        )
        failed_prepare = prepare_native_promotion(
            registry_entry(),
            acquisition,
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
            output=FailingCurrentOutput(),
        )
        self.assertEqual(failed_prepare, FAILURE)

        output = FailingApplyOutput()
        prepared = prepare_native_promotion(
            registry_entry(),
            acquisition,
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
            output=output,
        )
        assert isinstance(prepared, Ok)
        failed_apply = finalize_registry_mutation(
            prepared.value,
            prepared.value.review_digest,
            output=output,
        )
        self.assertEqual(failed_apply, FAILURE)

    def test_prepare_is_read_only_and_finalize_requires_the_exact_review(self) -> None:
        output = FakeRegistryOutput()
        prepared = prepare_native_promotion(
            registry_entry(),
            NativeReferenceAcquisition(
                "https://github.com/example/reference-skills.git",
                "main",
                "a" * 40,
                native_snapshot(),
            ),
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
            output=output,
        )
        assert isinstance(prepared, Ok), prepared
        self.assertEqual(output.apply_calls, 0)

        wrong = finalize_registry_mutation(
            prepared.value,
            ObjectDigest("sha256", "0" * 64),
            output=output,
        )
        self.assertIsInstance(wrong, Err)
        self.assertEqual(output.apply_calls, 0)

        applied = finalize_registry_mutation(
            prepared.value,
            prepared.value.review_digest,
            output=output,
        )
        self.assertIsInstance(applied, Ok)
        self.assertEqual(output.apply_calls, 1)

    def test_noop_finalize_rechecks_workspace_state_after_review(self) -> None:
        output = FakeRegistryOutput()
        initial = prepare_native_promotion(
            registry_entry(),
            NativeReferenceAcquisition(
                "https://github.com/example/reference-skills.git",
                "main",
                "a" * 40,
                native_snapshot(),
            ),
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
            output=output,
        )
        assert isinstance(initial, Ok)
        self.assertIsInstance(
            finalize_registry_mutation(
                initial.value,
                initial.value.review_digest,
                output=output,
            ),
            Ok,
        )
        noop = prepare_native_promotion(
            registry_entry(),
            NativeReferenceAcquisition(
                "https://github.com/example/reference-skills.git",
                "main",
                "a" * 40,
                native_snapshot(),
            ),
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
            output=output,
        )
        assert isinstance(noop, Ok), noop
        self.assertEqual(noop.value.changed_paths, 0)
        unavailable = FailingCurrentOutput()
        unavailable.snapshot = output.snapshot
        self.assertEqual(
            finalize_registry_mutation(
                noop.value,
                noop.value.review_digest,
                output=unavailable,
            ),
            FAILURE,
        )
        self.assertIsInstance(
            finalize_registry_mutation(
                noop.value,
                noop.value.review_digest,
                output=output,
            ),
            Ok,
        )

        source = json.loads(snapshot_file(output.snapshot, "aart-source.json"))
        source["display_name"] = "Changed after review"
        output.snapshot = replace_snapshot_file(
            output.snapshot,
            "aart-source.json",
            json.dumps(source).encode(),
        )
        result = finalize_registry_mutation(
            noop.value,
            noop.value.review_digest,
            output=output,
        )
        self.assertIsInstance(result, Err)
        self.assertEqual(output.apply_calls, 1)

    def test_apply_receipt_must_match_the_reviewed_plan(self) -> None:
        output = BadReceiptOutput()
        prepared = prepare_native_promotion(
            registry_entry(),
            NativeReferenceAcquisition(
                "https://github.com/example/reference-skills.git",
                "main",
                "a" * 40,
                native_snapshot(),
            ),
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
            output=output,
        )
        assert isinstance(prepared, Ok)
        result = finalize_registry_mutation(
            prepared.value,
            prepared.value.review_digest,
            output=output,
        )
        self.assertIsInstance(result, Err)


if __name__ == "__main__":
    unittest.main()
