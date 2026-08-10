"""Maintainer registry commands over pure plans and reviewed filesystem effects."""

from __future__ import annotations

import json
import os
import tempfile
from urllib.parse import urlsplit

from agent_artifacts.application.registry_commands import (
    finalize_registry_workspace,
    prepare_artifact_scaffold,
    prepare_registry_build,
    prepare_registry_format,
    prepare_registry_init,
    prepare_registry_lock,
)
from agent_artifacts.configuration.model import ConfiguredSource, SourceKind
from agent_artifacts.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    Severity,
    diagnostic_to_data,
)
from agent_artifacts.domain.identifiers import SourceAlias, SourceId
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.importers.legacy_catalog import LegacyCatalogOptions
from agent_artifacts.importers.model import ImporterInput, ImportOrigin
from agent_artifacts.io.registry_workspace import FilesystemRegistryWorkspace
from agent_artifacts.model import Request
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.native_tree import SnapshotEntryKind, SourceSnapshot
from agent_artifacts.protocol.registry_models import RegistryEntry, RegistryManifest
from agent_artifacts.protocol.registry_schema import (
    parse_registry_entry,
    parse_registry_manifest,
)
from agent_artifacts.protocol.semver import SemVer, parse_semver
from agent_artifacts.registry_commands.migration import plan_legacy_registry_migration
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
from agent_artifacts.sources.git import acquire_git_snapshot
from agent_artifacts.sources.model import (
    GitSnapshotRequest,
    SnapshotLimits,
    SourceCandidate,
    source_instance_id,
)

from . import _common

_VERSION = SemVer(1, 0, 0)
_CAPABILITIES = tuple(
    Capability(value)
    for value in (
        "artifact-manifest-v1",
        "keychain-secret",
        "lockfile-v1",
        "managed-file",
        "open-browser",
        "registry-entry-v1",
    )
)
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
        request.type_filter is None
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
            request.type_filter,
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
    checked = audit_registry_workspace(current.value)
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


def _legacy_acquisition(request: Request) -> Result[ImporterInput]:
    assert request.legacy_source is not None
    location = request.legacy_source
    parsed = urlsplit(location)
    is_remote = parsed.scheme in {"https", "ssh"} or location.startswith("git@")
    if not is_remote:
        location = os.path.abspath(location)
        if request.origin_url is None:
            return _error(
                "local --legacy-source requires --origin-url for honest provenance metadata"
            )
    origin_url = request.legacy_source if is_remote else request.origin_url
    assert origin_url is not None
    with tempfile.TemporaryDirectory(prefix="aart-legacy-source-") as temporary:
        temporary = os.path.abspath(temporary)
        acquired = _candidate(
            location,
            request.ref or "HEAD",
            alias="legacy-migration-source",
            mirror=os.path.join(temporary, "mirror.git"),
            temporary_root=os.path.join(temporary, "tmp"),
            allow_local_transport=not is_remote,
        )
        if isinstance(acquired, Err):
            return acquired
        try:
            origin = ImportOrigin(
                origin_url,
                acquired.value.resolved_revision,
                None,
            )
            return Ok(ImporterInput(origin, acquired.value.snapshot))
        except ValueError as error:
            return _error(str(error))


def _run_migrate(request: Request, workspace: FilesystemRegistryWorkspace) -> int:
    version = _version(request.artifact_version, "--artifact-version")
    if isinstance(version, Err):
        return _emit_error(request, "migrate", version)
    if (
        request.legacy_source is None
        or request.source_id is None
        or request.display_name is None
        or not request.profiles
    ):
        return _emit_error(
            request,
            "migrate",
            _error("legacy source, source ID, display name, and profiles are required"),
        )
    acquired = _legacy_acquisition(request)
    if isinstance(acquired, Err):
        return _emit_error(request, "migrate", acquired)
    try:
        options = LegacyCatalogOptions(
            SourceId(request.source_id),
            request.display_name,
            version.value,
            request.profiles,
            request.registry_platforms,
        )
    except ValueError as error:
        return _emit_error(request, "migrate", _error(str(error)))
    planned = plan_legacy_registry_migration(
        acquired.value,
        options,
        display_name=request.display_name,
        executable_version=_VERSION,
    )
    if isinstance(planned, Err):
        return _emit_error(request, "migrate", planned)
    current = workspace.snapshot()
    if isinstance(current, Err):
        return _emit_error(request, "migrate", current)
    if current.value != planned.value.current:
        return _emit_error(
            request,
            "migrate",
            _error("legacy migration destination must contain no managed registry files"),
        )
    if not request.apply:
        _emit_plan(request, "migrate", planned.value.plan, applied=False)
        return _common.OK
    return _apply_or_check(
        request,
        "migrate",
        workspace,
        planned.value.plan,
        check_only=False,
    )


def run(request: Request) -> int:
    action = request.registry_action or "unknown"
    workspace = FilesystemRegistryWorkspace(_root(request))
    if action == "init":
        return _run_init(request, workspace)
    if action == "scaffold":
        return _run_scaffold(request, workspace)
    if action == "format":
        return _run_format(request, workspace)
    if action in {"lock", "build"}:
        return _run_generated(request, workspace, action)
    if action == "validate":
        return _run_validate(request, workspace)
    if action == "audit":
        return _run_audit(request, workspace)
    if action == "test":
        return _run_test(request, workspace)
    if action == "diff":
        return _run_diff(request, workspace)
    if action == "migrate":
        return _run_migrate(request, workspace)
    return _emit_error(request, action, _error("unknown registry action"))
