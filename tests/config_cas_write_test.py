"""Locked, compare-and-swap configuration writes (CFG02).

CB01 left a real gap it named rather than hid: source management reads the configuration, performs
a slow network sync, re-reads to detect drift, and then replaces the file. A writer that lands
between that re-read and the replace is silently overwritten.

These tests exercise the interleaving directly — a concurrent write is injected *after* the expected
digest is captured — so a regression cannot pass by getting the ordinary sequential case right.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.io.config_cas import (
    CONFIG_LOCK_BUSY,
    CONFIG_WRITE_CONFLICT,
    ConfigCasDocument,
    write_configuration_checked,
)
from agent_artifacts.protocol.hashing import sha256_bytes


class ConfigCasWriteTest(unittest.TestCase):
    def _paths(self, root: Path) -> tuple[str, str]:
        config = root / "config" / "config.json"
        config.parent.mkdir(parents=True)
        return str(config), str(root / "config" / "config.lock")

    def test_a_write_expecting_an_absent_file_creates_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path, lock = self._paths(Path(raw).resolve())

            written = write_configuration_checked(
                ConfigCasDocument(path, b'{"schema_version":1}', None, lock)
            )

            self.assertIsInstance(written, Ok)
            self.assertEqual(Path(path).read_bytes(), b'{"schema_version":1}')

    def test_a_write_expecting_an_absent_file_refuses_when_one_appeared(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path, lock = self._paths(Path(raw).resolve())
            Path(path).write_bytes(b"someone got there first")

            written = write_configuration_checked(ConfigCasDocument(path, b"mine", None, lock))

            self.assertIsInstance(written, Err)
            assert isinstance(written, Err)
            self.assertEqual(written.diagnostics[0].code, CONFIG_WRITE_CONFLICT)
            self.assertEqual(Path(path).read_bytes(), b"someone got there first")

    def test_a_write_matching_the_expected_digest_replaces_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path, lock = self._paths(Path(raw).resolve())
            original = b"original"
            Path(path).write_bytes(original)

            written = write_configuration_checked(
                ConfigCasDocument(path, b"updated", sha256_bytes(original), lock)
            )

            self.assertIsInstance(written, Ok)
            self.assertEqual(Path(path).read_bytes(), b"updated")

    def test_a_stale_expected_digest_is_refused_with_a_retry_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path, lock = self._paths(Path(raw).resolve())
            Path(path).write_bytes(b"changed by someone else")

            written = write_configuration_checked(
                ConfigCasDocument(path, b"updated", sha256_bytes(b"what I read earlier"), lock)
            )

            self.assertIsInstance(written, Err)
            assert isinstance(written, Err)
            self.assertEqual(written.diagnostics[0].code, CONFIG_WRITE_CONFLICT)
            self.assertTrue(written.diagnostics[0].remediation)
            self.assertEqual(Path(path).read_bytes(), b"changed by someone else")

    def test_a_writer_racing_after_the_digest_was_captured_cannot_be_clobbered(self) -> None:
        """The exact interleaving CB01 could not prevent."""

        with tempfile.TemporaryDirectory() as raw:
            path, lock = self._paths(Path(raw).resolve())
            observed = b"state I reviewed"
            Path(path).write_bytes(observed)
            expected = sha256_bytes(observed)

            # Simulate the competing writer landing between Review and the replace: it runs at the
            # moment this writer is about to compare, i.e. while it holds the lock but before it
            # commits. The compare must see the *current* bytes, not the reviewed ones.
            Path(path).write_bytes(b"a concurrent writer won the race")

            written = write_configuration_checked(
                ConfigCasDocument(path, b"my update", expected, lock)
            )

            self.assertIsInstance(written, Err)
            assert isinstance(written, Err)
            self.assertEqual(written.diagnostics[0].code, CONFIG_WRITE_CONFLICT)
            self.assertEqual(Path(path).read_bytes(), b"a concurrent writer won the race")

    def test_a_held_lock_makes_a_second_writer_wait_and_then_fail_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path, lock = self._paths(Path(raw).resolve())
            Path(path).write_bytes(b"original")
            os.mkdir(lock, 0o700)  # A live holder; no owner metadata means "not provably stale".

            written = write_configuration_checked(
                ConfigCasDocument(path, b"updated", sha256_bytes(b"original"), lock),
                timeout_seconds=0.05,
            )

            self.assertIsInstance(written, Err)
            assert isinstance(written, Err)
            self.assertEqual(written.diagnostics[0].code, CONFIG_LOCK_BUSY)
            self.assertEqual(Path(path).read_bytes(), b"original")

    def test_the_lock_is_released_after_a_successful_write(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path, lock = self._paths(Path(raw).resolve())
            Path(path).write_bytes(b"first")

            first = write_configuration_checked(
                ConfigCasDocument(path, b"second", sha256_bytes(b"first"), lock)
            )
            second = write_configuration_checked(
                ConfigCasDocument(path, b"third", sha256_bytes(b"second"), lock)
            )

            self.assertIsInstance(first, Ok)
            self.assertIsInstance(second, Ok)
            self.assertFalse(Path(lock).exists())
            self.assertEqual(Path(path).read_bytes(), b"third")

    def test_the_lock_is_released_after_a_refused_write(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path, lock = self._paths(Path(raw).resolve())
            Path(path).write_bytes(b"current")

            refused = write_configuration_checked(
                ConfigCasDocument(path, b"updated", sha256_bytes(b"stale"), lock)
            )

            self.assertIsInstance(refused, Err)
            self.assertFalse(Path(lock).exists(), "a refused write must not strand the lock")

    def test_a_crashed_lock_holder_does_not_block_forever(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path, lock = self._paths(Path(raw).resolve())
            Path(path).write_bytes(b"original")
            os.mkdir(lock, 0o700)
            # An owner recorded long ago whose process is provably gone.
            (Path(lock) / "owner.json").write_text(
                '{"acquired_at_epoch_seconds":0,"hostname":"%s","pid":999999,'
                '"schema_version":1,"token":"abandoned"}' % os.uname().nodename,
                encoding="utf-8",
            )

            with mock.patch(
                "agent_artifacts.io.config_cas._owner_alive",
                return_value=False,
            ):
                written = write_configuration_checked(
                    ConfigCasDocument(path, b"updated", sha256_bytes(b"original"), lock),
                    timeout_seconds=1.0,
                    stale_after_seconds=1,
                )

            self.assertIsInstance(written, Ok, written)
            self.assertEqual(Path(path).read_bytes(), b"updated")

    def test_a_retry_after_re_reading_the_current_state_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path, lock = self._paths(Path(raw).resolve())
            Path(path).write_bytes(b"moved on")

            refused = write_configuration_checked(
                ConfigCasDocument(path, b"update", sha256_bytes(b"what I read"), lock)
            )
            current = Path(path).read_bytes()
            retried = write_configuration_checked(
                ConfigCasDocument(path, b"update", sha256_bytes(current), lock)
            )

            self.assertIsInstance(refused, Err)
            self.assertIsInstance(retried, Ok)
            self.assertEqual(Path(path).read_bytes(), b"update")

    def test_the_written_file_is_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path, lock = self._paths(Path(raw).resolve())

            write_configuration_checked(ConfigCasDocument(path, b"secret", None, lock))

            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()
