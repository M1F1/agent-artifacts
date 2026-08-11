from __future__ import annotations

import unittest

from agent_artifacts.configuration.model import ConfiguredSource, SourceKind
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest, SourceAlias, SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.sources.model import (
    CurrentSource,
    GitSnapshotRequest,
    HealthStatus,
    LocalSnapshotRequest,
    SnapshotLimits,
    SourceCandidate,
    SourceInstanceId,
    SourceLockLease,
    SourceLockRequest,
    SourcePublishCommand,
    SourceStorePaths,
    ValidatedSourceCandidate,
    assess_source_health,
    legacy_source_instance_id,
    make_source_candidate,
    source_instance_id,
    source_store_paths,
)


def _path(raw: str):
    parsed = parse_relative_path(raw)
    assert isinstance(parsed, Ok)
    return parsed.value


def _snapshot(content: bytes = b"content") -> SourceSnapshot:
    return SourceSnapshot(
        SnapshotOrigin.LOCAL,
        (
            SnapshotEntry(_path("nested"), SnapshotEntryKind.DIRECTORY),
            SnapshotEntry(_path("nested/file.txt"), SnapshotEntryKind.FILE, content),
        ),
    )


class SourceModelTest(unittest.TestCase):
    def test_instance_identity_uses_origin_and_ref_but_not_alias(self) -> None:
        first = ConfiguredSource(
            SourceAlias("first"),
            SourceKind.SOURCE_GIT,
            "https://example.test/team/repo.git",
            "main",
            True,
        )
        renamed = ConfiguredSource(
            SourceAlias("renamed"),
            SourceKind.SOURCE_GIT,
            "https://example.test/team/repo.git",
            "release",
            True,
        )
        registry = ConfiguredSource(
            SourceAlias("registry"),
            SourceKind.REGISTRY_GIT,
            "https://example.test/team/repo.git",
            "main",
            True,
        )

        # SRC02: the alias is still not part of the identity, but the ref now is — two refs of one
        # origin must own separate mirrors and pointers rather than retargeting each other.
        self.assertNotEqual(source_instance_id(first), source_instance_id(renamed))
        self.assertEqual(legacy_source_instance_id(first), legacy_source_instance_id(renamed))
        self.assertNotEqual(source_instance_id(first), source_instance_id(registry))
        self.assertRegex(source_instance_id(first).value, r"^git-[0-9a-f]{32}$")

        aliased = ConfiguredSource(
            SourceAlias("different-alias"),
            SourceKind.SOURCE_GIT,
            "https://example.test/team/repo.git",
            "main",
            True,
        )
        self.assertEqual(source_instance_id(first), source_instance_id(aliased))

    def test_store_paths_are_pure_normalized_and_scoped_by_instance(self) -> None:
        source = ConfiguredSource(
            SourceAlias("local"), SourceKind.SOURCE_LOCAL, "/work/source", None, True
        )
        paths = source_store_paths("/test/data", source_instance_id(source))

        self.assertEqual(paths.root, f"/test/data/sources/{source_instance_id(source).value}")
        self.assertEqual(paths.mirror, f"{paths.root}/mirror.git")
        self.assertEqual(paths.snapshots, f"{paths.root}/snapshots")
        self.assertEqual(paths.current_file, f"{paths.root}/current.json")
        self.assertEqual(paths.lock_directory, f"{paths.root}/sync.lock")
        with self.assertRaises(ValueError):
            source_store_paths("relative", source_instance_id(source))

    def test_candidate_digest_is_content_bound_origin_independent_and_sorted(self) -> None:
        instance = source_instance_id(
            ConfiguredSource(
                SourceAlias("local"), SourceKind.SOURCE_LOCAL, "/work/source", None, True
            )
        )
        local = make_source_candidate(instance, SourceAlias("local"), "local", _snapshot())
        git_snapshot = SourceSnapshot(
            SnapshotOrigin.IMMUTABLE_GIT,
            tuple(reversed(_snapshot().entries)),
        )
        git = make_source_candidate(instance, SourceAlias("local"), "a" * 40, git_snapshot)
        changed = make_source_candidate(
            instance,
            SourceAlias("local"),
            "local",
            _snapshot(b"changed"),
        )

        self.assertIsInstance(local, Ok)
        self.assertIsInstance(git, Ok)
        self.assertIsInstance(changed, Ok)
        assert isinstance(local, Ok)
        assert isinstance(git, Ok)
        assert isinstance(changed, Ok)
        self.assertEqual(local.value.snapshot_digest, git.value.snapshot_digest)
        self.assertNotEqual(local.value.snapshot_digest, changed.value.snapshot_digest)

    def test_health_distinguishes_missing_fresh_stale_and_degraded(self) -> None:
        instance = source_instance_id(
            ConfiguredSource(
                SourceAlias("local"), SourceKind.SOURCE_LOCAL, "/work/source", None, True
            )
        )
        candidate = make_source_candidate(instance, SourceAlias("local"), "local", _snapshot())
        assert isinstance(candidate, Ok)
        current = CurrentSource(
            candidate.value,
            SourceId("fixture-source"),
            published_at_epoch_seconds=100,
            snapshot_root="/test/snapshot",
        )
        warning = Diagnostic(DiagnosticCode("source-unavailable"), Severity.WARNING, "offline")

        self.assertIs(
            assess_source_health(None, now=120, max_age_seconds=30).status, HealthStatus.MISSING
        )
        self.assertIs(
            assess_source_health(current, now=120, max_age_seconds=30).status,
            HealthStatus.HEALTHY,
        )
        self.assertIs(
            assess_source_health(current, now=131, max_age_seconds=30).status,
            HealthStatus.STALE,
        )
        self.assertIs(
            assess_source_health(
                current,
                now=120,
                max_age_seconds=30,
                diagnostics=(warning,),
            ).status,
            HealthStatus.DEGRADED,
        )
        with self.assertRaises(ValueError):
            SnapshotLimits(max_files=0)
        with self.assertRaises(ValueError):
            SnapshotLimits(max_total_bytes=101 * 1024 * 1024)

    def test_unsafe_snapshot_shapes_fail_before_candidate_construction(self) -> None:
        path = _path("file.txt")
        invalid = (
            SourceSnapshot("invalid", ()),  # type: ignore[arg-type]
            SourceSnapshot(
                SnapshotOrigin.LOCAL,
                (
                    SnapshotEntry(path, SnapshotEntryKind.FILE, b"one"),
                    SnapshotEntry(path, SnapshotEntryKind.FILE, b"two"),
                ),
            ),
            SourceSnapshot(
                SnapshotOrigin.LOCAL,
                (SnapshotEntry(path, SnapshotEntryKind.DIRECTORY, b"metadata"),),
            ),
            SourceSnapshot(
                SnapshotOrigin.LOCAL,
                (SnapshotEntry(path, SnapshotEntryKind.SYMLINK),),
            ),
            SourceSnapshot(
                SnapshotOrigin.LOCAL,
                (SnapshotEntry(path, SnapshotEntryKind.FILE, "not-bytes"),),  # type: ignore[arg-type]
            ),
        )
        instance = SourceInstanceId("local-" + "f" * 32)
        for snapshot in invalid:
            with self.subTest(snapshot=snapshot):
                self.assertIsInstance(
                    make_source_candidate(instance, SourceAlias("local"), "revision", snapshot),
                    Err,
                )

    def test_frozen_source_values_reject_invalid_identity_time_and_paths(self) -> None:
        valid_candidate = make_source_candidate(
            SourceInstanceId("local-" + "e" * 32),
            SourceAlias("local"),
            "revision",
            _snapshot(),
        )
        assert isinstance(valid_candidate, Ok)
        candidate = valid_candidate.value
        invalid_constructors = (
            lambda: SourceInstanceId("bad"),
            lambda: SourceStorePaths("relative", "/m", "/s", "/c", "/l", "/t"),
            lambda: SourceCandidate(
                candidate.instance_id,
                candidate.alias,
                "bad\nrevision",
                candidate.snapshot_digest,
                candidate.snapshot,
            ),
            lambda: SourceCandidate(
                candidate.instance_id,
                candidate.alias,
                "revision",
                ObjectDigest("sha1", "a" * 64),
                candidate.snapshot,
            ),
            lambda: SourceCandidate(
                candidate.instance_id,
                candidate.alias,
                "revision",
                ObjectDigest("sha256", "a" * 64),
                candidate.snapshot,
            ),
            lambda: ValidatedSourceCandidate(candidate, SourceId("")),
            lambda: CurrentSource(candidate, SourceId(""), 0, "/snapshot"),
            lambda: CurrentSource(candidate, SourceId("id"), -1, "/snapshot"),
            lambda: CurrentSource(candidate, SourceId("id"), 0, "relative"),
            lambda: LocalSnapshotRequest(
                candidate.instance_id, SourceAlias("local"), "relative", SnapshotLimits()
            ),
            lambda: GitSnapshotRequest(
                candidate.instance_id,
                SourceAlias("git"),
                "https://example.test/repo.git",
                "bad\nref",
                "/mirror",
                "/tmp",
                SnapshotLimits(),
                30,
            ),
            lambda: GitSnapshotRequest(
                candidate.instance_id,
                SourceAlias("git"),
                "https://example.test/repo.git",
                "main",
                "relative",
                "/tmp",
                SnapshotLimits(),
                30,
            ),
            lambda: GitSnapshotRequest(
                candidate.instance_id,
                SourceAlias("git"),
                "https://example.test/repo.git",
                "main",
                "/mirror",
                "/tmp",
                SnapshotLimits(),
                0,
            ),
            lambda: SourcePublishCommand(
                source_store_paths("/managed", candidate.instance_id),
                ValidatedSourceCandidate(candidate, SourceId("id")),
                -1,
            ),
            lambda: SourceLockRequest("relative", 1, 1),
            lambda: SourceLockRequest("/lock", 0, 1),
            lambda: SourceLockLease("relative", "token"),
        )
        for constructor in invalid_constructors:
            with self.subTest(constructor=constructor), self.assertRaises(ValueError):
                constructor()

        self.assertIsInstance(
            make_source_candidate(
                candidate.instance_id,
                candidate.alias,
                "bad\nrevision",
                candidate.snapshot,
            ),
            Err,
        )
        with self.assertRaises(ValueError):
            assess_source_health(None, now=-1, max_age_seconds=1)


if __name__ == "__main__":
    unittest.main()
