"""ERR03: pure wizard-stage failure envelope contracts."""

from __future__ import annotations

import dataclasses
import unittest

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity, SourceLocation
from agent_artifacts.domain.result import Err
from agent_artifacts.tui_failures import WizardStageFailure, wizard_stage_failure
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


if __name__ == "__main__":
    unittest.main()
