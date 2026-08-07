from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from agent_artifacts.application.importers import finalize_legacy_import, prepare_legacy_import
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.io.import_output import FilesystemImportOutput
from agent_artifacts.protocol.native_tree import load_native_source
from agent_artifacts.protocol.semver import SemVer
from tests.importer_fixtures import importer_input
from tests.legacy_importer_test import options


class LegacyImporterE2ETest(unittest.TestCase):
    def test_fixture_runs_through_stage_review_atomic_apply_and_noop(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            output = FilesystemImportOutput(parent, "canonical-output")
            prepared = prepare_legacy_import(
                importer_input(),
                options(),
                executable_version=SemVer(1, 0, 0),
                output=output,
            )
            assert isinstance(prepared, Ok), prepared
            self.assertFalse(os.path.exists(output.destination))
            self.assertTrue(os.path.isdir(prepared.value.staged.stage_id))

            applied = finalize_legacy_import(
                prepared.value,
                prepared.value.apply_plan.review_digest,
                output=output,
            )
            assert isinstance(applied, Ok), applied
            self.assertEqual(applied.value.output_digest, prepared.value.apply_plan.output_digest)
            current = output.current()
            assert isinstance(current, Ok)
            assert current.value is not None
            loaded = load_native_source(
                current.value,
                executable_version=SemVer(1, 0, 0),
                available_capabilities=(),
            )
            self.assertIsInstance(loaded, Ok)

            noop = prepare_legacy_import(
                importer_input(),
                options(),
                executable_version=SemVer(1, 0, 0),
                output=output,
            )
            assert isinstance(noop, Ok)
            receipt = finalize_legacy_import(
                noop.value,
                noop.value.apply_plan.review_digest,
                output=output,
            )
            assert isinstance(receipt, Ok)
            self.assertEqual(receipt.value.changed_paths, 0)
            self.assertTrue(receipt.value.warnings)
            self.assertFalse(os.path.exists(noop.value.staged.stage_id))

    def test_apply_failure_restores_the_reviewed_destination(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            output = FilesystemImportOutput(parent, "canonical-output")
            initial = prepare_legacy_import(
                importer_input(),
                options(),
                executable_version=SemVer(1, 0, 0),
                output=output,
            )
            assert isinstance(initial, Ok)
            first = finalize_legacy_import(
                initial.value,
                initial.value.apply_plan.review_digest,
                output=output,
            )
            assert isinstance(first, Ok)
            changed = prepare_legacy_import(
                importer_input(),
                options(display_name="Changed display"),
                executable_version=SemVer(1, 0, 0),
                output=output,
            )
            assert isinstance(changed, Ok)
            real_replace = os.replace

            def fail_publish(source: str, destination: str) -> None:
                if source == changed.value.staged.stage_id and destination == output.destination:
                    raise OSError("injected publish failure")
                real_replace(source, destination)

            with patch("agent_artifacts.io.import_output.os.replace", side_effect=fail_publish):
                result = finalize_legacy_import(
                    changed.value,
                    changed.value.apply_plan.review_digest,
                    output=output,
                )

            self.assertIsInstance(result, Err)
            current = output.current()
            assert isinstance(current, Ok)
            assert current.value is not None
            restored = prepare_legacy_import(
                importer_input(),
                options(),
                executable_version=SemVer(1, 0, 0),
                output=output,
            )
            assert isinstance(restored, Ok)
            self.assertEqual(
                current.value,
                restored.value.validated.materialized.snapshot,
            )
            self.assertFalse(os.path.lexists(changed.value.staged.stage_id))
            output.discard(restored.value.staged)

    def test_destination_change_after_review_fails_without_overwriting_it(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            output = FilesystemImportOutput(parent, "canonical-output")
            initial = prepare_legacy_import(
                importer_input(),
                options(),
                executable_version=SemVer(1, 0, 0),
                output=output,
            )
            assert isinstance(initial, Ok)
            first = finalize_legacy_import(
                initial.value,
                initial.value.apply_plan.review_digest,
                output=output,
            )
            assert isinstance(first, Ok)
            changed = prepare_legacy_import(
                importer_input(),
                options(display_name="Changed display"),
                executable_version=SemVer(1, 0, 0),
                output=output,
            )
            assert isinstance(changed, Ok)
            marker = os.path.join(output.destination, "maintainer-change.txt")
            with open(marker, "wb") as stream:
                stream.write(b"keep me\n")

            result = finalize_legacy_import(
                changed.value,
                changed.value.apply_plan.review_digest,
                output=output,
            )

            self.assertIsInstance(result, Err)
            with open(marker, "rb") as stream:
                self.assertEqual(stream.read(), b"keep me\n")
            self.assertFalse(os.path.exists(changed.value.staged.stage_id))

    def test_tampered_stage_symlink_is_rejected_without_reading_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            output = FilesystemImportOutput(parent, "canonical-output")
            prepared = prepare_legacy_import(
                importer_input(),
                options(),
                executable_version=SemVer(1, 0, 0),
                output=output,
            )
            assert isinstance(prepared, Ok)
            staged_manifest = os.path.join(prepared.value.staged.stage_id, "aart-source.json")
            outside = os.path.join(parent, "outside.txt")
            with open(outside, "wb") as stream:
                stream.write(b"outside must remain unread and unchanged\n")
            os.unlink(staged_manifest)
            os.symlink(outside, staged_manifest)

            result = finalize_legacy_import(
                prepared.value,
                prepared.value.apply_plan.review_digest,
                output=output,
            )

            self.assertIsInstance(result, Err)
            with open(outside, "rb") as stream:
                self.assertEqual(stream.read(), b"outside must remain unread and unchanged\n")
            self.assertFalse(os.path.exists(output.destination))
            self.assertFalse(os.path.lexists(prepared.value.staged.stage_id))


if __name__ == "__main__":
    unittest.main()
