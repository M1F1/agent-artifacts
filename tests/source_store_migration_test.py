"""Ref-aware source identity and the v1 -> v2 store migration (SRC02).

The migration moves real user data, so these tests pin the properties that make it safe: it never
clobbers an existing pointer, never guesses which ref a legacy directory belonged to, is idempotent,
and resumes correctly from a partially applied state.
"""

from __future__ import annotations

import unittest

from agent_artifacts.configuration.model import (
    ConfiguredSource,
    ReportingSettings,
    SourceKind,
    SyncSettings,
    UserConfiguration,
)
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.sources.migration import (
    SOURCE_STORE_SCHEMA_VERSION,
    RebindAction,
    plan_source_store_migration,
)
from agent_artifacts.sources.model import legacy_source_instance_id, source_instance_id


def _git(alias: str, location: str, ref: str | None = "main") -> ConfiguredSource:
    return ConfiguredSource(SourceAlias(alias), SourceKind.SOURCE_GIT, location, ref, True)


def _configuration(*sources: ConfiguredSource) -> UserConfiguration:
    return UserConfiguration(1, sources, None, SyncSettings(), ReportingSettings())


class RefAwareIdentityTests(unittest.TestCase):
    def test_two_refs_of_one_origin_get_distinct_instance_identities(self) -> None:
        main = _git("main-track", "https://git.example/team.git", "main")
        release = _git("release-track", "https://git.example/team.git", "release")

        self.assertNotEqual(source_instance_id(main), source_instance_id(release))

    def test_identity_hashes_the_literal_location_not_a_normalized_origin(self) -> None:
        # Normalization lives in the configuration uniqueness invariant, which already makes two
        # spellings of one origin at one ref impossible — so the store key never has to resolve
        # them, and every existing directory name stays stable.
        https = _git("a", "https://Git.Example/Team.git", "main")
        ssh = _git("b", "git@git.example:Team.git", "main")

        self.assertNotEqual(source_instance_id(https), source_instance_id(ssh))

    def test_a_local_source_identity_is_unchanged_by_ref_awareness(self) -> None:
        local = ConfiguredSource(
            SourceAlias("ref"), SourceKind.SOURCE_LOCAL, "/srv/catalog", None, True
        )

        self.assertEqual(source_instance_id(local), legacy_source_instance_id(local))

    def test_the_legacy_identity_ignores_ref_by_construction(self) -> None:
        main = _git("main-track", "https://git.example/team.git", "main")
        release = _git("release-track", "https://git.example/team.git", "release")

        self.assertEqual(legacy_source_instance_id(main), legacy_source_instance_id(release))

    def test_configuration_now_permits_one_origin_at_two_refs(self) -> None:
        configuration = _configuration(
            _git("main-track", "https://git.example/team.git", "main"),
            _git("release-track", "https://git.example/team.git", "release"),
        )

        self.assertEqual(len(configuration.sources), 2)

    def test_configuration_still_rejects_one_origin_at_the_same_ref_twice(self) -> None:
        with self.assertRaises(ValueError):
            _configuration(
                _git("a", "https://git.example/team.git", "main"),
                _git("b", "git@git.example:team.git", "main"),
            )


class MigrationPlanningTests(unittest.TestCase):
    def test_a_legacy_directory_is_planned_for_rebind_to_the_ref_aware_identity(self) -> None:
        source = _git("team", "https://git.example/team.git", "main")
        configuration = _configuration(source)

        planned = plan_source_store_migration(
            configuration,
            existing=(legacy_source_instance_id(source).value,),
        )

        self.assertIsInstance(planned, Ok)
        assert isinstance(planned, Ok)
        self.assertEqual(len(planned.value.rebinds), 1)
        rebind = planned.value.rebinds[0]
        self.assertEqual(rebind.action, RebindAction.REBIND)
        self.assertEqual(rebind.source_directory, legacy_source_instance_id(source).value)
        self.assertEqual(rebind.target_directory, source_instance_id(source).value)

    def test_an_already_migrated_directory_needs_no_rebind_only_a_version_stamp(self) -> None:
        source = _git("team", "https://git.example/team.git", "main")

        planned = plan_source_store_migration(
            _configuration(source),
            existing=(source_instance_id(source).value,),
        )

        self.assertIsInstance(planned, Ok)
        assert isinstance(planned, Ok)
        self.assertEqual(planned.value.rebinds, ())
        # No data moves, but the layout version is still unrecorded, so applying is not a no-op.
        self.assertTrue(planned.value.required)

    def test_a_source_with_no_stored_directory_plans_nothing(self) -> None:
        planned = plan_source_store_migration(
            _configuration(_git("team", "https://git.example/team.git", "main")),
            existing=(),
        )

        self.assertIsInstance(planned, Ok)
        assert isinstance(planned, Ok)
        self.assertEqual(planned.value.rebinds, ())

    def test_a_legacy_and_a_ref_aware_directory_together_are_a_conflict_not_an_overwrite(
        self,
    ) -> None:
        source = _git("team", "https://git.example/team.git", "main")

        planned = plan_source_store_migration(
            _configuration(source),
            existing=(
                legacy_source_instance_id(source).value,
                source_instance_id(source).value,
            ),
        )

        self.assertIsInstance(planned, Err)
        assert isinstance(planned, Err)
        self.assertEqual(planned.diagnostics[0].code.value, "source-store-conflict")

    def test_one_legacy_directory_for_two_configured_refs_is_ambiguous(self) -> None:
        main = _git("main-track", "https://git.example/team.git", "main")
        release = _git("release-track", "https://git.example/team.git", "release")

        planned = plan_source_store_migration(
            _configuration(main, release),
            existing=(legacy_source_instance_id(main).value,),
        )

        self.assertIsInstance(planned, Err)
        assert isinstance(planned, Err)
        diagnostic = planned.diagnostics[0]
        self.assertEqual(diagnostic.code.value, "source-store-ambiguous")
        self.assertIn("main-track", diagnostic.message)
        self.assertIn("release-track", diagnostic.message)

    def test_unrelated_directories_are_left_alone(self) -> None:
        source = _git("team", "https://git.example/team.git", "main")

        planned = plan_source_store_migration(
            _configuration(source),
            existing=("registry-deadbeef", "store.json"),
        )

        self.assertIsInstance(planned, Ok)
        assert isinstance(planned, Ok)
        self.assertEqual(planned.value.rebinds, ())

    def test_a_completed_store_version_makes_the_plan_a_no_op(self) -> None:
        source = _git("team", "https://git.example/team.git", "main")

        planned = plan_source_store_migration(
            _configuration(source),
            existing=(legacy_source_instance_id(source).value,),
            stored_schema_version=SOURCE_STORE_SCHEMA_VERSION,
        )

        self.assertIsInstance(planned, Ok)
        assert isinstance(planned, Ok)
        self.assertEqual(planned.value.rebinds, ())
        self.assertFalse(planned.value.required)

    def test_rebinds_are_ordered_deterministically(self) -> None:
        first = _git("alpha", "https://git.example/alpha.git", "main")
        second = _git("beta", "https://git.example/beta.git", "main")

        planned = plan_source_store_migration(
            _configuration(first, second),
            existing=(
                legacy_source_instance_id(second).value,
                legacy_source_instance_id(first).value,
            ),
        )

        self.assertIsInstance(planned, Ok)
        assert isinstance(planned, Ok)
        self.assertEqual(
            tuple(rebind.alias.value for rebind in planned.value.rebinds),
            ("alpha", "beta"),
        )


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()
