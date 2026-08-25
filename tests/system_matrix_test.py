from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.credential_fixtures import assignment
from tests.packaging_test import REPO_ROOT, _load_script

EXPECTED_SCENARIOS = (
    "direct-only",
    "public-company-team",
    "native-reference",
    "collision",
    "trust-downgrade",
    "offline",
    "concurrent-sync-install",
    "corrupt-lock-object",
    "setup-partial",
    "security-provider-failure",
    "reporting-absent",
)


class SystemMatrixTest(unittest.TestCase):
    def test_manifest_is_complete_ordered_and_uses_exact_test_ids(self) -> None:
        matrix = _load_script("system_matrix")

        self.assertEqual(matrix.scenario_names(), EXPECTED_SCENARIOS)
        self.assertEqual(matrix.validate_manifest(), ())
        for _name, budget_seconds, test_ids in matrix.SCENARIOS:
            self.assertGreaterEqual(budget_seconds, 1)
            self.assertEqual(tuple(sorted(set(test_ids))), tuple(sorted(test_ids)))
            self.assertTrue(all(test_id.startswith("tests.") for test_id in test_ids))

    def test_success_receipt_is_deterministic_and_processes_are_hermetic(self) -> None:
        matrix = _load_script("system_matrix")
        observed: list[tuple[tuple[str, ...], Path, dict[str, str], int]] = []

        def succeed(command, cwd, environment, timeout_seconds):
            observed.append((command, cwd, environment, timeout_seconds))
            self.assertTrue(Path(environment["HOME"]).is_dir())
            self.assertTrue(Path(environment["TMPDIR"]).is_dir())
            return subprocess.CompletedProcess(command, 0, "ok", "")

        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            first = matrix.run_matrix(
                REPO_ROOT,
                selected=("direct-only",),
                process_runner=succeed,
                temporary_parent=parent,
            )
            second = matrix.run_matrix(
                REPO_ROOT,
                selected=("direct-only",),
                process_runner=succeed,
                temporary_parent=parent,
            )
            self.assertEqual(tuple(parent.iterdir()), ())

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "passed")
        self.assertEqual(first["passed"], 1)
        self.assertEqual(first["failed"], 0)
        self.assertEqual(first["recovery_commands"], [])
        command, cwd, environment, timeout_seconds = observed[0]
        self.assertEqual(command[:4], (matrix.PYTHON, "-m", "unittest", "-v"))
        self.assertEqual(cwd, REPO_ROOT)
        self.assertGreaterEqual(timeout_seconds, 1)
        self.assertEqual(environment["PYTHONNOUSERSITE"], "1")
        self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")
        for prohibited in (
            "PYTHONPATH",
            "PYTHONHOME",
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "AWS_SECRET_ACCESS_KEY",
            "ATLASSIAN_API_TOKEN",
        ):
            self.assertNotIn(prohibited, environment)

    def test_nonzero_and_timeout_are_typed_redacted_and_actionable(self) -> None:
        matrix = _load_script("system_matrix")

        def fail(command, _cwd, _environment, _timeout_seconds):
            return subprocess.CompletedProcess(
                command,
                7,
                assignment("token", "must-not-leak"),
                assignment("password", "must-not-leak"),
            )

        def timeout(command, _cwd, _environment, timeout_seconds):
            raise subprocess.TimeoutExpired(command, timeout_seconds, output=b"secret")

        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            failed = matrix.run_matrix(
                REPO_ROOT,
                selected=("reporting-absent",),
                process_runner=fail,
                temporary_parent=parent,
            )
            timed_out = matrix.run_matrix(
                REPO_ROOT,
                selected=("offline",),
                process_runner=timeout,
                temporary_parent=parent,
            )
            self.assertEqual(tuple(parent.iterdir()), ())

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["scenarios"][0]["diagnostic_code"], "scenario-exit-nonzero")
        self.assertEqual(timed_out["scenarios"][0]["diagnostic_code"], "scenario-timeout")
        self.assertEqual(
            failed["recovery_commands"],
            ["python scripts/system_matrix.py --scenario reporting-absent --json"],
        )
        self.assertEqual(
            timed_out["recovery_commands"],
            ["python scripts/system_matrix.py --scenario offline --json"],
        )
        self.assertNotIn("must-not-leak", repr(failed))
        self.assertNotIn("secret", repr(timed_out))

    def test_selection_rejects_unknown_or_duplicate_scenarios_before_running(self) -> None:
        matrix = _load_script("system_matrix")

        with self.assertRaisesRegex(ValueError, "unknown system-matrix scenario"):
            matrix.select_scenarios(("missing",))
        with self.assertRaisesRegex(ValueError, "duplicate system-matrix scenario"):
            matrix.select_scenarios(("offline", "offline"))


if __name__ == "__main__":
    unittest.main()
