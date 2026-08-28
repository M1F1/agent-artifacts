from __future__ import annotations

import unittest

from agent_artifacts.configuration.model import ReportingMode
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.reporting.application import (
    RegistryReportingRoute,
    ReportingApplicationService,
)
from agent_artifacts.reporting.model import (
    ReportingDestination,
    ReportingSubmission,
    UsageReport,
    UsageResult,
)
from agent_artifacts.reporting.projection import RegistryUsageReport
from tests.credential_fixtures import assignment


def _event(name: str = "review") -> UsageReport:
    return UsageReport(
        "1.0.0a1",
        "tui",
        "darwin",
        "install",
        (
            UsageResult(
                "skill",
                name,
                "codex",
                "project",
                "copy",
                ("copy",),
                "changed",
                "not-required",
            ),
        ),
    )


class ReportingApplicationTest(unittest.TestCase):
    def test_disabled_without_destination_has_no_plan_or_provider_call(self) -> None:
        calls = []
        service = ReportingApplicationService(
            None,
            browser=lambda _plan: calls.append("browser"),
            authenticated=lambda _plan: calls.append("authenticated"),
        )

        prepared = service.prepare(_event())

        assert isinstance(prepared, Ok), prepared
        self.assertIsNone(prepared.value)
        self.assertEqual(calls, [])

    def test_prompt_and_automatic_modes_use_distinct_injected_ports(self) -> None:
        calls = []

        def browser(plan):
            calls.append(("browser", plan.payload))
            return Ok(ReportingSubmission("browser-opened"))

        def authenticated(plan):
            calls.append(("authenticated", plan.payload))
            return Ok(ReportingSubmission("submitted"))

        for mode, expected in (
            (ReportingMode.PROMPT, "browser"),
            (ReportingMode.AUTOMATIC, "authenticated"),
        ):
            with self.subTest(mode=mode):
                calls.clear()
                service = ReportingApplicationService(
                    ReportingDestination(mode, "github.com", "org/registry"),
                    browser=browser,
                    authenticated=authenticated,
                )
                prepared = service.prepare(_event())
                assert isinstance(prepared, Ok) and prepared.value is not None
                submitted = service.submit(prepared.value)
                assert isinstance(submitted, Ok), submitted
                self.assertEqual(calls[0][0], expected)
                self.assertEqual(calls[0][1], prepared.value.payload)

    def test_provider_failure_is_a_typed_reporting_result(self) -> None:
        failure = Err(
            (
                Diagnostic(
                    DiagnosticCode("reporting-provider-failed"),
                    Severity.ERROR,
                    "provider unavailable",
                ),
            )
        )
        service = ReportingApplicationService(
            ReportingDestination(ReportingMode.AUTOMATIC, "github.com", "org/registry"),
            browser=lambda _plan: failure,
            authenticated=lambda _plan: failure,
        )
        prepared = service.prepare(_event())
        assert isinstance(prepared, Ok) and prepared.value is not None

        self.assertIsInstance(service.submit(prepared.value), Err)

    def test_provider_exception_is_isolated_and_automatic_skips_browser_url(self) -> None:
        many = tuple(
            UsageResult(
                "skill",
                f"artifact-{index}",
                "codex",
                "project",
                "copy",
                ("copy",),
                "changed",
                "not-required",
            )
            for index in range(100)
        )
        event = UsageReport("1.0.0a1", "tui", "darwin", "install", many)
        service = ReportingApplicationService(
            ReportingDestination(ReportingMode.AUTOMATIC, "github.com", "org/registry"),
            browser=lambda _plan: self.fail("browser provider used"),
            authenticated=lambda _plan: (_ for _ in ()).throw(
                RuntimeError(assignment("TOKEN", "secret"))
            ),
        )

        prepared = service.prepare(event)
        assert isinstance(prepared, Ok) and prepared.value is not None, prepared
        self.assertIsNone(prepared.value.browser_url)
        submitted = service.submit(prepared.value)
        assert isinstance(submitted, Err), submitted
        self.assertEqual(submitted.diagnostics[0].code.value, "reporting-invalid")
        self.assertNotIn("secret", submitted.diagnostics[0].message)

    def test_registry_routes_partition_payloads_and_deduplicate_the_same_endpoint(self) -> None:
        company = ReportingDestination(ReportingMode.PROMPT, "github.com", "org/company-usage")
        public = ReportingDestination(ReportingMode.PROMPT, "github.com", "org/public-usage")
        service = ReportingApplicationService(
            None,
            browser=lambda _plan: Ok(ReportingSubmission("browser-opened")),
            authenticated=lambda _plan: self.fail("automatic provider used for prompt routes"),
            routes=(
                RegistryReportingRoute(SourceAlias("company"), company),
                RegistryReportingRoute(SourceAlias("company-release"), company),
                RegistryReportingRoute(SourceAlias("public"), public),
            ),
        )
        routed = (
            RegistryUsageReport(SourceAlias("company"), _event("review")),
            RegistryUsageReport(SourceAlias("company-release"), _event("lint")),
            RegistryUsageReport(SourceAlias("public"), _event("search")),
        )
        combined = UsageReport(
            "1.0.0a1",
            "tui",
            "darwin",
            "install",
            tuple(result for item in routed for result in item.report.results),
        )

        prepared = service.prepare_routed(combined, routed)

        assert isinstance(prepared, Ok), prepared
        self.assertEqual(len(prepared.value), 2)
        by_repository = {plan.destination.repository: plan for plan in prepared.value}
        company_payload = by_repository["org/company-usage"].payload.decode("utf-8")
        public_payload = by_repository["org/public-usage"].payload.decode("utf-8")
        self.assertIn('"artifact_name":"review"', company_payload)
        self.assertIn('"artifact_name":"lint"', company_payload)
        self.assertNotIn('"artifact_name":"search"', company_payload)
        self.assertIn('"artifact_name":"search"', public_payload)
        self.assertNotIn("company-release", company_payload)


if __name__ == "__main__":
    unittest.main()
