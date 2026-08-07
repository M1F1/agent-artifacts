"""Functional compiler orchestration with injected acquisition, object, and publish effects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

from agent_artifacts.compiler.model import (
    AcquiredCompilation,
    AcquiredSource,
    CompilationCandidate,
    CompilerContext,
    CompilerMode,
    CompilerPhase,
    CompilerRequest,
    CompilerRun,
    ObjectPlan,
    ObjectReceipt,
    PhaseOutput,
    PhaseReport,
    PhaseStatus,
    PublishReceipt,
    PublishRequest,
    ResolvedCompilation,
    SourceRequest,
    acquired_compilation,
    materialization_digest,
    publication_request,
)
from agent_artifacts.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    Severity,
    SourceLocation,
)
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.ports import CommandPort, QueryPort
from agent_artifacts.domain.result import Err, Ok, Result

COMPILER_SOURCE_NOT_FROZEN = DiagnosticCode("compiler-source-not-frozen")
COMPILER_SOURCE_MISMATCH = DiagnosticCode("compiler-source-mismatch")
COMPILER_UNFROZEN_RESOLUTION = DiagnosticCode("compiler-unfrozen-resolution")
COMPILER_PHASE_OUTPUT_INVALID = DiagnosticCode("compiler-phase-output-invalid")
COMPILER_OBJECT_RECEIPT_MISMATCH = DiagnosticCode("compiler-object-receipt-mismatch")
COMPILER_PUBLISH_RECEIPT_MISMATCH = DiagnosticCode("compiler-publish-receipt-mismatch")

ParseT = TypeVar("ParseT")
HandshakeT = TypeVar("HandshakeT")
ResolveT = TypeVar("ResolveT")
NormalizeT = TypeVar("NormalizeT")
ValidateT = TypeVar("ValidateT")


@dataclass(frozen=True, slots=True)
class CompilerSteps(Generic[ParseT, HandshakeT, ResolveT, NormalizeT, ValidateT]):
    parse: Callable[
        [AcquiredCompilation, CompilerContext],
        Result[PhaseOutput[ParseT]],
    ]
    handshake: Callable[
        [PhaseOutput[ParseT], CompilerContext],
        Result[PhaseOutput[HandshakeT]],
    ]
    resolve: Callable[
        [PhaseOutput[HandshakeT], CompilerContext],
        Result[PhaseOutput[ResolvedCompilation[ResolveT]]],
    ]
    normalize: Callable[
        [PhaseOutput[ResolvedCompilation[ResolveT]], CompilerContext],
        Result[PhaseOutput[NormalizeT]],
    ]
    validate: Callable[
        [PhaseOutput[NormalizeT], CompilerContext],
        Result[PhaseOutput[ValidateT]],
    ]
    index: Callable[
        [PhaseOutput[ValidateT], CompilerContext],
        Result[PhaseOutput[CompilationCandidate]],
    ]


@dataclass(frozen=True, slots=True)
class CompilerPorts:
    acquire: QueryPort[SourceRequest, AcquiredSource]
    materialize: CommandPort[ObjectPlan, ObjectReceipt]
    publish: CommandPort[PublishRequest, PublishReceipt]


def _diagnostic(
    code: DiagnosticCode,
    message: str,
    *,
    source: SourceRequest | None = None,
) -> Diagnostic:
    location = None if source is None else SourceLocation(source=source.alias)
    return Diagnostic(code, Severity.ERROR, message, location)


def _failed_run(
    reports: list[PhaseReport],
    phase: CompilerPhase,
    diagnostics: tuple[Diagnostic, ...],
    *,
    input_digest: ObjectDigest | None = None,
    candidate: CompilationCandidate | None = None,
) -> CompilerRun:
    reports.append(
        PhaseReport(
            phase,
            PhaseStatus.FAILED,
            input_digest=input_digest,
            diagnostics=diagnostics,
        )
    )
    position = tuple(CompilerPhase).index(phase)
    reports.extend(
        PhaseReport(remaining, PhaseStatus.SKIPPED)
        for remaining in tuple(CompilerPhase)[position + 1 :]
    )
    return CompilerRun(tuple(reports), candidate=candidate)


OutputT = TypeVar("OutputT")


def _accepted_output(
    result: Result[PhaseOutput[OutputT]],
) -> tuple[PhaseOutput[OutputT] | None, tuple[Diagnostic, ...]]:
    if isinstance(result, Err):
        return None, result.diagnostics
    errors = tuple(
        diagnostic
        for diagnostic in result.value.diagnostics
        if diagnostic.severity is Severity.ERROR
    )
    return (None, result.value.diagnostics) if errors else (result.value, ())


def _success_report(
    phase: CompilerPhase,
    input_digest: ObjectDigest,
    output: PhaseOutput[object],
) -> PhaseReport:
    return PhaseReport(
        phase,
        PhaseStatus.SUCCEEDED,
        input_digest,
        output.digest,
        output.diagnostics,
    )


def _acquire(
    request: CompilerRequest,
    port: QueryPort[SourceRequest, AcquiredSource],
) -> Result[AcquiredCompilation]:
    diagnostics: list[Diagnostic] = []
    if request.mode is CompilerMode.CONSUMER:
        for source in request.sources:
            if source.locked_revision is None or source.expected_snapshot_digest is None:
                diagnostics.append(
                    _diagnostic(
                        COMPILER_SOURCE_NOT_FROZEN,
                        f"consumer source {source.alias} requires locked revision and snapshot digest",
                        source=source,
                    )
                )
    if diagnostics:
        return Err(tuple(diagnostics))
    acquired: list[AcquiredSource] = []
    for source in request.sources:
        result = port(source)
        if isinstance(result, Err):
            diagnostics.extend(result.diagnostics)
            continue
        item = result.value
        if item.alias != source.alias:
            diagnostics.append(
                _diagnostic(
                    COMPILER_SOURCE_MISMATCH,
                    f"acquisition returned alias {item.alias} for requested {source.alias}",
                    source=source,
                )
            )
            continue
        if request.mode is CompilerMode.CONSUMER and (
            item.resolved_revision != source.locked_revision
            or item.snapshot_digest != source.expected_snapshot_digest
        ):
            diagnostics.append(
                _diagnostic(
                    COMPILER_SOURCE_MISMATCH,
                    f"acquisition did not match frozen source {source.alias}",
                    source=source,
                )
            )
            continue
        acquired.append(item)
    if diagnostics:
        return Err(tuple(diagnostics))
    return Ok(acquired_compilation(tuple(acquired), request.options_digest))


def compile_sources(
    request: CompilerRequest,
    steps: CompilerSteps[ParseT, HandshakeT, ResolveT, NormalizeT, ValidateT],
    ports: CompilerPorts,
) -> CompilerRun:
    """Run the deterministic compiler; publication is unreachable after any failed phase."""

    reports: list[PhaseReport] = []
    acquired_result = _acquire(request, ports.acquire)
    if isinstance(acquired_result, Err):
        return _failed_run(
            reports,
            CompilerPhase.ACQUIRE,
            acquired_result.diagnostics,
            input_digest=request.options_digest,
        )
    acquired = acquired_result.value
    reports.append(
        PhaseReport(
            CompilerPhase.ACQUIRE,
            PhaseStatus.SUCCEEDED,
            request.options_digest,
            acquired.input_digest,
        )
    )
    context = CompilerContext(
        request.build_key,
        request.mode,
        request.options_digest,
        acquired.input_digest,
    )

    parsed, diagnostics = _accepted_output(steps.parse(acquired, context))
    if parsed is None:
        return _failed_run(
            reports,
            CompilerPhase.PARSE,
            diagnostics,
            input_digest=acquired.input_digest,
        )
    reports.append(_success_report(CompilerPhase.PARSE, acquired.input_digest, parsed))

    handshaken, diagnostics = _accepted_output(steps.handshake(parsed, context))
    if handshaken is None:
        return _failed_run(
            reports,
            CompilerPhase.HANDSHAKE,
            diagnostics,
            input_digest=parsed.digest,
        )
    reports.append(_success_report(CompilerPhase.HANDSHAKE, parsed.digest, handshaken))

    resolved, diagnostics = _accepted_output(steps.resolve(handshaken, context))
    if resolved is None:
        return _failed_run(
            reports,
            CompilerPhase.RESOLVE,
            diagnostics,
            input_digest=handshaken.digest,
        )
    if request.mode is CompilerMode.CONSUMER and not resolved.value.frozen:
        return _failed_run(
            reports,
            CompilerPhase.RESOLVE,
            (
                _diagnostic(
                    COMPILER_UNFROZEN_RESOLUTION,
                    "consumer resolution must be frozen by committed revisions and digests",
                ),
            ),
            input_digest=handshaken.digest,
        )
    reports.append(_success_report(CompilerPhase.RESOLVE, handshaken.digest, resolved))

    normalized, diagnostics = _accepted_output(steps.normalize(resolved, context))
    if normalized is None:
        return _failed_run(
            reports,
            CompilerPhase.NORMALIZE,
            diagnostics,
            input_digest=resolved.digest,
        )
    reports.append(_success_report(CompilerPhase.NORMALIZE, resolved.digest, normalized))

    validated, diagnostics = _accepted_output(steps.validate(normalized, context))
    if validated is None:
        return _failed_run(
            reports,
            CompilerPhase.VALIDATE,
            diagnostics,
            input_digest=normalized.digest,
        )
    reports.append(_success_report(CompilerPhase.VALIDATE, normalized.digest, validated))

    indexed, diagnostics = _accepted_output(steps.index(validated, context))
    if indexed is None:
        return _failed_run(
            reports,
            CompilerPhase.INDEX,
            diagnostics,
            input_digest=validated.digest,
        )
    candidate = indexed.value
    invariant_diagnostics: list[Diagnostic] = []
    if candidate.input_digest != acquired.input_digest:
        invariant_diagnostics.append(
            _diagnostic(
                COMPILER_PHASE_OUTPUT_INVALID,
                "index candidate does not bind the complete compiler input digest",
            )
        )
    if indexed.digest != candidate.index_digest:
        invariant_diagnostics.append(
            _diagnostic(
                COMPILER_PHASE_OUTPUT_INVALID,
                "index phase digest does not match candidate index bytes",
            )
        )
    if invariant_diagnostics:
        return _failed_run(
            reports,
            CompilerPhase.INDEX,
            tuple(invariant_diagnostics),
            input_digest=validated.digest,
        )
    reports.append(_success_report(CompilerPhase.INDEX, validated.digest, indexed))

    receipts: list[ObjectReceipt] = []
    materialize_diagnostics: list[Diagnostic] = []
    for plan in candidate.objects:
        result = ports.materialize(plan)
        if isinstance(result, Err):
            materialize_diagnostics.extend(result.diagnostics)
            continue
        if result.value.digest != plan.digest:
            materialize_diagnostics.append(
                _diagnostic(
                    COMPILER_OBJECT_RECEIPT_MISMATCH,
                    f"object receipt does not match planned digest {plan.digest}",
                )
            )
            continue
        receipts.append(result.value)
    if materialize_diagnostics:
        return _failed_run(
            reports,
            CompilerPhase.MATERIALIZE,
            tuple(materialize_diagnostics),
            input_digest=candidate.index_digest,
            candidate=candidate,
        )
    materialized_digest = materialization_digest(tuple(receipts))
    reports.append(
        PhaseReport(
            CompilerPhase.MATERIALIZE,
            PhaseStatus.SUCCEEDED,
            candidate.index_digest,
            materialized_digest,
        )
    )

    publish_request = publication_request(candidate, request.build_key)
    publish_result = ports.publish(publish_request)
    if isinstance(publish_result, Err):
        return _failed_run(
            reports,
            CompilerPhase.PUBLISH,
            publish_result.diagnostics,
            input_digest=publish_request.snapshot_digest,
            candidate=candidate,
        )
    if publish_result.value.snapshot_digest != publish_request.snapshot_digest:
        return _failed_run(
            reports,
            CompilerPhase.PUBLISH,
            (
                _diagnostic(
                    COMPILER_PUBLISH_RECEIPT_MISMATCH,
                    "publish receipt does not match the complete snapshot digest",
                ),
            ),
            input_digest=publish_request.snapshot_digest,
            candidate=candidate,
        )
    reports.append(
        PhaseReport(
            CompilerPhase.PUBLISH,
            PhaseStatus.SUCCEEDED,
            publish_request.snapshot_digest,
            publish_result.value.snapshot_digest,
        )
    )
    return CompilerRun(tuple(reports), candidate, publish_result.value)
