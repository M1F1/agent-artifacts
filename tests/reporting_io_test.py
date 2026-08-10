from __future__ import annotations

import subprocess
import unittest

from agent_artifacts.configuration.model import ReportingMode
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.reporting.application import ReportingApplicationService
from agent_artifacts.reporting.io import GitHubIssueProvider, browser_provider
from agent_artifacts.reporting.model import (
    ReportingDestination,
    UsageReport,
    UsageResult,
)


def _plan(mode: ReportingMode):
    service = ReportingApplicationService(
        ReportingDestination(mode, "github.company.example", "agents/usage"),
        browser=lambda _plan: Err(()),  # unreachable
        authenticated=lambda _plan: Err(()),  # unreachable
    )
    prepared = service.prepare(
        UsageReport(
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
    )
    assert isinstance(prepared, Ok) and prepared.value is not None
    return prepared.value


class ReportingIoTest(unittest.TestCase):
    def test_browser_opens_only_the_exact_prepared_enterprise_url(self) -> None:
        calls = []
        provider = browser_provider(lambda url: calls.append(url) or True)
        plan = _plan(ReportingMode.PROMPT)

        result = provider(plan)

        assert isinstance(result, Ok), result
        self.assertEqual(result.value.status, "browser-opened")
        self.assertEqual(calls, [plan.browser_url])

    def test_authenticated_provider_checks_host_then_creates_issue_with_stdin_body(self) -> None:
        calls = []

        def run(argv, *, input, timeout, shell, check, capture_output):
            calls.append((argv, input, timeout, shell, check, capture_output))
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        plan = _plan(ReportingMode.AUTOMATIC)
        result = GitHubIssueProvider(run=run)(plan)

        assert isinstance(result, Ok), result
        self.assertEqual(calls[0][0], ("gh", "auth", "status", "--hostname", plan.destination.host))
        self.assertEqual(calls[0][1], b"")
        self.assertEqual(
            calls[1][0],
            (
                "gh",
                "issue",
                "create",
                "--repo",
                "github.company.example/agents/usage",
                "--title",
                plan.title,
                "--body-file",
                "-",
            ),
        )
        self.assertEqual(calls[1][1], plan.body.encode("utf-8"))
        self.assertTrue(all(call[3] is False for call in calls))

    def test_provider_failure_never_exposes_command_output(self) -> None:
        def run(argv, **_kwargs):
            return subprocess.CompletedProcess(argv, 1, b"TOKEN=secret", b"/Users/alice/private")

        result = GitHubIssueProvider(run=run)(_plan(ReportingMode.AUTOMATIC))

        assert isinstance(result, Err), result
        diagnostic = result.diagnostics[0]
        self.assertNotIn("secret", diagnostic.message)
        self.assertNotIn("/Users", diagnostic.message)
        self.assertEqual(diagnostic.code.value, "reporting-provider-failed")


if __name__ == "__main__":
    unittest.main()
