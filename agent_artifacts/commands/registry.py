"""Maintainer registry commands over pure plans and reviewed filesystem effects."""

from __future__ import annotations

import json
import os

from agent_artifacts import command_outcome as _common
from agent_artifacts.curation.model import (
    DEFAULT_MAXIMUM_AART,
    DEFAULT_MINIMUM_AART,
    CurationAction,
    CurationOutcome,
    CurationRequest,
    CurationReview,
    render_curation_outcome,
    render_curation_review,
)
from agent_artifacts.curation.runtime import (
    default_native_acquirer,
    load_local_curation_service,
)
from agent_artifacts.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    Severity,
    diagnostic_to_data,
)
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.io.registry_workspace import FilesystemRegistryWorkspace
from agent_artifacts.model import Request
from agent_artifacts.protocol.native_tree import SnapshotEntryKind, SourceSnapshot
from agent_artifacts.protocol.registry_models import RegistryManifest
from agent_artifacts.protocol.registry_schema import parse_registry_manifest
from agent_artifacts.protocol.semver import SemVer, parse_semver
from agent_artifacts.registry_commands.model import RegistryQualityReport
from agent_artifacts.registry_commands.planning import (
    audit_registry_workspace,
    test_registry_compatibility,
    validate_registry_workspace,
)
from agent_artifacts.runtime_contract import EXECUTABLE_CAPABILITIES, EXECUTABLE_VERSION

_VERSION = EXECUTABLE_VERSION
_CAPABILITIES = EXECUTABLE_CAPABILITIES
REGISTRY_COMMAND_INVALID = DiagnosticCode("registry-command-invalid")


# `RS-09`: what an operator does next after this module refuses. The planning module carries the
# same idea for the refusals it raises; these are the ones raised before planning is reached, where
# the problem is the invocation rather than the workspace.
_READ_THE_ACTIONS = ("`aart registry --help` lists the actions this command accepts",)
_NAME_THE_ARTIFACT = (
    "name exactly one artifact kind and name, in the form the action's own `--help` shows",
)
_INITIALIZE = (
    "point `--source` at a registry checkout, or create one with "
    "`aart registry init --source-id SLUG --display-name NAME --yes`",
)
_STATE_THE_RELEASE = (
    "state the release to test against: `aart registry test --latest-version VERSION`",
)
_MINIMUM_VERSION = (
    "record a minimum AART version in `aart-registry.json` — `requires_aart.min_inclusive` — then "
    "`aart registry test`",
)


def _error(message: str, remediation: tuple[str, ...]) -> Err:
    return Err(
        (Diagnostic(REGISTRY_COMMAND_INVALID, Severity.ERROR, message, remediation=remediation),)
    )


def _root(request: Request) -> str:
    return os.path.abspath(request.source_dir or ".")


def _version(raw: str | None, label: str) -> Result[SemVer]:
    if raw is None:
        return _error(f"{label} is required", _STATE_THE_RELEASE)
    parsed = parse_semver(raw)
    if isinstance(parsed, Err):
        return _error(f"{label} must be canonical SemVer", _STATE_THE_RELEASE)
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
        "changes": [{"path": item.path, "status": item.status} for item in review.changes],
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


def _emit_curation_finalization(
    request: Request,
    review: CurationReview,
    outcome: CurationOutcome,
) -> None:
    if request.json:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "ok": outcome.status != "failed",
                    "operation": f"registry.{outcome.action.value}",
                    "phase": "finalized",
                    "review": _curation_review_data(review),
                    "outcome": _curation_outcome_data(outcome),
                },
                indent=2,
            )
        )
        return
    _emit_curation_review(request, review)
    _emit_curation_outcome(request, outcome)


def _curation_request(request: Request, action: CurationAction) -> Result[CurationRequest]:
    if action in {
        CurationAction.PROMOTE_NATIVE,
        CurationAction.REFRESH_NATIVE,
        CurationAction.VENDOR,
        CurationAction.REVENDOR,
    } and (request.artifact_kind is None or len(request.names) != 1):
        return _error(
            f"{action.value} requires an exact artifact kind and name", _NAME_THE_ARTIFACT
        )
    try:
        return Ok(
            CurationRequest(
                action,
                _root(request),
                kind=request.artifact_kind,
                name=request.names[0] if len(request.names) == 1 else None,
                summary=request.summary,
                # Re-vendoring is the one action where an unstated version is an answer rather
                # than a gap: it means "tell me what moved, plan nothing".
                artifact_version=(
                    request.artifact_version
                    if action is CurationAction.REVENDOR
                    else request.artifact_version or "1.0.0"
                ),
                artifact_license=request.artifact_license,
                profiles=request.profiles,
                platforms=request.registry_platforms,
                scopes=request.registry_scopes or ("project",),
                modes=request.registry_modes or ("copy",),
                url=request.native_url,
                ref=request.ref or "main",
                path=request.native_path,
                setup_recipe=request.setup_recipe,
                review_policy=request.review_policy or "manual-review-v1",
                source_id=request.source_id,
                display_name=request.display_name,
                # `RS-02`: only `init` declares a compatibility window, and only `init` reads one
                # back, so every other action arrives here with both unset.  The substitute has to
                # be the window of the AART that is running -- literals bound a registry to the
                # release they were typed in, and `1.0.0`/`2.0.0` had already stopped a major
                # short of the executable stamping them.
                minimum_version=request.minimum_version or DEFAULT_MINIMUM_AART,
                maximum_version=request.maximum_version or DEFAULT_MAXIMUM_AART,
            )
        )
    except ValueError as error:
        return _error(str(error), _READ_THE_ACTIONS)


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
    if request.check:
        _emit_curation_review(request, review)
        # A failed check counts as drift.  Without this, `revendor --check` against an unreachable
        # upstream would exit zero for having written nothing, which is the one reading design §6
        # forbids.
        return (
            _common.OK
            if all(item.status == "unchanged" for item in review.changes)
            and all(item.passed for item in review.checks)
            else _common.ERROR
        )
    if not request.yes:
        _emit_curation_review(request, review)
        return _common.OK
    finalized = service.value.finalize(prepared.value, review.review_digest)
    if isinstance(finalized, Err):
        return _emit_error(request, action.value, finalized)
    _emit_curation_finalization(request, review, finalized.value)
    return _common.OK if finalized.value.status != "failed" else _common.ERROR


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
            # `RS-09`: the JSON envelope carried remediation through `diagnostic_to_data` all along
            # and this renderer dropped it, which is `LAF-52`'s shape one command family over. A
            # report is where `validate` and `audit` state a refusal, so it renders the next step
            # exactly as `_emit_error` does.
            for remediation in diagnostic.remediation:
                print(f"    remediation: {remediation}")


def _snapshot(workspace: FilesystemRegistryWorkspace) -> Result[SourceSnapshot]:
    return workspace.snapshot()


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
        # The audit reads the committed workspace and nothing else unless asked: `--check-upstream`
        # is what turns it into a command that resolves vendored origins, and it still only reports.
        upstream_acquirer=default_native_acquirer if request.check_upstream else None,
    )
    if isinstance(checked, Err):
        return _emit_error(request, "audit", checked)
    _emit_report(request, "audit", checked.value)
    return _common.OK if checked.value.passed else _common.ERROR


def _registry_manifest(snapshot: SourceSnapshot) -> Result[RegistryManifest]:
    for item in snapshot.entries:
        if str(item.path) == "aart-registry.json" and item.kind is SnapshotEntryKind.FILE:
            return parse_registry_manifest(item.content)
    return _error("registry workspace requires aart-registry.json", _INITIALIZE)


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
            _error("registry compatibility tests require a minimum AART version", _MINIMUM_VERSION),
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
    if action == "vendor":
        return _run_curation(request, CurationAction.VENDOR)
    if action == "revendor":
        return _run_curation(request, CurationAction.REVENDOR)
    if action in {"lock", "build"}:
        return _run_curation(request, CurationAction(action))
    if action == "validate":
        return _run_validate(request, workspace)
    if action == "audit":
        return _run_audit(request, workspace)
    if action == "test":
        return _run_test(request, workspace)
    if action == "diff":
        return _run_curation(request, CurationAction.DIFF)
    return _emit_error(request, action, _error("unknown registry action", _READ_THE_ACTIONS))
