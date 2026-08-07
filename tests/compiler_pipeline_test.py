from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace

from agent_artifacts.application.compiler import CompilerPorts, CompilerSteps, compile_sources
from agent_artifacts.compiler.model import (
    AcquiredSource,
    CompilerMode,
    CompilerPhase,
    CompilerRequest,
    ObjectReceipt,
    PhaseOutput,
    PhaseStatus,
    PublishReceipt,
    ResolvedCompilation,
    SourceRequest,
    compilation_candidate,
    object_plan,
    phase_output,
)
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest, SourceAlias
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.native_tree import SnapshotOrigin, SourceSnapshot


def _digest(character: str) -> ObjectDigest:
    return ObjectDigest("sha256", character * 64)


def _source(
    alias: str,
    *,
    locator: str | None = None,
    revision: str = "a" * 40,
    digest: ObjectDigest | None = None,
) -> SourceRequest:
    return SourceRequest(
        SourceAlias(alias),
        locator or f"https://example.test/{alias}.git",
        revision,
        digest or _digest(alias[0]),
    )


def _acquired(request: SourceRequest) -> AcquiredSource:
    assert request.locked_revision is not None
    assert request.expected_snapshot_digest is not None
    return AcquiredSource(
        request.alias,
        request.locked_revision,
        request.expected_snapshot_digest,
        SourceSnapshot(SnapshotOrigin.IMMUTABLE_GIT, ()),
    )


def _candidate(input_digest: ObjectDigest):
    return compilation_candidate(
        input_digest=input_digest,
        index_bytes=b'{"schema_version":1}\n',
        objects=(object_plan(b"second"), object_plan(b"first")),
    )


def _steps(calls: list[str], *, warning: Diagnostic | None = None):
    def parse(acquired, _request):
        calls.append("parse")
        diagnostics = () if warning is None else (warning,)
        return Ok(phase_output("parsed", b"parsed", diagnostics=diagnostics))

    def handshake(parsed, _request):
        calls.append("handshake")
        return Ok(phase_output("compatible", b"compatible" + parsed.digest.value.encode()))

    def resolve(handshaken, _request):
        calls.append("resolve")
        return Ok(
            phase_output(
                ResolvedCompilation("resolved", frozen=True),
                b"resolved" + handshaken.digest.value.encode(),
            )
        )

    def normalize(resolved, _request):
        calls.append("normalize")
        return Ok(phase_output("normalized", b"normalized" + resolved.digest.value.encode()))

    def validate(normalized, _request):
        calls.append("validate")
        return Ok(phase_output("validated", b"validated" + normalized.digest.value.encode()))

    def index(validated, context):
        calls.append("index")
        candidate = _candidate(context.input_digest)
        return Ok(PhaseOutput(candidate, candidate.index_digest))

    return CompilerSteps(parse, handshake, resolve, normalize, validate, index)


class CompilerPipelineTest(unittest.TestCase):
    def test_success_runs_every_phase_materializes_in_digest_order_and_publishes(self) -> None:
        calls: list[str] = []
        materialized: list[str] = []
        published: list[str] = []

        def acquire(request):
            calls.append(f"acquire:{request.alias}")
            return Ok(_acquired(request))

        def materialize(plan):
            materialized.append(str(plan.digest))
            return Ok(ObjectReceipt(plan.digest))

        def publish(request):
            published.append(str(request.snapshot_digest))
            return Ok(PublishReceipt(request.snapshot_digest))

        request = CompilerRequest(
            "consumer-build",
            CompilerMode.CONSUMER,
            (_source("beta"), _source("alpha")),
            _digest("f"),
        )

        result = compile_sources(
            request,
            _steps(calls),
            CompilerPorts(acquire, materialize, publish),
        )

        self.assertTrue(result.succeeded)
        self.assertIsNotNone(result.candidate)
        self.assertIsNotNone(result.publication)
        self.assertEqual(
            tuple(report.phase for report in result.reports),
            tuple(CompilerPhase),
        )
        self.assertTrue(all(report.status is PhaseStatus.SUCCEEDED for report in result.reports))
        self.assertEqual(calls[:2], ["acquire:alpha", "acquire:beta"])
        self.assertEqual(
            calls[2:], ["parse", "handshake", "resolve", "normalize", "validate", "index"]
        )
        self.assertEqual(materialized, sorted(materialized))
        self.assertEqual(len(published), 1)

    def test_acquire_accumulates_independent_errors_and_never_enters_pure_or_write_phases(
        self,
    ) -> None:
        calls: list[str] = []
        diagnostic_a = Diagnostic(DiagnosticCode("source-a-failed"), Severity.ERROR, "source a")
        diagnostic_b = Diagnostic(DiagnosticCode("source-b-failed"), Severity.ERROR, "source b")

        def acquire(request):
            return Err((diagnostic_b if str(request.alias) == "beta" else diagnostic_a,))

        def forbidden(_value):
            self.fail("write/publish port must not run")

        result = compile_sources(
            CompilerRequest(
                "failed-build",
                CompilerMode.CONSUMER,
                (_source("beta"), _source("alpha")),
                _digest("f"),
            ),
            _steps(calls),
            CompilerPorts(acquire, forbidden, forbidden),
        )

        self.assertFalse(result.succeeded)
        self.assertIsNone(result.candidate)
        self.assertEqual(calls, [])
        self.assertEqual(
            tuple(item.code.value for item in result.diagnostics),
            ("source-a-failed", "source-b-failed"),
        )
        self.assertIs(result.reports[0].status, PhaseStatus.FAILED)
        self.assertTrue(all(report.status is PhaseStatus.SKIPPED for report in result.reports[1:]))

    def test_each_pure_phase_failure_stops_later_phases_and_publication(self) -> None:
        phases = (
            CompilerPhase.PARSE,
            CompilerPhase.HANDSHAKE,
            CompilerPhase.RESOLVE,
            CompilerPhase.NORMALIZE,
            CompilerPhase.VALIDATE,
            CompilerPhase.INDEX,
        )
        for failing_phase in phases:
            with self.subTest(failing_phase=failing_phase):
                calls: list[str] = []
                base = _steps(calls)
                failure = Err(
                    (
                        Diagnostic(
                            DiagnosticCode(f"{failing_phase.value}-failed"),
                            Severity.ERROR,
                            "expected",
                        ),
                    )
                )
                replacements = {
                    "parse": base.parse,
                    "handshake": base.handshake,
                    "resolve": base.resolve,
                    "normalize": base.normalize,
                    "validate": base.validate,
                    "index": base.index,
                }
                replacements[failing_phase.value] = (
                    lambda *_args, phase_failure=failure: phase_failure
                )
                steps = CompilerSteps(**replacements)

                def forbidden(_value):
                    self.fail("write/publish port must not run")

                result = compile_sources(
                    CompilerRequest(
                        "phase-failure",
                        CompilerMode.CONSUMER,
                        (_source("alpha"),),
                        _digest("f"),
                    ),
                    steps,
                    CompilerPorts(lambda request: Ok(_acquired(request)), forbidden, forbidden),
                )

                report = next(item for item in result.reports if item.phase is failing_phase)
                self.assertIs(report.status, PhaseStatus.FAILED)
                self.assertIsNone(result.candidate)
                self.assertIsNone(result.publication)

    def test_consumer_rejects_unfrozen_resolution_before_normalize(self) -> None:
        calls: list[str] = []
        steps = _steps(calls)

        def unresolved(previous, _request):
            calls.append("resolve")
            return Ok(phase_output(ResolvedCompilation("moving-main", frozen=False), b"moving"))

        steps = CompilerSteps(
            steps.parse,
            steps.handshake,
            unresolved,
            steps.normalize,
            steps.validate,
            steps.index,
        )
        result = compile_sources(
            CompilerRequest(
                "unfrozen",
                CompilerMode.CONSUMER,
                (_source("alpha"),),
                _digest("f"),
            ),
            steps,
            CompilerPorts(
                lambda request: Ok(_acquired(request)),
                lambda _value: self.fail("must not materialize"),
                lambda _value: self.fail("must not publish"),
            ),
        )

        self.assertFalse(result.succeeded)
        self.assertEqual(calls, ["parse", "handshake", "resolve"])
        self.assertIn(
            "compiler-unfrozen-resolution", {item.code.value for item in result.diagnostics}
        )

    def test_consumer_requires_frozen_acquisition_and_rejects_port_mismatches(self) -> None:
        missing_lock = compile_sources(
            CompilerRequest(
                "missing-lock",
                CompilerMode.CONSUMER,
                (SourceRequest(SourceAlias("alpha"), "https://example.test/alpha.git"),),
                _digest("f"),
            ),
            _steps([]),
            CompilerPorts(
                lambda _request: self.fail("invalid frozen input must not be acquired"),
                lambda _value: self.fail("must not materialize"),
                lambda _value: self.fail("must not publish"),
            ),
        )
        self.assertIn(
            "compiler-source-not-frozen", {item.code.value for item in missing_lock.diagnostics}
        )

        sources = (_source("alpha"), _source("beta"))

        def mismatched(request):
            acquired = _acquired(request)
            if str(request.alias) == "alpha":
                return Ok(replace(acquired, alias=SourceAlias("wrong")))
            return Ok(replace(acquired, snapshot_digest=_digest("e")))

        mismatch = compile_sources(
            CompilerRequest("mismatch", CompilerMode.CONSUMER, sources, _digest("f")),
            _steps([]),
            CompilerPorts(
                mismatched,
                lambda _value: self.fail("must not materialize"),
                lambda _value: self.fail("must not publish"),
            ),
        )
        self.assertEqual(
            tuple(item.code.value for item in mismatch.diagnostics),
            ("compiler-source-mismatch", "compiler-source-mismatch"),
        )

    def test_maintainer_mode_may_acquire_and_resolve_unfrozen_inputs(self) -> None:
        calls: list[str] = []
        steps = _steps(calls)

        def unresolved(previous, _context):
            calls.append("resolve")
            return Ok(phase_output(ResolvedCompilation("moving-main", frozen=False), b"moving"))

        result = compile_sources(
            CompilerRequest(
                "maintainer",
                CompilerMode.MAINTAINER,
                (SourceRequest(SourceAlias("alpha"), "/working/tree"),),
                _digest("f"),
            ),
            replace(steps, resolve=unresolved),
            CompilerPorts(
                lambda request: Ok(
                    AcquiredSource(
                        request.alias,
                        "working-tree",
                        _digest("a"),
                        SourceSnapshot(SnapshotOrigin.LOCAL, ()),
                    )
                ),
                lambda plan: Ok(ObjectReceipt(plan.digest)),
                lambda publish: Ok(PublishReceipt(publish.snapshot_digest)),
            ),
        )

        self.assertTrue(result.succeeded)

    def test_materialize_accumulates_failures_and_blocks_publish(self) -> None:
        calls: list[str] = []
        attempted: list[str] = []

        def materialize(plan):
            attempted.append(str(plan.digest))
            return Err(
                (
                    Diagnostic(
                        DiagnosticCode(f"store-{plan.digest.value[0]}-failed"),
                        Severity.ERROR,
                        "store failed",
                    ),
                )
            )

        result = compile_sources(
            CompilerRequest(
                "store-failure",
                CompilerMode.CONSUMER,
                (_source("alpha"),),
                _digest("f"),
            ),
            _steps(calls),
            CompilerPorts(
                lambda request: Ok(_acquired(request)),
                materialize,
                lambda _value: self.fail("must not publish"),
            ),
        )

        self.assertEqual(len(attempted), 2)
        self.assertIsNotNone(result.candidate)
        self.assertIsNone(result.publication)
        materialize_report = next(
            report for report in result.reports if report.phase is CompilerPhase.MATERIALIZE
        )
        self.assertIs(materialize_report.status, PhaseStatus.FAILED)

    def test_port_receipt_mismatch_and_publish_failure_are_explicit(self) -> None:
        calls: list[str] = []
        mismatch = compile_sources(
            CompilerRequest(
                "receipt-mismatch",
                CompilerMode.CONSUMER,
                (_source("alpha"),),
                _digest("f"),
            ),
            _steps(calls),
            CompilerPorts(
                lambda request: Ok(_acquired(request)),
                lambda _plan: Ok(ObjectReceipt(_digest("e"))),
                lambda _value: self.fail("must not publish"),
            ),
        )
        self.assertIn(
            "compiler-object-receipt-mismatch", {item.code.value for item in mismatch.diagnostics}
        )

        publish_failure = compile_sources(
            CompilerRequest(
                "publish-failure",
                CompilerMode.CONSUMER,
                (_source("alpha"),),
                _digest("f"),
            ),
            _steps([]),
            CompilerPorts(
                lambda request: Ok(_acquired(request)),
                lambda plan: Ok(ObjectReceipt(plan.digest)),
                lambda _request: Err(
                    (
                        Diagnostic(
                            DiagnosticCode("publish-unavailable"),
                            Severity.ERROR,
                            "publish unavailable",
                        ),
                    )
                ),
            ),
        )
        self.assertIsNone(publish_failure.publication)
        self.assertEqual(publish_failure.reports[-1].status, PhaseStatus.FAILED)

        publish_mismatch = compile_sources(
            CompilerRequest(
                "publish-mismatch",
                CompilerMode.CONSUMER,
                (_source("alpha"),),
                _digest("f"),
            ),
            _steps([]),
            CompilerPorts(
                lambda request: Ok(_acquired(request)),
                lambda plan: Ok(ObjectReceipt(plan.digest)),
                lambda _publish: Ok(PublishReceipt(_digest("e"))),
            ),
        )
        self.assertIn(
            "compiler-publish-receipt-mismatch",
            {item.code.value for item in publish_mismatch.diagnostics},
        )

    def test_index_candidate_must_bind_complete_inputs_and_its_own_bytes(self) -> None:
        for mismatch in ("input", "index"):
            with self.subTest(mismatch=mismatch):
                steps = _steps([])

                def invalid_index(_validated, context, mismatch_kind=mismatch):
                    candidate = _candidate(
                        _digest("e") if mismatch_kind == "input" else context.input_digest
                    )
                    digest = _digest("0") if mismatch_kind == "index" else candidate.index_digest
                    return Ok(PhaseOutput(candidate, digest))

                result = compile_sources(
                    CompilerRequest(
                        "invalid-index",
                        CompilerMode.CONSUMER,
                        (_source("alpha"),),
                        _digest("f"),
                    ),
                    replace(steps, index=invalid_index),
                    CompilerPorts(
                        lambda request: Ok(_acquired(request)),
                        lambda _value: self.fail("must not materialize"),
                        lambda _value: self.fail("must not publish"),
                    ),
                )

                self.assertIn(
                    "compiler-phase-output-invalid",
                    {item.code.value for item in result.diagnostics},
                )
                self.assertIsNone(result.candidate)

    def test_error_output_retains_its_independent_warning(self) -> None:
        warning = Diagnostic(DiagnosticCode("parse-warning"), Severity.WARNING, "warning")
        error = Diagnostic(DiagnosticCode("parse-error"), Severity.ERROR, "error")
        steps = _steps([])
        result = compile_sources(
            CompilerRequest(
                "output-errors",
                CompilerMode.CONSUMER,
                (_source("alpha"),),
                _digest("f"),
            ),
            replace(
                steps,
                parse=lambda _acquired, _context: Ok(
                    phase_output("invalid", b"invalid", diagnostics=(error, warning))
                ),
            ),
            CompilerPorts(
                lambda request: Ok(_acquired(request)),
                lambda _value: self.fail("must not materialize"),
                lambda _value: self.fail("must not publish"),
            ),
        )

        self.assertEqual(
            {item.code.value for item in result.diagnostics},
            {"parse-error", "parse-warning"},
        )

    def test_replay_is_equal_despite_request_order_locator_and_diagnostic_order(self) -> None:
        warning_a = Diagnostic(DiagnosticCode("warning-a"), Severity.WARNING, "a")
        first_request = CompilerRequest(
            "replay",
            CompilerMode.CONSUMER,
            (_source("beta", locator="/tmp/one"), _source("alpha", locator="/tmp/two")),
            _digest("f"),
        )
        second_request = CompilerRequest(
            "replay",
            CompilerMode.CONSUMER,
            (_source("alpha", locator="/different/a"), _source("beta", locator="/different/b")),
            _digest("f"),
        )

        def run(request):
            return compile_sources(
                request,
                _steps([], warning=warning_a),
                CompilerPorts(
                    lambda source: Ok(_acquired(source)),
                    lambda plan: Ok(ObjectReceipt(plan.digest)),
                    lambda publish: Ok(PublishReceipt(publish.snapshot_digest)),
                ),
            )

        self.assertEqual(run(first_request), run(second_request))

    def test_compiler_values_are_frozen_and_candidate_binds_bytes(self) -> None:
        output = phase_output("value", b"canonical")
        candidate = _candidate(_digest("f"))

        with self.assertRaises(FrozenInstanceError):
            output.value = "changed"  # type: ignore[misc]
        with self.assertRaises(ValueError):
            type(candidate)(
                candidate.input_digest,
                candidate.index_bytes,
                _digest("0"),
                candidate.objects,
            )


if __name__ == "__main__":
    unittest.main()
