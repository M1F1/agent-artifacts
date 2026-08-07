from __future__ import annotations

import json
import unittest

from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.importers.legacy_catalog import (
    materialize_legacy_catalog,
    plan_legacy_catalog,
    scan_legacy_catalog,
)
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.registry_maintenance.model import UpstreamDisposition
from agent_artifacts.registry_maintenance.planning import check_materialized_upstream
from tests.importer_fixtures import importer_input, replace_file
from tests.legacy_importer_test import options
from tests.registry_maintenance_fixtures import replace_snapshot_file, snapshot_file


def _current_output():
    request = importer_input()
    scanned = scan_legacy_catalog(request)
    assert isinstance(scanned, Ok)
    planned = plan_legacy_catalog(scanned.value, options())
    assert isinstance(planned, Ok)
    materialized = materialize_legacy_catalog(request, planned.value)
    assert isinstance(materialized, Ok)
    return materialized.value.snapshot


class MaterializedUpstreamUpdateTest(unittest.TestCase):
    def test_recorded_importer_rerun_is_up_to_date_or_a_reviewable_diff(self) -> None:
        current = _current_output()
        same = check_materialized_upstream(
            current,
            importer_input(),
            options(),
            executable_version=SemVer(1, 0, 0),
        )
        assert isinstance(same, Ok), same
        self.assertEqual(same.value.disposition, UpstreamDisposition.UP_TO_DATE)

        changed_input = importer_input(
            replace_file(
                importer_input().snapshot,
                "skills/demo/SKILL.md",
                b"---\nname: demo\ndescription: Changed imported skill.\n"
                b"compatibility.profiles: claude, tabnine\n---\n# Changed\n",
            )
        )
        changed = check_materialized_upstream(
            current,
            changed_input,
            options(),
            executable_version=SemVer(1, 0, 0),
        )
        assert isinstance(changed, Ok), changed
        self.assertEqual(changed.value.disposition, UpstreamDisposition.CHANGED)
        self.assertTrue(
            any(item.kind.value == "changed" for item in changed.value.apply_plan.changes)
        )

    def test_changed_importer_options_are_not_an_upstream_rerun(self) -> None:
        result = check_materialized_upstream(
            _current_output(),
            importer_input(),
            options(display_name="Different options"),
            executable_version=SemVer(1, 0, 0),
        )
        self.assertIsInstance(result, Err)

    def test_forged_recorded_importer_is_rejected(self) -> None:
        current = _current_output()
        path = "artifacts/guideline/style/provenance.json"
        provenance = json.loads(snapshot_file(current, path))
        provenance["importer"]["id"] = "different-importer-v1"
        forged = replace_snapshot_file(current, path, json.dumps(provenance).encode())
        result = check_materialized_upstream(
            forged,
            importer_input(),
            options(),
            executable_version=SemVer(1, 0, 0),
        )
        self.assertIsInstance(result, Err)


if __name__ == "__main__":
    unittest.main()
