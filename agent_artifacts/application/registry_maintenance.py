"""Maintainer registry orchestration through an injected reviewed-mutation port."""

from __future__ import annotations

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.registry_models import RegistryEntry
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.registry_maintenance.model import (
    NativeReferenceAcquisition,
    RegistryApplyCommand,
    RegistryApplyReceipt,
    RegistryMutationPlan,
)
from agent_artifacts.registry_maintenance.planning import (
    plan_native_promotion,
    project_registry_mutation,
)
from agent_artifacts.registry_maintenance.ports import RegistryMutationPort

REGISTRY_REVIEW_MISMATCH = DiagnosticCode("registry-review-mismatch")
REGISTRY_APPLY_MISMATCH = DiagnosticCode("registry-apply-mismatch")


def _error(code: DiagnosticCode, message: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message),))


def prepare_native_promotion(
    entry: RegistryEntry,
    acquisition: NativeReferenceAcquisition,
    *,
    executable_version: SemVer,
    available_capabilities: tuple[Capability, ...],
    output: RegistryMutationPort,
) -> Result[RegistryMutationPlan]:
    """Read the workspace and derive a complete plan without applying it."""

    current = output.current()
    if isinstance(current, Err):
        return current
    return plan_native_promotion(
        current.value,
        entry,
        acquisition,
        executable_version=executable_version,
        available_capabilities=available_capabilities,
    )


def finalize_registry_mutation(
    plan: RegistryMutationPlan,
    reviewed_digest: ObjectDigest,
    *,
    output: RegistryMutationPort,
) -> Result[RegistryApplyReceipt]:
    """Apply only the exact reviewed plan; no Git commit or push is part of this port."""

    if reviewed_digest != plan.review_digest:
        return _error(
            REGISTRY_REVIEW_MISMATCH,
            "reviewed registry plan digest does not match the prepared mutation",
        )
    if plan.changed_paths == 0:
        current = output.current()
        if isinstance(current, Err):
            return current
        verified = project_registry_mutation(current.value, plan)
        if isinstance(verified, Err):
            return verified
        return Ok(RegistryApplyReceipt(plan.review_digest, plan.next_inputs_digest, 0))
    applied = output.apply(RegistryApplyCommand(plan))
    if isinstance(applied, Err):
        return applied
    if (
        applied.value.review_digest != plan.review_digest
        or applied.value.inputs_digest != plan.next_inputs_digest
        or applied.value.changed_paths != plan.changed_paths
    ):
        return _error(
            REGISTRY_APPLY_MISMATCH,
            "registry apply receipt does not match the reviewed mutation",
        )
    return applied
