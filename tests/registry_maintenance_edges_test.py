from __future__ import annotations

import json
import unittest
from dataclasses import replace

from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.native_tree import SnapshotEntry, SnapshotEntryKind, SourceSnapshot
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.registry_maintenance.model import NativeReferenceAcquisition
from agent_artifacts.registry_maintenance.planning import (
    check_native_reference,
    plan_native_promotion,
    plan_registry_entry_add,
    project_registry_mutation,
)
from tests.registry_maintenance_fixtures import (
    append_snapshot_file,
    empty_registry_snapshot,
    native_snapshot,
    registry_entry,
    replace_snapshot_file,
    snapshot_file,
    without_snapshot_paths,
)

VERSION = SemVer(1, 0, 0)
CAPABILITIES = (Capability("artifact-manifest-v1"),)


def _acquisition(snapshot=None, *, commit: str = "a" * 40):
    return NativeReferenceAcquisition(
        "https://github.com/example/reference-skills.git",
        "main",
        commit,
        native_snapshot() if snapshot is None else snapshot,
    )


def _promoted():
    initial = empty_registry_snapshot()
    plan = plan_native_promotion(
        initial,
        registry_entry(),
        _acquisition(),
        executable_version=VERSION,
        available_capabilities=CAPABILITIES,
    )
    assert isinstance(plan, Ok), plan
    projected = project_registry_mutation(initial, plan.value)
    assert isinstance(projected, Ok), projected
    return projected.value


class RegistryMaintenanceEdgesTest(unittest.TestCase):
    def test_entry_add_rejects_missing_manifest_owned_identity_and_conflict(self) -> None:
        missing = without_snapshot_paths(empty_registry_snapshot(), "aart-registry.json")
        self.assertIsInstance(plan_registry_entry_add(missing, registry_entry()), Err)

        owned = append_snapshot_file(
            empty_registry_snapshot(),
            "artifacts/skill/code-review/artifact.json",
            b"{}",
        )
        self.assertIsInstance(plan_registry_entry_add(owned, registry_entry()), Err)

        custom_source = json.loads(snapshot_file(empty_registry_snapshot(), "aart-source.json"))
        custom_source["artifact_roots"] = ["packages"]
        custom = replace_snapshot_file(
            empty_registry_snapshot(),
            "aart-source.json",
            json.dumps(custom_source).encode(),
        )
        custom = append_snapshot_file(
            custom,
            "packages/skill/code-review/artifact.json",
            b"{}",
        )
        self.assertIsInstance(plan_registry_entry_add(custom, registry_entry()), Err)

        mismatched_source = dict(custom_source)
        mismatched_source["source_id"] = "not-the-registry"
        mismatched = replace_snapshot_file(
            empty_registry_snapshot(),
            "aart-source.json",
            json.dumps(mismatched_source).encode(),
        )
        self.assertIsInstance(plan_registry_entry_add(mismatched, registry_entry()), Err)

        first = plan_registry_entry_add(empty_registry_snapshot(), registry_entry())
        assert isinstance(first, Ok)
        current = project_registry_mutation(empty_registry_snapshot(), first.value)
        assert isinstance(current, Ok)
        different = replace(
            registry_entry(),
            source=replace(registry_entry().source, ref="different-ref"),
        )
        self.assertIsInstance(plan_registry_entry_add(current.value, different), Err)
        self.assertIsInstance(
            plan_native_promotion(
                current.value,
                different,
                _acquisition(),
                executable_version=VERSION,
                available_capabilities=CAPABILITIES,
            ),
            Err,
        )

    def test_native_acquisition_must_match_entry_and_load_as_native(self) -> None:
        wrong_origin = replace(_acquisition(), url="https://github.com/example/other.git")
        self.assertIsInstance(
            plan_native_promotion(
                empty_registry_snapshot(),
                registry_entry(),
                wrong_origin,
                executable_version=VERSION,
                available_capabilities=CAPABILITIES,
            ),
            Err,
        )
        invalid_native = without_snapshot_paths(native_snapshot(), "aart-source.json")
        self.assertIsInstance(
            plan_native_promotion(
                empty_registry_snapshot(),
                registry_entry(),
                _acquisition(invalid_native),
                executable_version=VERSION,
                available_capabilities=CAPABILITIES,
            ),
            Err,
        )

    def test_registry_workspace_must_be_compatible_before_promotion(self) -> None:
        registry = json.loads(snapshot_file(empty_registry_snapshot(), "aart-registry.json"))
        registry["requires_aart"] = {
            "min_inclusive": "2.0.0",
            "max_exclusive": "3.0.0",
        }
        incompatible = replace_snapshot_file(
            empty_registry_snapshot(),
            "aart-registry.json",
            json.dumps(registry).encode(),
        )
        self.assertIsInstance(
            plan_native_promotion(
                incompatible,
                registry_entry(),
                _acquisition(),
                executable_version=VERSION,
                available_capabilities=CAPABILITIES,
            ),
            Err,
        )

        source = json.loads(snapshot_file(empty_registry_snapshot(), "aart-source.json"))
        source["required_capabilities"] = ["unavailable-capability"]
        missing_capability = replace_snapshot_file(
            empty_registry_snapshot(),
            "aart-source.json",
            json.dumps(source).encode(),
        )
        self.assertIsInstance(
            plan_native_promotion(
                missing_capability,
                registry_entry(),
                _acquisition(),
                executable_version=VERSION,
                available_capabilities=CAPABILITIES,
            ),
            Err,
        )

    def test_existing_reference_requires_parseable_matching_lock_and_index(self) -> None:
        current = _promoted()
        for path in ("aart.lock.json", "aart.index.json"):
            with self.subTest(path=path):
                self.assertIsInstance(
                    check_native_reference(
                        without_snapshot_paths(current, path),
                        registry_entry(),
                        _acquisition(),
                        executable_version=VERSION,
                        available_capabilities=CAPABILITIES,
                    ),
                    Err,
                )
                self.assertIsInstance(
                    check_native_reference(
                        replace_snapshot_file(current, path, b"{}"),
                        registry_entry(),
                        _acquisition(),
                        executable_version=VERSION,
                        available_capabilities=CAPABILITIES,
                    ),
                    Err,
                )

        index = json.loads(snapshot_file(current, "aart.index.json"))
        index["artifacts"] = []
        self.assertIsInstance(
            check_native_reference(
                replace_snapshot_file(current, "aart.index.json", json.dumps(index).encode()),
                registry_entry(),
                _acquisition(),
                executable_version=VERSION,
                available_capabilities=CAPABILITIES,
            ),
            Err,
        )

    def test_native_source_identity_cannot_change_during_update(self) -> None:
        current = _promoted()
        source = json.loads(snapshot_file(native_snapshot(), "aart-source.json"))
        source["source_id"] = "renamed-source"
        changed_source = replace_snapshot_file(
            native_snapshot(),
            "aart-source.json",
            json.dumps(source).encode(),
        )
        result = check_native_reference(
            current,
            registry_entry(),
            _acquisition(changed_source, commit="b" * 40),
            executable_version=VERSION,
            available_capabilities=CAPABILITIES,
        )
        self.assertIsInstance(result, Err)

    def test_non_file_generated_outputs_are_rejected(self) -> None:
        current = _promoted()
        entries = tuple(
            SnapshotEntry(entry.path, SnapshotEntryKind.DIRECTORY)
            if str(entry.path) == "aart.lock.json"
            else entry
            for entry in current.entries
        )
        malformed = SourceSnapshot(current.origin, entries)
        self.assertIsInstance(
            check_native_reference(
                malformed,
                registry_entry(),
                _acquisition(),
                executable_version=VERSION,
                available_capabilities=CAPABILITIES,
            ),
            Err,
        )


if __name__ == "__main__":
    unittest.main()
