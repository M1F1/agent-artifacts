"""Registry command orchestration through an injected workspace port."""

from __future__ import annotations

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ArtifactIdentity, ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.paths import SafeRelativePath
from agent_artifacts.protocol.registry_models import ReviewRecord
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.registry_commands.model import (
    ArtifactScaffoldOptions,
    RegistryApplyCommand,
    RegistryApplyReceipt,
    RegistryInitOptions,
    RegistryWorkspacePlan,
    VendoredArtifactCheck,
    VendoredArtifactPlan,
)
from agent_artifacts.registry_commands.planning import (
    VendoredArtifactOrigin,
    plan_artifact_revendor,
    plan_artifact_scaffold,
    plan_artifact_vendor,
    plan_registry_build,
    plan_registry_format,
    plan_registry_init,
    plan_registry_lock,
    project_registry_workspace_plan,
    read_vendored_artifact,
)
from agent_artifacts.registry_commands.ports import RegistryWorkspacePort
from agent_artifacts.registry_maintenance.model import NativeReferenceAcquisition
from agent_artifacts.registry_maintenance.vendoring import VendorOptions

REGISTRY_REVIEW_MISMATCH = DiagnosticCode("registry-review-mismatch")
REGISTRY_APPLY_MISMATCH = DiagnosticCode("registry-apply-mismatch")


def _error(code: DiagnosticCode, message: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message),))


def prepare_registry_init(
    options: RegistryInitOptions,
    *,
    output: RegistryWorkspacePort,
) -> Result[RegistryWorkspacePlan]:
    current = output.current()
    if isinstance(current, Err):
        return current
    return plan_registry_init(current.value, options)


def prepare_artifact_scaffold(
    options: ArtifactScaffoldOptions,
    *,
    output: RegistryWorkspacePort,
) -> Result[RegistryWorkspacePlan]:
    current = output.current()
    if isinstance(current, Err):
        return current
    return plan_artifact_scaffold(current.value, options)


def prepare_artifact_vendor(
    acquisition: NativeReferenceAcquisition,
    options: VendorOptions,
    *,
    path: SafeRelativePath,
    review: ReviewRecord,
    importer_version: SemVer,
    output: RegistryWorkspacePort,
) -> Result[VendoredArtifactPlan]:
    current = output.current()
    if isinstance(current, Err):
        return current
    return plan_artifact_vendor(
        current.value,
        acquisition,
        options,
        path=path,
        review=review,
        importer_version=importer_version,
    )


def read_vendored_artifact_origin(
    identity: ArtifactIdentity,
    *,
    output: RegistryWorkspacePort,
) -> Result[VendoredArtifactOrigin]:
    current = output.current()
    if isinstance(current, Err):
        return current
    return read_vendored_artifact(current.value, identity)


def prepare_artifact_revendor(
    acquisition: NativeReferenceAcquisition,
    vendored: VendoredArtifactOrigin,
    *,
    version: SemVer | None,
    review: ReviewRecord,
    importer_version: SemVer,
    output: RegistryWorkspacePort,
) -> Result[VendoredArtifactCheck]:
    current = output.current()
    if isinstance(current, Err):
        return current
    return plan_artifact_revendor(
        current.value,
        acquisition,
        vendored,
        version=version,
        review=review,
        importer_version=importer_version,
    )


def prepare_registry_format(*, output: RegistryWorkspacePort) -> Result[RegistryWorkspacePlan]:
    current = output.current()
    if isinstance(current, Err):
        return current
    return plan_registry_format(current.value)


def prepare_registry_lock(
    acquisitions: tuple[NativeReferenceAcquisition, ...],
    *,
    executable_version: SemVer,
    available_capabilities: tuple[Capability, ...],
    output: RegistryWorkspacePort,
) -> Result[RegistryWorkspacePlan]:
    current = output.current()
    if isinstance(current, Err):
        return current
    return plan_registry_lock(
        current.value,
        acquisitions,
        executable_version=executable_version,
        available_capabilities=available_capabilities,
    )


def prepare_registry_build(
    acquisitions: tuple[NativeReferenceAcquisition, ...],
    *,
    executable_version: SemVer,
    available_capabilities: tuple[Capability, ...],
    output: RegistryWorkspacePort,
) -> Result[RegistryWorkspacePlan]:
    current = output.current()
    if isinstance(current, Err):
        return current
    return plan_registry_build(
        current.value,
        acquisitions,
        executable_version=executable_version,
        available_capabilities=available_capabilities,
    )


def finalize_registry_workspace(
    plan: RegistryWorkspacePlan,
    reviewed_digest: ObjectDigest,
    *,
    output: RegistryWorkspacePort,
) -> Result[RegistryApplyReceipt]:
    """Apply only the exact reviewed plan; a no-op still rechecks its precondition."""

    if reviewed_digest != plan.review_digest:
        return _error(
            REGISTRY_REVIEW_MISMATCH,
            "reviewed registry command digest does not match the prepared plan",
        )
    if plan.changed_paths == 0:
        current = output.current()
        if isinstance(current, Err):
            return current
        verified = project_registry_workspace_plan(current.value, plan)
        if isinstance(verified, Err):
            return verified
        return Ok(
            RegistryApplyReceipt(
                plan.review_digest,
                plan.next_snapshot_digest,
                0,
            )
        )
    applied = output.apply(RegistryApplyCommand(plan))
    if isinstance(applied, Err):
        return applied
    if (
        applied.value.review_digest != plan.review_digest
        or applied.value.snapshot_digest != plan.next_snapshot_digest
        or applied.value.changed_paths != plan.changed_paths
    ):
        return _error(
            REGISTRY_APPLY_MISMATCH,
            "registry apply receipt does not match the reviewed plan",
        )
    return applied
