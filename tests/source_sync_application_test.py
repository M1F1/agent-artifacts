from __future__ import annotations

import unittest
from dataclasses import replace

from agent_artifacts.application.sources import (
    SourceStatusRequest,
    SourceSyncPorts,
    SourceSyncRequest,
    sync_source,
)
from agent_artifacts.configuration.model import ConfiguredSource, SourceKind
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import SourceAlias, SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.capabilities import parse_capability
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.protocol.semver import parse_semver
from agent_artifacts.sources.model import (
    CurrentSource,
    CurrentSourceRequest,
    SourceLockLease,
    SourcePublishReceipt,
    SyncDisposition,
    SyncFallback,
    ValidatedSourceCandidate,
    make_source_candidate,
    source_instance_id,
    source_store_paths,
)


def _unwrap(result):
    assert isinstance(result, Ok), result
    return result.value


def _candidate(source: ConfiguredSource, content: bytes = b"content"):
    snapshot = SourceSnapshot(
        SnapshotOrigin.LOCAL
        if source.kind is SourceKind.SOURCE_LOCAL
        else SnapshotOrigin.IMMUTABLE_GIT,
        (
            SnapshotEntry(
                _unwrap(parse_relative_path("file.txt")),
                SnapshotEntryKind.FILE,
                content,
            ),
        ),
    )
    return _unwrap(
        make_source_candidate(
            source_instance_id(source),
            source.alias,
            "local" if source.kind is SourceKind.SOURCE_LOCAL else "a" * 40,
            snapshot,
        )
    )


def _current(candidate, *, source_id: str = "fixture-source") -> CurrentSource:
    return CurrentSource(candidate, SourceId(source_id), 90, "/managed/snapshot")


def _failure(code: str = "source-unavailable") -> Err:
    return Err((Diagnostic(DiagnosticCode(code), Severity.ERROR, "sync failed token=secret"),))


class _FakePorts:
    def __init__(self, candidate, current=None):
        self.candidate_result = Ok(candidate)
        self.current_result = Ok(current)
        self.validation_result = Ok(ValidatedSourceCandidate(candidate, SourceId("fixture-source")))
        self.events: list[str] = []
        self.publishes = []

    def acquire_lock(self, request):
        self.events.append("lock")
        return Ok(SourceLockLease(request.lock_directory, "lease-token"))

    def release_lock(self, _lease):
        self.events.append("release")
        return Ok(None)

    def read_current(self, _request):
        self.events.append("current")
        return self.current_result

    def acquire_local(self, _request):
        self.events.append("local")
        return self.candidate_result

    def acquire_git(self, _request):
        self.events.append("git")
        return self.candidate_result

    def validate(self, _request):
        self.events.append("validate")
        return self.validation_result

    def publish(self, command):
        self.events.append("publish")
        self.publishes.append(command)
        current = CurrentSource(
            command.validated.candidate,
            command.validated.declared_source_id,
            command.observed_at_epoch_seconds,
            f"{command.paths.snapshots}/published/source",
        )
        return Ok(SourcePublishReceipt(current, created=True))

    def ports(self):
        return SourceSyncPorts(
            self.acquire_lock,
            self.release_lock,
            self.read_current,
            self.acquire_local,
            self.acquire_git,
            self.validate,
            self.publish,
        )


def _request(source: ConfiguredSource, *, fallback=SyncFallback.REQUIRE_FRESH, offline=False):
    return SourceSyncRequest(
        source=source,
        data_root="/managed/data",
        executable_version=_unwrap(parse_semver("1.0.0")),
        available_capabilities=(_unwrap(parse_capability("artifact-manifest-v1")),),
        observed_at_epoch_seconds=100,
        fallback=fallback,
        offline=offline,
        timeout_seconds=30,
    )


class SourceSyncApplicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.local = ConfiguredSource(
            SourceAlias("local"), SourceKind.SOURCE_LOCAL, "/work/source", None, True
        )
        self.git = ConfiguredSource(
            SourceAlias("git"),
            SourceKind.SOURCE_GIT,
            "https://example.test/team/repo.git",
            "main",
            True,
        )

    def test_local_and_git_candidates_validate_before_atomic_publish(self) -> None:
        for source, acquisition_event in ((self.local, "local"), (self.git, "git")):
            with self.subTest(source=source):
                candidate = _candidate(source)
                fake = _FakePorts(candidate)

                result = sync_source(_request(source), fake.ports())

                self.assertIsInstance(result, Ok)
                assert isinstance(result, Ok)
                self.assertIs(result.value.disposition, SyncDisposition.PUBLISHED)
                self.assertEqual(
                    fake.events,
                    ["lock", "current", acquisition_event, "validate", "publish", "release"],
                )
                self.assertEqual(len(fake.publishes), 1)

    def test_fetch_or_validation_failure_can_explicitly_use_last_known_good(self) -> None:
        candidate = _candidate(self.git, b"new")
        prior = _current(_candidate(self.git, b"old"))
        for failure_at in ("acquire", "validate"):
            with self.subTest(failure_at=failure_at):
                fake = _FakePorts(candidate, prior)
                if failure_at == "acquire":
                    fake.candidate_result = _failure()
                else:
                    fake.validation_result = _failure("source-invalid")

                result = sync_source(
                    _request(self.git, fallback=SyncFallback.ALLOW_LAST_KNOWN_GOOD),
                    fake.ports(),
                )

                self.assertIsInstance(result, Ok)
                assert isinstance(result, Ok)
                self.assertIs(result.value.disposition, SyncDisposition.RETAINED)
                self.assertEqual(result.value.current, prior)
                self.assertTrue(result.value.diagnostics)
                self.assertTrue(
                    all(item.severity is Severity.WARNING for item in result.value.diagnostics)
                )
                self.assertNotIn("secret", repr(result.value.diagnostics))
                self.assertNotIn("publish", fake.events)
                self.assertEqual(fake.events[-1], "release")

    def test_required_fresh_or_missing_cache_returns_error_without_publication(self) -> None:
        candidate = _candidate(self.git)
        cases = (
            (_current(candidate), SyncFallback.REQUIRE_FRESH),
            (None, SyncFallback.ALLOW_LAST_KNOWN_GOOD),
        )
        for current, fallback in cases:
            with self.subTest(current=current, fallback=fallback):
                fake = _FakePorts(candidate, current)
                fake.candidate_result = _failure()

                result = sync_source(_request(self.git, fallback=fallback), fake.ports())

                self.assertIsInstance(result, Err)
                self.assertNotIn("publish", fake.events)
                self.assertEqual(fake.events[-1], "release")

    def test_offline_mode_never_calls_git_and_requires_a_cached_snapshot(self) -> None:
        candidate = _candidate(self.git)
        cached = _current(candidate)
        fake = _FakePorts(candidate, cached)

        result = sync_source(
            _request(
                self.git,
                fallback=SyncFallback.ALLOW_LAST_KNOWN_GOOD,
                offline=True,
            ),
            fake.ports(),
        )

        self.assertIsInstance(result, Ok)
        assert isinstance(result, Ok)
        self.assertIs(result.value.disposition, SyncDisposition.RETAINED)
        self.assertEqual(fake.events, ["lock", "current", "release"])

        missing = _FakePorts(candidate)
        self.assertIsInstance(
            sync_source(
                _request(
                    self.git,
                    fallback=SyncFallback.ALLOW_LAST_KNOWN_GOOD,
                    offline=True,
                ),
                missing.ports(),
            ),
            Err,
        )

    def test_declared_source_identity_change_is_rejected_and_lock_is_always_released(self) -> None:
        candidate = _candidate(self.git, b"new")
        fake = _FakePorts(candidate, _current(_candidate(self.git, b"old"), source_id="old-id"))

        result = sync_source(_request(self.git), fake.ports())

        self.assertIsInstance(result, Err)
        assert isinstance(result, Err)
        self.assertEqual(result.diagnostics[0].code.value, "source-invalid")
        self.assertNotIn("publish", fake.events)
        self.assertEqual(fake.events[-1], "release")

    def test_invalid_validator_and_publication_receipts_fail_closed(self) -> None:
        candidate = _candidate(self.git, b"expected")
        other = _candidate(self.git, b"other")

        invalid_validation = _FakePorts(candidate)
        invalid_validation.validation_result = Ok(
            ValidatedSourceCandidate(other, SourceId("fixture-source"))
        )
        validated = sync_source(_request(self.git), invalid_validation.ports())
        self.assertIsInstance(validated, Err)
        self.assertNotIn("publish", invalid_validation.events)

        invalid_publication = _FakePorts(candidate)

        def wrong_receipt(command):
            invalid_publication.events.append("publish")
            return Ok(SourcePublishReceipt(_current(other), created=True))

        invalid_publication.publish = wrong_receipt
        published = sync_source(_request(self.git), invalid_publication.ports())
        self.assertIsInstance(published, Err)

    def test_unchanged_publish_failure_and_current_read_failure_are_explicit(self) -> None:
        candidate = _candidate(self.git)
        unchanged = _FakePorts(candidate, _current(candidate))
        result = sync_source(_request(self.git), unchanged.ports())
        self.assertIsInstance(result, Ok)
        assert isinstance(result, Ok)
        self.assertIs(result.value.disposition, SyncDisposition.UNCHANGED)

        publish_failure = _FakePorts(candidate, _current(candidate))

        def fail_publish(_command):
            publish_failure.events.append("publish")
            return _failure()

        publish_failure.publish = fail_publish
        retained = sync_source(
            _request(self.git, fallback=SyncFallback.ALLOW_LAST_KNOWN_GOOD),
            publish_failure.ports(),
        )
        self.assertIsInstance(retained, Ok)
        assert isinstance(retained, Ok)
        self.assertIs(retained.value.disposition, SyncDisposition.RETAINED)

        current_failure = _FakePorts(candidate)
        current_failure.current_result = _failure("source-invalid")
        self.assertIsInstance(sync_source(_request(self.git), current_failure.ports()), Err)
        self.assertEqual(current_failure.events, ["lock", "current", "release"])

    def test_disabled_lock_and_release_failures_have_deterministic_precedence(self) -> None:
        candidate = _candidate(self.git)
        disabled = replace(self.git, enabled=False)
        disabled_ports = _FakePorts(candidate)
        self.assertIsInstance(sync_source(_request(disabled), disabled_ports.ports()), Err)
        self.assertEqual(disabled_ports.events, [])

        lock_failure = _FakePorts(candidate)

        def fail_lock(_request):
            lock_failure.events.append("lock")
            return _failure("source-lock-busy")

        lock_failure.acquire_lock = fail_lock
        self.assertIsInstance(sync_source(_request(self.git), lock_failure.ports()), Err)
        self.assertEqual(lock_failure.events, ["lock"])

        release_after_success = _FakePorts(candidate)

        def fail_release(_lease):
            release_after_success.events.append("release")
            return _failure("source-unavailable")

        release_after_success.release_lock = fail_release
        self.assertIsInstance(sync_source(_request(self.git), release_after_success.ports()), Err)

        release_after_failure = _FakePorts(candidate)
        release_after_failure.candidate_result = _failure("acquire-failed")
        release_after_failure.release_lock = fail_release
        combined = sync_source(_request(self.git), release_after_failure.ports())
        self.assertIsInstance(combined, Err)
        assert isinstance(combined, Err)
        self.assertEqual(len(combined.diagnostics), 2)

    def test_sync_and_status_requests_validate_their_bounds(self) -> None:
        valid = _request(self.git)
        for changes in (
            {"data_root": "relative"},
            {"observed_at_epoch_seconds": -1},
            {"fallback": "invalid"},
            {"offline": 1},
            {"timeout_seconds": 0},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(valid, **changes)  # type: ignore[arg-type]
        paths = source_store_paths("/managed", source_instance_id(self.local))
        with self.assertRaises(ValueError):
            SourceStatusRequest(
                CurrentSourceRequest(paths, self.local.alias),
                now_epoch_seconds=-1,
                max_age_seconds=10,
            )


if __name__ == "__main__":
    unittest.main()
