"""Versioned, redacted, destination-bound optional usage reporting."""

from .aggregation import DashboardFiles, UsageAggregate, aggregate_issue_export, dashboard_files
from .application import RegistryReportingRoute, ReportingApplicationService
from .destination import configured_reporting_source, destination_from_services
from .io import GitHubIssueProvider, browser_provider
from .model import (
    ReportingDestination,
    ReportingFailure,
    ReportingPlan,
    ReportingSubmission,
    UsageReport,
    UsageResult,
    reporting_browser_url,
    reporting_issue_body,
    usage_report_bytes,
)
from .projection import (
    RegistryUsageReport,
    SetupReportState,
    usage_report_from_consumer,
    usage_reports_by_registry_from_consumer,
)
from .runtime import (
    load_local_reporting_service,
    reporting_destination_from_current,
    reporting_routes_from_current,
)

__all__ = [
    "ReportingApplicationService",
    "RegistryReportingRoute",
    "RegistryUsageReport",
    "ReportingDestination",
    "ReportingFailure",
    "ReportingPlan",
    "ReportingSubmission",
    "GitHubIssueProvider",
    "DashboardFiles",
    "SetupReportState",
    "UsageReport",
    "UsageAggregate",
    "UsageResult",
    "configured_reporting_source",
    "browser_provider",
    "aggregate_issue_export",
    "dashboard_files",
    "destination_from_services",
    "load_local_reporting_service",
    "reporting_browser_url",
    "reporting_issue_body",
    "usage_report_bytes",
    "usage_report_from_consumer",
    "usage_reports_by_registry_from_consumer",
    "reporting_destination_from_current",
    "reporting_routes_from_current",
]
