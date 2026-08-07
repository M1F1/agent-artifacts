from __future__ import annotations

import unittest
from dataclasses import replace

from agent_artifacts.domain.identifiers import ObjectDigest, SourceId
from agent_artifacts.domain.result import Ok
from agent_artifacts.importers import built_in_importers, find_importer
from agent_artifacts.importers.legacy_catalog import (
    LEGACY_CATALOG_IMPORTER,
    LegacyCatalogOptions,
    build_import_apply_plan,
    diff_legacy_import,
    materialize_legacy_catalog,
    plan_legacy_catalog,
    scan_legacy_catalog,
    validate_legacy_import,
)
from agent_artifacts.importers.model import (
    AppliedImport,
    ImportApplyPlan,
    ImportChange,
    ImportDiff,
    ImporterDescriptor,
    ImporterInput,
    ImportOrigin,
    ImportPlan,
    ImportScan,
    MaterializedImport,
    PreparedImport,
    StagedImport,
    ValidatedImport,
)
from agent_artifacts.protocol.json import JsonObject
from agent_artifacts.protocol.native_tree import SnapshotOrigin, SourceSnapshot
from agent_artifacts.protocol.paths import SafeRelativePath
from agent_artifacts.protocol.semver import SemVer
from tests.importer_fixtures import importer_input
from tests.legacy_importer_test import options


class ImporterModelTest(unittest.TestCase):
    def test_builtin_registry_is_closed_versioned_and_deterministic(self) -> None:
        self.assertEqual(built_in_importers(), (LEGACY_CATALOG_IMPORTER,))
        self.assertEqual(find_importer("legacy-catalog-v1"), LEGACY_CATALOG_IMPORTER)
        self.assertIsNone(find_importer("external-plugin"))
        self.assertEqual(LEGACY_CATALOG_IMPORTER.version, SemVer(1, 0, 0))

    def test_importer_origin_descriptor_and_legacy_options_enforce_invariants(self) -> None:
        options = LegacyCatalogOptions(
            SourceId("legacy-catalog"),
            "Legacy catalog",
            SemVer(1, 0, 0),
            ("tabnine", "claude", "claude"),
            ("linux", "darwin"),
        )
        self.assertEqual(options.profiles, ("claude", "tabnine"))
        self.assertEqual(options.platforms, ("darwin", "linux"))

        invalid = (
            lambda: ImporterDescriptor("Bad_ID", SemVer(1, 0, 0), (), ("skill",)),
            lambda: ImportOrigin("https://user:secret@example.test/repo.git", "a" * 40, None),
            lambda: ImportOrigin("https://example.test/repo.git", "main", None),
            lambda: LegacyCatalogOptions(
                SourceId("legacy-catalog"),
                "Legacy catalog",
                SemVer(1, 0, 0),
                (),
                ("darwin",),
            ),
        )
        for constructor in invalid:
            with self.subTest(constructor=constructor), self.assertRaises(ValueError):
                constructor()

        self.assertEqual(
            ImportOrigin("git@example.test:team/repo.git", "b" * 40, None).url,
            "git@example.test:team/repo.git",
        )
        for url in (
            "git@example.test:../repo.git",
            "https://example.test/team/repo.git?token=secret",
            "https://example.test/team/%72epo.git",
            "https://example.test/team/repo.git\n",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                ImportOrigin(url, "b" * 40, None)

    def test_workflow_values_reject_inconsistent_state(self) -> None:
        request = importer_input()
        scan = scan_legacy_catalog(request)
        assert isinstance(scan, Ok)
        plan = plan_legacy_catalog(scan.value, options())
        assert isinstance(plan, Ok)
        materialized = materialize_legacy_catalog(request, plan.value)
        assert isinstance(materialized, Ok)
        validated = validate_legacy_import(
            materialized.value,
            executable_version=SemVer(1, 0, 0),
        )
        assert isinstance(validated, Ok)
        diff = diff_legacy_import(validated.value, None)
        assert isinstance(diff, Ok)
        apply_plan = build_import_apply_plan(validated.value, diff.value)
        stage = StagedImport("stage", materialized.value.output_digest)
        prepared = PreparedImport(validated.value, apply_plan, stage)
        self.assertEqual(prepared.apply_plan.output_digest, materialized.value.output_digest)

        other_digest = ObjectDigest("sha256", "f" * 64)
        invalid_digest = ObjectDigest("md5", "f" * 32)
        invalid = (
            lambda: ImporterInput(
                request.origin,
                SourceSnapshot(SnapshotOrigin.LOCAL, request.snapshot.entries),
            ),
            lambda: replace(scan.value.artifacts[0], summary=""),
            lambda: replace(
                scan.value.artifacts[0],
                setup_recipe=SafeRelativePath(("outside.json",)),
                setup_platforms=("darwin",),
            ),
            lambda: replace(
                scan.value.artifacts[0],
                provenance_extensions=(("com.example.same", 1), ("com.example.same", 2)),
            ),
            lambda: ImportScan(scan.value.importer, scan.value.input_digest, (), ()),
            lambda: ImportPlan(
                scan.value,
                JsonObject(()),
                invalid_digest,
                plan.value.plan_digest,
            ),
            lambda: MaterializedImport(
                plan.value,
                request.snapshot,
                materialized.value.output_digest,
            ),
            lambda: ValidatedImport(materialized.value, object()),  # type: ignore[arg-type]
            lambda: ImportChange(SafeRelativePath(("path",)), "added"),  # type: ignore[arg-type]
            lambda: ImportDiff(None, materialized.value.output_digest, ()),
            lambda: ImportApplyPlan(materialized.value, None, (), apply_plan.review_digest),
            lambda: StagedImport("bad\nstage", materialized.value.output_digest),
            lambda: PreparedImport(
                validated.value,
                apply_plan,
                StagedImport("stage", other_digest),
            ),
            lambda: AppliedImport(materialized.value.output_digest, -1),
        )
        for constructor in invalid:
            with self.subTest(constructor=constructor), self.assertRaises(ValueError):
                constructor()


if __name__ == "__main__":
    unittest.main()
