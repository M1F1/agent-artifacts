from __future__ import annotations

import unittest
from typing import cast

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
    SourceRequest,
    acquired_compilation,
    compilation_candidate,
    materialization_digest,
    object_plan,
    phase_output,
    publication_request,
)
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest, SourceAlias
from agent_artifacts.protocol.native_tree import SnapshotOrigin, SourceSnapshot


def _digest(character: str) -> ObjectDigest:
    return ObjectDigest("sha256", character * 64)


def _source(alias: str = "alpha") -> SourceRequest:
    return SourceRequest(
        SourceAlias(alias), f"https://example.test/{alias}", "locked", _digest("a")
    )


def _acquired(alias: str = "alpha") -> AcquiredSource:
    return AcquiredSource(
        SourceAlias(alias),
        "locked",
        _digest("a"),
        SourceSnapshot(SnapshotOrigin.IMMUTABLE_GIT, ()),
    )


class CompilerModelTest(unittest.TestCase):
    def test_request_and_acquisition_invariants_reject_unsafe_programmer_values(self) -> None:
        invalid_digest = ObjectDigest("md5", "0" * 64)
        cases = (
            lambda: SourceRequest(SourceAlias(""), "locator"),
            lambda: SourceRequest(SourceAlias("alpha"), ""),
            lambda: SourceRequest(SourceAlias("alpha"), "locator", "bad\nrevision"),
            lambda: SourceRequest(SourceAlias("alpha"), "locator", "locked", invalid_digest),
            lambda: CompilerRequest("", CompilerMode.CONSUMER, (), _digest("a")),
            lambda: CompilerRequest("key", cast(CompilerMode, "invalid"), (), _digest("a")),
            lambda: CompilerRequest("key", CompilerMode.CONSUMER, (), invalid_digest),
            lambda: CompilerRequest(
                "key", CompilerMode.CONSUMER, (_source(), _source()), _digest("a")
            ),
            lambda: AcquiredSource(
                SourceAlias(""), "locked", _digest("a"), SourceSnapshot(SnapshotOrigin.LOCAL, ())
            ),
            lambda: AcquiredSource(
                SourceAlias("alpha"),
                "bad\nrevision",
                _digest("a"),
                SourceSnapshot(SnapshotOrigin.LOCAL, ()),
            ),
            lambda: AcquiredSource(
                SourceAlias("alpha"),
                "locked",
                invalid_digest,
                SourceSnapshot(SnapshotOrigin.LOCAL, ()),
            ),
            lambda: AcquiredSource(
                SourceAlias("alpha"),
                "locked",
                _digest("a"),
                cast(SourceSnapshot, object()),
            ),
            lambda: AcquiredCompilation((_acquired(), _acquired()), _digest("a")),
            lambda: CompilerContext(
                "key",
                CompilerMode.CONSUMER,
                _digest("a"),
                invalid_digest,
            ),
            lambda: CompilerContext("", CompilerMode.CONSUMER, _digest("a"), _digest("b")),
            lambda: CompilerContext(
                "key", cast(CompilerMode, "invalid"), _digest("a"), _digest("b")
            ),
            lambda: CompilerContext("key", CompilerMode.CONSUMER, invalid_digest, _digest("b")),
        )
        for factory in cases:
            with self.subTest(factory=factory):
                with self.assertRaises(ValueError):
                    factory()

    def test_phase_and_object_values_validate_digests_bytes_and_order(self) -> None:
        invalid_digest = ObjectDigest("sha256", "bad")
        warning_b = Diagnostic(DiagnosticCode("warning-b"), Severity.WARNING, "b")
        warning_a = Diagnostic(DiagnosticCode("warning-a"), Severity.WARNING, "a")
        output = phase_output("value", b"value", diagnostics=(warning_b, warning_a))
        first = object_plan(b"first")
        second = object_plan(b"second")
        candidate = compilation_candidate(
            input_digest=_digest("a"),
            index_bytes=b"index",
            objects=(second, first),
        )

        self.assertEqual(
            tuple(item.code.value for item in output.diagnostics), ("warning-a", "warning-b")
        )
        self.assertEqual(
            candidate.objects, tuple(sorted((first, second), key=lambda item: str(item.digest)))
        )
        self.assertEqual(
            materialization_digest((ObjectReceipt(second.digest), ObjectReceipt(first.digest))),
            materialization_digest((ObjectReceipt(first.digest), ObjectReceipt(second.digest))),
        )

        cases = (
            lambda: PhaseOutput("value", invalid_digest),
            lambda: ObjectPlan(_digest("a"), b"different"),
            lambda: ObjectReceipt(invalid_digest),
            lambda: CompilationCandidate(_digest("a"), b"index", _digest("b"), ()),
            lambda: CompilationCandidate(
                _digest("a"),
                b"index",
                candidate.index_digest,
                (first, first),
            ),
        )
        for factory in cases:
            with self.subTest(factory=factory):
                with self.assertRaises(ValueError):
                    factory()

    def test_publication_request_binds_build_input_index_and_objects(self) -> None:
        candidate = compilation_candidate(
            input_digest=_digest("a"),
            index_bytes=b"index",
            objects=(object_plan(b"first"), object_plan(b"second")),
        )
        request = publication_request(candidate, "build")

        self.assertEqual(request.object_digests, tuple(sorted(request.object_digests, key=str)))
        cases = (
            lambda: PublishRequest(
                "",
                request.input_digest,
                request.index_bytes,
                request.index_digest,
                request.object_digests,
                request.snapshot_digest,
            ),
            lambda: PublishRequest(
                request.build_key,
                request.input_digest,
                b"changed",
                request.index_digest,
                request.object_digests,
                request.snapshot_digest,
            ),
            lambda: PublishRequest(
                request.build_key,
                request.input_digest,
                request.index_bytes,
                request.index_digest,
                (request.object_digests[0], request.object_digests[0]),
                request.snapshot_digest,
            ),
            lambda: PublishRequest(
                request.build_key,
                request.input_digest,
                request.index_bytes,
                request.index_digest,
                (ObjectDigest("md5", "0" * 64),),
                request.snapshot_digest,
            ),
            lambda: PublishRequest(
                request.build_key,
                request.input_digest,
                request.index_bytes,
                request.index_digest,
                request.object_digests,
                _digest("e"),
            ),
            lambda: PublishReceipt(ObjectDigest("sha256", "bad")),
        )
        for factory in cases:
            with self.subTest(factory=factory):
                with self.assertRaises(ValueError):
                    factory()

    def test_phase_reports_and_complete_run_enforce_shape(self) -> None:
        warning = Diagnostic(DiagnosticCode("warning"), Severity.WARNING, "warning")
        report = PhaseReport(
            CompilerPhase.PARSE,
            PhaseStatus.SUCCEEDED,
            _digest("a"),
            _digest("b"),
            (warning,),
        )
        self.assertEqual(report.diagnostics, (warning,))

        with self.assertRaises(ValueError):
            PhaseReport(CompilerPhase.PARSE, PhaseStatus.FAILED, ObjectDigest("sha256", "bad"))
        with self.assertRaises(ValueError):
            CompilerRun((report,))

        reports = tuple(
            PhaseReport(phase, PhaseStatus.SKIPPED) for phase in reversed(tuple(CompilerPhase))
        )
        candidate = compilation_candidate(
            input_digest=_digest("a"), index_bytes=b"index", objects=()
        )
        receipt = PublishReceipt(_digest("b"))
        with self.assertRaises(ValueError):
            CompilerRun(reports, publication=receipt)
        complete = CompilerRun(reports, candidate=candidate)
        self.assertEqual(tuple(item.phase for item in complete.reports), tuple(CompilerPhase))
        self.assertFalse(complete.succeeded)

    def test_acquired_input_digest_ignores_locator_and_source_order(self) -> None:
        first = acquired_compilation((_acquired("beta"), _acquired("alpha")), _digest("f"))
        second = acquired_compilation((_acquired("alpha"), _acquired("beta")), _digest("f"))

        self.assertEqual(first, second)
        self.assertNotEqual(
            first.input_digest,
            acquired_compilation(
                (_acquired("alpha"), _acquired("beta")), _digest("e")
            ).input_digest,
        )
        changed_revision = AcquiredSource(
            SourceAlias("alpha"),
            "new-revision",
            _digest("a"),
            SourceSnapshot(SnapshotOrigin.IMMUTABLE_GIT, ()),
        )
        self.assertNotEqual(
            first.input_digest,
            acquired_compilation((changed_revision, _acquired("beta")), _digest("f")).input_digest,
        )
        with self.assertRaises(ValueError):
            acquired_compilation((), ObjectDigest("md5", "0" * 64))


if __name__ == "__main__":
    unittest.main()
