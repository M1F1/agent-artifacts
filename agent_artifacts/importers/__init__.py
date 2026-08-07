"""Closed built-in registry for maintainer-only source importers."""

from .legacy_catalog import (
    LEGACY_CATALOG_IMPORTER,
    LegacyCatalogOptions,
    build_import_apply_plan,
    diff_legacy_import,
    materialize_legacy_catalog,
    plan_legacy_catalog,
    scan_legacy_catalog,
    validate_legacy_import,
)
from .model import (
    ImportApplyPlan,
    ImportChange,
    ImportChangeKind,
    ImportDiff,
    ImporterDescriptor,
    ImporterInput,
    ImportOrigin,
    ImportPlan,
    ImportScan,
    LegacyArtifactCandidate,
    MaterializedImport,
    ValidatedImport,
)


def built_in_importers() -> tuple[ImporterDescriptor, ...]:
    return (LEGACY_CATALOG_IMPORTER,)


def find_importer(importer_id: str) -> ImporterDescriptor | None:
    return next((item for item in built_in_importers() if item.id == importer_id), None)


__all__ = [
    "LEGACY_CATALOG_IMPORTER",
    "ImportApplyPlan",
    "ImportChange",
    "ImportChangeKind",
    "ImportDiff",
    "ImportOrigin",
    "ImportPlan",
    "ImportScan",
    "ImporterDescriptor",
    "ImporterInput",
    "LegacyArtifactCandidate",
    "LegacyCatalogOptions",
    "MaterializedImport",
    "ValidatedImport",
    "build_import_apply_plan",
    "built_in_importers",
    "diff_legacy_import",
    "find_importer",
    "materialize_legacy_catalog",
    "plan_legacy_catalog",
    "scan_legacy_catalog",
    "validate_legacy_import",
]
