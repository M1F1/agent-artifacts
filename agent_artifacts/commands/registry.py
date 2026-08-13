"""Maintainer registry commands over pure plans and reviewed filesystem effects."""

from __future__ import annotations

import json
import os
import tempfile

from agent_artifacts.application.registry_commands import (
    finalize_registry_workspace,
    prepare_artifact_scaffold,
    prepare_registry_build,
    prepare_registry_format,
    prepare_registry_init,
    prepare_registry_lock,
)
from agent_artifacts.curation.model import (
    CurationAction,
    CurationOutcome,
    CurationRequest,
    CurationReview,
    render_curation_outcome,
    render_curation_review,
)
from agent_artifacts.curation.runtime import load_local_curation_service
from agent_artifacts.configuration.model import ConfiguredSource, SourceKind
from agent_artifacts.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    Severity,
    diagnostic_to_data,
)
from agent_artifacts.domain.identifiers import SourceAlias, SourceId
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.io.registry_workspace import FilesystemRegistryWorkspace
from agent_artifacts.model import Request
from agent_artifacts.protocol.native_tree import SnapshotEntryKind, SourceSnapshot
from agent_artifacts.protocol.registry_models import RegistryEntry, RegistryManifest
from agent_artifacts.protocol.registry_schema import (
    parse_registry_entry,
    parse_registry_manifest,
)
from agent_artifacts.protocol.semver import SemVer, parse_semver
from agent_artifacts.registry_commands.model import (
    ArtifactScaffoldOptions,
    RegistryInitOptions,
    RegistryQualityReport,
    RegistryWorkspacePlan,
)
from agent_artifacts.registry_commands.planning import (
    audit_registry_workspace,
    test_registry_compatibility,
    validate_registry_workspace,
)
from agent_artifacts.registry_maintenance.model import NativeReferenceAcquisition
from agent_artifacts.runtime_contract import EXECUTABLE_CAPABILITIES, EXECUTABLE_VERSION
from agent_artifacts.sources.git import acquire_git_snapshot
from agent_artifacts.sources.model import (
    GitSnapshotRequest,
    SnapshotLimits,
    SourceCandidate,
    source_instance_id,
)

from agent_artifacts import command_outcome as _common

_VERSION = EXECUTABLE_VERSION
_CAPABILITIES = EXECUTABLE_CAPABILITIES
REGISTRY_COMMAND_INVALID = DiagnosticCode("registry-command-invalid")


def _error(message: str) -> Err:
    return Err((Diagnostic(REGISTRY_COMMAND_INVALID, Severity.ERROR, message),))


def _root(request: Request) -> str:
    return os.path.abspath(request.source_dir or ".")


def _version(raw: str | None, label: str) -> Result[SemVer]:
    if raw is None:
        return _error(f"{label} is required")
    parsed = parse_semver(raw)
    if isinstance(parsed, Err):
        return _error(f"{label} must be canonical SemVer")
    return parsed


def _emit_error(request: Request, action: str, result: Err) -> int:
    if request.json:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "ok": False,
                    "operation": f"registry.{action}",
                    "diagnostics": [diagnostic_to_data(item) for item in result.diagnostics],
                },
                indent=2,
            )
        )
    else:
        for diagnostic in result.diagnostics:
            print(f"{diagnostic.severity.value}: {diagnostic.message}")
            for remediation in diagnostic.remediation:
                print(f"  remediation: {remediation}")
    return _common.ERROR


def _curation_review_data(review: CurationReview) -> dict[str, object]:
    return {
        "schema_version": 1,
        "ok": True,
        "operation": f"registry.{review.action.value}",
        "phase": "review",
        "applied": False,
        "mutating": review.mutating,
        "review_digest": str(review.review_digest),
        "snapshot_digest": str(review.snapshot_digest),
        "changes": [
            {"path": item.path, "status": item.status} for item in review.changes
        ],
        "checks": [
            {"name": item.name, "passed": item.passed, "details": list(item.details)}
            for item in review.checks
        ],
        "warnings": list(review.warnings),
        "follow_up_commands": list(review.follow_up_commands),
    }


def _curation_outcome_data(outcome: CurationOutcome) -> dict[str, object]:
    return {
        "schema_version": 1,
        "ok": outcome.status != "failed",
        "operation": f"registry.{outcome.action.value}",
        "phase": "finalized",
        "status": outcome.status,
        "changed_paths": outcome.changed_paths,
        "observed_paths": outcome.observed_paths,
        "checks": [
            {"name": item.name, "passed": item.passed, "details": list(item.details)}
            for item in outcome.checks
        ],
        "warnings": list(outcome.warnings),
        "follow_up_commands": list(outcome.follow_up_commands),
    }


def _emit_curation_review(request: Request, review: CurationReview) -> None:
    if request.json:
        print(json.dumps(_curation_review_data(review), indent=2))
        return
    print("\n".join(render_curation_review(review)))


def _emit_curation_outcome(request: Request, outcome: CurationOutcome) -> None:
    if request.json:
        print(json.dumps(_curation_outcome_data(outcome), indent=2))
        return
    print("\n".join(render_curation_outcome(outcome)))


def _curation_request(request: Request, action: CurationAction) -> Result[CurationRequest]:
    if action in {CurationAction.PROMOTE_NATIVE, CurationAction.REFRESH_NATIVE} and (
        request.artifact_kind is None or len(request.names) != 1
    ):
        return _error(f"{action.value} requires an exact artifact kind and name")
    try:
        return Ok(
            CurationRequest(
                action,
                _root(request),
                kind=request.artifact_kind,
                name=request.names[0] if len(request.names) == 1 else None,
                summary=request.summary,
                artifact_version=request.artifact_version or "1.0.0",
                profiles=request.profiles,
                platforms=request.registry_platforms,
                scopes=request.registry_scopes or ("project",),
                modes=request.registry_modes or ("copy",),
                url=request.native_url,
                ref=request.ref or "main",
                path=request.native_path,
                review_policy=request.review_policy or "manual-review-v1",
                source_id=request.source_id,
                display_name=request.display_name,
                minimum_version=request.minimum_version or "1.0.0",
                maximum_version=request.maximum_version or "2.0.0",
            )
        )
    except ValueError as error:
        return _error(str(error))


def _run_curation(request: Request, action: CurationAction) -> int:
    curation_request = _curation_request(request, action)
    if isinstance(curation_request, Err):
        return _emit_error(request, action.value, curation_request)
    service = load_local_curation_service(_root(request))
    if isinstance(service, Err):
        return _emit_error(request, action.value, service)
    prepared = service.value.prepare(curation_request.value)
    if isinstance(prepared, Err):
        return _emit_error(request, action.value, prepared)
    review = prepared.value.review
    _emit_curation_review(request, review)
    if request.check:
        return (
            _common.OK
            if all(item.status == "unchanged" for item in review.changes)
            else _common.ERROR
        )
    if not request.yes:
        return _common.OK
    finalized = service.value.finalize(prepared.value, review.review_digest)
    if isinstance(finalized, Err):
        return _emit_error(request, action.value, finalized)
    _emit_curation_outcome(request, finalized.value)
    return _common.OK if finalized.value.status != "failed" else _common.ERROR


def _plan_data(action: str, plan: RegistryWorkspacePlan, *, applied: bool) -> dict[str, object]:
    return {
        "schema_version": 1,
        "ok": True,
        "operation": f"registry.{action}",
        "applied": applied,
        "changed_paths": plan.changed_paths,
        "review_digest": str(plan.review_digest),
        "changes": [
            {
                "path": str(change.path),
                "status": change.kind.value,
                "after_digest": str(change.after_digest),
            }
            for change in plan.changes
        ],
    }


def _emit_plan(
    request: Request,
    action: str,
    plan: RegistryWorkspacePlan,
    *,
    applied: bool,
) -> None:
    data = _plan_data(action, plan, applied=applied)
    if request.json:
        print(json.dumps(data, indent=2))
        return
    state = "applied" if applied else "planned"
    print(f"registry {action}: {state}; {plan.changed_paths} managed path(s) changed")
    for change in plan.changes:
        if change.kind.value != "unchanged":
            print(f"  {change.kind.value}: {change.path}")


def _emit_report(request: Request, action: str, report: RegistryQualityReport) -> None:
    if request.json:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "ok": report.passed,
                    "operation": f"registry.{action}",
                    "checks": [
                        {
                            "name": check.name,
                            "passed": check.passed,
                            "diagnostics": [diagnostic_to_data(item) for item in check.diagnostics],
                        }
                        for check in report.checks
                    ],
                },
                indent=2,
            )
        )
        return
    for check in report.checks:
        print(f"registry {check.name}: {'passed' if check.passed else 'failed'}")
        for diagnostic in check.diagnostics:
            print(f"  {diagnostic.severity.value}: {diagnostic.message}")


def _apply_or_check(
    request: Request,
    action: str,
    workspace: FilesystemRegistryWorkspace,
    plan: RegistryWorkspacePlan,
    *,
    check_only: bool,
) -> int:
    if check_only:
        _emit_plan(request, action, plan, applied=False)
        return _common.OK if plan.changed_paths == 0 else _common.ERROR
    applied = finalize_registry_workspace(
        plan,
        plan.review_digest,
        output=workspace,
    )
    if isinstance(applied, Err):
        return _emit_error(request, action, applied)
    _emit_plan(request, action, plan, applied=True)
    return _common.OK


def _snapshot(workspace: FilesystemRegistryWorkspace) -> Result[SourceSnapshot]:
    return workspace.snapshot()


def _parse_entry_files(snapshot: SourceSnapshot) -> Result[tuple[RegistryEntry, ...]]:
    entries: list[RegistryEntry] = []
    for item in snapshot.entries:
        raw = str(item.path)
        if not raw.startswith("entries/") or item.kind is not SnapshotEntryKind.FILE:
            continue
        parsed = parse_registry_entry(item.content, path=raw)
        if isinstance(parsed, Err):
            return parsed
        expected = f"entries/{parsed.value.identity.kind}/{parsed.value.identity.name}.json"
        if raw != expected:
            return _error(f"registry entry identity does not match its path: {raw}")
        if parsed.value.review.status != "approved":
            return _error(
                f"refusing to acquire an unapproved registry reference: {parsed.value.identity}"
            )
        entries.append(parsed.value)
    identities = tuple(item.identity for item in entries)
    if len(set(identities)) != len(identities):
        return _error("registry workspace contains duplicate entry identities")
    return Ok(tuple(sorted(entries, key=lambda item: str(item.identity))))


def _candidate(
    location: str,
    ref: str,
    *,
    alias: str,
    mirror: str,
    temporary_root: str,
    allow_local_transport: bool,
) -> Result[SourceCandidate]:
    configured = ConfiguredSource(
        SourceAlias(alias),
        SourceKind.SOURCE_GIT,
        location,
        ref,
        True,
    )
    return acquire_git_snapshot(
        GitSnapshotRequest(
            source_instance_id(configured),
            configured.alias,
            configured.location,
            ref,
            mirror,
            temporary_root,
            SnapshotLimits(),
            60,
            allow_local_transport,
        )
    )


def _acquire_references(
    snapshot: SourceSnapshot,
) -> Result[tuple[NativeReferenceAcquisition, ...]]:
    parsed = _parse_entry_files(snapshot)
    if isinstance(parsed, Err):
        return parsed
    acquisitions: list[NativeReferenceAcquisition] = []
    with tempfile.TemporaryDirectory(prefix="aart-registry-sources-") as temporary:
        temporary = os.path.abspath(temporary)
        for position, entry in enumerate(parsed.value):
            acquired = _candidate(
                entry.source.url,
                entry.source.ref,
                alias=f"registry-reference-{position}",
                mirror=os.path.join(temporary, f"mirror-{position}.git"),
                temporary_root=os.path.join(temporary, f"tmp-{position}"),
                allow_local_transport=False,
            )
            if isinstance(acquired, Err):
                return acquired
            acquisitions.append(
                NativeReferenceAcquisition(
                    entry.source.url,
                    entry.source.ref,
                    acquired.value.resolved_revision,
                    acquired.value.snapshot,
                )
            )
    return Ok(tuple(acquisitions))


def _run_init(request: Request, workspace: FilesystemRegistryWorkspace) -> int:
    minimum = _version(request.minimum_version, "--minimum-version")
    maximum = _version(request.maximum_version, "--maximum-version")
    if isinstance(minimum, Err):
        return _emit_error(request, "init", minimum)
    if isinstance(maximum, Err):
        return _emit_error(request, "init", maximum)
    if request.source_id is None or request.display_name is None:
        return _emit_error(request, "init", _error("source ID and display name are required"))
    try:
        options = RegistryInitOptions(
            request.source_id,
            request.display_name,
            minimum.value,
            maximum.value,
        )
    except ValueError as error:
        return _emit_error(request, "init", _error(str(error)))
    planned = prepare_registry_init(options, output=workspace)
    if isinstance(planned, Err):
        return _emit_error(request, "init", planned)
    return _apply_or_check(request, "init", workspace, planned.value, check_only=False)


def _run_scaffold(request: Request, workspace: FilesystemRegistryWorkspace) -> int:
    version = _version(request.artifact_version, "--artifact-version")
    if isinstance(version, Err):
        return _emit_error(request, "scaffold", version)
    if (
        request.artifact_kind is None
        or len(request.names) != 1
        or request.summary is None
        or not request.profiles
    ):
        return _emit_error(
            request,
            "scaffold",
            _error("kind, name, summary, and at least one profile are required"),
        )
    try:
        options = ArtifactScaffoldOptions(
            request.artifact_kind,
            request.names[0],
            version.value,
            request.summary,
            request.profiles,
            request.registry_platforms,
            request.registry_scopes,
            request.registry_modes,
        )
    except ValueError as error:
        return _emit_error(request, "scaffold", _error(str(error)))
    planned = prepare_artifact_scaffold(options, output=workspace)
    if isinstance(planned, Err):
        return _emit_error(request, "scaffold", planned)
    return _apply_or_check(request, "scaffold", workspace, planned.value, check_only=False)


def _run_format(request: Request, workspace: FilesystemRegistryWorkspace) -> int:
    planned = prepare_registry_format(output=workspace)
    if isinstance(planned, Err):
        return _emit_error(request, "format", planned)
    return _apply_or_check(
        request,
        "format",
        workspace,
        planned.value,
        check_only=request.check,
    )


def _run_generated(
    request: Request,
    workspace: FilesystemRegistryWorkspace,
    action: str,
) -> int:
    current = _snapshot(workspace)
    if isinstance(current, Err):
        return _emit_error(request, action, current)
    acquired = _acquire_references(current.value)
    if isinstance(acquired, Err):
        return _emit_error(request, action, acquired)
    if action == "lock":
        planned = prepare_registry_lock(
            acquired.value,
            executable_version=_VERSION,
            available_capabilities=_CAPABILITIES,
            output=workspace,
        )
    else:
        planned = prepare_registry_build(
            acquired.value,
            executable_version=_VERSION,
            available_capabilities=_CAPABILITIES,
            output=workspace,
        )
    if isinstance(planned, Err):
        return _emit_error(request, action, planned)
    return _apply_or_check(
        request,
        action,
        workspace,
        planned.value,
        check_only=request.check,
    )


def _run_validate(request: Request, workspace: FilesystemRegistryWorkspace) -> int:
    current = _snapshot(workspace)
    if isinstance(current, Err):
        return _emit_error(request, "validate", current)
    checked = validate_registry_workspace(
        current.value,
        executable_version=_VERSION,
        available_capabilities=_CAPABILITIES,
        require_compiled=request.strict or request.frozen,
    )
    if isinstance(checked, Err):
        return _emit_error(request, "validate", checked)
    _emit_report(request, "validate", checked.value)
    return _common.OK if checked.value.passed else _common.ERROR


def _run_audit(request: Request, workspace: FilesystemRegistryWorkspace) -> int:
    current = _snapshot(workspace)
    if isinstance(current, Err):
        return _emit_error(request, "audit", current)
    checked = audit_registry_workspace(
        current.value,
        executable_version=_VERSION,
        available_capabilities=_CAPABILITIES,
    )
    if isinstance(checked, Err):
        return _emit_error(request, "audit", checked)
    _emit_report(request, "audit", checked.value)
    return _common.OK if checked.value.passed else _common.ERROR


def _registry_manifest(snapshot: SourceSnapshot) -> Result[RegistryManifest]:
    for item in snapshot.entries:
        if str(item.path) == "aart-registry.json" and item.kind is SnapshotEntryKind.FILE:
            return parse_registry_manifest(item.content)
    return _error("registry workspace requires aart-registry.json")


def _run_test(request: Request, workspace: FilesystemRegistryWorkspace) -> int:
    current = _snapshot(workspace)
    if isinstance(current, Err):
        return _emit_error(request, "test", current)
    manifest = _registry_manifest(current.value)
    latest = _version(request.latest_version, "--latest-version")
    if isinstance(manifest, Err):
        return _emit_error(request, "test", manifest)
    if isinstance(latest, Err):
        return _emit_error(request, "test", latest)
    minimum = manifest.value.requires_aart.min_inclusive
    if minimum is None:
        return _emit_error(
            request,
            "test",
            _error("registry compatibility tests require a minimum AART version"),
        )
    checked = test_registry_compatibility(
        current.value,
        minimum=minimum,
        latest=latest.value,
        available_capabilities=_CAPABILITIES,
    )
    if isinstance(checked, Err):
        return _emit_error(request, "test", checked)
    selected = checked.value
    if request.compatibility in {"minimum", "latest"}:
        selected = RegistryQualityReport(
            tuple(item for item in selected.checks if item.name == request.compatibility)
        )
    _emit_report(request, "test", selected)
    return _common.OK if selected.passed else _common.ERROR


def _run_diff(request: Request, workspace: FilesystemRegistryWorkspace) -> int:
    planned = prepare_registry_format(output=workspace)
    if isinstance(planned, Err):
        return _emit_error(request, "diff", planned)
    _emit_plan(request, "diff", planned.value, applied=False)
    return _common.OK


def run(request: Request) -> int:
    action = request.registry_action or "unknown"
    workspace = FilesystemRegistryWorkspace(_root(request))
    if action == "init":
        return _run_curation(request, CurationAction.INIT)
    if action == "scaffold":
        return _run_curation(request, CurationAction.SCAFFOLD)
    if action == "format":
        return _run_curation(request, CurationAction.FORMAT)
    if action == "promote-native":
        return _run_curation(request, CurationAction.PROMOTE_NATIVE)
    if action == "refresh-native":
        return _run_curation(request, CurationAction.REFRESH_NATIVE)
    if action in {"lock", "build"}:
        return _run_curation(request, CurationAction(action))
    if action == "validate":
        return _run_validate(request, workspace)
    if action == "audit":
        return _run_audit(request, workspace)
    if action == "test":
        return _run_test(request, workspace)
    if action == "diff":
        return _run_diff(request, workspace)
    return _emit_error(request, action, _error("unknown registry action"))
