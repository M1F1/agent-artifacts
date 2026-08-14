from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.io.source_store import (
    _owner_alive,
    acquire_source_lock,
    release_source_lock,
)
from agent_artifacts.sources.model import SourceLockLease, SourceLockRequest


class SourceLockAdapterTest(unittest.TestCase):
    def test_lock_serializes_owners_and_release_checks_token(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            lock = str(Path(root) / "sync.lock")
            request = SourceLockRequest(lock, timeout_seconds=0.01, stale_after_seconds=60)
            first = acquire_source_lock(request, token_factory=lambda: "first")
            self.assertIsInstance(first, Ok)

            busy = acquire_source_lock(
                request,
                token_factory=lambda: "second",
                sleep=lambda _seconds: None,
            )
            self.assertIsInstance(busy, Err)
            self.assertTrue(Path(lock).is_dir())

            wrong = release_source_lock(SourceLockLease(lock, "wrong"))
            self.assertIsInstance(wrong, Err)
            self.assertTrue(Path(lock).is_dir())
            assert isinstance(first, Ok)
            self.assertEqual(release_source_lock(first.value), Ok(None))
            self.assertFalse(Path(lock).exists())

    def test_abandoned_stale_owner_is_recovered_without_exposing_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            lock = Path(root) / "sync.lock"
            lock.mkdir()
            (lock / "owner.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "token": "old-secret-token",
                        "hostname": "old-host",
                        "pid": 123,
                        "acquired_at_epoch_seconds": 1,
                    }
                ),
                encoding="utf-8",
            )
            request = SourceLockRequest(str(lock), 0.01, stale_after_seconds=10)

            recovered = acquire_source_lock(
                request,
                token_factory=lambda: "new-token",
                now=lambda: 100.0,
                owner_alive=lambda _host, _pid: False,
                sleep=lambda _seconds: None,
            )

            self.assertIsInstance(recovered, Ok)
            assert isinstance(recovered, Ok)
            self.assertEqual(recovered.value.token, "new-token")
            self.assertNotIn("old-secret-token", repr(recovered))
            self.assertEqual(release_source_lock(recovered.value), Ok(None))

    def test_invalid_owner_token_and_filesystem_failures_are_typed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            lock = Path(root) / "sync.lock"
            request = SourceLockRequest(str(lock), 0.01, stale_after_seconds=10)
            invalid_token = acquire_source_lock(request, token_factory=lambda: "bad\ntoken")
            self.assertIsInstance(invalid_token, Err)

            lock.mkdir()
            (lock / "owner.json").write_text("[]", encoding="utf-8")
            clock = iter((100.0, 101.0))
            busy = acquire_source_lock(
                request,
                token_factory=lambda: "new",
                monotonic=lambda: next(clock),
                sleep=lambda _seconds: None,
            )
            self.assertIsInstance(busy, Err)
            self.assertIsInstance(release_source_lock(SourceLockLease(str(lock), "new")), Err)

        with tempfile.TemporaryDirectory() as root:
            request = SourceLockRequest(str(Path(root) / "sync.lock"), 0.01, 10)
            with patch(
                "agent_artifacts.io.source_store.os.mkdir", side_effect=PermissionError("denied")
            ):
                failed = acquire_source_lock(request, token_factory=lambda: "token")
            self.assertIsInstance(failed, Err)

        with tempfile.TemporaryDirectory() as root:
            lock = str(Path(root) / "sync.lock")
            acquired = acquire_source_lock(
                SourceLockRequest(lock, 0.01, 10), token_factory=lambda: "token"
            )
            assert isinstance(acquired, Ok)
            with patch("agent_artifacts.io.source_store.os.rename", side_effect=OSError("rename")):
                self.assertIsInstance(release_source_lock(acquired.value), Err)

    def test_default_owner_liveness_is_conservative_and_detects_missing_local_pid(self) -> None:
        self.assertTrue(_owner_alive("another-host", 123))
        with patch("agent_artifacts.io.source_store.os.kill", side_effect=ProcessLookupError):
            self.assertFalse(_owner_alive(__import__("socket").gethostname(), 123))
        with patch("agent_artifacts.io.source_store.os.kill", side_effect=PermissionError):
            self.assertTrue(_owner_alive(__import__("socket").gethostname(), 123))

    def _busy(self, lock: Path, *, alive: bool, stale_after: int = 600):
        """Attempt an already-held lock once and return the refusal."""

        clock = iter((100.0, 101.0))
        refused = acquire_source_lock(
            SourceLockRequest(str(lock), 0.01, stale_after_seconds=stale_after),
            token_factory=lambda: "new-token",
            now=lambda: 1000.0,
            monotonic=lambda: next(clock),
            owner_alive=lambda _host, _pid: alive,
            sleep=lambda _seconds: None,
        )
        self.assertIsInstance(refused, Err)
        assert isinstance(refused, Err)
        self.assertEqual(len(refused.diagnostics), 1, refused)
        return refused.diagnostics[0]

    def _held_by(self, root: str, *, pid: int, acquired_at: int) -> Path:
        lock = Path(root) / "sync.lock"
        lock.mkdir()
        (lock / "owner.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "token": "held-secret-token",
                    "hostname": "peer-host",
                    "pid": pid,
                    "acquired_at_epoch_seconds": acquired_at,
                }
            ),
            encoding="utf-8",
        )
        return lock

    def test_a_busy_lock_reports_the_holder_its_age_and_the_stale_window(self) -> None:
        """SI-6: "already running" is not actionable without knowing whether it really is.

        The four facts that decide whether to wait or to retry are the age, the pid, whether that
        pid is alive, and how long a holder must be silent before it is reclaimed.
        """

        with tempfile.TemporaryDirectory() as root:
            lock = self._held_by(root, pid=4321, acquired_at=910)

            refused = self._busy(lock, alive=True)

            self.assertEqual(refused.code.value, "source-lock-busy")
            self.assertIn("held for 90s", refused.message)
            self.assertIn("pid 4321", refused.message)
            self.assertIn("peer-host", refused.message)
            self.assertIn("alive", refused.message)
            self.assertIn("600s", refused.message)
            self.assertTrue(refused.remediation)
            # The holder's identity is reported; the holder's token stays out of it.
            self.assertNotIn("held-secret-token", refused.message)

    def test_a_busy_lock_whose_holder_is_gone_says_so_rather_than_implying_progress(self) -> None:
        """A dead holder inside the stale window still refuses, but must not read as "in progress"."""

        with tempfile.TemporaryDirectory() as root:
            lock = self._held_by(root, pid=4321, acquired_at=910)

            refused = self._busy(lock, alive=False)

            self.assertIn("not running", refused.message)
            self.assertTrue(any("stale window" in line for line in refused.remediation))

    def test_a_busy_lock_without_an_owner_record_says_the_holder_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            lock = Path(root) / "sync.lock"
            lock.mkdir()
            (lock / "owner.json").write_text("[]", encoding="utf-8")

            refused = self._busy(lock, alive=True)

            self.assertIn("did not record who it is", refused.message)
            self.assertTrue(refused.remediation)

    def test_ownerless_lock_left_by_interrupted_acquisition_is_recovered_when_stale(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            lock = Path(root) / "sync.lock"
            lock.mkdir()
            os.utime(lock, (1, 1))
            request = SourceLockRequest(str(lock), 0.01, stale_after_seconds=10)

            recovered = acquire_source_lock(
                request,
                token_factory=lambda: "new-token",
                now=lambda: 100.0,
                sleep=lambda _seconds: None,
            )

            self.assertIsInstance(recovered, Ok)
            assert isinstance(recovered, Ok)
            self.assertEqual(release_source_lock(recovered.value), Ok(None))


if __name__ == "__main__":
    unittest.main()
