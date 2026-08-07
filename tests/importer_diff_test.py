from __future__ import annotations

import unittest

from agent_artifacts.domain.result import Ok
from agent_artifacts.importers.legacy_catalog import (
    build_import_apply_plan,
    diff_legacy_import,
    materialize_legacy_catalog,
    plan_legacy_catalog,
    scan_legacy_catalog,
    validate_legacy_import,
)
from agent_artifacts.importers.model import ImportChangeKind
from agent_artifacts.protocol.semver import SemVer
from tests.importer_fixtures import importer_input, replace_file
from tests.legacy_importer_test import options


class ImporterDiffTest(unittest.TestCase):
    def _validated(self):
        request = importer_input()
        scanned = scan_legacy_catalog(request)
        assert isinstance(scanned, Ok), scanned
        planned = plan_legacy_catalog(scanned.value, options())
        assert isinstance(planned, Ok), planned
        materialized = materialize_legacy_catalog(request, planned.value)
        assert isinstance(materialized, Ok), materialized
        validated = validate_legacy_import(materialized.value, executable_version=SemVer(1, 0, 0))
        assert isinstance(validated, Ok), validated
        return validated.value

    def test_diff_and_reviewed_apply_plan_are_deterministic_and_digest_bound(self) -> None:
        validated = self._validated()
        initial = diff_legacy_import(validated, None)
        unchanged = diff_legacy_import(validated, validated.materialized.snapshot)
        changed_snapshot = replace_file(
            validated.materialized.snapshot,
            "artifacts/skill/demo/payload/SKILL.md",
            b"changed\n",
        )
        changed = diff_legacy_import(validated, changed_snapshot)
        assert isinstance(initial, Ok)
        assert isinstance(unchanged, Ok)
        assert isinstance(changed, Ok)

        self.assertTrue(initial.value.changes)
        self.assertEqual(
            {item.kind for item in initial.value.changes},
            {ImportChangeKind.ADDED},
        )
        self.assertEqual(
            {item.kind for item in unchanged.value.changes},
            {ImportChangeKind.UNCHANGED},
        )
        self.assertIn(ImportChangeKind.CHANGED, {item.kind for item in changed.value.changes})
        plan = build_import_apply_plan(validated, changed.value)
        repeated = build_import_apply_plan(validated, changed.value)
        self.assertEqual(plan, repeated)
        self.assertEqual(plan.output_digest, validated.materialized.output_digest)
        self.assertEqual(plan.expected_destination_digest, changed.value.before_digest)


if __name__ == "__main__":
    unittest.main()
