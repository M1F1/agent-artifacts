from __future__ import annotations

import unittest
from unittest.mock import patch

from agent_artifacts.application.importers import finalize_legacy_import, prepare_legacy_import
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.importers.model import AppliedImport, StagedImport
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import SafeRelativePath
from agent_artifacts.protocol.semver import SemVer
from tests.importer_fixtures import importer_input
from tests.legacy_importer_test import options


class FakeOutput:
    def __init__(
        self,
        *,
        forge_stage: bool = False,
        fail_current: bool = False,
        fail_stage: bool = False,
        fail_apply: bool = False,
        fail_discard: bool = False,
        forge_apply: bool = False,
    ):
        self.snapshot = None
        self.staged_snapshot = None
        self.forge_stage = forge_stage
        self.fail_current = fail_current
        self.fail_stage = fail_stage
        self.fail_apply = fail_apply
        self.fail_discard = fail_discard
        self.forge_apply = forge_apply
        self.apply_calls = 0
        self.discard_calls = 0

    @staticmethod
    def failure():
        return Err(
            (
                Diagnostic(
                    DiagnosticCode("fake-output-error"),
                    Severity.ERROR,
                    "injected output failure",
                ),
            )
        )

    def current(self):
        if self.fail_current:
            return self.failure()
        return Ok(self.snapshot)

    def stage(self, snapshot, output_digest):
        if self.fail_stage:
            return self.failure()
        self.staged_snapshot = snapshot
        digest = ObjectDigest("sha256", "f" * 64) if self.forge_stage else output_digest
        return Ok(StagedImport("stage-1", digest))

    def apply(self, staged, *, expected_destination_digest, changed_paths):
        self.apply_calls += 1
        if self.fail_apply:
            return self.failure()
        self.snapshot = self.staged_snapshot
        digest = ObjectDigest("sha256", "e" * 64) if self.forge_apply else staged.output_digest
        return Ok(AppliedImport(digest, changed_paths))

    def discard(self, staged):
        self.discard_calls += 1
        if self.fail_discard:
            return self.failure()
        self.staged_snapshot = None
        return Ok(None)


class ImporterApplicationTest(unittest.TestCase):
    def test_prepare_stages_only_and_finalize_requires_exact_review_digest(self) -> None:
        output = FakeOutput()
        prepared = prepare_legacy_import(
            importer_input(),
            options(),
            executable_version=SemVer(1, 0, 0),
            output=output,
        )
        assert isinstance(prepared, Ok), prepared
        self.assertIsNone(output.snapshot)
        self.assertIsNotNone(output.staged_snapshot)

        wrong = finalize_legacy_import(
            prepared.value,
            ObjectDigest("sha256", "0" * 64),
            output=output,
        )
        self.assertIsInstance(wrong, Err)
        self.assertEqual(output.apply_calls, 0)

        applied = finalize_legacy_import(
            prepared.value,
            prepared.value.apply_plan.review_digest,
            output=output,
        )
        self.assertIsInstance(applied, Ok)
        self.assertEqual(output.apply_calls, 1)
        self.assertIsNotNone(output.snapshot)

    def test_forged_stage_receipt_is_discarded_and_never_prepared(self) -> None:
        output = FakeOutput(forge_stage=True)

        result = prepare_legacy_import(
            importer_input(),
            options(),
            executable_version=SemVer(1, 0, 0),
            output=output,
        )

        self.assertIsInstance(result, Err)
        self.assertEqual(output.apply_calls, 0)
        self.assertEqual(output.discard_calls, 1)

    def test_output_failures_are_propagated_without_publishing(self) -> None:
        for name, output in (
            ("current", FakeOutput(fail_current=True)),
            ("stage", FakeOutput(fail_stage=True)),
        ):
            with self.subTest(name=name):
                result = prepare_legacy_import(
                    importer_input(),
                    options(),
                    executable_version=SemVer(1, 0, 0),
                    output=output,
                )
                self.assertIsInstance(result, Err)
                self.assertEqual(output.apply_calls, 0)

        for name, output in (
            ("apply", FakeOutput(fail_apply=True)),
            ("receipt", FakeOutput(forge_apply=True)),
        ):
            with self.subTest(name=name):
                prepared = prepare_legacy_import(
                    importer_input(),
                    options(),
                    executable_version=SemVer(1, 0, 0),
                    output=output,
                )
                assert isinstance(prepared, Ok)
                result = finalize_legacy_import(
                    prepared.value,
                    prepared.value.apply_plan.review_digest,
                    output=output,
                )
                self.assertIsInstance(result, Err)

    def test_noop_discard_failure_is_reported(self) -> None:
        output = FakeOutput()
        first = prepare_legacy_import(
            importer_input(),
            options(),
            executable_version=SemVer(1, 0, 0),
            output=output,
        )
        assert isinstance(first, Ok)
        applied = finalize_legacy_import(
            first.value,
            first.value.apply_plan.review_digest,
            output=output,
        )
        assert isinstance(applied, Ok)
        output.fail_discard = True
        noop = prepare_legacy_import(
            importer_input(),
            options(),
            executable_version=SemVer(1, 0, 0),
            output=output,
        )
        assert isinstance(noop, Ok)

        result = finalize_legacy_import(
            noop.value,
            noop.value.apply_plan.review_digest,
            output=output,
        )

        self.assertIsInstance(result, Err)

    def test_invalid_input_incompatible_output_and_unsafe_destination_fail_prepare(self) -> None:
        invalid_input = prepare_legacy_import(
            object(),  # type: ignore[arg-type]
            options(),
            executable_version=SemVer(1, 0, 0),
            output=FakeOutput(),
        )
        incompatible = prepare_legacy_import(
            importer_input(),
            options(),
            executable_version=SemVer(2, 0, 0),
            output=FakeOutput(),
        )
        unsafe_output = FakeOutput()
        unsafe_output.snapshot = SourceSnapshot(
            SnapshotOrigin.LOCAL,
            (
                SnapshotEntry(
                    SafeRelativePath(("unsafe",)),
                    SnapshotEntryKind.SYMLINK,
                ),
            ),
        )
        unsafe_destination = prepare_legacy_import(
            importer_input(),
            options(),
            executable_version=SemVer(1, 0, 0),
            output=unsafe_output,
        )

        self.assertIsInstance(invalid_input, Err)
        self.assertIsInstance(incompatible, Err)
        self.assertIsInstance(unsafe_destination, Err)

    def test_inconsistent_prepared_value_is_discarded(self) -> None:
        output = FakeOutput()
        with patch(
            "agent_artifacts.application.importers.PreparedImport",
            side_effect=ValueError("injected invariant failure"),
        ):
            result = prepare_legacy_import(
                importer_input(),
                options(),
                executable_version=SemVer(1, 0, 0),
                output=output,
            )

        self.assertIsInstance(result, Err)
        self.assertEqual(output.discard_calls, 1)


if __name__ == "__main__":
    unittest.main()
