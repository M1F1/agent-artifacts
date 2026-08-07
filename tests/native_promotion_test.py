from __future__ import annotations

import json
import unittest
from dataclasses import replace

from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.registry_schema import parse_registry_index, parse_registry_lock
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.registry_maintenance.model import NativeReferenceAcquisition
from agent_artifacts.registry_maintenance.planning import (
    plan_native_promotion,
    plan_registry_entry_add,
    project_registry_mutation,
)
from tests.registry_maintenance_fixtures import (
    append_snapshot_file,
    empty_registry_snapshot,
    native_snapshot,
    registry_entry,
    registry_with_owned_package,
    renamed_native_snapshot,
    replace_snapshot_file,
)


class NativePromotionTest(unittest.TestCase):
    def test_native_promotion_writes_only_entry_lock_and_index(self) -> None:
        acquisition = NativeReferenceAcquisition(
            "https://github.com/example/reference-skills.git",
            "main",
            "a" * 40,
            native_snapshot(),
        )
        result = plan_native_promotion(
            empty_registry_snapshot(),
            registry_entry(),
            acquisition,
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
        )
        assert isinstance(result, Ok), result
        self.assertEqual(
            tuple(str(change.path) for change in result.value.changes),
            ("aart.index.json", "aart.lock.json", "entries/skill/code-review.json"),
        )
        self.assertFalse(
            any(str(change.path).startswith("artifacts/") for change in result.value.changes)
        )
        self.assertFalse(any(b"# Code review" in change.content for change in result.value.changes))

        projected = project_registry_mutation(empty_registry_snapshot(), result.value)
        assert isinstance(projected, Ok), projected
        files = {str(item.path): item.content for item in projected.value.entries}
        lock = parse_registry_lock(files["aart.lock.json"])
        index = parse_registry_index(files["aart.index.json"])
        assert isinstance(lock, Ok), lock
        assert isinstance(index, Ok), index
        locked = lock.value.entries[0][1]
        self.assertEqual(locked.requested_ref, "main")
        self.assertEqual(locked.resolved_commit, "a" * 40)
        self.assertEqual(locked.artifact_version, SemVer(1, 0, 0))
        self.assertEqual(index.value.artifacts[0].object_digest, locked.object_digest)
        self.assertEqual(index.value.artifacts[0].payload_digest, locked.payload_digest)
        self.assertEqual(str(index.value.artifacts[0].source_id), "reference-native-source")

    def test_identity_mismatch_is_rejected_without_a_partial_plan(self) -> None:
        result = plan_native_promotion(
            empty_registry_snapshot(),
            registry_entry(name="other"),
            NativeReferenceAcquisition(
                "https://github.com/example/reference-skills.git",
                "main",
                "a" * 40,
                native_snapshot(),
            ),
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
        )
        self.assertIsInstance(result, Err)

    def test_pending_entry_cannot_be_promoted(self) -> None:
        result = plan_native_promotion(
            empty_registry_snapshot(),
            registry_entry(review_status="pending"),
            NativeReferenceAcquisition(
                "https://github.com/example/reference-skills.git",
                "main",
                "a" * 40,
                native_snapshot(),
            ),
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
        )
        self.assertIsInstance(result, Err)

    def test_review_only_transition_can_promote_a_previously_authored_entry(self) -> None:
        current = empty_registry_snapshot()
        authored = plan_registry_entry_add(
            current,
            registry_entry(review_status="pending"),
        )
        assert isinstance(authored, Ok)
        current_with_pending = project_registry_mutation(current, authored.value)
        assert isinstance(current_with_pending, Ok)

        result = plan_native_promotion(
            current_with_pending.value,
            registry_entry(),
            NativeReferenceAcquisition(
                "https://github.com/example/reference-skills.git",
                "main",
                "a" * 40,
                native_snapshot(),
            ),
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
        )
        assert isinstance(result, Ok), result
        entry_change = next(
            change
            for change in result.value.changes
            if str(change.path) == "entries/skill/code-review.json"
        )
        self.assertEqual(entry_change.kind.value, "changed")

    def test_new_reviewed_entry_can_be_promoted_beside_existing_locked_references(self) -> None:
        initial = empty_registry_snapshot()
        first = plan_native_promotion(
            initial,
            registry_entry(),
            NativeReferenceAcquisition(
                "https://github.com/example/reference-skills.git",
                "main",
                "a" * 40,
                native_snapshot(),
            ),
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
        )
        assert isinstance(first, Ok)
        current = project_registry_mutation(initial, first.value)
        assert isinstance(current, Ok)
        pending = plan_registry_entry_add(
            current.value,
            registry_entry(name="other", review_status="pending"),
        )
        assert isinstance(pending, Ok)
        with_pending = project_registry_mutation(current.value, pending.value)
        assert isinstance(with_pending, Ok)

        promoted = plan_native_promotion(
            with_pending.value,
            registry_entry(name="other"),
            NativeReferenceAcquisition(
                "https://github.com/example/reference-skills.git",
                "main",
                "b" * 40,
                renamed_native_snapshot("other"),
            ),
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
        )
        assert isinstance(promoted, Ok), promoted
        projected = project_registry_mutation(with_pending.value, promoted.value)
        assert isinstance(projected, Ok)
        files = {str(item.path): item.content for item in projected.value.entries}
        lock = parse_registry_lock(files["aart.lock.json"])
        assert isinstance(lock, Ok)
        self.assertEqual(
            {str(identity) for identity, _item in lock.value.entries},
            {"skill/code-review", "skill/other"},
        )

    def test_review_change_of_locked_reference_is_recompiled_explicitly(self) -> None:
        initial = empty_registry_snapshot()
        acquisition = NativeReferenceAcquisition(
            "https://github.com/example/reference-skills.git",
            "main",
            "a" * 40,
            native_snapshot(),
        )
        first = plan_native_promotion(
            initial,
            registry_entry(),
            acquisition,
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
        )
        assert isinstance(first, Ok)
        current = project_registry_mutation(initial, first.value)
        assert isinstance(current, Ok)
        rereviewed = registry_entry()
        rereviewed = replace(
            rereviewed,
            review=replace(rereviewed.review, policy="stronger-review-v2"),
        )
        review_plan = plan_registry_entry_add(current.value, rereviewed)
        assert isinstance(review_plan, Ok)
        reviewed = project_registry_mutation(current.value, review_plan.value)
        assert isinstance(reviewed, Ok)

        promotion = plan_native_promotion(
            reviewed.value,
            rereviewed,
            acquisition,
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
        )
        assert isinstance(promotion, Ok), promotion
        projected = project_registry_mutation(reviewed.value, promotion.value)
        assert isinstance(projected, Ok)
        files = {str(item.path): item.content for item in projected.value.entries}
        lock = parse_registry_lock(files["aart.lock.json"])
        assert isinstance(lock, Ok)
        self.assertEqual(lock.value.entries[0][1].review.policy, "stronger-review-v2")

    def test_promotion_preserves_registry_owned_packages_without_copying_them(self) -> None:
        current = registry_with_owned_package()
        result = plan_native_promotion(
            current,
            registry_entry(name="other"),
            NativeReferenceAcquisition(
                "https://github.com/example/reference-skills.git",
                "main",
                "b" * 40,
                renamed_native_snapshot("other"),
            ),
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
        )
        assert isinstance(result, Ok), result
        projected = project_registry_mutation(current, result.value)
        assert isinstance(projected, Ok), projected
        files = {str(item.path): item.content for item in projected.value.entries}
        index = parse_registry_index(files["aart.index.json"])
        assert isinstance(index, Ok), index
        self.assertEqual(
            {str(item.identity) for item in index.value.artifacts},
            {"skill/code-review", "skill/other"},
        )
        self.assertFalse(
            any(str(change.path).startswith("artifacts/") for change in result.value.changes)
        )

    def test_promotion_compiles_registry_collections_with_the_new_reference(self) -> None:
        current = empty_registry_snapshot()
        source_file = next(item for item in current.entries if str(item.path) == "aart-source.json")
        source = json.loads(source_file.content)
        source["collection_roots"] = ["collections"]
        current = replace_snapshot_file(
            current,
            "aart-source.json",
            json.dumps(source).encode(),
        )
        current = append_snapshot_file(
            current,
            "collections/essentials.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "name": "essentials",
                    "summary": "Reviewed essentials.",
                    "artifacts": [{"type": "skill", "name": "code-review"}],
                    "collections": [],
                }
            ).encode(),
        )
        result = plan_native_promotion(
            current,
            registry_entry(),
            NativeReferenceAcquisition(
                "https://github.com/example/reference-skills.git",
                "main",
                "a" * 40,
                native_snapshot(),
            ),
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
        )
        assert isinstance(result, Ok), result
        projected = project_registry_mutation(current, result.value)
        assert isinstance(projected, Ok)
        files = {str(item.path): item.content for item in projected.value.entries}
        index = parse_registry_index(files["aart.index.json"])
        assert isinstance(index, Ok)
        self.assertEqual(index.value.artifacts[0].collections, ("essentials",))


if __name__ == "__main__":
    unittest.main()
