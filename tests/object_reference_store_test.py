from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_artifacts.application.store import (
    ReferenceUpdatePorts,
    ReferenceUpdateRequest,
    replace_references,
)
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.io.reference_store import read_references, write_references
from agent_artifacts.io.store_lock import acquire_store_lock, release_store_lock
from agent_artifacts.store.model import (
    ReferenceIndex,
    ReferenceKind,
    ReferenceReadRequest,
    ReferenceWriteCommand,
    object_store_paths,
)
from tests.credential_fixtures import assignment_bytes, secret_object


class ObjectReferenceStoreTest(unittest.TestCase):
    def test_missing_then_atomic_private_owner_kind_replacement_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(root)
            ports = ReferenceUpdatePorts(
                acquire_store_lock,
                release_store_lock,
                read_references,
                write_references,
            )
            first = ObjectDigest("sha256", "a" * 64)
            second = ObjectDigest("sha256", "b" * 64)
            self.assertEqual(
                read_references(ReferenceReadRequest(paths)), Ok(ReferenceIndex(1, ()))
            )

            updated = replace_references(
                ReferenceUpdateRequest(
                    paths, ReferenceKind.INSTALLED, "project/demo", (first, second)
                ),
                ports,
            )
            replaced = replace_references(
                ReferenceUpdateRequest(paths, ReferenceKind.INSTALLED, "project/demo", (second,)),
                ports,
            )

            self.assertIsInstance(updated, Ok)
            self.assertIsInstance(replaced, Ok)
            loaded = read_references(ReferenceReadRequest(paths))
            self.assertIsInstance(loaded, Ok)
            assert isinstance(loaded, Ok)
            self.assertEqual(tuple(item.digest for item in loaded.value.references), (second,))
            self.assertEqual(os.stat(paths.references_file).st_mode & 0o777, 0o600)

    def test_corrupt_reference_state_is_typed_and_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(root)
            path = Path(paths.references_file)
            path.parent.mkdir(parents=True)
            path.write_bytes(secret_object("token", "secret", trailing=",broken"))

            result = read_references(ReferenceReadRequest(paths))

            self.assertIsInstance(result, Err)
            assert isinstance(result, Err)
            self.assertNotIn("secret", repr(result.diagnostics))

    def test_concurrent_distinct_owners_do_not_lose_references(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(root)
            ports = ReferenceUpdatePorts(
                acquire_store_lock,
                release_store_lock,
                read_references,
                write_references,
            )
            results = []

            def update(index: int) -> None:
                results.append(
                    replace_references(
                        ReferenceUpdateRequest(
                            paths,
                            ReferenceKind.SETUP,
                            f"setup/{index}",
                            (ObjectDigest("sha256", str(index) * 64),),
                        ),
                        ports,
                    )
                )

            threads = [threading.Thread(target=update, args=(index,)) for index in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertTrue(all(isinstance(result, Ok) for result in results), results)
            loaded = read_references(ReferenceReadRequest(paths))
            assert isinstance(loaded, Ok)
            self.assertEqual(len(loaded.value.references), 4)

    def test_failed_atomic_replace_preserves_previous_reference_index(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(root)
            ports = ReferenceUpdatePorts(
                acquire_store_lock,
                release_store_lock,
                read_references,
                write_references,
            )
            first = ObjectDigest("sha256", "a" * 64)
            second = ObjectDigest("sha256", "b" * 64)
            self.assertIsInstance(
                replace_references(
                    ReferenceUpdateRequest(
                        paths, ReferenceKind.INSTALLED, "project/demo", (first,)
                    ),
                    ports,
                ),
                Ok,
            )

            with patch(
                "agent_artifacts.io.reference_store.os.replace",
                side_effect=OSError("replace failed"),
            ):
                failed = replace_references(
                    ReferenceUpdateRequest(
                        paths, ReferenceKind.INSTALLED, "project/demo", (second,)
                    ),
                    ports,
                )

            self.assertIsInstance(failed, Err)
            loaded = read_references(ReferenceReadRequest(paths))
            assert isinstance(loaded, Ok)
            self.assertEqual(tuple(item.digest for item in loaded.value.references), (first,))
            self.assertEqual(tuple(Path(paths.state).glob(".object-references-*")), ())

            with patch(
                "agent_artifacts.io.reference_store.os.open",
                side_effect=PermissionError("denied"),
            ):
                self.assertIsInstance(read_references(ReferenceReadRequest(paths)), Err)

    def test_reference_reader_never_follows_a_state_file_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(root)
            external = Path(root) / "secret"
            external.write_bytes(assignment_bytes("token", "must-not-be-read"))
            reference_path = Path(paths.references_file)
            reference_path.parent.mkdir(parents=True)
            reference_path.symlink_to(external)

            result = read_references(ReferenceReadRequest(paths))

            self.assertIsInstance(result, Err)
            assert isinstance(result, Err)
            self.assertNotIn("must-not-be-read", repr(result.diagnostics))

    def test_reference_writer_rejects_symlinked_state_directory_before_external_write(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(str(Path(root) / "managed"))
            external = Path(root) / "external"
            external.mkdir()
            managed = Path(paths.root)
            managed.mkdir()
            (managed / "state").symlink_to(external, target_is_directory=True)

            result = write_references(ReferenceWriteCommand(paths, ReferenceIndex(1, ())))

            self.assertIsInstance(result, Err)
            self.assertEqual(tuple(external.iterdir()), ())

    def test_reference_reader_detects_open_and_read_races_and_cleanup_failure_is_typed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = object_store_paths(root)
            index = ReferenceIndex(1, ())
            self.assertIsInstance(write_references(ReferenceWriteCommand(paths, index)), Ok)
            reference_path = Path(paths.references_file)
            original = os.stat(reference_path, follow_symlinks=False)
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
            with patch("agent_artifacts.io.reference_store.os.fstat", return_value=raced):
                self.assertIsInstance(read_references(ReferenceReadRequest(paths)), Err)

            real_stat = os.stat

            def report_larger_file(path, *args, **kwargs):
                status = real_stat(path, *args, **kwargs)
                if Path(path) != reference_path:
                    return status
                values = list(status)
                values[6] += 1
                return os.stat_result(values)

            with patch(
                "agent_artifacts.io.reference_store.os.stat",
                side_effect=report_larger_file,
            ):
                self.assertIsInstance(read_references(ReferenceReadRequest(paths)), Err)

            with (
                patch(
                    "agent_artifacts.io.reference_store.os.replace",
                    side_effect=OSError("replace failed"),
                ),
                patch(
                    "agent_artifacts.io.reference_store.os.unlink",
                    side_effect=OSError("cleanup failed"),
                ),
            ):
                self.assertIsInstance(
                    write_references(ReferenceWriteCommand(paths, index)),
                    Err,
                )


if __name__ == "__main__":
    unittest.main()
