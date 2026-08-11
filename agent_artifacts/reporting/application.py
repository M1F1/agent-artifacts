"""Destination-bound reporting orchestration through injected provider ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from agent_artifacts.configuration.model import ReportingMode
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import SourceAlias
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
from .projection import RegistryUsageReport

REPORTING_INVALID = DiagnosticCode("reporting-invalid")
ReportingProvider = Callable[[ReportingPlan], Result[ReportingSubmission]]


def _error(message: str) -> Err:
    return Err((Diagnostic(REPORTING_INVALID, Severity.ERROR, message),))


@dataclass(frozen=True, slots=True)
class RegistryReportingRoute:
    source_alias: SourceAlias
    destination: ReportingDestination

    def __post_init__(self) -> None:
        if (
            not self.source_alias.value
            or not isinstance(self.destination, ReportingDestination)
            or self.destination.mode is not ReportingMode.PROMPT
        ):
            raise ValueError("registry reporting route is invalid")


@dataclass(frozen=True, slots=True)
class ReportingApplicationService:
    destination: ReportingDestination | None
    browser: ReportingProvider
    authenticated: ReportingProvider
    routes: tuple[RegistryReportingRoute, ...] = ()

    def __post_init__(self) -> None:
        aliases = tuple(route.source_alias for route in self.routes)
        if (
            any(not isinstance(route, RegistryReportingRoute) for route in self.routes)
            or len(set(aliases)) != len(aliases)
            or (self.destination is not None and self.routes)
        ):
            raise ValueError("reporting service routes are invalid")

    def _prepare_for(
        self, destination: ReportingDestination, event: UsageReport
    ) -> Result[ReportingPlan]:
        try:
            payload = usage_report_bytes(event)
            body = reporting_issue_body(event)
            title = f"AART usage report: {event.action} / {event.session_outcome}"
            return Ok(
                ReportingPlan(
                    destination,
                    event,
                    title,
                    body,
                    payload,
                    (
                        reporting_browser_url(destination, event)
                        if destination.mode is ReportingMode.PROMPT
                        else None
                    ),
                )
            )
        except ValueError as error:
            return _error(str(error))

    def prepare(self, event: UsageReport) -> Result[ReportingPlan | None]:
        if self.destination is None:
            return Ok(None)
        return self._prepare_for(self.destination, event)

    def prepare_routed(
        self,
        combined: UsageReport,
        reports: tuple[RegistryUsageReport, ...],
    ) -> Result[tuple[ReportingPlan, ...]]:
        """Prepare one central report or one destination-isolated report per registry endpoint."""

        if self.destination is not None:
            prepared = self._prepare_for(self.destination, combined)
            return prepared if isinstance(prepared, Err) else Ok((prepared.value,))
        route_by_alias = {route.source_alias: route.destination for route in self.routes}
        grouped: dict[ReportingDestination, list[UsageReport]] = {}
        for routed in reports:
            destination = route_by_alias.get(routed.source_alias)
            if destination is not None:
                grouped.setdefault(destination, []).append(routed.report)
        plans = []
        for destination in sorted(grouped, key=lambda item: (item.host, item.repository)):
            events = grouped[destination]
            if any(
                (
                    event.aart_version,
                    event.interface,
                    event.platform,
                    event.action,
                )
                != (
                    combined.aart_version,
                    combined.interface,
                    combined.platform,
                    combined.action,
                )
                for event in events
            ):
                return _error("routed usage reports do not share one session identity")
            event = UsageReport(
                combined.aart_version,
                combined.interface,
                combined.platform,
                combined.action,
                tuple(result for item in events for result in item.results),
            )
            prepared = self._prepare_for(destination, event)
            if isinstance(prepared, Err):
                return prepared
            plans.append(prepared.value)
        return Ok(tuple(plans))

    def submit(self, plan: ReportingPlan) -> Result[ReportingSubmission]:
        allowed = (
            (self.destination,)
            if self.destination is not None
            else tuple(route.destination for route in self.routes)
        )
        if plan.destination not in allowed:
            return _error("reporting plan targets a different effective destination")
        try:
            return (
                self.browser(plan)
                if plan.destination.mode is ReportingMode.PROMPT
                else self.authenticated(plan)
            )
        except Exception:
            return _error("reporting provider failed")
