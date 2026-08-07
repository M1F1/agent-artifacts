"""Maintainer-only importer orchestration through an injected output port."""

from __future__ import annotations

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.importers.legacy_catalog import (
    LegacyCatalogOptions,
    build_import_apply_plan,
    diff_legacy_import,
    materialize_legacy_catalog,
    plan_legacy_catalog,
    scan_legacy_catalog,
    validate_legacy_import,
)
from agent_artifacts.importers.model import AppliedImport, ImporterInput, PreparedImport
from agent_artifacts.importers.ports import ImportOutputPort
from agent_artifacts.protocol.semver import SemVer

IMPORT_INVALID = DiagnosticCode("import-invalid")
IMPORT_REVIEW_MISMATCH = DiagnosticCode("import-review-mismatch")


def _error(code: DiagnosticCode, message: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message),))


def prepare_legacy_import(
    request: ImporterInput,
    options: LegacyCatalogOptions,
    *,
    executable_version: SemVer,
    output: ImportOutputPort,
) -> Result[PreparedImport]:
    """Derive and validate output, then stage it without changing the destination."""

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
    current = output.current()
    if isinstance(current, Err):
        return current
    diff = diff_legacy_import(validated.value, current.value)
    if isinstance(diff, Err):
        return diff
    apply_plan = build_import_apply_plan(validated.value, diff.value)
    staged = output.stage(
        validated.value.materialized.snapshot,
        validated.value.materialized.output_digest,
    )
    if isinstance(staged, Err):
        return staged
    if staged.value.output_digest != apply_plan.output_digest:
        output.discard(staged.value)
        return _error(IMPORT_INVALID, "staged importer output digest does not match the plan")
    try:
        return Ok(PreparedImport(validated.value, apply_plan, staged.value))
    except ValueError as error:
        output.discard(staged.value)
        return _error(IMPORT_INVALID, str(error))


def finalize_legacy_import(
    prepared: PreparedImport,
    reviewed_digest: ObjectDigest,
    *,
    output: ImportOutputPort,
) -> Result[AppliedImport]:
    """Apply only the exact staged tree and destination precondition reviewed by the maintainer."""

    if reviewed_digest != prepared.apply_plan.review_digest:
        return _error(
            IMPORT_REVIEW_MISMATCH,
            "reviewed importer plan digest does not match the prepared plan",
        )
    changed_paths = sum(item.kind.value != "unchanged" for item in prepared.apply_plan.changes)
    if changed_paths == 0:
        discarded = output.discard(prepared.staged)
        if isinstance(discarded, Err):
            return discarded
        return Ok(
            AppliedImport(
                prepared.apply_plan.output_digest,
                0,
                ("canonical importer output already matches the destination",),
            )
        )
    applied = output.apply(
        prepared.staged,
        expected_destination_digest=prepared.apply_plan.expected_destination_digest,
        changed_paths=changed_paths,
    )
    if isinstance(applied, Err):
        output.discard(prepared.staged)
        return applied
    if applied.value.output_digest != prepared.apply_plan.output_digest:
        return _error(IMPORT_INVALID, "applied importer output digest does not match the plan")
    return applied
