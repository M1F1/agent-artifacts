"""Incremental translations between the 0.1.x model and the AART 1.0 domain kernel."""

from __future__ import annotations

from typing import TypeVar

from agent_artifacts import model as legacy
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ArtifactIdentity
from agent_artifacts.domain.result import Err, Ok, Result

T = TypeVar("T")
_LEGACY_ERROR = DiagnosticCode("legacy-error")
_EXIT_CODE_DETAIL = "exit_code"


def artifact_identity_from_legacy(artifact: legacy.Artifact) -> ArtifactIdentity:
    return ArtifactIdentity(artifact.type, artifact.name)


def result_from_legacy(result: legacy.Ok[T] | legacy.Err) -> Result[T]:
    if isinstance(result, legacy.Ok):
        return Ok(result.value)
    diagnostic = Diagnostic(
        code=_LEGACY_ERROR,
        severity=Severity.ERROR,
        message=result.reason,
        details=((_EXIT_CODE_DETAIL, str(result.code)),),
    )
    return Err((diagnostic,))


def _legacy_exit_code(diagnostic: Diagnostic) -> int:
    details = dict(diagnostic.details)
    try:
        return int(details[_EXIT_CODE_DETAIL])
    except (KeyError, ValueError):
        return 1


def result_to_legacy(result: Result[T]) -> legacy.Ok[T] | legacy.Err:
    if isinstance(result, Ok):
        return legacy.Ok(result.value)
    codes = {_legacy_exit_code(diagnostic) for diagnostic in result.diagnostics}
    code = codes.pop() if len(codes) == 1 else 1
    reason = "; ".join(diagnostic.message for diagnostic in result.diagnostics)
    return legacy.Err(reason, code=code)
