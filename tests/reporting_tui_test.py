from __future__ import annotations

import unittest

from agent_artifacts import tui
from agent_artifacts.configuration.model import ReportingMode
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.reporting.application import ReportingApplicationService
from agent_artifacts.reporting.model import (
    ReportingDestination,
    ReportingSubmission,
    UsageReport,
    UsageResult,
)


def _event() -> UsageReport:
    return UsageReport(
        "1.0.0a1",
        "tui",
        "darwin",
        "install",
        (
            UsageResult(
                "skill",
                "review",
                "codex",
                "project",
                "copy",
                ("copy",),
                "changed",
                "not-required",
            ),
        ),
    )


def _failure() -> Err:
    return Err(
        (
            Diagnostic(
                DiagnosticCode("reporting-provider-failed"),
                Severity.ERROR,
                "provider unavailable",
            ),
        )
    )


class ReportingTuiTest(unittest.TestCase):
    def test_disabled_reporting_has_no_prompt_preview_or_provider_call(self) -> None:
        calls = []
        service = ReportingApplicationService(
            None,
            lambda _plan: calls.append("browser") or _failure(),
            lambda _plan: calls.append("authenticated") or _failure(),
        )

        tui._offer_usage_report(
            service,
            _event(),
            read=lambda _prompt: self.fail("disabled reporting prompted"),
            write=lambda line: calls.append(line),
        )

        self.assertEqual(calls, [])

    def test_prompt_defaults_to_no_then_previews_exact_payload_before_browser(self) -> None:
        provider_calls = []
        service = ReportingApplicationService(
            ReportingDestination(ReportingMode.PROMPT, "github.com", "org/registry"),
            lambda plan: provider_calls.append(plan.payload)
            or Ok(ReportingSubmission("browser-opened")),
            lambda _plan: self.fail("authenticated provider used in prompt mode"),
        )
        writes = []

        tui._offer_usage_report(
            service,
            _event(),
            read=lambda _prompt: "",
            write=writes.append,
        )
        self.assertEqual(provider_calls, [])
        self.assertNotIn("Exact redacted", "\n".join(writes))

        writes.clear()
        answers = iter(("y", "y"))
        tui._offer_usage_report(
            service,
            _event(),
            read=lambda _prompt: next(answers),
            write=writes.append,
        )
        self.assertEqual(len(provider_calls), 1)
        self.assertIn(provider_calls[0].decode().strip(), writes)
        self.assertIn("Usage report opened in the browser.", writes)

    def test_automatic_failure_is_warning_only_and_never_prompts(self) -> None:
        service = ReportingApplicationService(
            ReportingDestination(ReportingMode.AUTOMATIC, "github.com", "org/registry"),
            lambda _plan: self.fail("browser provider used in automatic mode"),
            lambda _plan: _failure(),
        )
        writes = []

        tui._offer_usage_report(
            service,
            _event(),
            read=lambda _prompt: self.fail("automatic reporting prompted"),
            write=writes.append,
        )

        self.assertTrue(any(line.startswith("warning:") for line in writes))
        self.assertTrue(any('"report_type":"aart-usage-session"' in line for line in writes))


if __name__ == "__main__":
    unittest.main()
