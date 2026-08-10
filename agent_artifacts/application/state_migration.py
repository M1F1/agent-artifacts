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
        return plan_legacy_migration(content.value, candidates, paths)

    def apply(self, plan: StateMigrationPlan) -> Result[MigrationReceipt]:
        return self.store.apply(plan)

    def rollback(self, receipt: MigrationReceipt) -> Result[RollbackReceipt]:
        return self.store.rollback(receipt)
