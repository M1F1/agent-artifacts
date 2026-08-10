"""Effect ports owned by the installation-state migration context."""

from __future__ import annotations

from typing import Protocol

from agent_artifacts.domain.result import Result

from .model import InstallStatePaths, MigrationReceipt, RollbackReceipt, StateMigrationPlan


class StateMigrationPort(Protocol):
    def read(self, path: str) -> Result[bytes | None]: ...

    def apply(self, plan: StateMigrationPlan) -> Result[MigrationReceipt]: ...

    def rollback(self, receipt: MigrationReceipt) -> Result[RollbackReceipt]: ...

    def current_receipt(self, paths: InstallStatePaths) -> Result[MigrationReceipt | None]: ...
