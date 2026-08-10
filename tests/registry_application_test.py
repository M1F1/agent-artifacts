from __future__ import annotations

import unittest

from agent_artifacts.application.registry_commands import (
    finalize_registry_workspace,
    prepare_registry_format,
    prepare_registry_init,
)
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.registry_commands.model import (
    RegistryApplyCommand,
    RegistryApplyReceipt,
    RegistryInitOptions,
)
from agent_artifacts.registry_commands.planning import project_registry_workspace_plan


class MemoryWorkspace:
    def __init__(self) -> None:
        self.snapshot = SourceSnapshot(SnapshotOrigin.LOCAL, ())
        self.applied = 0

    def current(self):
        return Ok(self.snapshot)

    def apply(self, command: RegistryApplyCommand):
        projected = project_registry_workspace_plan(self.snapshot, command.plan)
        if isinstance(projected, Err):
            return projected
        self.snapshot = projected.value
        self.applied += 1
        return Ok(
            RegistryApplyReceipt(
                command.plan.review_digest,
                command.plan.next_snapshot_digest,
                command.plan.changed_paths,
            )
        )


class RegistryApplicationTest(unittest.TestCase):
    def options(self) -> RegistryInitOptions:
        return RegistryInitOptions(
            "company-registry",
            "Company Registry",
            SemVer(1, 0, 0),
            SemVer(2, 0, 0),
        )

    def test_prepare_is_read_only_and_finalize_applies_only_exact_reviewed_plan(self) -> None:
        workspace = MemoryWorkspace()
        plan = prepare_registry_init(self.options(), output=workspace)
        assert isinstance(plan, Ok), plan
        self.assertEqual(workspace.applied, 0)

        forged = ObjectDigest("sha256", "f" * 64)
        self.assertIsInstance(
            finalize_registry_workspace(plan.value, forged, output=workspace),
            Err,
        )
        self.assertEqual(workspace.applied, 0)

        applied = finalize_registry_workspace(
            plan.value,
            plan.value.review_digest,
            output=workspace,
        )
        assert isinstance(applied, Ok), applied
        self.assertEqual(workspace.applied, 1)

    def test_finalize_rejects_a_receipt_that_does_not_match_the_reviewed_plan(self) -> None:
        class ForgingWorkspace(MemoryWorkspace):
            def apply(self, command: RegistryApplyCommand):
                return Ok(
                    RegistryApplyReceipt(
                        command.plan.review_digest,
                        command.plan.expected_snapshot_digest,
                        command.plan.changed_paths,
                    )
                )

        workspace = ForgingWorkspace()
        plan = prepare_registry_init(self.options(), output=workspace)
        assert isinstance(plan, Ok)
        self.assertIsInstance(
            finalize_registry_workspace(
                plan.value,
                plan.value.review_digest,
                output=workspace,
            ),
            Err,
        )

    def test_no_op_finalize_rechecks_the_exact_workspace_snapshot(self) -> None:
        workspace = MemoryWorkspace()
        initialized = prepare_registry_init(self.options(), output=workspace)
        assert isinstance(initialized, Ok)
        applied = finalize_registry_workspace(
            initialized.value,
            initialized.value.review_digest,
            output=workspace,
        )
        assert isinstance(applied, Ok)
        formatted = prepare_registry_format(output=workspace)
        assert isinstance(formatted, Ok)
        self.assertEqual(formatted.value.changed_paths, 0)
        path = parse_relative_path("artifacts")
        assert isinstance(path, Ok)
        workspace.snapshot = SourceSnapshot(
            workspace.snapshot.origin,
            (*workspace.snapshot.entries, SnapshotEntry(path.value, SnapshotEntryKind.DIRECTORY)),
        )

        finalized = finalize_registry_workspace(
            formatted.value,
            formatted.value.review_digest,
            output=workspace,
        )

        self.assertIsInstance(finalized, Err)
        self.assertEqual(workspace.applied, 1)


if __name__ == "__main__":
    unittest.main()
