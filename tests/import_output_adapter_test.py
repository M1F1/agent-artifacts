from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import agent_artifacts.io.import_output as import_output
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.importers.model import StagedImport
from agent_artifacts.io.import_output import FilesystemImportOutput
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import SafeRelativePath
from agent_artifacts.sources.model import source_snapshot_digest


def _snapshot(content: bytes = b"{}\n") -> SourceSnapshot:
    return SourceSnapshot(
        SnapshotOrigin.LOCAL,
        (
            SnapshotEntry(
                SafeRelativePath(("artifact.json",)),
                SnapshotEntryKind.FILE,
                content,
            ),
        ),
    )


def _digest(snapshot: SourceSnapshot) -> ObjectDigest:
    result = source_snapshot_digest(snapshot)
    assert isinstance(result, Ok)
    return result.value


class ImportOutputAdapterTest(unittest.TestCase):
    def test_rejects_symlink_destination_and_stage_receipts_outside_parent(self) -> None:
        with tempfile.TemporaryDirectory() as parent, tempfile.TemporaryDirectory() as outside:
            output = FilesystemImportOutput(parent, "canonical-output")
            os.symlink(outside, output.destination)

            current = output.current()
            forged = output.apply(
                StagedImport(outside, ObjectDigest("sha256", "a" * 64)),
                expected_destination_digest=None,
                changed_paths=1,
            )

            self.assertIsInstance(current, Err)
            self.assertIsInstance(forged, Err)

    def test_constructor_rejects_broad_relative_or_symlinked_parents(self) -> None:
        with tempfile.TemporaryDirectory() as parent, tempfile.TemporaryDirectory() as target:
            link = os.path.join(parent, "link")
            os.symlink(target, link)
            for args in (("relative", "output"), (link, "output"), (parent, "../output")):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    FilesystemImportOutput(*args)

    def test_stage_and_current_enforce_entry_bounds_before_mutation(self) -> None:
        snapshot = _snapshot()
        with tempfile.TemporaryDirectory() as parent:
            output = FilesystemImportOutput(parent, "canonical-output")
            with patch("agent_artifacts.io.import_output._MAX_FILES", 0):
                staged = output.stage(snapshot, _digest(snapshot))
            self.assertIsInstance(staged, Err)
            self.assertEqual(os.listdir(parent), [])

            os.mkdir(output.destination)
            os.mkdir(os.path.join(output.destination, "nested"))
            with patch("agent_artifacts.io.import_output._MAX_FILES", 0):
                current = output.current()
            self.assertIsInstance(current, Err)

    def test_stage_rejects_bad_digest_size_and_creation_failure(self) -> None:
        snapshot = _snapshot()
        with tempfile.TemporaryDirectory() as parent:
            output = FilesystemImportOutput(parent, "canonical-output")
            self.assertIsInstance(
                output.stage(snapshot, ObjectDigest("sha256", "f" * 64)),
                Err,
            )
            with patch("agent_artifacts.io.import_output._MAX_FILE_BYTES", 1):
                self.assertIsInstance(output.stage(snapshot, _digest(snapshot)), Err)
            with patch(
                "agent_artifacts.io.import_output.tempfile.mkdtemp",
                side_effect=OSError("injected create failure"),
            ):
                self.assertIsInstance(output.stage(snapshot, _digest(snapshot)), Err)
            self.assertEqual(os.listdir(parent), [])

    def test_stage_rejects_unsafe_parent_and_failed_filesystem_verification(self) -> None:
        snapshot = _snapshot()
        with tempfile.TemporaryDirectory() as parent:
            output = FilesystemImportOutput(parent, "canonical-output")
            with patch("agent_artifacts.io.import_output._safe_parent", return_value=False):
                self.assertIsInstance(output.stage(snapshot, _digest(snapshot)), Err)
            failure = import_output._read_directory(os.path.join(parent, "missing"))
            assert isinstance(failure, Err)
            with patch(
                "agent_artifacts.io.import_output._read_directory",
                return_value=failure,
            ):
                self.assertIsInstance(output.stage(snapshot, _digest(snapshot)), Err)
            with patch(
                "agent_artifacts.io.import_output._read_directory",
                return_value=Ok(_snapshot(b"different\n")),
            ):
                self.assertIsInstance(output.stage(snapshot, _digest(snapshot)), Err)
            with patch(
                "agent_artifacts.io.import_output._fsync_directory",
                side_effect=OSError("injected sync failure"),
            ):
                self.assertIsInstance(output.stage(snapshot, _digest(snapshot)), Err)
            self.assertEqual(os.listdir(parent), [])

    def test_current_rejects_file_special_depth_and_size_violations(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            output = FilesystemImportOutput(parent, "canonical-output")
            with open(output.destination, "wb") as stream:
                stream.write(b"not a directory\n")
            self.assertIsInstance(output.current(), Err)
            os.unlink(output.destination)

            os.mkdir(output.destination)
            nested = os.path.join(output.destination, "nested")
            os.mkdir(nested)
            with patch("agent_artifacts.io.import_output._MAX_DEPTH", 0):
                self.assertIsInstance(output.current(), Err)
            os.rmdir(nested)
            path = os.path.join(output.destination, "large.txt")
            with open(path, "wb") as stream:
                stream.write(b"large\n")
            with patch("agent_artifacts.io.import_output._MAX_FILE_BYTES", 1):
                self.assertIsInstance(output.current(), Err)
            with patch("agent_artifacts.io.import_output._MAX_TOTAL_BYTES", 1):
                self.assertIsInstance(output.current(), Err)
            os.unlink(path)
            if hasattr(os, "mkfifo"):
                fifo = os.path.join(output.destination, "special")
                os.mkfifo(fifo)
                self.assertIsInstance(output.current(), Err)
                os.unlink(fifo)

    def test_apply_rejects_invalid_counts_tampering_and_backup_collision(self) -> None:
        snapshot = _snapshot()
        with tempfile.TemporaryDirectory() as parent:
            output = FilesystemImportOutput(parent, "canonical-output")
            staged = output.stage(snapshot, _digest(snapshot))
            assert isinstance(staged, Ok)
            for count in (True, -1):
                with self.subTest(count=count):
                    self.assertIsInstance(
                        output.apply(
                            staged.value,
                            expected_destination_digest=None,
                            changed_paths=count,
                        ),
                        Err,
                    )
            with open(os.path.join(staged.value.stage_id, "artifact.json"), "wb") as stream:
                stream.write(b"tampered\n")
            self.assertIsInstance(
                output.apply(
                    staged.value,
                    expected_destination_digest=None,
                    changed_paths=1,
                ),
                Err,
            )
            output.discard(staged.value)

            clean = output.stage(snapshot, _digest(snapshot))
            assert isinstance(clean, Ok)
            os.mkdir(f"{clean.value.stage_id}.previous")
            self.assertIsInstance(
                output.apply(
                    clean.value,
                    expected_destination_digest=None,
                    changed_paths=1,
                ),
                Err,
            )
            output.discard(clean.value)

    def test_discard_rejects_symlink_and_accepts_an_absent_known_stage(self) -> None:
        with tempfile.TemporaryDirectory() as parent, tempfile.TemporaryDirectory() as outside:
            output = FilesystemImportOutput(parent, "canonical-output")
            staged = output.stage(_snapshot(), _digest(_snapshot()))
            assert isinstance(staged, Ok)
            shutil.rmtree(staged.value.stage_id)
            self.assertIsInstance(output.discard(staged.value), Ok)

            issued = output.stage(_snapshot(), _digest(_snapshot()))
            assert isinstance(issued, Ok)
            shutil.rmtree(issued.value.stage_id)
            os.symlink(outside, issued.value.stage_id)
            receipt = issued.value
            self.assertIsInstance(output.discard(receipt), Err)
            self.assertTrue(os.path.isdir(outside))

            stage_id = os.path.join(output.parent, ".canonical-output.aart-import-stage-forged")
            receipt = StagedImport(stage_id, ObjectDigest("sha256", "a" * 64))
            os.unlink(issued.value.stage_id)
            self.assertIsInstance(output.discard(receipt), Err)
            os.mkdir(stage_id)
            self.assertIsInstance(output.discard(receipt), Err)
            self.assertTrue(os.path.isdir(stage_id))
            os.rmdir(stage_id)
            os.symlink(outside, stage_id)
            self.assertIsInstance(output.discard(receipt), Err)
            self.assertTrue(os.path.isdir(outside))
            self.assertIsInstance(
                output.discard(StagedImport(outside, ObjectDigest("sha256", "a" * 64))),
                Err,
            )

    def test_discard_reports_filesystem_failure(self) -> None:
        snapshot = _snapshot()
        with tempfile.TemporaryDirectory() as parent:
            output = FilesystemImportOutput(parent, "canonical-output")
            staged = output.stage(snapshot, _digest(snapshot))
            assert isinstance(staged, Ok)
            with patch(
                "agent_artifacts.io.import_output.os.stat",
                side_effect=OSError("injected stat failure"),
            ):
                self.assertIsInstance(output.discard(staged.value), Err)
            self.assertIsInstance(output.discard(staged.value), Ok)

    def test_replacement_reports_a_retained_private_backup(self) -> None:
        first_snapshot = _snapshot()
        second_snapshot = _snapshot(b'{"changed":true}\n')
        with tempfile.TemporaryDirectory() as parent:
            output = FilesystemImportOutput(parent, "canonical-output")
            first = output.stage(first_snapshot, _digest(first_snapshot))
            assert isinstance(first, Ok)
            applied = output.apply(
                first.value,
                expected_destination_digest=None,
                changed_paths=1,
            )
            assert isinstance(applied, Ok)
            second = output.stage(second_snapshot, _digest(second_snapshot))
            assert isinstance(second, Ok)
            real_rmtree = __import__("shutil").rmtree

            def retain_backup(path: str, *args, **kwargs) -> None:
                if path.endswith(".previous"):
                    raise OSError("injected cleanup failure")
                real_rmtree(path, *args, **kwargs)

            with patch(
                "agent_artifacts.io.import_output.shutil.rmtree",
                side_effect=retain_backup,
            ):
                result = output.apply(
                    second.value,
                    expected_destination_digest=_digest(first_snapshot),
                    changed_paths=1,
                )

            assert isinstance(result, Ok)
            self.assertTrue(result.value.warnings)

    def test_failed_published_verification_restores_previous_output(self) -> None:
        first_snapshot = _snapshot()
        second_snapshot = _snapshot(b'{"changed":true}\n')
        with tempfile.TemporaryDirectory() as parent:
            output = FilesystemImportOutput(parent, "canonical-output")
            first = output.stage(first_snapshot, _digest(first_snapshot))
            assert isinstance(first, Ok)
            self.assertIsInstance(
                output.apply(
                    first.value,
                    expected_destination_digest=None,
                    changed_paths=1,
                ),
                Ok,
            )
            second = output.stage(second_snapshot, _digest(second_snapshot))
            assert isinstance(second, Ok)
            failure = import_output._read_directory(os.path.join(parent, "missing"))
            assert isinstance(failure, Err)
            real_read = import_output._read_directory
            destination_reads = 0

            def fail_after_publish(path: str):
                nonlocal destination_reads
                if path == output.destination:
                    destination_reads += 1
                    if destination_reads == 2:
                        return failure
                return real_read(path)

            with patch(
                "agent_artifacts.io.import_output._read_directory",
                side_effect=fail_after_publish,
            ):
                result = output.apply(
                    second.value,
                    expected_destination_digest=_digest(first_snapshot),
                    changed_paths=1,
                )

            self.assertIsInstance(result, Err)
            restored = output.current()
            assert isinstance(restored, Ok)
            assert restored.value is not None
            self.assertEqual(source_snapshot_digest(restored.value), Ok(_digest(first_snapshot)))

    def test_incomplete_rollback_is_reported_explicitly(self) -> None:
        first_snapshot = _snapshot()
        second_snapshot = _snapshot(b'{"changed":true}\n')
        with tempfile.TemporaryDirectory() as parent:
            output = FilesystemImportOutput(parent, "canonical-output")
            first = output.stage(first_snapshot, _digest(first_snapshot))
            assert isinstance(first, Ok)
            self.assertIsInstance(
                output.apply(
                    first.value,
                    expected_destination_digest=None,
                    changed_paths=1,
                ),
                Ok,
            )
            second = output.stage(second_snapshot, _digest(second_snapshot))
            assert isinstance(second, Ok)
            real_replace = os.replace
            backup = f"{second.value.stage_id}.previous"

            def fail_publish_and_rollback(source: str, destination: str) -> None:
                if (source, destination) in {
                    (second.value.stage_id, output.destination),
                    (backup, output.destination),
                }:
                    raise OSError("injected rename failure")
                real_replace(source, destination)

            with patch(
                "agent_artifacts.io.import_output.os.replace",
                side_effect=fail_publish_and_rollback,
            ):
                result = output.apply(
                    second.value,
                    expected_destination_digest=_digest(first_snapshot),
                    changed_paths=1,
                )

            self.assertIsInstance(result, Err)
            assert isinstance(result, Err)
            self.assertIn("rollback was incomplete", result.diagnostics[0].message)

    def test_post_publish_fsync_failure_is_a_success_warning(self) -> None:
        snapshot = _snapshot()
        with tempfile.TemporaryDirectory() as parent:
            output = FilesystemImportOutput(parent, "canonical-output")
            staged = output.stage(snapshot, _digest(snapshot))
            assert isinstance(staged, Ok)
            with patch(
                "agent_artifacts.io.import_output._fsync_directory",
                side_effect=OSError("injected durability failure"),
            ):
                result = output.apply(
                    staged.value,
                    expected_destination_digest=None,
                    changed_paths=1,
                )

            assert isinstance(result, Ok)
            self.assertTrue(result.value.warnings)
            self.assertTrue(os.path.isdir(output.destination))


if __name__ == "__main__":
    unittest.main()
