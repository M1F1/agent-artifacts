from __future__ import annotations

import unittest

from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.registry_commands.migration import plan_legacy_registry_migration
from agent_artifacts.registry_commands.planning import project_registry_workspace_plan
from tests.importer_fixtures import importer_input
from tests.legacy_importer_test import options


class RegistryMigrationTest(unittest.TestCase):
    def test_legacy_migration_is_deterministic_reviewable_and_dry_run_first(self) -> None:
        first = plan_legacy_registry_migration(
            importer_input(),
            options(display_name="Migrated Registry"),
            display_name="Migrated Registry",
            executable_version=SemVer(1, 0, 0),
        )
        second = plan_legacy_registry_migration(
            importer_input(),
            options(display_name="Migrated Registry"),
            display_name="Migrated Registry",
            executable_version=SemVer(1, 0, 0),
        )
        assert isinstance(first, Ok), first
        self.assertEqual(first, second)
        self.assertGreater(first.value.changed_paths, 0)
        projected = project_registry_workspace_plan(first.value.current, first.value.plan)
        assert isinstance(projected, Ok), projected
        paths = {str(item.path) for item in projected.value.entries}
        self.assertIn("aart-registry.json", paths)
        self.assertIn("artifacts/skill/demo/artifact.json", paths)
        self.assertIn(".github/workflows/aart-registry.yml", paths)
        self.assertNotIn("aart.lock.json", paths)

    def test_registry_and_imported_source_display_names_cannot_diverge(self) -> None:
        migrated = plan_legacy_registry_migration(
            importer_input(),
            options(display_name="Imported Source"),
            display_name="Different Registry",
            executable_version=SemVer(1, 0, 0),
        )

        self.assertIsInstance(migrated, Err)


if __name__ == "__main__":
    unittest.main()
