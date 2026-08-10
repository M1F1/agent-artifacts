"""Application service for dry-run/apply/rollback of legacy installation state."""

from __future__ import annotations

from dataclasses import dataclass

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Result
from agent_artifacts.install_state.migration import plan_legacy_migration
from agent_artifacts.install_state.model import (
    InstallStatePaths,
    LegacyMigrationCandidate,
    MigrationReceipt,
    RollbackReceipt,
    StateMigrationPlan,
)
from agent_artifacts.install_state.ports import StateMigrationPort

STATE_MISSING = DiagnosticCode("legacy-state-missing")
STATE_BACKUP_COLLISION = DiagnosticCode("state-migration-backup-collision")
STATE_DESTINATION_OCCUPIED = DiagnosticCode("state-migration-destination-occupied")


@dataclass(frozen=True, slots=True)
class StateMigrationService:
    store: StateMigrationPort

    def prepare(
        self,
        paths: InstallStatePaths,
        candidates: tuple[LegacyMigrationCandidate, ...],
    ) -> Result[StateMigrationPlan]:
        """Read only the explicit legacy path and return an immutable reviewed plan."""

        content = self.store.read(paths.legacy_path)
        if isinstance(content, Err):
            return content
        if content.value is None:
            return Err(
                (
                    Diagnostic(
                        STATE_MISSING,
                        Severity.ERROR,
                        f"legacy installation state does not exist at {paths.legacy_path}",
                    ),
                )
            )
        for collision_index in range(10_001):
            planned = plan_legacy_migration(
                content.value,
                candidates,
                paths,
                collision_index=collision_index,
            )
            if isinstance(planned, Err):
                return planned
            backup = self.store.read(planned.value.backup_path)
            if isinstance(backup, Err):
                return backup
            journal = self.store.read(planned.value.journal_path)
            if isinstance(journal, Err):
                return journal
            if backup.value in {None, planned.value.legacy_content} and journal.value in {
                None,
                planned.value.journal_content,
            }:
                if paths.scope == "user":
                    destination = self.store.read(paths.destination_path)
                    if isinstance(destination, Err):
                        return destination
                    if destination.value not in {None, planned.value.replacement}:
                        return Err(
                            (
                                Diagnostic(
                                    STATE_DESTINATION_OCCUPIED,
                                    Severity.ERROR,
                                    "user installation-state destination already contains "
                                    "unrelated state",
                                ),
                            )
                        )
                    if (
                        destination.value == planned.value.replacement
                        and backup.value != planned.value.legacy_content
                    ):
                        return Err(
                            (
                                Diagnostic(
                                    STATE_DESTINATION_OCCUPIED,
                                    Severity.ERROR,
                                    "user installation-state destination has no matching "
                                    "legacy backup",
                                ),
                            )
                        )
                return planned
        return Err(
            (
                Diagnostic(
                    STATE_BACKUP_COLLISION,
                    Severity.ERROR,
                    "migration backup collision limit was exceeded",
                ),
            )
        )

    def apply(self, plan: StateMigrationPlan) -> Result[MigrationReceipt]:
        return self.store.apply(plan)

    def rollback(self, receipt: MigrationReceipt) -> Result[RollbackReceipt]:
        return self.store.rollback(receipt)

    def current_receipt(self, paths: InstallStatePaths) -> Result[MigrationReceipt | None]:
        """Load a completed receipt from durable backup/journal evidence."""

        return self.store.current_receipt(paths)
