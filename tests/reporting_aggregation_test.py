from __future__ import annotations

import json
import unittest

from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.reporting.aggregation import aggregate_issue_export, dashboard_files
from agent_artifacts.reporting.model import UsageReport, UsageResult, reporting_issue_body


def _report(name: str, status: str) -> UsageReport:
    return UsageReport(
        "1.0.0a1",
        "tui",
        "linux",
        "install",
        (
            UsageResult(
                "skill",
                name,
                "codex",
                "project",
                "copy",
                ("copy",),
                status,
                "not-required",
            ),
        ),
    )


class ReportingAggregationTest(unittest.TestCase):
    def test_aggregate_counts_allowlisted_dimensions_and_day_without_identity(self) -> None:
        export = json.dumps(
            [
                {
                    "body": reporting_issue_body(_report("review", "changed")),
                    "createdAt": "2026-08-09T10:11:12Z",
                },
                {
                    "body": reporting_issue_body(_report("review", "current")),
                    "createdAt": "2026-08-10T12:00:00Z",
                },
            ]
        ).encode()

        result = aggregate_issue_export(export)

        assert isinstance(result, Ok), result
        self.assertEqual(result.value.accepted, 2)
        self.assertEqual(result.value.rejected, 0)
        dimensions = {name: dict(values) for name, values in result.value.dimensions}
        self.assertEqual(dimensions["artifact"], {"skill/review": 2})
        self.assertEqual(dimensions["artifact_outcome"], {"changed": 1, "current": 1})
        self.assertEqual(dimensions["day"], {"2026-08-09": 1, "2026-08-10": 1})
        rendered = dashboard_files(result.value)
        self.assertNotIn(b"author", rendered.json)
        self.assertNotIn(b"repository", rendered.json)
        self.assertIn(b"Voluntary, redacted usage reports", rendered.html)

    def test_invalid_records_are_counted_not_executed_and_bounds_fail_closed(self) -> None:
        export = json.dumps(
            [
                {"body": "$(touch /tmp/pwned)", "createdAt": "2026-08-10T12:00:00Z"},
                {"body": reporting_issue_body(_report("good", "changed")), "createdAt": "bad"},
            ]
        ).encode()
        result = aggregate_issue_export(export)
        assert isinstance(result, Ok), result
        self.assertEqual((result.value.accepted, result.value.rejected), (0, 2))
        impossible_date = json.dumps(
            [
                {
                    "body": reporting_issue_body(_report("good", "changed")),
                    "createdAt": "2026-99-99T12:00:00Z",
                }
            ]
        ).encode()
        invalid_date = aggregate_issue_export(impossible_date)
        assert isinstance(invalid_date, Ok), invalid_date
        self.assertEqual((invalid_date.value.accepted, invalid_date.value.rejected), (0, 1))
        self.assertIsInstance(aggregate_issue_export(b"[" + b" " * (11 * 1024 * 1024)), Err)


if __name__ == "__main__":
    unittest.main()
