"""D01 contracts for the IO-free typed domain kernel and legacy boundary."""

from __future__ import annotations

import ast
import dataclasses
import importlib
import pathlib
import unittest
from typing import Protocol, cast

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _DataclassParams(Protocol):
    frozen: bool


class DomainIdentifiersTest(unittest.TestCase):
    def test_identifiers_are_nominal_frozen_and_render_canonical_coordinates(self):
        from agent_artifacts.domain.identifiers import (
            ArtifactCoordinate,
            ArtifactIdentity,
            ObjectDigest,
            SourceAlias,
            SourceId,
            SourceOrigin,
        )

        alias = SourceAlias("public")
        identity = ArtifactIdentity("skill", "code-review")
        coordinate = ArtifactCoordinate(alias, identity, "1.4.2")
        digest = ObjectDigest("sha256", "a" * 64)

        self.assertEqual(str(SourceId("public-agent-artifacts")), "public-agent-artifacts")
        self.assertEqual(
            str(SourceOrigin("https://example.test/artifacts.git")),
            "https://example.test/artifacts.git",
        )
        self.assertEqual(str(identity), "skill/code-review")
        self.assertEqual(str(coordinate), "public/skill/code-review@1.4.2")
        self.assertEqual(str(ObjectDigest("sha256", "a" * 64)), f"sha256:{'a' * 64}")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            digest.value = "b" * 64  # type: ignore[misc]


class DomainDiagnosticsTest(unittest.TestCase):
    def test_diagnostics_sort_by_location_and_serialize_only_through_boundary(self):
        from agent_artifacts.domain.diagnostics import (
            Diagnostic,
            DiagnosticCode,
            Severity,
            SourceLocation,
            diagnostic_to_data,
            sort_diagnostics,
        )
        from agent_artifacts.domain.identifiers import SourceAlias

        later = Diagnostic(
            code=DiagnosticCode("source-invalid"),
            severity=Severity.ERROR,
            message="later",
            location=SourceLocation(SourceAlias("zeta"), "b.json", "/name", 4, 2),
            remediation=("aart source health zeta",),
        )
        earlier = Diagnostic(
            code=DiagnosticCode("source-incompatible"),
            severity=Severity.WARNING,
            message="earlier",
            location=SourceLocation(SourceAlias("alpha"), "a.json", "/version", 1, 1),
        )

        self.assertEqual(sort_diagnostics((later, earlier)), (earlier, later))
        self.assertEqual(
            diagnostic_to_data(earlier),
            {
                "code": "source-incompatible",
                "severity": "warning",
                "message": "earlier",
                "location": {
                    "source": "alpha",
                    "path": "a.json",
                    "pointer": "/version",
                    "line": 1,
                    "column": 1,
                },
                "remediation": [],
            },
        )

    def test_initial_stable_codes_match_the_spec(self):
        from agent_artifacts.domain.diagnostics import INITIAL_ERROR_CODES

        self.assertEqual(
            INITIAL_ERROR_CODES,
            (
                "artifact-ambiguous",
                "artifact-incompatible",
                "artifact-not-found",
                "digest-mismatch",
                "import-lossy",
                "import-stale",
                "install-conflict",
                "lock-stale",
                "no-source-configured",
                "offline-object-missing",
                "setup-policy-denied",
                "source-auth-failed",
                "source-incompatible",
                "source-invalid",
                "source-policy-denied",
                "source-unavailable",
            ),
        )


class DomainResultTest(unittest.TestCase):
    def test_result_combinators_are_typed_and_accumulate_sorted_diagnostics(self):
        from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
        from agent_artifacts.domain.result import Err, Ok, bind, collect, map_ok

        first = Diagnostic(DiagnosticCode("z-problem"), Severity.ERROR, "z")
        second = Diagnostic(DiagnosticCode("a-problem"), Severity.ERROR, "a")

        self.assertEqual(map_ok(Ok(2), lambda value: value * 3), Ok(6))
        self.assertEqual(bind(Ok(2), lambda value: Ok(str(value))), Ok("2"))
        failed = collect((Ok(1), Err((first,)), Ok(2), Err((second,))))
        self.assertIsInstance(failed, Err)
        assert isinstance(failed, Err)
        self.assertEqual(
            tuple(item.code.value for item in failed.diagnostics), ("a-problem", "z-problem")
        )

    def test_err_requires_at_least_one_diagnostic(self):
        from agent_artifacts.domain.result import Err

        with self.assertRaises(ValueError):
            Err(())

    def test_result_predicates_mapping_and_error_factory_preserve_typed_values(self):
        from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
        from agent_artifacts.domain.result import Err, Ok, Result, err, is_err, is_ok, map_err

        problem = Diagnostic(DiagnosticCode("source-invalid"), Severity.ERROR, "invalid")
        failure = err(problem)
        mapped: Result[object] = map_err(
            failure,
            lambda item: Diagnostic(item.code, Severity.WARNING, item.message),
        )

        self.assertTrue(is_ok(Ok("value")))
        self.assertFalse(is_ok(failure))
        self.assertTrue(is_err(failure))
        self.assertFalse(is_err(Ok("value")))
        self.assertEqual(mapped, Err((Diagnostic(problem.code, Severity.WARNING, "invalid"),)))
        self.assertEqual(map_err(Ok("value"), lambda item: item), Ok("value"))


class DomainOutcomeTest(unittest.TestCase):
    def test_terminal_outcome_is_canonical_and_has_structured_counts(self):
        from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
        from agent_artifacts.domain.outcomes import (
            OperationOutcome,
            TerminalItem,
            TerminalStatus,
            changed_count,
            operation_outcome_to_data,
            outcome_counts,
        )

        failure = Diagnostic(DiagnosticCode("artifact-incompatible"), Severity.ERROR, "unsupported")
        outcome = OperationOutcome(
            operation="install",
            selected=3,
            items=(
                TerminalItem("zeta/skill/b", TerminalStatus.CURRENT),
                TerminalItem("alpha/skill/a", TerminalStatus.CHANGED),
                TerminalItem("alpha/skill/c", TerminalStatus.FAILED, (failure,)),
            ),
            diagnostics=(failure,),
            remediation=("aart check",),
        )

        self.assertEqual(
            tuple(item.key for item in outcome.items),
            ("alpha/skill/a", "alpha/skill/c", "zeta/skill/b"),
        )
        self.assertEqual(outcome_counts(outcome), (("changed", 1), ("current", 1), ("failed", 1)))
        self.assertEqual(changed_count(outcome), 1)
        data = operation_outcome_to_data(outcome)
        self.assertEqual(data["selected"], 3)
        self.assertEqual(data["changed"], 1)
        self.assertEqual(data["counts"], {"changed": 1, "current": 1, "failed": 1})

    def test_session_status_accounts_for_root_errors_partial_work_and_cancellation(self):
        from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
        from agent_artifacts.domain.outcomes import (
            OperationOutcome,
            SessionStatus,
            TerminalItem,
            TerminalStatus,
            session_status,
        )

        problem = Diagnostic(DiagnosticCode("source-unavailable"), Severity.ERROR, "offline")
        changed = TerminalItem("skill/a", TerminalStatus.CHANGED)
        failed = TerminalItem("skill/b", TerminalStatus.FAILED, (problem,))
        cancelled = TerminalItem("skill/c", TerminalStatus.CANCELLED)

        self.assertEqual(session_status(OperationOutcome("sync", 0)), SessionStatus.SUCCEEDED)
        self.assertEqual(
            session_status(OperationOutcome("sync", 0, diagnostics=(problem,))),
            SessionStatus.FAILED,
        )
        self.assertEqual(
            session_status(OperationOutcome("install", 2, (changed, failed))),
            SessionStatus.PARTIAL,
        )
        self.assertEqual(
            session_status(OperationOutcome("install", 1, (cancelled,))),
            SessionStatus.CANCELLED,
        )
        self.assertEqual(
            session_status(OperationOutcome("install", 2, (changed, cancelled))),
            SessionStatus.PARTIAL,
        )
        with self.assertRaises(ValueError):
            OperationOutcome("install", -1)


class DomainCollectionsTest(unittest.TestCase):
    def test_sorted_upsert_and_remove_return_replacements_without_mutating_input(self):
        from agent_artifacts.domain.collections import remove_sorted, sorted_values, upsert_sorted

        original = (("b", 2), ("a", 1))
        ordered = sorted_values(original, key=lambda item: item[0])
        updated = upsert_sorted(ordered, ("b", 3), key=lambda item: item[0])
        removed = remove_sorted(updated, "a", key=lambda item: item[0])

        self.assertEqual(original, (("b", 2), ("a", 1)))
        self.assertEqual(ordered, (("a", 1), ("b", 2)))
        self.assertEqual(updated, (("a", 1), ("b", 3)))
        self.assertEqual(removed, (("b", 3),))


class DomainPortsTest(unittest.TestCase):
    def test_ports_are_small_runtime_checkable_callable_protocols(self):
        from agent_artifacts.domain.ports import CommandPort, QueryPort
        from agent_artifacts.domain.result import Ok

        class UpperQuery:
            def __call__(self, request: str):
                return Ok(request.upper())

        class LengthCommand:
            def __call__(self, command: str):
                return Ok(len(command))

        self.assertIsInstance(UpperQuery(), QueryPort)
        self.assertIsInstance(LengthCommand(), CommandPort)
        self.assertEqual(UpperQuery()("aart"), Ok("AART"))
        self.assertEqual(LengthCommand()("aart"), Ok(4))


class DomainArchitectureTest(unittest.TestCase):
    def test_domain_modules_do_not_import_io_or_legacy_layers(self):
        domain = ROOT / "agent_artifacts" / "domain"
        self.assertTrue(domain.is_dir(), domain)
        forbidden_roots = {"http", "os", "pathlib", "shutil", "socket", "subprocess", "urllib"}
        forbidden_modules = {"agent_artifacts.model", "agent_artifacts.outcomes"}
        violations: list[str] = []
        for path in sorted(domain.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    modules = () if node.module is None else (node.module,)
                else:
                    continue
                for module in modules:
                    if module.split(".", 1)[0] in forbidden_roots or module in forbidden_modules:
                        violations.append(f"{path.name}: {module}")
        self.assertEqual(violations, [])

    def test_every_domain_dataclass_is_frozen(self):
        module_names = (
            "diagnostics",
            "identifiers",
            "outcomes",
            "result",
        )
        mutable: list[str] = []
        found: list[str] = []
        for name in module_names:
            module = importlib.import_module(f"agent_artifacts.domain.{name}")
            for value in vars(module).values():
                if not isinstance(value, type) or value.__module__ != module.__name__:
                    continue
                if not dataclasses.is_dataclass(value):
                    continue
                found.append(f"{name}.{value.__name__}")
                params = cast(_DataclassParams, vars(value)["__dataclass_params__"])
                if not params.frozen:
                    mutable.append(f"{name}.{value.__name__}")
        self.assertGreater(len(found), 0)
        self.assertEqual(mutable, [])


if __name__ == "__main__":
    unittest.main()
