"""ERR03: pure wizard-stage failure envelope contracts."""

from __future__ import annotations

import dataclasses
import unittest

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity, SourceLocation
from agent_artifacts.domain.result import Err
from agent_artifacts.tui_failures import (
    WizardStageFailure,
    render_wizard_stage_failure,
    wizard_stage_failure,
)
from agent_artifacts.wizard import WizardSession


class WizardStageFailureTests(unittest.TestCase):
    def test_load_failure_keeps_original_diagnostics_and_read_only_recovery_context(self) -> None:
        diagnostic = Diagnostic(
            DiagnosticCode("install-state-legacy"),
            Severity.ERROR,
            "AART 0.1 installation state was detected.",
            SourceLocation(path="/work/project/.agent-artifacts/manifest.json"),
            remediation=("Preview migration first.",),
            details=(("detected_schema", "install-state-v0.1"),),
        )
        session = WizardSession(
            current="artifacts",
            action="install",
            scope="project",
        )
        failure = wizard_stage_failure(session, "load", Err((diagnostic,)))

        self.assertEqual(
            failure,
            WizardStageFailure(
                stage="artifacts",
                operation="load",
                diagnostics=(diagnostic,),
                action="install",
                scope="project",
                project=None,
                recoverable=True,
                choices=("retry", "back", "quit"),
            ),
        )
        self.assertIs(failure.diagnostics[0], diagnostic)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            failure.stage = "review"  # type: ignore[misc]

    def test_stage_failure_rejects_missing_diagnostics_and_inconsistent_recovery(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one diagnostic"):
            WizardStageFailure(
                "artifacts",
                "load",
                (),
                None,
                "project",
                None,
                True,
                ("retry", "back", "quit"),
            )

    def test_renderer_is_bounded_and_contains_only_safe_context_and_allowed_recovery(self) -> None:
        failure = WizardStageFailure(
            stage="artifacts",
            operation="load",
            diagnostics=(
                Diagnostic(
                    DiagnosticCode("install-state-legacy"),
                    Severity.ERROR,
                    "AART 0.1 installation state was detected while loading a project artifact view.",
                    SourceLocation(
                        path="/work/project/.agent-artifacts/manifest.json",
                        pointer="/installed",
                    ),
                    remediation=(
                        "Preview migration: aart migrate state --from 0.1 --scope project --dry-run",
                    ),
                    details=(
                        ("detected_schema", "install-state-v0.1"),
                        ("private_token", "must-not-render"),
                    ),
                ),
            ),
            action="install",
            scope="project",
            project="/work/project",
            recoverable=True,
            choices=("retry", "back", "quit"),
        )

        for width in (40, 80, 120, 200):
            with self.subTest(width=width):
                lines = render_wizard_stage_failure(failure, width=width)
                rendered = "\n".join(lines)

                self.assertIn("Artifacts could not be loaded", rendered)
                self.assertIn("error [install-state-legacy]", rendered)
                self.assertIn("/work/project", rendered)
                self.assertIn("/installed", rendered)
                self.assertIn("install-state-v0.1", rendered)
                self.assertIn("Preview migration", rendered)
                self.assertIn("Retry = r", rendered)
                self.assertIn("Back = b", rendered)
                self.assertIn("Quit = q", rendered)
                self.assertNotIn("private_token", rendered)
                self.assertNotIn("must-not-render", rendered)
                self.assertTrue(all(len(line) <= min(width, 100) for line in lines))

    def test_renderer_does_not_advertise_retry_when_the_failure_cannot_retry(self) -> None:
        failure = WizardStageFailure(
            "review",
            "review",
            (Diagnostic(DiagnosticCode("install-conflict"), Severity.ERROR, "conflict"),),
            "install",
            "project",
            "/work/project",
            False,
            ("back", "quit"),
        )

        rendered = "\n".join(render_wizard_stage_failure(failure, width=80))

        self.assertNotIn("Retry = r", rendered)
        self.assertIn("Back = b", rendered)
        self.assertIn("Quit = q", rendered)
        diagnostic = Diagnostic(DiagnosticCode("source-invalid"), Severity.ERROR, "invalid")
        with self.assertRaisesRegex(ValueError, "retry"):
            WizardStageFailure(
                "artifacts",
                "load",
                (diagnostic,),
                None,
                "project",
                None,
                False,
                ("retry", "back", "quit"),
            )

    def test_legacy_exit_status_is_not_rendered_or_used_to_reduce_read_recovery(self) -> None:
        diagnostic = Diagnostic(
            DiagnosticCode("legacy-wizard-read-failed"),
            Severity.ERROR,
            "catalog could not open",
            details=(("legacy_exit_code", "7"),),
        )
        failure = wizard_stage_failure(
            WizardSession(current="artifacts", action="install", scope="project"),
            "load",
            Err((diagnostic,)),
        )

        self.assertTrue(failure.recoverable)
        self.assertEqual(failure.choices, ("retry", "back", "quit"))
        self.assertNotIn("legacy exit code", "\n".join(render_wizard_stage_failure(failure)))


if __name__ == "__main__":
    unittest.main()
