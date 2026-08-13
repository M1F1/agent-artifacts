from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_artifacts.domain.identifiers import SourceAlias, SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.io.source_store import (
    discard_source_store,
    prune_source_store_root,
    publish_source_snapshot,
    read_current_source,
)
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.sources.model import (
    CurrentSourceRequest,
    SourceInstanceId,
    SourcePublishCommand,
    ValidatedSourceCandidate,
    make_source_candidate,
    source_store_paths,
)
from agent_artifacts.sources.pointer import (
    CurrentPointer,
    current_pointer_bytes,
    parse_current_pointer,
)


def _candidate(content: bytes = b"content"):
    path = parse_relative_path("nested/file.txt")
    directory = parse_relative_path("nested")
    assert isinstance(path, Ok)
    assert isinstance(directory, Ok)
    snapshot = SourceSnapshot(
        SnapshotOrigin.LOCAL,
        (
            SnapshotEntry(directory.value, SnapshotEntryKind.DIRECTORY),
            SnapshotEntry(path.value, SnapshotEntryKind.FILE, content, executable=True),
        ),
    )
    initial = make_source_candidate(
        SourceInstanceId("local-" + "a" * 32),
        SourceAlias("local"),
        "temporary",
        snapshot,
    )
    assert isinstance(initial, Ok)
    result = make_source_candidate(
        initial.value.instance_id,
        initial.value.alias,
        f"local:{initial.value.snapshot_digest.value}",
        snapshot,
    )
    assert isinstance(result, Ok)
    return result.value


class SourceStoreAdapterTest(unittest.TestCase):
    def test_publish_is_atomic_private_and_round_trips_current_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = source_store_paths(root, SourceInstanceId("local-" + "a" * 32))
            validated = ValidatedSourceCandidate(_candidate(), SourceId("fixture-source"))
            command = SourcePublishCommand(paths, validated, 100)

            published = publish_source_snapshot(command)
            loaded = read_current_source(CurrentSourceRequest(paths, SourceAlias("renamed")))

            self.assertIsInstance(published, Ok)
            self.assertIsInstance(loaded, Ok)
            assert isinstance(published, Ok)
            assert isinstance(loaded, Ok)
            self.assertIsNotNone(loaded.value)
            assert loaded.value is not None
            self.assertEqual(loaded.value.candidate.alias, SourceAlias("renamed"))
            self.assertEqual(
                loaded.value.candidate.snapshot_digest, validated.candidate.snapshot_digest
            )
            self.assertEqual(loaded.value.declared_source_id, SourceId("fixture-source"))
            self.assertEqual(os.stat(paths.current_file).st_mode & 0o777, 0o600)
            payload = Path(loaded.value.snapshot_root) / "nested" / "file.txt"
            self.assertEqual(payload.read_bytes(), b"content")
            self.assertEqual(os.stat(payload).st_mode & 0o111, 0o100)
            self.assertEqual(tuple(Path(paths.snapshots).glob(".stage-*")), ())

    def test_concurrent_identical_publications_converge_on_one_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = source_store_paths(root, SourceInstanceId("local-" + "a" * 32))
            command = SourcePublishCommand(
                paths,
                ValidatedSourceCandidate(_candidate(), SourceId("fixture-source")),
                100,
            )
            results = []

            def publish() -> None:
                results.append(publish_source_snapshot(command))

            threads = [threading.Thread(target=publish) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertTrue(all(isinstance(result, Ok) for result in results), results)
            snapshots = tuple(
                path for path in Path(paths.snapshots).iterdir() if not path.name.startswith(".")
            )
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(tuple(Path(paths.snapshots).glob(".stage-*")), ())

    def test_pointer_replace_failure_preserves_previous_current(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = source_store_paths(root, SourceInstanceId("local-" + "a" * 32))
            first = SourcePublishCommand(
                paths,
                ValidatedSourceCandidate(_candidate(b"old"), SourceId("fixture-source")),
                100,
            )
            second = SourcePublishCommand(
                paths,
                ValidatedSourceCandidate(_candidate(b"new"), SourceId("fixture-source")),
                200,
            )
            self.assertIsInstance(publish_source_snapshot(first), Ok)

            with patch(
                "agent_artifacts.io.source_store.os.replace",
                side_effect=OSError("replace failed token=secret"),
            ):
                failed = publish_source_snapshot(second)

            self.assertIsInstance(failed, Err)
            assert isinstance(failed, Err)
            self.assertNotIn("secret", failed.diagnostics[0].message)
            loaded = read_current_source(CurrentSourceRequest(paths, SourceAlias("local")))
            self.assertIsInstance(loaded, Ok)
            assert isinstance(loaded, Ok)
            assert loaded.value is not None
            self.assertEqual(loaded.value.candidate.snapshot.entries[-1].content, b"old")

    def test_corrupt_convergent_snapshot_never_replaces_last_known_good(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = source_store_paths(root, SourceInstanceId("local-" + "a" * 32))
            old = SourcePublishCommand(
                paths,
                ValidatedSourceCandidate(_candidate(b"old"), SourceId("fixture-source")),
                100,
            )
            new = SourcePublishCommand(
                paths,
                ValidatedSourceCandidate(_candidate(b"new"), SourceId("fixture-source")),
                200,
            )
            self.assertIsInstance(publish_source_snapshot(old), Ok)
            corrupt = (
                Path(paths.snapshots)
                / new.validated.candidate.snapshot_digest.value
                / "source"
                / "nested"
            )
            corrupt.mkdir(parents=True)
            (corrupt / "file.txt").write_bytes(b"not-the-validated-content")

            failed = publish_source_snapshot(new)

            self.assertIsInstance(failed, Err)
            loaded = read_current_source(CurrentSourceRequest(paths, SourceAlias("local")))
            self.assertIsInstance(loaded, Ok)
            assert isinstance(loaded, Ok)
            assert loaded.value is not None
            self.assertEqual(loaded.value.candidate.snapshot.entries[-1].content, b"old")

    def test_symlink_cannot_impersonate_a_convergent_snapshot_directory(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            candidate = _candidate()
            external_paths = source_store_paths(
                str(Path(root) / "external"), SourceInstanceId("local-" + "a" * 32)
            )
            command = SourcePublishCommand(
                external_paths,
                ValidatedSourceCandidate(candidate, SourceId("fixture-source")),
                100,
            )
            self.assertIsInstance(publish_source_snapshot(command), Ok)
            external_snapshot = Path(external_paths.snapshots) / candidate.snapshot_digest.value

            paths = source_store_paths(
                str(Path(root) / "managed"), SourceInstanceId("local-" + "a" * 32)
            )
            Path(paths.snapshots).mkdir(parents=True)
            target = Path(paths.snapshots) / candidate.snapshot_digest.value
            target.symlink_to(external_snapshot, target_is_directory=True)

            result = publish_source_snapshot(
                SourcePublishCommand(
                    paths,
                    ValidatedSourceCandidate(candidate, SourceId("fixture-source")),
                    200,
                )
            )

            self.assertIsInstance(result, Err)
            self.assertFalse(Path(paths.current_file).exists())

    def test_candidate_cannot_publish_under_another_source_instance(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = source_store_paths(root, SourceInstanceId("local-" + "b" * 32))
            result = publish_source_snapshot(
                SourcePublishCommand(
                    paths,
                    ValidatedSourceCandidate(_candidate(), SourceId("fixture-source")),
                    100,
                )
            )

            self.assertIsInstance(result, Err)
            self.assertFalse(Path(paths.root).exists())

    def test_missing_and_corrupt_current_are_distinct_typed_results(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = source_store_paths(root, SourceInstanceId("local-" + "a" * 32))
            request = CurrentSourceRequest(paths, SourceAlias("local"))
            self.assertEqual(read_current_source(request), Ok(None))

            Path(paths.root).mkdir(parents=True)
            Path(paths.current_file).write_bytes(b'{"token":"secret",broken')
            corrupt = read_current_source(request)
            self.assertIsInstance(corrupt, Err)
            assert isinstance(corrupt, Err)
            self.assertNotIn("secret", repr(corrupt.diagnostics))

    def test_wrong_instance_missing_snapshot_and_unreadable_pointer_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = source_store_paths(root, SourceInstanceId("local-" + "a" * 32))
            command = SourcePublishCommand(
                paths,
                ValidatedSourceCandidate(_candidate(), SourceId("fixture-source")),
                100,
            )
            published = publish_source_snapshot(command)
            self.assertIsInstance(published, Ok)
            encoded = Path(paths.current_file).read_bytes()
            pointer = parse_current_pointer(encoded)
            assert isinstance(pointer, Ok)
            wrong = CurrentPointer(
                SourceInstanceId("local-" + "b" * 32),
                pointer.value.resolved_revision,
                pointer.value.snapshot_digest,
                pointer.value.declared_source_id,
                pointer.value.origin,
                pointer.value.published_at_epoch_seconds,
            )
            Path(paths.current_file).write_bytes(current_pointer_bytes(wrong))
            request = CurrentSourceRequest(paths, SourceAlias("local"))
            self.assertIsInstance(read_current_source(request), Err)

            Path(paths.current_file).write_bytes(encoded)
            snapshot_root = Path(paths.snapshots) / pointer.value.snapshot_digest.value / "source"
            os.rename(snapshot_root, snapshot_root.with_name("missing"))
            self.assertIsInstance(read_current_source(request), Err)

            with patch(
                "agent_artifacts.io.source_store.Path.read_bytes",
                side_effect=PermissionError("token=secret"),
            ):
                unreadable = read_current_source(request)
            self.assertIsInstance(unreadable, Err)
            assert isinstance(unreadable, Err)
            self.assertNotIn("secret", repr(unreadable.diagnostics))


class SourceStoreDiscardTest(unittest.TestCase):
    """Ending a subscription must leave nothing behind that could bind the origin again."""

    def _published(self, root: str):
        paths = source_store_paths(root, SourceInstanceId("local-" + "a" * 32))
        command = SourcePublishCommand(
            paths,
            ValidatedSourceCandidate(_candidate(), SourceId("fixture-source")),
            100,
        )
        published = publish_source_snapshot(command)
        assert isinstance(published, Ok), published
        return paths

    def test_discard_removes_pointer_and_snapshots_and_reports_that_it_existed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = self._published(root)

            discarded = discard_source_store(paths)

            self.assertIsInstance(discarded, Ok)
            assert isinstance(discarded, Ok)
            self.assertTrue(discarded.value)
            self.assertFalse(Path(paths.current_file).exists())
            self.assertFalse(Path(paths.snapshots).exists())
            loaded = read_current_source(CurrentSourceRequest(paths, SourceAlias("local")))
            self.assertIsInstance(loaded, Ok)
            assert isinstance(loaded, Ok)
            self.assertIsNone(loaded.value)

    def test_discarding_an_absent_store_is_a_success_that_removed_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = source_store_paths(root, SourceInstanceId("local-" + "c" * 32))

            discarded = discard_source_store(paths)

            self.assertIsInstance(discarded, Ok)
            assert isinstance(discarded, Ok)
            self.assertFalse(discarded.value)

    def test_discard_keeps_the_lock_directory_it_is_running_under(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = self._published(root)
            lock = Path(paths.lock_directory)
            lock.mkdir(parents=True, exist_ok=True)

            discarded = discard_source_store(paths)

            self.assertIsInstance(discarded, Ok)
            self.assertTrue(lock.is_dir())
            # The root is still occupied by the live lock, so pruning must decline silently.
            prune_source_store_root(paths)
            self.assertTrue(Path(paths.root).is_dir())

    def test_pruning_removes_the_instance_root_once_nothing_is_left(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = self._published(root)
            self.assertIsInstance(discard_source_store(paths), Ok)

            prune_source_store_root(paths)

            self.assertFalse(Path(paths.root).exists())


if __name__ == "__main__":
    unittest.main()
