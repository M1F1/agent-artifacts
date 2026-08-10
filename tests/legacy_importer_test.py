from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from agent_artifacts.domain.identifiers import ObjectDigest, SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.importers.legacy_catalog import (
    LegacyCatalogOptions,
    materialize_legacy_catalog,
    plan_legacy_catalog,
    scan_legacy_catalog,
    validate_legacy_import,
)
from agent_artifacts.protocol.native_schema import parse_collection_manifest, parse_provenance
from agent_artifacts.protocol.native_tree import SnapshotEntryKind
from agent_artifacts.protocol.semver import SemVer
from tests.importer_fixtures import FIXTURE_ROOT, importer_input


def options(
    *, display_name: str = "Imported legacy catalog", license: str | None = None
) -> LegacyCatalogOptions:
    return LegacyCatalogOptions(
        SourceId("legacy-catalog"),
        display_name,
        SemVer(1, 0, 0),
        ("claude", "opencode", "tabnine", "vibe"),
        ("darwin", "linux"),
        license=license,
    )


class LegacyImporterTest(unittest.TestCase):
    def test_explicit_import_license_is_written_to_every_artifact_manifest(self) -> None:
        request = importer_input()
        scanned = scan_legacy_catalog(request)
        assert isinstance(scanned, Ok), scanned
        planned = plan_legacy_catalog(scanned.value, options(license="MIT"))
        assert isinstance(planned, Ok), planned
        materialized = materialize_legacy_catalog(request, planned.value)
        assert isinstance(materialized, Ok), materialized
        manifests = tuple(
            entry.content
            for entry in materialized.value.snapshot.entries
            if str(entry.path).endswith("/artifact.json")
        )
        self.assertTrue(manifests)
        self.assertTrue(all(b'"license":"MIT"' in content for content in manifests))

    def test_complete_legacy_catalog_materializes_as_valid_canonical_source(self) -> None:
        request = importer_input()
        scanned = scan_legacy_catalog(request)
        assert isinstance(scanned, Ok), scanned
        self.assertEqual(len(scanned.value.artifacts), 5)
        self.assertEqual(len(scanned.value.collections), 1)
        self.assertEqual(
            tuple(str(item.identity) for item in scanned.value.artifacts),
            ("guideline/style", "hook/lint", "mcp/database", "memory/house", "skill/demo"),
        )

        planned = plan_legacy_catalog(scanned.value, options())
        repeated_plan = plan_legacy_catalog(scanned.value, options())
        assert isinstance(planned, Ok), planned
        self.assertEqual(planned, repeated_plan)
        materialized = materialize_legacy_catalog(request, planned.value)
        repeated = materialize_legacy_catalog(request, planned.value)
        assert isinstance(materialized, Ok), materialized
        self.assertEqual(materialized, repeated)

        validated = validate_legacy_import(materialized.value, executable_version=SemVer(1, 0, 0))
        assert isinstance(validated, Ok), validated
        self.assertEqual(len(validated.value.source.artifacts), 5)
        self.assertEqual(len(validated.value.source.collections), 1)
        paths = {str(entry.path) for entry in materialized.value.snapshot.entries}
        self.assertIn("aart-source.json", paths)
        self.assertIn("artifacts/skill/demo/artifact.json", paths)
        self.assertIn("artifacts/skill/demo/payload/SKILL.md", paths)
        self.assertIn("artifacts/mcp/database/setup/installer.json", paths)
        self.assertIn("collections/base.json", paths)
        self.assertTrue(
            all(
                entry.kind is not SnapshotEntryKind.SYMLINK
                for entry in materialized.value.snapshot.entries
            )
        )
        collection_entry = next(
            entry
            for entry in materialized.value.snapshot.entries
            if str(entry.path) == "collections/base.json"
        )
        collection = parse_collection_manifest(collection_entry.content)
        assert isinstance(collection, Ok), collection
        self.assertEqual(collection.value.extensions[0][0], "com.m1f1.legacy-pins")

        serialized = b"".join(
            entry.content
            for entry in materialized.value.snapshot.entries
            if entry.kind is SnapshotEntryKind.FILE
        )
        self.assertNotIn(str(Path(FIXTURE_ROOT).resolve()).encode(), serialized)
        self.assertNotIn(b"2026-01-01T00:00:00Z", serialized)

    def test_provenance_uses_tracked_upstream_or_pinned_catalog_origin(self) -> None:
        request = importer_input()
        scanned = scan_legacy_catalog(request)
        assert isinstance(scanned, Ok), scanned
        planned = plan_legacy_catalog(scanned.value, options())
        assert isinstance(planned, Ok), planned
        materialized = materialize_legacy_catalog(request, planned.value)
        assert isinstance(materialized, Ok), materialized
        entries = {str(entry.path): entry for entry in materialized.value.snapshot.entries}

        tracked = parse_provenance(entries["artifacts/guideline/style/provenance.json"].content)
        owned = parse_provenance(entries["artifacts/skill/demo/provenance.json"].content)

        assert isinstance(tracked, Ok), tracked
        assert isinstance(owned, Ok), owned
        self.assertEqual(
            tracked.value.origin.url,
            "https://github.com/example/agent-guidelines.git",
        )
        self.assertEqual(
            tracked.value.origin.resolved_commit,
            "0123456789abcdef0123456789abcdef01234567",
        )
        self.assertEqual(str(tracked.value.origin.path), "guidelines/style.md")
        self.assertEqual(owned.value.origin.url, request.origin.url)
        self.assertEqual(owned.value.origin.resolved_commit, request.origin.resolved_commit)
        self.assertEqual(str(owned.value.origin.path), "skills/demo")
        self.assertEqual(owned.value.importer.id, "legacy-catalog-v1")
        self.assertEqual(owned.value.importer.version, SemVer(1, 0, 0))

    def test_option_change_changes_canonical_output_without_changing_input_scan(self) -> None:
        request = importer_input()
        scanned = scan_legacy_catalog(request)
        assert isinstance(scanned, Ok), scanned
        first_plan = plan_legacy_catalog(scanned.value, options())
        second_plan = plan_legacy_catalog(scanned.value, options(display_name="Other display"))
        assert isinstance(first_plan, Ok)
        assert isinstance(second_plan, Ok)
        first = materialize_legacy_catalog(request, first_plan.value)
        second = materialize_legacy_catalog(request, second_plan.value)
        assert isinstance(first, Ok)
        assert isinstance(second, Ok)

        self.assertEqual(first_plan.value.scan, second_plan.value.scan)
        self.assertNotEqual(first_plan.value.options_digest, second_plan.value.options_digest)
        self.assertNotEqual(first.value.output_digest, second.value.output_digest)

    def test_materialization_rejects_a_forged_plan_digest(self) -> None:
        request = importer_input()
        scanned = scan_legacy_catalog(request)
        assert isinstance(scanned, Ok)
        planned = plan_legacy_catalog(scanned.value, options())
        assert isinstance(planned, Ok)
        forged = replace(
            planned.value,
            plan_digest=ObjectDigest("sha256", "f" * 64),
        )

        result = materialize_legacy_catalog(request, forged)

        self.assertIsInstance(result, Err)


if __name__ == "__main__":
    unittest.main()
