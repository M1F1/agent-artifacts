"""Destination-bound reporting orchestration through injected provider ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from agent_artifacts.configuration.model import ReportingMode
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result

from .model import (
    ReportingDestination,
    ReportingPlan,
    ReportingSubmission,
    UsageReport,
    reporting_browser_url,
    reporting_issue_body,
    usage_report_bytes,
)

REPORTING_INVALID = DiagnosticCode("reporting-invalid")
ReportingProvider = Callable[[ReportingPlan], Result[ReportingSubmission]]


def _error(message: str) -> Err:
    return Err((Diagnostic(REPORTING_INVALID, Severity.ERROR, message),))


@dataclass(frozen=True, slots=True)
class ReportingApplicationService:
    destination: ReportingDestination | None
    browser: ReportingProvider
    authenticated: ReportingProvider

    def prepare(self, event: UsageReport) -> Result[ReportingPlan | None]:
        if self.destination is None:
            return Ok(None)
        try:
            payload = usage_report_bytes(event)
            body = reporting_issue_body(event)
            title = f"AART usage report: {event.action} / {event.session_outcome}"
            return Ok(
                ReportingPlan(
                    self.destination,
                    event,
                    title,
                    body,
                    payload,
                    (
                        reporting_browser_url(self.destination, event)
                        if self.destination.mode is ReportingMode.PROMPT
                        else None
                    ),
                )
            )
        except ValueError as error:
            return _error(str(error))

    def submit(self, plan: ReportingPlan) -> Result[ReportingSubmission]:
        if self.destination is None or plan.destination != self.destination:
            return _error("reporting plan targets a different effective destination")
        try:
            return (
                self.browser(plan)
                if self.destination.mode is ReportingMode.PROMPT
                else self.authenticated(plan)
            )
        except Exception:
            return _error("reporting provider failed")
