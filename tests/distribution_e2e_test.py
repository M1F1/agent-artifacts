"""Local editable-to-wheel lifecycle proof from outside the source checkout."""

from __future__ import annotations

import unittest

from tests.packaging_test import REPO_ROOT, _load_script


class DistributionE2ETest(unittest.TestCase):
    def test_editable_and_wheel_environment_recreation_preserves_managed_symlink(self) -> None:
        smoke = _load_script("distribution_smoke")

        receipt = smoke.run_smoke(REPO_ROOT)

        self.assertEqual(receipt["schema_version"], 1)
        self.assertEqual(receipt["source_sync"], "published")
        self.assertEqual(receipt["initial_copy"], 1)
        self.assertEqual(receipt["initial_symlink"], 1)
        self.assertEqual(receipt["resumed_current"], 2)
        self.assertEqual(receipt["removed"], 2)
        self.assertEqual(receipt["reinstalled_symlink"], 1)
        self.assertTrue(receipt["survived_editable_removal"])
        self.assertTrue(receipt["survived_wheel_removal"])
        self.assertEqual(receipt["runtime_dependencies"], 0)
        self.assertTrue(receipt["upgrade_dry_run"])
        self.assertIn("/objects/sha256/", receipt["symlink_target"])
        self.assertNotIn(receipt["editable_environment"], receipt["symlink_target"])
        self.assertNotIn(receipt["wheel_environment"], receipt["symlink_target"])


if __name__ == "__main__":
    unittest.main()
