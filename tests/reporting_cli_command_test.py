from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from agent_artifacts import cli
from agent_artifacts.commands import reporting
from agent_artifacts.model import Request
from agent_artifacts.reporting.model import UsageReport, UsageResult, reporting_issue_body


def _report() -> UsageReport:
    return UsageReport(
        "1.0.0a1",
        "cli",
        "linux",
        "status",
        (
            UsageResult(
                "skill",
                "review",
                "codex",
                "project",
                "copy",
                ("copy",),
                "current",
                "not-required",
            ),
        ),
    )


class ReportingCliCommandTest(unittest.TestCase):
    def test_parser_maps_reporting_commands_to_request_fields(self) -> None:
        request = cli._to_request(
            cli.build_parser().parse_args(
                ["reporting", "aggregate", "issues.json", "--output", "site"]
            )
        )
        self.assertEqual(request.reporting_action, "aggregate")
        self.assertEqual(request.reporting_input, "issues.json")
        self.assertEqual(request.reporting_output, "site")
        self.assertIn("reporting", cli.DISPATCH)

    def test_validate_issue_and_aggregate_write_only_fixed_dashboard_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            issue = root / "issue.md"
            issue.write_text(reporting_issue_body(_report()), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    reporting.run(
                        Request(
                            "reporting",
                            reporting_action="validate-issue",
                            reporting_input=str(issue),
                        )
                    ),
                    0,
                )
            export = root / "issues.json"
            export.write_text(
                json.dumps(
                    [
                        {
                            "body": reporting_issue_body(_report()),
                            "createdAt": "2026-08-10T12:00:00Z",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            output = root / "site"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    reporting.run(
                        Request(
                            "reporting",
                            reporting_action="aggregate",
                            reporting_input=str(export),
                            reporting_output=str(output),
                        )
                    ),
                    0,
                )
            self.assertEqual({path.name for path in output.iterdir()}, {"index.html", "usage.json"})

    def test_invalid_issue_returns_error_without_echoing_untrusted_content(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "bad.md"
            path.write_text("TOKEN=secret /Users/alice", encoding="utf-8")
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                code = reporting.run(
                    Request(
                        "reporting",
                        reporting_action="validate-issue",
                        reporting_input=str(path),
                    )
                )
            self.assertEqual(code, 1)
            self.assertNotIn("secret", error.getvalue())
            self.assertNotIn("/Users", error.getvalue())


if __name__ == "__main__":
    unittest.main()
