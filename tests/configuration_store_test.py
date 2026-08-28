from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_artifacts.application.configuration import (
    ConfigDocument,
    ConfigReadRequest,
    ConfigRecoveryPlan,
)
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.io.config_store import (
    read_configuration,
    recover_configuration,
    write_configuration,
)
from agent_artifacts.protocol.hashing import sha256_bytes
from tests.credential_fixtures import assignment, secret_object


class ConfigurationStoreTest(unittest.TestCase):
    def test_missing_read_and_atomic_private_write(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = str(Path(root) / "nested" / "config.json")

            self.assertEqual(read_configuration(ConfigReadRequest(path)), Ok(None))
            result = write_configuration(ConfigDocument(path, b'{"schema_version":1}\n'))

            self.assertIsInstance(result, Ok)
            self.assertEqual(Path(path).read_bytes(), b'{"schema_version":1}\n')
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(tuple(Path(path).parent.glob(".aart-config-*")), ())

    def test_replace_failure_preserves_existing_document_and_cleans_stage(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "config.json"
            path.write_bytes(b"old")

            with patch(
                "agent_artifacts.io.config_store.os.replace",
                side_effect=OSError("replace failed " + assignment("token", "secret")),
            ):
                result = write_configuration(ConfigDocument(str(path), b"new"))

            self.assertIsInstance(result, Err)
            assert isinstance(result, Err)
            self.assertEqual(path.read_bytes(), b"old")
            self.assertEqual(tuple(path.parent.glob(".aart-config-*")), ())
            self.assertNotIn("secret", result.diagnostics[0].message)

    def test_recovery_backs_up_exact_corrupt_bytes_and_writes_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "config.json"
            backup = Path(root) / "config.json.corrupt"
            corrupt = secret_object("password", "do-not-log", trailing=",broken")
            replacement = b'{"schema_version":1}\n'
            path.write_bytes(corrupt)
            plan = ConfigRecoveryPlan(
                str(path),
                str(backup),
                sha256_bytes(corrupt),
                replacement,
            )

            result = recover_configuration(plan)

            self.assertIsInstance(result, Ok)
            self.assertEqual(backup.read_bytes(), corrupt)
            self.assertEqual(path.read_bytes(), replacement)
            assert isinstance(result, Ok)
            self.assertEqual(result.value.original_digest, sha256_bytes(corrupt))
            self.assertEqual(result.value.replacement_digest, sha256_bytes(replacement))

    def test_io_errors_are_typed_and_recovery_preconditions_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "directory"
            directory.mkdir()
            read = read_configuration(ConfigReadRequest(str(directory)))
            self.assertIsInstance(read, Err)

            blocker = Path(root) / "blocker"
            blocker.write_bytes(b"file")
            written = write_configuration(ConfigDocument(str(blocker / "config.json"), b"new"))
            self.assertIsInstance(written, Err)

            missing = recover_configuration(
                ConfigRecoveryPlan(
                    str(Path(root) / "missing.json"),
                    str(Path(root) / "backup.json"),
                    sha256_bytes(b"missing"),
                    b"replacement",
                )
            )
            self.assertIsInstance(missing, Err)

            path = Path(root) / "config.json"
            path.write_bytes(b"changed")
            stale = recover_configuration(
                ConfigRecoveryPlan(
                    str(path),
                    str(Path(root) / "backup.json"),
                    sha256_bytes(b"old"),
                    b"replacement",
                )
            )
            self.assertIsInstance(stale, Err)

    def test_recovery_reuses_matching_backup_and_rejects_other_backup(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "config.json"
            backup = Path(root) / "backup.json"
            current = b"corrupt"
            path.write_bytes(current)
            backup.write_bytes(current)
            plan = ConfigRecoveryPlan(
                str(path),
                str(backup),
                sha256_bytes(current),
                b'{"schema_version":1}\n',
            )

            self.assertIsInstance(recover_configuration(plan), Ok)

            path.write_bytes(current)
            backup.write_bytes(b"other")
            self.assertIsInstance(recover_configuration(plan), Err)

    def test_recovery_reports_unreadable_backup_and_write_failures(self) -> None:
        failure = Err(
            (Diagnostic(DiagnosticCode("config-io-failed"), Severity.ERROR, "write failed"),)
        )
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "config.json"
            path.write_bytes(b"corrupt")
            backup_directory = Path(root) / "backup"
            backup_directory.mkdir()
            unreadable = ConfigRecoveryPlan(
                str(path),
                str(backup_directory),
                sha256_bytes(b"corrupt"),
                b"replacement",
            )
            self.assertIsInstance(recover_configuration(unreadable), Err)

            missing_backup = ConfigRecoveryPlan(
                str(path),
                str(Path(root) / "missing-backup"),
                sha256_bytes(b"corrupt"),
                b"replacement",
            )
            with patch("agent_artifacts.io.config_store.write_configuration", return_value=failure):
                self.assertEqual(recover_configuration(missing_backup), failure)

            matching_backup = Path(root) / "matching-backup"
            matching_backup.write_bytes(b"corrupt")
            replacement_failure = ConfigRecoveryPlan(
                str(path),
                str(matching_backup),
                sha256_bytes(b"corrupt"),
                b"replacement",
            )
            with patch("agent_artifacts.io.config_store.write_configuration", return_value=failure):
                self.assertEqual(recover_configuration(replacement_failure), failure)


if __name__ == "__main__":
    unittest.main()
