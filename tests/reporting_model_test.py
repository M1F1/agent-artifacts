from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlsplit

from agent_artifacts.configuration.model import ReportingMode
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.reporting.model import (
    ReportingDestination,
    ReportingFailure,
    UsageReport,
    UsageResult,
    reporting_browser_url,
    reporting_issue_body,
    usage_report_bytes,
)


class ReportingModelTest(unittest.TestCase):
    def _result(self, name: str = "atlassian", *, artifact: str = "changed") -> UsageResult:
        return UsageResult(
            "mcp",
            name,
            "tabnine",
            "user",
            "copy",
            ("copy",),
            artifact,
            "configured",
            ObjectDigest("sha256", "a" * 64),
        )

    def test_event_is_canonical_versioned_and_contains_no_source_or_machine_identity(self) -> None:
        event = UsageReport("1.0.0a1", "tui", "darwin", "install", (self._result(),))
        payload = usage_report_bytes(event)

        self.assertEqual(payload, usage_report_bytes(event))
        self.assertIn(b'"report_type":"aart-usage-session"', payload)
        self.assertIn(b'"session_outcome":"succeeded"', payload)
        for forbidden in (
            b"source",
            b"repository",
            b"username",
            b"hostname",
            b"path",
            b"stdout",
            b"stderr",
            b"credential",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, payload)

    def test_partial_session_preserves_all_eleven_terminal_results(self) -> None:
        successful = tuple(self._result(f"artifact-{index}") for index in range(10))
        failed = UsageResult(
            "mcp",
            "artifact-10",
            "tabnine",
            "user",
            "copy",
            ("copy",),
            "failed",
            "skipped",
            failure=ReportingFailure(
                "artifact-install",
                "unexpected",
                "artifact-failed",
                retryable=True,
            ),
        )
        event = UsageReport("1.0.0a1", "tui", "darwin", "install", (*successful, failed))

        self.assertEqual(len(event.results), 11)
        self.assertEqual(event.session_outcome, "partial")
        self.assertEqual(dict(event.summary)["selected"], 11)
        self.assertEqual(dict(event.summary)["artifact_failed"], 1)

    def test_issue_body_and_enterprise_browser_url_bind_the_exact_payload(self) -> None:
        event = UsageReport("1.0.0a1", "tui", "darwin", "install", (self._result(),))
        body = reporting_issue_body(event)
        destination = ReportingDestination(
            ReportingMode.PROMPT,
            "github.company.example",
            "agents/company-agent-artifacts-registry",
        )
        url = reporting_browser_url(destination, event)

        self.assertEqual(body.count("```json"), 1)
        self.assertIn(usage_report_bytes(event).decode("utf-8").strip(), body)
        self.assertTrue(
            url.startswith(
                "https://github.company.example/agents/company-agent-artifacts-registry/issues/new?"
            )
        )
        self.assertIn("template=usage-report.yml", url)
        self.assertIn("report=", url)
        self.assertEqual(
            parse_qs(urlsplit(url).query)["report"],
            [usage_report_bytes(event).decode("utf-8").strip()],
        )
        self.assertNotIn("```", parse_qs(urlsplit(url).query)["report"][0])

    def test_values_reject_unbounded_or_path_shaped_data(self) -> None:
        for build in (
            lambda: ReportingDestination(ReportingMode.DISABLED, "github.com", "org/repo"),
            lambda: ReportingDestination(ReportingMode.PROMPT, "https://github.com", "org/repo"),
            lambda: ReportingDestination(ReportingMode.PROMPT, "github.com", "org/repo/extra"),
            lambda: UsageResult(
                "mcp",
                "../secret",
                "tabnine",
                "user",
                "copy",
                ("copy",),
                "failed",
                "skipped",
            ),
            lambda: UsageResult(
                "skill",
                "a" * 65,
                "codex",
                "project",
                "copy",
                ("copy",),
                "changed",
                "not-required",
            ),
            lambda: ReportingFailure(
                "artifact-install",
                "unexpected",
                "bad code",
            ),
        ):
            with self.subTest(build=build):
                with self.assertRaises(ValueError):
                    build()


if __name__ == "__main__":
    unittest.main()
