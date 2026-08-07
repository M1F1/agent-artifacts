from __future__ import annotations

import json
import unittest

from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.registry_schema import parse_registry_lock
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.registry_maintenance.model import (
    NativeReferenceAcquisition,
    UpstreamDisposition,
)
from agent_artifacts.registry_maintenance.planning import (
    check_native_upstream,
    plan_native_promotion,
    project_registry_mutation,
)
from tests.registry_maintenance_fixtures import (
    empty_registry_snapshot,
    native_snapshot,
    registry_entry,
    replace_snapshot_file,
    snapshot_file,
)


class RegistryUpstreamUpdateTest(unittest.TestCase):
    def _promoted(self):
        acquisition = NativeReferenceAcquisition(
            "https://github.com/example/reference-skills.git",
            "main",
            "a" * 40,
            native_snapshot(),
        )
        plan = plan_native_promotion(
            empty_registry_snapshot(),
            registry_entry(),
            acquisition,
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
        )
        assert isinstance(plan, Ok), plan
        projected = project_registry_mutation(empty_registry_snapshot(), plan.value)
        assert isinstance(projected, Ok), projected
        return projected.value, acquisition

    def test_same_pin_is_up_to_date_and_changed_upstream_is_an_explicit_diff(self) -> None:
        current, acquisition = self._promoted()
        same = check_native_upstream(
            current,
            registry_entry(),
            acquisition,
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
        )
        assert isinstance(same, Ok), same
        self.assertEqual(same.value.disposition, UpstreamDisposition.UP_TO_DATE)

        changed_snapshot = replace_snapshot_file(
            native_snapshot(),
            "artifacts/skill/code-review/payload/SKILL.md",
            b"# Changed upstream\n",
        )
        changed = check_native_upstream(
            current,
            registry_entry(),
            NativeReferenceAcquisition(
                acquisition.url,
                acquisition.requested_ref,
                "b" * 40,
                changed_snapshot,
            ),
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
        )
        assert isinstance(changed, Ok), changed
        self.assertEqual(changed.value.disposition, UpstreamDisposition.CHANGED)
        changed_paths = {
            str(item.path) for item in changed.value.plan.changes if item.kind.value != "unchanged"
        }
        self.assertEqual(changed_paths, {"aart.index.json", "aart.lock.json"})

        projected = project_registry_mutation(current, changed.value.plan)
        assert isinstance(projected, Ok)
        lock_bytes = next(
            item.content for item in projected.value.entries if str(item.path) == "aart.lock.json"
        )
        lock = parse_registry_lock(lock_bytes)
        assert isinstance(lock, Ok)
        self.assertEqual(lock.value.entries[0][1].resolved_commit, "b" * 40)

    def test_existing_lock_and_index_must_agree_before_an_update(self) -> None:
        current, acquisition = self._promoted()
        index = json.loads(snapshot_file(current, "aart.index.json"))
        index["artifacts"][0]["object_digest"] = f"sha256:{'f' * 64}"
        inconsistent = replace_snapshot_file(
            current,
            "aart.index.json",
            json.dumps(index).encode(),
        )
        result = check_native_upstream(
            inconsistent,
            registry_entry(),
            acquisition,
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
        )
        self.assertIsInstance(result, Err)

        lock = json.loads(snapshot_file(current, "aart.lock.json"))
        lock["registry_inputs_digest"] = f"sha256:{'0' * 64}"
        stale_lock = replace_snapshot_file(
            current,
            "aart.lock.json",
            json.dumps(lock).encode(),
        )
        result = check_native_upstream(
            stale_lock,
            registry_entry(),
            acquisition,
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
        )
        self.assertIsInstance(result, Err)


if __name__ == "__main__":
    unittest.main()
