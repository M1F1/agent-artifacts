"""Deterministic legacy-catalog to registry migration planning."""

from __future__ import annotations

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.importers.legacy_catalog import (
    LegacyCatalogOptions,
    materialize_legacy_catalog,
    plan_legacy_catalog,
    scan_legacy_catalog,
    validate_legacy_import,
)
from agent_artifacts.importers.model import ImporterInput
from agent_artifacts.protocol.native_tree import SnapshotEntryKind, SnapshotOrigin, SourceSnapshot
from agent_artifacts.protocol.semver import SemVer

from .model import LegacyRegistryMigration, RegistryInitOptions, RegistryOperation
from .planning import (
    plan_registry_init,
    plan_registry_workspace_files,
    project_registry_workspace_plan,
)

REGISTRY_MIGRATION_INVALID = DiagnosticCode("registry-migration-invalid")


def plan_legacy_registry_migration(
    request: ImporterInput,
    options: LegacyCatalogOptions,
    *,
    display_name: str,
    executable_version: SemVer,
) -> Result[LegacyRegistryMigration]:
    """Convert a pinned legacy catalog into a new reviewable registry tree."""

    if display_name != options.display_name:
        return Err(
            (
                Diagnostic(
                    REGISTRY_MIGRATION_INVALID,
                    Severity.ERROR,
                    "registry and imported source display names must match",
                ),
            )
        )

    scanned = scan_legacy_catalog(request)
    if isinstance(scanned, Err):
        return scanned
    planned = plan_legacy_catalog(scanned.value, options)
    if isinstance(planned, Err):
        return planned
    materialized = materialize_legacy_catalog(request, planned.value)
    if isinstance(materialized, Err):
        return materialized
    validated = validate_legacy_import(
        materialized.value,
        executable_version=executable_version,
    )
    if isinstance(validated, Err):
        return validated
    current = SourceSnapshot(SnapshotOrigin.LOCAL, ())
    initialized = plan_registry_init(
        current,
        RegistryInitOptions(
            options.source_id.value,
            display_name,
            SemVer(1, 0, 0),
            SemVer(2, 0, 0),
        ),
    )
    if isinstance(initialized, Err):
        return initialized
    initial_snapshot = project_registry_workspace_plan(current, initialized.value)
    assert isinstance(initial_snapshot, Ok)
    desired = {
        str(item.path): (item.content, item.executable)
        for item in initial_snapshot.value.entries
        if item.kind is SnapshotEntryKind.FILE
    }
    desired.update(
        {
            str(item.path): (item.content, item.executable)
            for item in validated.value.materialized.snapshot.entries
            if item.kind is SnapshotEntryKind.FILE
        }
    )
    migration = plan_registry_workspace_files(
        RegistryOperation.MIGRATE,
        current,
        tuple((path, content, executable) for path, (content, executable) in desired.items()),
    )
    if isinstance(migration, Err):
        return migration
    return Ok(LegacyRegistryMigration(current, migration.value))
