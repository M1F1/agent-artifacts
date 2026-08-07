from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_artifacts.compiler.model import ObjectPlan
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.io.object_store import (
    delete_object,
    inventory_objects,
    materialize_compiler_object,
    publish_object,
    read_object,
)
from agent_artifacts.protocol.hashing import sha256_bytes
from agent_artifacts.protocol.native_tree import SnapshotEntry, SnapshotEntryKind
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.store.model import (
    ObjectDeleteCommand,
    ObjectPublishCommand,
    ObjectReadRequest,
    make_object_candidate,
    object_store_paths,
)


def _candidate(content: bytes = b"payload"):
    artifact = parse_relative_path("artifact.json")
    payload = parse_relative_path("payload/file.txt")
    assert isinstance(artifact, Ok)
    assert isinstance(payload, Ok)
    result = make_object_candidate(
        (
            SnapshotEntry(artifact.value, SnapshotEntryKind.FILE, b"{}\n"),
            SnapshotEntry(payload.value, SnapshotEntryKind.FILE, content, executable=True),
        )
    )
    assert isinstance(result, Ok)
    return result.value


class ObjectStoreAdapterTest(unittest.TestCase):
    def test_publish_is_read_only_digest_verified_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(root)
            candidate = _candidate()
            published = publish_object(ObjectPublishCommand(paths, candidate))
            loaded = read_object(ObjectReadRequest(paths, candidate.digest))

            self.assertIsInstance(published, Ok)
            self.assertIsInstance(loaded, Ok)
            assert isinstance(published, Ok)
            assert isinstance(loaded, Ok)
            self.assertTrue(published.value.created)
            self.assertFalse(published.value.repaired)
            self.assertIsNotNone(loaded.value)
            assert loaded.value is not None
            self.assertEqual(loaded.value.candidate, candidate)
            self.assertEqual(os.stat(loaded.value.root).st_mode & 0o222, 0)
            for path in Path(loaded.value.root).rglob("*"):
                self.assertEqual(os.lstat(path).st_mode & 0o222, 0)

    def test_concurrent_identical_publication_converges_and_corruption_repairs(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(root)
            candidate = _candidate()
            command = ObjectPublishCommand(paths, candidate)
            results = []

            def publish() -> None:
                results.append(publish_object(command))

            threads = [threading.Thread(target=publish) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertTrue(all(isinstance(result, Ok) for result in results), results)
            self.assertEqual(
                sum(result.value.created for result in results if isinstance(result, Ok)), 1
            )

            stored = read_object(ObjectReadRequest(paths, candidate.digest))
            assert isinstance(stored, Ok)
            assert stored.value is not None
            payload = Path(stored.value.root) / "payload" / "file.txt"
            os.chmod(payload, 0o600)
            payload.write_bytes(b"corrupt")

            repaired = publish_object(command)

            self.assertIsInstance(repaired, Ok)
            assert isinstance(repaired, Ok)
            self.assertTrue(repaired.value.repaired)
            verified = read_object(ObjectReadRequest(paths, candidate.digest))
            self.assertIsInstance(verified, Ok)

    def test_symlinked_object_is_rejected_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(str(Path(root) / "managed"))
            candidate = _candidate()
            external = Path(root) / "external"
            external.mkdir()
            marker = external / "marker"
            marker.write_bytes(b"keep")
            object_root = (
                Path(paths.objects) / candidate.digest.value[:2] / candidate.digest.value[2:]
            )
            object_root.parent.mkdir(parents=True)
            object_root.symlink_to(external, target_is_directory=True)

            self.assertIsInstance(publish_object(ObjectPublishCommand(paths, candidate)), Err)
            self.assertIsInstance(read_object(ObjectReadRequest(paths, candidate.digest)), Err)
            self.assertIsInstance(delete_object(ObjectDeleteCommand(paths, candidate.digest)), Err)
            self.assertEqual(marker.read_bytes(), b"keep")

    def test_managed_parent_symlink_is_rejected_before_external_write(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(str(Path(root) / "managed"))
            external = Path(root) / "external"
            external.mkdir()
            managed = Path(paths.root)
            managed.mkdir()
            (managed / "objects").symlink_to(external, target_is_directory=True)

            self.assertIsInstance(publish_object(ObjectPublishCommand(paths, _candidate())), Err)
            self.assertIsInstance(inventory_objects(paths), Err)
            self.assertEqual(tuple(external.iterdir()), ())

    def test_compiler_plan_inventory_and_exact_delete_share_the_same_digest_contract(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(root)
            candidate = _candidate()
            receipt = materialize_compiler_object(
                paths, ObjectPlan(candidate.digest, candidate.canonical_bytes)
            )
            inventory = inventory_objects(paths)

            self.assertIsInstance(receipt, Ok)
            self.assertIsInstance(inventory, Ok)
            assert isinstance(receipt, Ok)
            assert isinstance(inventory, Ok)
            self.assertEqual(receipt.value.digest, candidate.digest)
            self.assertEqual(inventory.value.digests, (candidate.digest,))
            self.assertEqual(delete_object(ObjectDeleteCommand(paths, candidate.digest)), Ok(None))
            self.assertEqual(read_object(ObjectReadRequest(paths, candidate.digest)), Ok(None))

            invalid = ObjectPlan(sha256_bytes(b"bad"), b"bad")
            self.assertIsInstance(materialize_compiler_object(paths, invalid), Err)

    def test_inventory_ignores_unrecognized_and_symlinked_paths_with_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(root)
            objects = Path(paths.objects)
            objects.mkdir(parents=True)
            (objects / "not-a-prefix").mkdir()
            external = Path(root) / "external"
            external.mkdir()
            (objects / "aa").symlink_to(external, target_is_directory=True)

            inventory = inventory_objects(paths)

            self.assertIsInstance(inventory, Ok)
            assert isinstance(inventory, Ok)
            self.assertEqual(inventory.value.digests, ())
            self.assertEqual(len(inventory.value.diagnostics), 2)

        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(root)
            self.assertEqual(inventory_objects(paths), Ok(type(inventory.value)(())))

    def test_inner_symlink_scan_and_stage_io_failure_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(root)
            candidate = _candidate()
            published = publish_object(ObjectPublishCommand(paths, candidate))
            assert isinstance(published, Ok)
            stored_root = Path(published.value.stored.root)
            payload = stored_root / "payload"
            os.chmod(stored_root, 0o700)
            os.chmod(payload, 0o700)
            (payload / "link").symlink_to(Path(root) / "outside")

            self.assertIsInstance(read_object(ObjectReadRequest(paths, candidate.digest)), Err)

        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(root)
            with patch(
                "agent_artifacts.io.object_store.os.open", side_effect=PermissionError("denied")
            ):
                failed = publish_object(ObjectPublishCommand(paths, _candidate()))
            self.assertIsInstance(failed, Err)

    def test_failed_repair_publish_rolls_corrupt_target_back_into_place(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(root)
            candidate = _candidate()
            published = publish_object(ObjectPublishCommand(paths, candidate))
            assert isinstance(published, Ok)
            target = Path(published.value.stored.root)
            payload = target / "payload" / "file.txt"
            os.chmod(payload, 0o600)
            payload.write_bytes(b"corrupt")
            real_rename = os.rename

            def fail_second_stage_rename(source, destination):
                if Path(source).name.startswith(".stage-") and not os.path.lexists(target):
                    raise OSError("repair publish failed")
                return real_rename(source, destination)

            with patch(
                "agent_artifacts.io.object_store.os.rename",
                side_effect=fail_second_stage_rename,
            ):
                failed = publish_object(ObjectPublishCommand(paths, candidate))

            self.assertIsInstance(failed, Err)
            self.assertTrue(target.is_dir())
            self.assertIsInstance(read_object(ObjectReadRequest(paths, candidate.digest)), Err)

    def test_delete_missing_object_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(root)
            candidate = _candidate()
            command = ObjectDeleteCommand(paths, candidate.digest)
            self.assertEqual(delete_object(command), Ok(None))
            self.assertEqual(delete_object(command), Ok(None))

    def test_failed_physical_delete_restores_verified_read_only_object(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(root)
            candidate = _candidate()
            published = publish_object(ObjectPublishCommand(paths, candidate))
            assert isinstance(published, Ok)

            with patch(
                "agent_artifacts.io.object_store.shutil.rmtree",
                side_effect=OSError("delete failed"),
            ):
                failed = delete_object(ObjectDeleteCommand(paths, candidate.digest))

            self.assertIsInstance(failed, Err)
            restored = read_object(ObjectReadRequest(paths, candidate.digest))
            self.assertIsInstance(restored, Ok)
            assert isinstance(restored, Ok)
            assert restored.value is not None
            self.assertEqual(restored.value.candidate, candidate)
            for path in (Path(restored.value.root), *Path(restored.value.root).rglob("*")):
                self.assertEqual(os.lstat(path).st_mode & 0o222, 0)

    def test_reader_rejects_unsafe_names_special_files_open_failures_and_races(self) -> None:
        def published(root: str):
            paths = object_store_paths(root)
            candidate = _candidate()
            result = publish_object(ObjectPublishCommand(paths, candidate))
            assert isinstance(result, Ok)
            object_root = Path(result.value.stored.root)
            os.chmod(object_root, 0o700)
            return paths, candidate, object_root

        with tempfile.TemporaryDirectory() as root:
            paths, candidate, object_root = published(root)
            (object_root / "bad\\name").write_bytes(b"unsafe")
            self.assertIsInstance(read_object(ObjectReadRequest(paths, candidate.digest)), Err)

        if hasattr(os, "mkfifo"):
            with tempfile.TemporaryDirectory() as root:
                paths, candidate, object_root = published(root)
                os.mkfifo(object_root / "zz-device")
                self.assertIsInstance(read_object(ObjectReadRequest(paths, candidate.digest)), Err)

        with tempfile.TemporaryDirectory() as root:
            paths, candidate, _object_root = published(root)
            with patch("agent_artifacts.io.object_store.os.scandir", side_effect=OSError("scan")):
                self.assertIsInstance(read_object(ObjectReadRequest(paths, candidate.digest)), Err)
            with patch("agent_artifacts.io.object_store.os.open", side_effect=OSError("open")):
                self.assertIsInstance(read_object(ObjectReadRequest(paths, candidate.digest)), Err)

            payload = Path(_object_root) / "artifact.json"
            original = os.stat(payload, follow_symlinks=False)
            raced = os.stat_result(
                (
                    original.st_mode,
                    original.st_ino + 1,
                    original.st_dev,
                    original.st_nlink,
                    original.st_uid,
                    original.st_gid,
                    original.st_size,
                    original.st_atime,
                    original.st_mtime,
                    original.st_ctime,
                )
            )
            with patch("agent_artifacts.io.object_store.os.fstat", return_value=raced):
                self.assertIsInstance(read_object(ObjectReadRequest(paths, candidate.digest)), Err)

    def test_reader_does_not_follow_directory_swapped_to_symlink_mid_scan(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(str(Path(root) / "managed"))
            candidate = _candidate()
            published = publish_object(ObjectPublishCommand(paths, candidate))
            assert isinstance(published, Ok)
            object_root = Path(published.value.stored.root)
            payload = object_root / "payload"
            external = Path(root) / "external"
            external.mkdir()
            external_file = external / "file.txt"
            external_file.write_bytes(b"payload")
            os.chmod(external_file, 0o500)
            original_payload = Path(root) / "original-payload"
            os.chmod(object_root, 0o700)
            os.chmod(payload, 0o700)
            real_open = os.open
            swapped = False

            def swap_before_file_open(path, flags, *args, **kwargs):
                nonlocal swapped
                if not swapped and str(path).endswith("artifact.json"):
                    payload.rename(original_payload)
                    payload.symlink_to(external, target_is_directory=True)
                    swapped = True
                return real_open(path, flags, *args, **kwargs)

            with patch(
                "agent_artifacts.io.object_store.os.open", side_effect=swap_before_file_open
            ):
                result = read_object(ObjectReadRequest(paths, candidate.digest))

            self.assertTrue(swapped)
            self.assertIsInstance(result, Err)

    def test_reader_enforces_depth_entry_file_and_total_size_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(root)
            candidate = _candidate()
            self.assertIsInstance(publish_object(ObjectPublishCommand(paths, candidate)), Ok)
            request = ObjectReadRequest(paths, candidate.digest)
            limits = (
                ("_MAX_DEPTH", 0),
                ("_MAX_ENTRIES", 1),
                ("_MAX_FILE_BYTES", 1),
                ("_MAX_TOTAL_BYTES", 4),
            )
            for name, value in limits:
                with (
                    self.subTest(name=name),
                    patch(f"agent_artifacts.io.object_store.{name}", value),
                ):
                    self.assertIsInstance(read_object(request), Err)

    def test_store_inventory_and_quarantine_roots_must_be_real_directories(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(str(Path(root) / "managed"))
            external = Path(root) / "external"
            external.mkdir()
            Path(paths.objects).parent.mkdir(parents=True)
            Path(paths.objects).symlink_to(external, target_is_directory=True)
            self.assertIsInstance(publish_object(ObjectPublishCommand(paths, _candidate())), Err)
            self.assertIsInstance(inventory_objects(paths), Err)

        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(root)
            prefix = Path(paths.objects) / "aa"
            prefix.mkdir(parents=True)
            (prefix / "bad-suffix").mkdir()
            inventory = inventory_objects(paths)
            self.assertIsInstance(inventory, Ok)
            assert isinstance(inventory, Ok)
            self.assertEqual(len(inventory.value.diagnostics), 1)

        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(root)
            candidate = _candidate()
            self.assertIsInstance(publish_object(ObjectPublishCommand(paths, candidate)), Ok)
            external = Path(root) / "external"
            external.mkdir()
            Path(paths.quarantine).parent.mkdir(parents=True, exist_ok=True)
            Path(paths.quarantine).symlink_to(external, target_is_directory=True)
            self.assertIsInstance(delete_object(ObjectDeleteCommand(paths, candidate.digest)), Err)
            self.assertEqual(tuple(external.iterdir()), ())


if __name__ == "__main__":
    unittest.main()
