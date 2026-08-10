"""Installation manifest v2 and explicit legacy migration context."""

from .migration import plan_legacy_migration
from .model import (
    ArtifactEvidence,
    EffectProof,
    InstallationRecord,
    InstallState,
    InstallStatePaths,
    LegacyMigrationCandidate,
    MigrationReceipt,
    RollbackReceipt,
    SourceEvidence,
    StateMigrationPlan,
)
from .paths import install_state_paths
from .schema import install_state_bytes, install_state_to_json, parse_install_state

__all__ = [
    "ArtifactEvidence",
    "EffectProof",
    "InstallState",
    "InstallStatePaths",
    "InstallationRecord",
    "LegacyMigrationCandidate",
    "MigrationReceipt",
    "RollbackReceipt",
    "SourceEvidence",
    "StateMigrationPlan",
    "install_state_bytes",
    "install_state_paths",
    "install_state_to_json",
    "parse_install_state",
    "plan_legacy_migration",
]
