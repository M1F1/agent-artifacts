from __future__ import annotations

import unittest

from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.registry_schema import parse_registry_entry
from agent_artifacts.registry_maintenance.model import RegistryChangeKind
from agent_artifacts.registry_maintenance.planning import (
    plan_registry_entry_add,
    project_registry_mutation,
)
from tests.registry_maintenance_fixtures import (
    append_snapshot_file,
    empty_registry_snapshot,
    registry_entry,
)


class RegistryEntryAddTest(unittest.TestCase):
    def test_entry_add_is_deterministic_reviewed_and_never_copies_payload(self) -> None:
        snapshot = empty_registry_snapshot()
        first = plan_registry_entry_add(snapshot, registry_entry())
        second = plan_registry_entry_add(snapshot, registry_entry())
        assert isinstance(first, Ok), first
        self.assertEqual(first, second)
        self.assertEqual(len(first.value.changes), 1)
        change = first.value.changes[0]
        self.assertEqual(str(change.path), "entries/skill/code-review.json")
        self.assertEqual(change.kind, RegistryChangeKind.ADDED)
        self.assertNotIn(b"# Code review", change.content)

        projected = project_registry_mutation(snapshot, first.value)
        assert isinstance(projected, Ok), projected
        entry_file = next(
            item
            for item in projected.value.entries
            if str(item.path) == "entries/skill/code-review.json"
        )
        self.assertEqual(parse_registry_entry(entry_file.content), Ok(registry_entry()))

    def test_pending_entry_can_be_authored_before_it_is_promoted(self) -> None:
        pending = registry_entry(review_status="pending")
        result = plan_registry_entry_add(empty_registry_snapshot(), pending)
        assert isinstance(result, Ok), result
        self.assertEqual(result.value.changed_paths, 1)

    def test_projection_rejects_a_changed_generated_target(self) -> None:
        snapshot = empty_registry_snapshot()
        result = plan_registry_entry_add(snapshot, registry_entry())
        assert isinstance(result, Ok)
        stale = append_snapshot_file(
            snapshot,
            "entries/skill/code-review.json",
            b"{}",
        )
        self.assertIsInstance(project_registry_mutation(stale, result.value), Err)


if __name__ == "__main__":
    unittest.main()
