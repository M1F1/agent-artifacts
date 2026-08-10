"""Local checkout adapter for canonical, digest-bound Maintainer curation."""

from __future__ import annotations

import json
import os
import shlex
import tempfile
from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.parse import urlsplit

from agent_artifacts.application.registry_commands import (
    finalize_registry_workspace,
    prepare_artifact_scaffold,
    prepare_registry_build,
    prepare_registry_init,
    prepare_registry_lock,
)
from agent_artifacts.application.registry_maintenance import finalize_registry_mutation
from agent_artifacts.configuration.model import ConfiguredSource, SourceKind
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest, SourceAlias, SourceId
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.importers.legacy_catalog import LegacyCatalogOptions, scan_legacy_catalog
from agent_artifacts.importers.model import ImporterInput, ImportOrigin
from agent_artifacts.io.registry_workspace import FilesystemRegistryWorkspace
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.native_tree import SnapshotEntryKind, SourceSnapshot
from agent_artifacts.protocol.registry_models import RegistryEntry
from agent_artifacts.protocol.registry_schema import parse_registry_entry
from agent_artifacts.protocol.semver import SemVer, parse_semver
from agent_artifacts.registry_commands.migration import plan_legacy_registry_migration
from agent_artifacts.registry_commands.model import (
    ArtifactScaffoldOptions,
    RegistryInitOptions,
    RegistryOperation,
    RegistryQualityReport,
    RegistryWorkspaceChange,
    RegistryWorkspacePlan,
    WorkspaceChangeKind,
    registry_workspace_review_digest,
)
from agent_artifacts.registry_commands.model import (
    RegistryApplyCommand as WorkspaceApplyCommand,
)
from agent_artifacts.registry_commands.planning import (
    audit_registry_workspace,
    plan_registry_format,
    validate_registry_workspace,
)
from agent_artifacts.registry_maintenance.model import (
    NativeReferenceAcquisition,
    RegistryMutationPlan,
)
from agent_artifacts.registry_maintenance.model import (
    RegistryApplyCommand as MutationApplyCommand,
)
from agent_artifacts.registry_maintenance.model import (
    RegistryApplyReceipt as MutationApplyReceipt,
)
from agent_artifacts.registry_maintenance.planning import (
    check_native_upstream,
    plan_native_promotion,
    project_registry_mutation,
)
from agent_artifacts.sources.git import acquire_git_snapshot
from agent_artifacts.sources.model import (
    GitSnapshotRequest,
    SnapshotLimits,
    SourceCandidate,
    source_instance_id,
    source_snapshot_digest,
)

from .model import (
    CurationAction,
    CurationChange,
    CurationCheck,
    CurationOutcome,
    CurationOutcomeStatus,
    CurationRequest,
    CurationReview,
    curation_review_digest,
)

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
CURATION_INVALID = DiagnosticCode("curation-invalid")
CURATION_STALE = DiagnosticCode("curation-stale")

NativeAcquirer = Callable[[str, str], Result[NativeReferenceAcquisition]]
LegacyAcquirer = Callable[[CurationRequest], Result[ImporterInput]]


@dataclass(frozen=True, slots=True)
class _ReadOnlyPrepared:
    snapshot: SourceSnapshot
    checks: tuple[CurationCheck, ...]


@dataclass(frozen=True, slots=True)
class PreparedCuration:
    review: CurationReview
    payload: RegistryWorkspacePlan | RegistryMutationPlan | _ReadOnlyPrepared | SourceSnapshot


class CurationService(Protocol):
    def prepare(self, request: CurationRequest) -> Result[PreparedCuration]: ...

    def finalize(
        self,
        prepared: PreparedCuration,
        reviewed_digest: ObjectDigest,
    ) -> Result[CurationOutcome]: ...


def _error(message: str, *, stale: bool = False) -> Err:
    return Err(
        (
            Diagnostic(
                CURATION_STALE if stale else CURATION_INVALID,
                Severity.ERROR,
                message,
            ),
        )
    )


def _semver(raw: str, label: str) -> Result[SemVer]:
    parsed = parse_semver(raw)
    if isinstance(parsed, Err):
        return _error(f"{label} must be canonical SemVer")
    return parsed


def _snapshot_digest(snapshot: SourceSnapshot) -> Result[ObjectDigest]:
    digest = source_snapshot_digest(snapshot)
    if isinstance(digest, Err):
        return _error("registry workspace snapshot cannot be hashed")
    return digest


def _workspace_changes(plan: RegistryWorkspacePlan) -> tuple[CurationChange, ...]:
    return tuple(CurationChange(str(item.path), item.kind.value) for item in plan.changes)


def _mutation_changes(plan: RegistryMutationPlan) -> tuple[CurationChange, ...]:
    return tuple(CurationChange(str(item.path), item.kind.value) for item in plan.changes)


def _checks(report: RegistryQualityReport) -> tuple[CurationCheck, ...]:
    return tuple(
        CurationCheck(
            item.name,
            item.passed,
            tuple(
                f"{diagnostic.severity.value}: {diagnostic.message}"
                for diagnostic in item.diagnostics
            ),
        )
        for item in report.checks
    )


def _follow_up(
    workspace: str,
    changes: tuple[CurationChange, ...],
    action: CurationAction,
) -> tuple[str, ...]:
    quoted = shlex.quote(workspace)
    changed = tuple(item.path for item in changes if item.status != "unchanged")
    diff = f"git -C {quoted} diff --"
    if changed:
        diff = f"{diff} {' '.join(shlex.quote(path) for path in changed)}"
    if action in {
        CurationAction.INIT,
        CurationAction.SCAFFOLD,
        CurationAction.IMPORT_FOREIGN,
    }:
        return (
            diff,
            f"aart registry validate --source {quoted}",
            f"aart registry lock --source {quoted}",
            f"aart registry build --source {quoted}",
            f"aart registry audit --source {quoted}",
        )
    return (
        diff,
        f"aart registry validate --source {quoted} --strict",
        f"aart registry audit --source {quoted}",
    )


def _candidate(
    location: str,
    ref: str,
    *,
    alias: str,
    allow_local_transport: bool,
) -> Result[SourceCandidate]:
    with tempfile.TemporaryDirectory(prefix="aart-curation-source-") as temporary:
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
                os.path.join(temporary, "mirror.git"),
                os.path.join(temporary, "tmp"),
                SnapshotLimits(),
                60,
                allow_local_transport,
            )
        )


def _default_native_acquirer(url: str, ref: str) -> Result[NativeReferenceAcquisition]:
    acquired = _candidate(url, ref, alias="curation-native", allow_local_transport=False)
    if isinstance(acquired, Err):
        return acquired
    try:
        return Ok(
            NativeReferenceAcquisition(
                url,
                ref,
                acquired.value.resolved_revision,
                acquired.value.snapshot,
            )
        )
    except ValueError as error:
        return _error(str(error))


def _default_legacy_acquirer(request: CurationRequest) -> Result[ImporterInput]:
    assert request.legacy_source is not None
    location = request.legacy_source
    parsed = urlsplit(location)
    remote = parsed.scheme in {"https", "ssh"} or location.startswith("git@")
    if not remote:
        location = os.path.abspath(location)
        if request.origin_url is None:
            return _error("local legacy source requires an origin URL for honest provenance")
    origin_url = request.legacy_source if remote else request.origin_url
    assert origin_url is not None
    acquired = _candidate(
        location,
        request.ref,
        alias="curation-legacy",
        allow_local_transport=not remote,
    )
    if isinstance(acquired, Err):
        return acquired
    try:
        return Ok(
            ImporterInput(
                ImportOrigin(origin_url, acquired.value.resolved_revision, None),
                acquired.value.snapshot,
            )
        )
    except ValueError as error:
        return _error(str(error))


class _MutationWorkspace:
    """Adapt exact registry-input plans to the checkout's exact snapshot applier."""

    def __init__(
        self,
        workspace: FilesystemRegistryWorkspace,
        expected_snapshot_digest: ObjectDigest,
    ):
        self.workspace = workspace
        self.expected_snapshot_digest = expected_snapshot_digest

    def _verified_current(self) -> Result[SourceSnapshot]:
        current = self.workspace.current()
        if isinstance(current, Err):
            return current
        digest = _snapshot_digest(current.value)
        if isinstance(digest, Err):
            return digest
        if digest.value != self.expected_snapshot_digest:
            return _error("registry workspace changed after curation review", stale=True)
        return current

    def current(self) -> Result[SourceSnapshot]:
        return self._verified_current()

    def apply(self, command: MutationApplyCommand) -> Result[MutationApplyReceipt]:
        current = self._verified_current()
        if isinstance(current, Err):
            return current
        projected = project_registry_mutation(current.value, command.plan)
        if isinstance(projected, Err):
            return projected
        before = _snapshot_digest(current.value)
        after = _snapshot_digest(projected.value)
        if isinstance(before, Err):
            return before
        if isinstance(after, Err):
            return after
        changes = tuple(
            RegistryWorkspaceChange(
                item.path,
                WorkspaceChangeKind(item.kind.value),
                item.content,
                item.before_digest,
                item.after_digest,
            )
            for item in command.plan.changes
        )
        workspace_plan = RegistryWorkspacePlan(
            RegistryOperation.BUILD,
            before.value,
            after.value,
            changes,
            registry_workspace_review_digest(
                RegistryOperation.BUILD,
                before.value,
                after.value,
                changes,
            ),
        )
        applied = self.workspace.apply(WorkspaceApplyCommand(workspace_plan))
        if isinstance(applied, Err):
            return applied
        return Ok(
            MutationApplyReceipt(
                command.plan.review_digest,
                command.plan.next_inputs_digest,
                command.plan.changed_paths,
            )
        )


class LocalCurationService:
    """Prepare complete reviews and apply only their exact digest to one local checkout."""

    def __init__(
        self,
        workspace: str,
        *,
        native_acquirer: NativeAcquirer = _default_native_acquirer,
        legacy_acquirer: LegacyAcquirer = _default_legacy_acquirer,
    ):
        if not os.path.isabs(workspace) or os.path.normpath(workspace) != workspace:
            raise ValueError("curation workspace must be normalized and absolute")
        self.root = workspace
        self.workspace = FilesystemRegistryWorkspace(workspace)
        self.native_acquirer = native_acquirer
        self.legacy_acquirer = legacy_acquirer

    def _current(self) -> Result[SourceSnapshot]:
        return self.workspace.current()

    def _mutation_target(self) -> Result[None]:
        return self.workspace.verify_mutation_target()

    def _workspace_review(
        self,
        request: CurationRequest,
        plan: RegistryWorkspacePlan,
        *,
        warnings: tuple[str, ...] = (),
    ) -> PreparedCuration:
        changes = _workspace_changes(plan)
        return PreparedCuration(
            CurationReview(
                request.action,
                self.root,
                True,
                plan.review_digest,
                plan.expected_snapshot_digest,
                changes,
                warnings=warnings,
                follow_up_commands=_follow_up(self.root, changes, request.action),
            ),
            plan,
        )

    def _mutation_review(
        self,
        request: CurationRequest,
        plan: RegistryMutationPlan,
        snapshot: SourceSnapshot,
    ) -> Result[PreparedCuration]:
        digest = _snapshot_digest(snapshot)
        if isinstance(digest, Err):
            return digest
        changes = _mutation_changes(plan)
        return Ok(
            PreparedCuration(
                CurationReview(
                    request.action,
                    self.root,
                    True,
                    plan.review_digest,
                    digest.value,
                    changes,
                    follow_up_commands=_follow_up(self.root, changes, request.action),
                ),
                plan,
            )
        )

    def _prepare_init(self, request: CurationRequest) -> Result[PreparedCuration]:
        if request.source_id is None or request.display_name is None:
            return _error("init requires source ID and display name")
        minimum = _semver(request.minimum_version, "minimum version")
        maximum = _semver(request.maximum_version, "maximum version")
        if isinstance(minimum, Err):
            return minimum
        if isinstance(maximum, Err):
            return maximum
        try:
            options = RegistryInitOptions(
                request.source_id,
                request.display_name,
                minimum.value,
                maximum.value,
            )
        except ValueError as error:
            return _error(str(error))
        planned = prepare_registry_init(options, output=self.workspace)
        if isinstance(planned, Err):
            return planned
        return Ok(self._workspace_review(request, planned.value))

    def _prepare_scaffold(self, request: CurationRequest) -> Result[PreparedCuration]:
        if (
            request.kind is None
            or request.name is None
            or request.summary is None
            or not request.profiles
            or not request.platforms
        ):
            return _error("scaffold requires kind, name, summary, profiles, and platforms")
        version = _semver(request.artifact_version, "artifact version")
        if isinstance(version, Err):
            return version
        try:
            options = ArtifactScaffoldOptions(
                request.kind,
                request.name,
                version.value,
                request.summary,
                request.profiles,
                request.platforms,
                request.scopes,
                request.modes,
            )
        except ValueError as error:
            return _error(str(error))
        planned = prepare_artifact_scaffold(options, output=self.workspace)
        if isinstance(planned, Err):
            return planned
        return Ok(
            self._workspace_review(
                request,
                planned.value,
                warnings=("Review and complete the generated starter payload before publication.",),
            )
        )

    def _entry(self, request: CurationRequest) -> Result[RegistryEntry]:
        if None in (request.kind, request.name, request.url, request.path):
            return _error("native promotion requires kind, name, URL, ref, and package path")
        parsed = parse_registry_entry(
            json.dumps(
                {
                    "schema_version": 1,
                    "type": request.kind,
                    "name": request.name,
                    "source": {
                        "kind": "git",
                        "url": request.url,
                        "ref": request.ref,
                        "path": request.path,
                    },
                    "review": {"status": "approved", "policy": request.review_policy},
                }
            )
        )
        if isinstance(parsed, Err):
            return parsed
        return parsed

    def _prepare_promote(self, request: CurationRequest) -> Result[PreparedCuration]:
        current = self._current()
        entry = self._entry(request)
        if isinstance(current, Err):
            return current
        if isinstance(entry, Err):
            return entry
        acquired = self.native_acquirer(entry.value.source.url, entry.value.source.ref)
        if isinstance(acquired, Err):
            return acquired
        planned = plan_native_promotion(
            current.value,
            entry.value,
            acquired.value,
            executable_version=_VERSION,
            available_capabilities=_CAPABILITIES,
        )
        if isinstance(planned, Err):
            return planned
        return self._mutation_review(request, planned.value, current.value)

    def _entries(self, snapshot: SourceSnapshot) -> Result[tuple[RegistryEntry, ...]]:
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
            entries.append(parsed.value)
        return Ok(tuple(sorted(entries, key=lambda item: str(item.identity))))

    def _prepare_update(self, request: CurationRequest) -> Result[PreparedCuration]:
        if request.kind is None or request.name is None:
            return _error("upstream update requires an exact artifact kind and name")
        current = self._current()
        if isinstance(current, Err):
            return current
        entries = self._entries(current.value)
        if isinstance(entries, Err):
            return entries
        entry = next(
            (
                item
                for item in entries.value
                if item.identity.kind == request.kind and item.identity.name == request.name
            ),
            None,
        )
        if entry is None:
            return _error(f"registry has no native reference {request.kind}/{request.name}")
        acquired = self.native_acquirer(entry.source.url, entry.source.ref)
        if isinstance(acquired, Err):
            return acquired
        checked = check_native_upstream(
            current.value,
            entry,
            acquired.value,
            executable_version=_VERSION,
            available_capabilities=_CAPABILITIES,
        )
        if isinstance(checked, Err):
            return checked
        return self._mutation_review(request, checked.value.plan, current.value)

    def _acquire_entries(
        self, snapshot: SourceSnapshot
    ) -> Result[tuple[NativeReferenceAcquisition, ...]]:
        entries = self._entries(snapshot)
        if isinstance(entries, Err):
            return entries
        acquired: list[NativeReferenceAcquisition] = []
        for entry in entries.value:
            if entry.review.status != "approved":
                return _error(f"refusing to acquire unapproved reference {entry.identity}")
            result = self.native_acquirer(entry.source.url, entry.source.ref)
            if isinstance(result, Err):
                return result
            acquired.append(result.value)
        return Ok(tuple(acquired))

    def _prepare_generated(self, request: CurationRequest) -> Result[PreparedCuration]:
        current = self._current()
        if isinstance(current, Err):
            return current
        acquired = self._acquire_entries(current.value)
        if isinstance(acquired, Err):
            return acquired
        if request.action is CurationAction.LOCK:
            planned = prepare_registry_lock(
                acquired.value,
                executable_version=_VERSION,
                available_capabilities=_CAPABILITIES,
                output=self.workspace,
            )
        else:
            planned = prepare_registry_build(
                acquired.value,
                executable_version=_VERSION,
                available_capabilities=_CAPABILITIES,
                output=self.workspace,
            )
        if isinstance(planned, Err):
            return planned
        return Ok(self._workspace_review(request, planned.value))

    def _prepare_import(self, request: CurationRequest) -> Result[PreparedCuration]:
        if (
            request.legacy_source is None
            or request.source_id is None
            or request.display_name is None
            or not request.profiles
        ):
            return _error(
                "foreign import requires legacy source, source ID, display name, and profiles"
            )
        version = _semver(request.artifact_version, "artifact version")
        if isinstance(version, Err):
            return version
        acquired = self.legacy_acquirer(request)
        if isinstance(acquired, Err):
            return acquired
        try:
            options = LegacyCatalogOptions(
                SourceId(request.source_id),
                request.display_name,
                version.value,
                request.profiles,
                request.platforms or ("darwin",),
            )
        except ValueError as error:
            return _error(str(error))
        scanned = scan_legacy_catalog(acquired.value)
        if isinstance(scanned, Err):
            return scanned
        planned = plan_legacy_registry_migration(
            acquired.value,
            options,
            display_name=request.display_name,
            executable_version=_VERSION,
        )
        if isinstance(planned, Err):
            return planned
        current = self._current()
        if isinstance(current, Err):
            return current
        if current.value != planned.value.current:
            return _error("foreign import destination must contain no managed registry files")
        warnings = tuple(
            sorted(
                {
                    "Conversion uses the built-in legacy-catalog-v1 importer; review every normalized file.",
                    *scanned.value.warnings,
                    *(warning for item in scanned.value.artifacts for warning in item.warnings),
                }
            )
        )
        return Ok(self._workspace_review(request, planned.value.plan, warnings=warnings))

    def _prepare_read_only(self, request: CurationRequest) -> Result[PreparedCuration]:
        current = self._current()
        if isinstance(current, Err):
            return current
        digest = _snapshot_digest(current.value)
        if isinstance(digest, Err):
            return digest
        changes: tuple[CurationChange, ...] = ()
        checks: tuple[CurationCheck, ...] = ()
        warnings: tuple[str, ...] = ()
        if request.action is CurationAction.VALIDATE:
            report = validate_registry_workspace(
                current.value,
                executable_version=_VERSION,
                available_capabilities=_CAPABILITIES,
                require_compiled=False,
            )
            if isinstance(report, Err):
                return report
            checks = _checks(report.value)
        elif request.action is CurationAction.AUDIT:
            report = audit_registry_workspace(current.value)
            if isinstance(report, Err):
                return report
            checks = _checks(report.value)
            warnings = (
                "Audit reports review, provenance, setup, license, and available security evidence; it is not a safety certificate.",
            )
        else:
            plan = plan_registry_format(current.value)
            if isinstance(plan, Err):
                return plan
            changes = _workspace_changes(plan.value)
        review_digest = curation_review_digest(
            request.action,
            digest.value,
            changes,
            checks,
            warnings,
        )
        review = CurationReview(
            request.action,
            self.root,
            False,
            review_digest,
            digest.value,
            changes,
            checks,
            warnings,
        )
        return Ok(PreparedCuration(review, _ReadOnlyPrepared(current.value, checks)))

    def prepare(self, request: CurationRequest) -> Result[PreparedCuration]:
        if request.workspace != self.root:
            return _error("curation request targets a different workspace")
        mutating = request.action in {
            CurationAction.INIT,
            CurationAction.SCAFFOLD,
            CurationAction.PROMOTE_NATIVE,
            CurationAction.IMPORT_FOREIGN,
            CurationAction.UPDATE_UPSTREAM,
            CurationAction.LOCK,
            CurationAction.BUILD,
        }
        if mutating:
            target = self._mutation_target()
            if isinstance(target, Err):
                return target
        if request.action is CurationAction.INIT:
            return self._prepare_init(request)
        if request.action is CurationAction.SCAFFOLD:
            return self._prepare_scaffold(request)
        if request.action is CurationAction.PROMOTE_NATIVE:
            return self._prepare_promote(request)
        if request.action is CurationAction.IMPORT_FOREIGN:
            return self._prepare_import(request)
        if request.action is CurationAction.UPDATE_UPSTREAM:
            return self._prepare_update(request)
        if request.action in {CurationAction.LOCK, CurationAction.BUILD}:
            return self._prepare_generated(request)
        return self._prepare_read_only(request)

    def finalize(
        self,
        prepared: PreparedCuration,
        reviewed_digest: ObjectDigest,
    ) -> Result[CurationOutcome]:
        if reviewed_digest != prepared.review.review_digest:
            return _error("reviewed curation digest does not match the prepared action")
        payload = prepared.payload
        if isinstance(payload, RegistryWorkspacePlan):
            workspace_applied = finalize_registry_workspace(
                payload, reviewed_digest, output=self.workspace
            )
            if isinstance(workspace_applied, Err):
                return workspace_applied
            changed = workspace_applied.value.changed_paths
        elif isinstance(payload, RegistryMutationPlan):
            mutation_applied = finalize_registry_mutation(
                payload,
                reviewed_digest,
                output=_MutationWorkspace(
                    self.workspace,
                    prepared.review.snapshot_digest,
                ),
            )
            if isinstance(mutation_applied, Err):
                return mutation_applied
            changed = mutation_applied.value.changed_paths
        elif isinstance(payload, _ReadOnlyPrepared):
            current = self._current()
            if isinstance(current, Err):
                return current
            digest = _snapshot_digest(current.value)
            if isinstance(digest, Err):
                return digest
            if digest.value != prepared.review.snapshot_digest:
                return _error("registry workspace changed after read-only review", stale=True)
            changed = 0
        else:
            return _error("prepared curation payload is not executable")
        read_only = not prepared.review.mutating
        status: CurationOutcomeStatus = (
            "failed"
            if read_only and any(not item.passed for item in prepared.review.checks)
            else "succeeded"
            if read_only or changed
            else "no-op"
        )
        observed = sum(item.status != "unchanged" for item in prepared.review.changes)
        return Ok(
            CurationOutcome(
                prepared.review.action,
                status,
                changed,
                observed,
                prepared.review.checks,
                prepared.review.warnings,
                prepared.review.follow_up_commands,
            )
        )


def load_local_curation_service(workspace: str) -> Result[LocalCurationService]:
    try:
        return Ok(LocalCurationService(os.path.abspath(workspace)))
    except ValueError as error:
        return _error(str(error))
