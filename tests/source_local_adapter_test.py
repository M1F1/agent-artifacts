from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.sources.local import read_local_snapshot
from agent_artifacts.sources.model import LocalSnapshotRequest, SnapshotLimits, SourceInstanceId

_REFERENCE = Path(__file__).parent / "fixtures" / "protocol" / "native-source-v1"


class SourceLocalAdapterTest(unittest.TestCase):
    def test_native_local_tree_is_bounded_deterministic_and_inert(self) -> None:
        request = LocalSnapshotRequest(
            SourceInstanceId("local-" + "a" * 32),
            SourceAlias("reference"),
            str(_REFERENCE),
            SnapshotLimits(),
        )

        first = read_local_snapshot(request)
        second = read_local_snapshot(request)

        self.assertIsInstance(first, Ok)
        self.assertEqual(first, second)
        assert isinstance(first, Ok)
        self.assertEqual(first.value.snapshot.origin.value, "local")
        self.assertIn(
            "aart-source.json", tuple(str(item.path) for item in first.value.snapshot.entries)
        )
        self.assertTrue(all(str(item.path) != ".git" for item in first.value.snapshot.entries))

    def test_symlinks_special_files_and_bounds_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source = Path(root)
            (source / "file").write_bytes(b"1234")
            (source / "link").symlink_to(source / "file")
            request = LocalSnapshotRequest(
                SourceInstanceId("local-" + "b" * 32),
                SourceAlias("unsafe"),
                root,
                SnapshotLimits(),
            )
            self.assertIsInstance(read_local_snapshot(request), Err)

            (source / "link").unlink()
            too_large = LocalSnapshotRequest(
                request.instance_id,
                request.alias,
                root,
                SnapshotLimits(max_file_bytes=3),
            )
            self.assertIsInstance(read_local_snapshot(too_large), Err)

            if hasattr(os, "mkfifo"):
                fifo = source / "pipe"
                os.mkfifo(fifo)
                self.assertIsInstance(read_local_snapshot(request), Err)

    def test_missing_root_and_file_count_limit_are_typed_errors(self) -> None:
        instance = SourceInstanceId("local-" + "c" * 32)
        missing = LocalSnapshotRequest(
            instance,
            SourceAlias("missing"),
            "/does/not/exist",
            SnapshotLimits(),
        )
        self.assertIsInstance(read_local_snapshot(missing), Err)

        with tempfile.TemporaryDirectory() as root:
            Path(root, "one").write_bytes(b"1")
            Path(root, "two").write_bytes(b"2")
            bounded = LocalSnapshotRequest(
                instance,
                SourceAlias("bounded"),
                root,
                SnapshotLimits(max_files=1),
            )
            self.assertIsInstance(read_local_snapshot(bounded), Err)

    def test_non_directory_depth_total_size_and_unsafe_name_are_rejected(self) -> None:
        instance = SourceInstanceId("local-" + "d" * 32)
        with tempfile.TemporaryDirectory() as root:
            file_root = Path(root) / "file"
            file_root.write_bytes(b"content")

            def request(path: Path, limits: SnapshotLimits | None = None) -> LocalSnapshotRequest:
                selected_limits = SnapshotLimits() if limits is None else limits
                return LocalSnapshotRequest(
                    instance, SourceAlias("bounded"), str(path), selected_limits
                )

            self.assertIsInstance(read_local_snapshot(request(file_root)), Err)

            nested = Path(root) / "nested"
            (nested / "one" / "two").mkdir(parents=True)
            (nested / "one" / "two" / "file").write_bytes(b"x")
            self.assertIsInstance(
                read_local_snapshot(request(nested, SnapshotLimits(max_depth=1))), Err
            )

            total = Path(root) / "total"
            total.mkdir()
            (total / "one").write_bytes(b"12")
            (total / "two").write_bytes(b"34")
            self.assertIsInstance(
                read_local_snapshot(request(total, SnapshotLimits(max_total_bytes=3))), Err
            )

            unsafe = Path(root) / "unsafe"
            unsafe.mkdir()
            (unsafe / "bad\\name").write_bytes(b"x")
            self.assertIsInstance(read_local_snapshot(request(unsafe)), Err)

    def test_directory_and_file_races_are_typed_errors(self) -> None:
        instance = SourceInstanceId("local-" + "e" * 32)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "file"
            path.write_bytes(b"content")
            request = LocalSnapshotRequest(instance, SourceAlias("racy"), root, SnapshotLimits())
            with patch("agent_artifacts.sources.local.os.scandir", side_effect=OSError("race")):
                self.assertIsInstance(read_local_snapshot(request), Err)
            real_open = os.open
            with patch("agent_artifacts.sources.local.os.open", wraps=real_open) as opened:
                self.assertIsInstance(read_local_snapshot(request), Ok)
            self.assertTrue(opened.called)
            self.assertTrue(opened.call_args.args[1] & getattr(os, "O_NOFOLLOW", 0))

            with patch("agent_artifacts.sources.local.os.open", side_effect=OSError("race")):
                self.assertIsInstance(read_local_snapshot(request), Err)
            original = os.stat(path, follow_symlinks=False)
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
            with patch("agent_artifacts.sources.local.os.fstat", return_value=raced):
                self.assertIsInstance(read_local_snapshot(request), Err)

    def test_root_git_metadata_is_never_part_of_a_local_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            metadata = Path(root) / ".git"
            metadata.mkdir()
            (metadata / "unsafe").symlink_to(Path(root) / "missing")
            Path(root, "artifact").write_bytes(b"content")
            request = LocalSnapshotRequest(
                SourceInstanceId("local-" + "f" * 32),
                SourceAlias("local"),
                root,
                SnapshotLimits(),
            )

            result = read_local_snapshot(request)

            self.assertIsInstance(result, Ok)
            assert isinstance(result, Ok)
            self.assertNotIn(".git", {str(entry.path) for entry in result.value.snapshot.entries})


if __name__ == "__main__":
    unittest.main()
