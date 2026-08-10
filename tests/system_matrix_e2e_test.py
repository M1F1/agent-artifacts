from __future__ import annotations

import unittest

from tests.packaging_test import REPO_ROOT, _load_script
from tests.system_matrix_test import EXPECTED_SCENARIOS


class SystemMatrixE2ETest(unittest.TestCase):
    def test_complete_hermetic_matrix_passes_with_stable_receipt(self) -> None:
        matrix = _load_script("system_matrix")

        receipt = matrix.run_matrix(REPO_ROOT)

        self.assertEqual(receipt["schema_version"], 1)
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["scenario_count"], len(EXPECTED_SCENARIOS))
        self.assertEqual(receipt["passed"], len(EXPECTED_SCENARIOS))
        self.assertEqual(receipt["failed"], 0)
        self.assertEqual(receipt["recovery_commands"], [])
        self.assertEqual(
            tuple(item["name"] for item in receipt["scenarios"]),
            EXPECTED_SCENARIOS,
        )
        self.assertTrue(all(item["status"] == "passed" for item in receipt["scenarios"]))


if __name__ == "__main__":
    unittest.main()
