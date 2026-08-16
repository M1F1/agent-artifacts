"""Local checkout adapter for canonical, digest-bound Maintainer curation."""

from __future__ import annotations

import json
import os
import shlex
import tempfile
from dataclasses import dataclass
from typing import Protocol, cast

from agent_artifacts.application.registry_commands import (
    finalize_registry_workspace,
    prepare_artifact_revendor,
    prepare_artifact_scaffold,
    prepare_artifact_vendor,
    prepare_registry_build,
    prepare_registry_init,
    prepare_registry_lock,
    read_vendored_artifact_origin,
)
from agent_artifacts.application.registry_maintenance import finalize_registry_mutation
from agent_artifacts.configuration.model import ConfiguredSource, SourceKind
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ArtifactIdentity, ObjectDigest, SourceAlias
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.io.registry_workspace import FilesystemRegistryWorkspace
from agent_artifacts.protocol.native_models import CanonicalArtifactType
from agent_artifacts.protocol.native_tree import SnapshotEntryKind, SourceSnapshot
from agent_artifacts.protocol.paths import SafeRelativePath, parse_relative_path
from agent_artifacts.protocol.registry_models import RegistryEntry, ReviewRecord
from agent_artifacts.protocol.registry_schema import parse_registry_entry
from agent_artifacts.protocol.semver import SemVer, parse_semver
from agent_artifacts.registry_commands.model import (
    ArtifactScaffoldOptions,
    RegistryInitOptions,
    RegistryOperation,
    RegistryQualityReport,
    RegistryWorkspaceChange,
    RegistryWorkspacePlan,
    VendoredArtifactCheck,
    WorkspaceChangeKind,
    registry_workspace_review_digest,
)
from agent_artifacts.registry_commands.model import (
    RegistryApplyCommand as WorkspaceApplyCommand,
)
from agent_artifacts.registry_commands.planning import (
    VendoredArtifactOrigin,
    audit_registry_workspace,
    plan_registry_format,
    validate_registry_workspace,
    verify_vendored_artifact,
)
from agent_artifacts.registry_maintenance.model import (
    NativeAcquirer,
    NativeReferenceAcquisition,
    NativeReferenceDisposition,
    RegistryMutationPlan,
)
from agent_artifacts.registry_maintenance.model import (
    RegistryApplyCommand as MutationApplyCommand,
)
from agent_artifacts.registry_maintenance.model import (
    RegistryApplyReceipt as MutationApplyReceipt,
)
from agent_artifacts.registry_maintenance.planning import (
    check_native_reference,
    plan_native_promotion,
    project_registry_mutation,
)
from agent_artifacts.registry_maintenance.vendoring import (
    DeliveryFinding,
    LicenseFinding,
    VendorOptions,
    copy_integrity_message,
    mcp_descriptor_message,
)
from agent_artifacts.runtime_contract import EXECUTABLE_CAPABILITIES, EXECUTABLE_VERSION
from agent_artifacts.security.model import AssessmentStatus, SecurityAssessment
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

_VERSION = EXECUTABLE_VERSION
_CAPABILITIES = EXECUTABLE_CAPABILITIES
CURATION_INVALID = DiagnosticCode("curation-invalid")
CURATION_STALE = DiagnosticCode("curation-stale")


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
        # A vendored package is new owned content, so the lock and index are stale until they are
        # rebuilt: `validate --strict` alone would fail and send the maintainer looking for a fault
        # in the copy.
        CurationAction.VENDOR,
        CurationAction.REVENDOR,
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


def default_native_acquirer(url: str, ref: str) -> Result[NativeReferenceAcquisition]:
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
        native_acquirer: NativeAcquirer = default_native_acquirer,
    ):
        if not os.path.isabs(workspace) or os.path.normpath(workspace) != workspace:
            raise ValueError("curation workspace must be normalized and absolute")
        self.root = workspace
        self.workspace = FilesystemRegistryWorkspace(workspace)
        self.native_acquirer = native_acquirer

    def _current(self) -> Result[SourceSnapshot]:
        return self.workspace.current()

    def _mutation_target(self) -> Result[None]:
        return self.workspace.verify_mutation_target()

    def _workspace_review(
        self,
        request: CurationRequest,
        plan: RegistryWorkspacePlan,
        *,
        checks: tuple[CurationCheck, ...] = (),
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
                checks=checks,
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
        if request.artifact_version is None:
            return _error("scaffold requires an artifact version")
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

    def _vendor_review_check(
        self,
        request: CurationRequest,
        acquisition: NativeReferenceAcquisition,
        plan: RegistryWorkspacePlan,
    ) -> CurationCheck:
        """State what is being copied, from where, and at which commit.

        The maintainer approves a copy of somebody else's bytes, so the review has to say whose,
        which revision, and how much — none of which the diff alone makes legible once the payload
        is more than a couple of files.
        """

        base = next(
            str(item.path).removesuffix("/artifact.json")
            for item in plan.changes
            if str(item.path).endswith("/artifact.json")
        )
        payload = sum(1 for item in plan.changes if str(item.path).startswith(f"{base}/payload/"))
        return CurationCheck(
            "vendor-origin",
            True,
            (
                f"origin: {acquisition.url}",
                f"ref: {acquisition.requested_ref}",
                f"resolved commit: {acquisition.resolved_commit}",
                f"subtree: {request.path}",
                f"target: {base}",
                f"declared version: {request.artifact_version}",
                f"payload files: {payload}",
            ),
        )

    def _vendor_license_check(
        self,
        request: CurationRequest,
        finding: LicenseFinding,
    ) -> CurationCheck:
        """Say what the subtree claims about its licence, and what this registry will record.

        It always passes. AART is not qualified to adjudicate a licence, and a maintainer vendoring
        their own company's code has nothing to record; the obligation is to make the omission
        visible rather than to block on it (design §7).
        """

        recorded = request.artifact_license or finding.identifier
        details = [f"discovered: {finding.note}"]
        if request.artifact_license is not None:
            details.append(f"stated: {request.artifact_license}")
        details.append(
            f"recorded: {recorded}"
            if recorded is not None
            else "recorded: none; state one with --license, or registry audit will report it"
        )
        return CurationCheck("vendor-license", True, tuple(details))

    def _vendor_delivery_check(
        self,
        identity: ArtifactIdentity,
        finding: DeliveryFinding,
    ) -> CurationCheck:
        """Say what installing this artifact delivers, and refuse a config that cannot run.

        Vendoring copies a subtree into the registry; installing an `mcp` merges one JSON object and
        copies nothing. A descriptor whose command names a file inside the payload names one that
        will not exist on any consumer machine, and a review that reported the copy while staying
        silent about that would be describing a package nobody can start (`LAF-46`, design §7).
        """

        details = [finding.note]
        if finding.withheld:
            details.append(
                "the assessment above covers the copied bytes, including the ones no consumer of "
                "this artifact receives"
            )
        details.extend(
            f"descriptor names a withheld payload file: {item}" for item in finding.referenced
        )
        if finding.starts_nothing:
            details.append(mcp_descriptor_message(identity, vendored=True))
        return CurationCheck(
            "vendor-delivery",
            not finding.referenced and not finding.starts_nothing,
            tuple(details),
        )

    def _vendor_assessment_check(self, assessment: SecurityAssessment) -> CurationCheck:
        """Report what the baseline found in the bytes this vendoring would write.

        The check passes when the assessment ran to completion, not when it found nothing: a
        scan that completed and reported three findings did its job, and the maintainer decides
        whether those findings are acceptable.  Nothing here calls the package safe.
        """

        details = [
            f"installation risk: {assessment.installation_risk.value}",
            f"findings: {len(assessment.findings)}",
        ]
        details.extend(
            f"{finding.rule_id} ({finding.severity.value}): {finding.message}"
            + ("" if finding.path is None else f" [{finding.path}]")
            for finding in assessment.findings
        )
        return CurationCheck(
            "vendor-assessment",
            assessment.status is AssessmentStatus.COMPLETE,
            tuple(details),
        )

    def _prepare_vendor(self, request: CurationRequest) -> Result[PreparedCuration]:
        if (
            request.kind is None
            or request.name is None
            or request.summary is None
            or request.url is None
            or request.path is None
            or not request.profiles
            or not request.platforms
        ):
            return _error(
                "vendoring requires kind, name, summary, URL, subtree path, profiles, and platforms"
            )
        if request.artifact_version is None:
            return _error("vendoring requires an artifact version")
        version = _semver(request.artifact_version, "artifact version")
        if isinstance(version, Err):
            return version
        path = parse_relative_path(request.path)
        if isinstance(path, Err):
            return _error(f"vendored subtree path is unsafe: {request.path}")
        recipe: SafeRelativePath | None = None
        if request.setup_recipe is not None:
            parsed = parse_relative_path(request.setup_recipe)
            if isinstance(parsed, Err):
                return _error(f"setup recipe path is unsafe: {request.setup_recipe}")
            recipe = parsed.value
        try:
            options = VendorOptions(
                ArtifactIdentity(cast(CanonicalArtifactType, request.kind), request.name),
                version.value,
                request.summary,
                request.profiles,
                request.platforms,
                request.scopes,
                request.modes,
                recipe,
                license=request.artifact_license,
            )
        except ValueError as error:
            return _error(str(error))
        acquired = self.native_acquirer(request.url, request.ref)
        if isinstance(acquired, Err):
            return acquired
        planned = prepare_artifact_vendor(
            acquired.value,
            options,
            path=path.value,
            # The record the maintainer is being asked to approve.  It gates the plan and is not
            # persisted: an owned package has no `entries/` document to carry a review.
            review=ReviewRecord("approved", request.review_policy),
            importer_version=_VERSION,
            output=self.workspace,
        )
        if isinstance(planned, Err):
            return planned
        return Ok(
            self._workspace_review(
                request,
                planned.value.plan,
                checks=(
                    self._vendor_review_check(request, acquired.value, planned.value.plan),
                    self._vendor_license_check(request, planned.value.license),
                    self._vendor_assessment_check(planned.value.assessment),
                    *(
                        ()
                        if planned.value.delivery is None
                        else (
                            self._vendor_delivery_check(options.identity, planned.value.delivery),
                        )
                    ),
                ),
                warnings=(
                    "Vendoring copies upstream bytes into this registry and pins them to a commit; "
                    "a successful vendor reports what was copied, and is not a safety claim.",
                    # Verbatim from the `security` command's own description: the vendor review is
                    # the same evidence under a different verb, and must not read as stronger.
                    "Assessments reduce uncertainty; they are not safety guarantees.",
                    "This registry now owns the copy: upstream fixes do not reach consumers until "
                    "it is vendored again.",
                ),
            )
        )

    def _informational_review(
        self,
        request: CurationRequest,
        snapshot: SourceSnapshot,
        checks: tuple[CurationCheck, ...],
        warnings: tuple[str, ...],
    ) -> Result[PreparedCuration]:
        """A review that reports and writes nothing, and whose failing checks fail the command."""

        digest = _snapshot_digest(snapshot)
        if isinstance(digest, Err):
            return digest
        return Ok(
            PreparedCuration(
                CurationReview(
                    request.action,
                    self.root,
                    False,
                    curation_review_digest(request.action, digest.value, (), checks, warnings),
                    digest.value,
                    (),
                    checks,
                    warnings,
                ),
                _ReadOnlyPrepared(snapshot, checks),
            )
        )

    def _drift_check(
        self,
        vendored: VendoredArtifactOrigin,
        checked: VendoredArtifactCheck,
    ) -> CurationCheck:
        """Say which of the three things happened, and never let two of them read alike.

        `up-to-date` passes.  `changed` without a stated version and `unreachable` both fail, for
        different reasons that the details spell out: one is work the maintainer has to finish, the
        other is an upstream they can no longer read.  Neither is a copy that is known to be current.
        """

        details = [
            f"disposition: {checked.disposition.value}",
            f"origin: {vendored.url}",
            f"ref: {vendored.ref}",
            f"subtree: {vendored.path}",
            f"recorded commit: {checked.recorded_commit}",
        ]
        if checked.resolved_commit is not None:
            details.append(f"resolved commit: {checked.resolved_commit}")
        if checked.disposition is NativeReferenceDisposition.UP_TO_DATE:
            # Two differing commits under `up-to-date` is the *normal* result of vendoring one
            # directory out of a monorepo, and it reads as a contradiction.  The line that
            # reconciles them is printed where they are, not left in a docstring (`LAF-42`).
            details.append(
                "the ref has not moved since this copy was taken"
                if checked.resolved_commit == checked.recorded_commit
                else f"the ref moved, and nothing under {vendored.path} changed; "
                "the copy stays pinned to the recorded commit"
            )
        if checked.disposition is NativeReferenceDisposition.CHANGED:
            details.extend(
                (
                    f"upstream files added: {checked.added}",
                    f"upstream files changed: {checked.changed}",
                    f"upstream files removed: {checked.removed}",
                )
            )
            if checked.plan is None:
                details.append(
                    "state the version this movement deserves with --artifact-version to plan it"
                )
        return CurationCheck(
            "vendor-drift",
            checked.disposition is NativeReferenceDisposition.UP_TO_DATE
            or checked.plan is not None,
            tuple(details),
        )

    def _prepare_revendor(self, request: CurationRequest) -> Result[PreparedCuration]:
        if request.kind is None or request.name is None:
            return _error("re-vendoring requires an exact artifact kind and name")
        current = self._current()
        if isinstance(current, Err):
            return current
        identity = ArtifactIdentity(cast(CanonicalArtifactType, request.kind), request.name)
        vendored = read_vendored_artifact_origin(identity, output=self.workspace)
        if isinstance(vendored, Err):
            return vendored
        version: SemVer | None = None
        if request.artifact_version is not None:
            parsed = _semver(request.artifact_version, "artifact version")
            if isinstance(parsed, Err):
                return parsed
            version = parsed.value
        integrity = verify_vendored_artifact(current.value, vendored.value)
        if isinstance(integrity, Err):
            return integrity
        if not integrity.value.matches:
            # Before the network, deliberately: nothing upstream says can make this copy the copy
            # its provenance describes, and re-vendoring over the difference would erase evidence
            # the maintainer has not seen yet (design §5).
            return self._informational_review(
                request,
                current.value,
                (
                    CurationCheck(
                        "vendor-copy-integrity",
                        False,
                        (
                            f"recorded: {integrity.value.recorded}",
                            f"copy: {integrity.value.recomputed}",
                            f"copied payload files: {integrity.value.files}",
                            copy_integrity_message(identity, integrity.value),
                        ),
                    ),
                ),
                (
                    "The copy no longer matches the origin it records; upstream was not contacted.",
                    "Nothing was written, and no drift was computed: a copy that is not the copy "
                    "cannot be reported as current or as behind.",
                ),
            )
        acquired = self.native_acquirer(vendored.value.url, vendored.value.ref)
        if isinstance(acquired, Err):
            # An upstream that cannot be read is a disposition, not a crash: the maintainer needs to
            # be told their copy's provenance can no longer be checked, which is a different fact
            # from the copy being current (design §6).
            return self._informational_review(
                request,
                current.value,
                (
                    self._drift_check(
                        vendored.value,
                        VendoredArtifactCheck(
                            NativeReferenceDisposition.UNREACHABLE,
                            None,
                            vendored.value.recorded_commit,
                            0,
                            0,
                            0,
                        ),
                    ),
                    CurationCheck(
                        "vendor-origin-error",
                        False,
                        tuple(" ".join(item.message.split()) for item in acquired.diagnostics),
                    ),
                ),
                (
                    "An unreachable upstream is not an up-to-date copy; nothing was compared.",
                    "The vendored copy is unchanged and still installable; only the check failed.",
                ),
            )
        checked = prepare_artifact_revendor(
            acquired.value,
            vendored.value,
            version=version,
            review=ReviewRecord("approved", request.review_policy),
            importer_version=_VERSION,
            output=self.workspace,
        )
        if isinstance(checked, Err):
            return checked
        drift = self._drift_check(vendored.value, checked.value)
        if checked.value.plan is None:
            return self._informational_review(
                request,
                current.value,
                (drift,),
                ("Nothing was written; re-vendoring compares upstream and reports.",)
                if checked.value.disposition is NativeReferenceDisposition.UP_TO_DATE
                else (
                    "Upstream moved. This registry owns the version, so it states the new one.",
                    "Nothing was written.",
                ),
            )
        assert checked.value.assessment is not None
        return Ok(
            self._workspace_review(
                request,
                checked.value.plan,
                checks=(
                    drift,
                    self._vendor_assessment_check(checked.value.assessment),
                    *(
                        ()
                        if checked.value.delivery is None
                        else (self._vendor_delivery_check(identity, checked.value.delivery),)
                    ),
                ),
                warnings=(
                    "Re-vendoring replaces the copied bytes and re-pins the commit; "
                    "a successful re-vendor reports what was copied, and is not a safety claim.",
                    "Assessments reduce uncertainty; they are not safety guarantees.",
                    "Consumers receive this movement only after the version you stated is published.",
                ),
            )
        )

    def _prepare_format(self, request: CurationRequest) -> Result[PreparedCuration]:
        current = self._current()
        if isinstance(current, Err):
            return current
        planned = plan_registry_format(current.value)
        if isinstance(planned, Err):
            return planned
        return Ok(self._workspace_review(request, planned.value))

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
            return _error("native reference refresh requires an exact artifact kind and name")
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
        checked = check_native_reference(
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
            report = audit_registry_workspace(
                current.value,
                executable_version=_VERSION,
                available_capabilities=_CAPABILITIES,
            )
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
            CurationAction.FORMAT,
            CurationAction.PROMOTE_NATIVE,
            CurationAction.REFRESH_NATIVE,
            CurationAction.VENDOR,
            CurationAction.REVENDOR,
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
        if request.action is CurationAction.FORMAT:
            return self._prepare_format(request)
        if request.action is CurationAction.VENDOR:
            return self._prepare_vendor(request)
        if request.action is CurationAction.REVENDOR:
            return self._prepare_revendor(request)
        if request.action is CurationAction.PROMOTE_NATIVE:
            return self._prepare_promote(request)
        if request.action is CurationAction.REFRESH_NATIVE:
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
