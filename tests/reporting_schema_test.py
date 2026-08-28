from __future__ import annotations

import json
import unittest

from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.reporting.model import UsageReport, UsageResult, usage_report_bytes
from agent_artifacts.reporting.schema import parse_issue_body, parse_usage_report
from tests.credential_fixtures import assignment


def _event() -> UsageReport:
    return UsageReport(
        "1.0.0a1",
        "tui",
        "linux",
        "update",
        (
            UsageResult(
                "skill",
                "review",
                "codex",
                "project",
                "symlink",
                ("symlink",),
                "current",
                "not-required",
            ),
        ),
    )


class ReportingSchemaTest(unittest.TestCase):
    def test_round_trip_is_exact_and_issue_body_extracts_one_fenced_event(self) -> None:
        data = usage_report_bytes(_event())
        parsed = parse_usage_report(data)
        assert isinstance(parsed, Ok), parsed
        self.assertEqual(usage_report_bytes(parsed.value), data)

        body = f"### Usage report\n\n```json\n{data.decode().strip()}\n```\n"
        extracted = parse_issue_body(body)
        assert isinstance(extracted, Ok), extracted
        self.assertEqual(extracted.value, parsed.value)

    def test_unknown_sensitive_or_inconsistent_input_fails_closed(self) -> None:
        original = json.loads(usage_report_bytes(_event()))
        variants = []
        unknown = dict(original)
        unknown["repository"] = "private/project"
        variants.append(unknown)
        secret = json.loads(json.dumps(original))
        secret["results"][0]["stdout"] = assignment("TOKEN", "secret")
        variants.append(secret)
        inconsistent = json.loads(json.dumps(original))
        inconsistent["summary"]["selected"] = 99
        variants.append(inconsistent)
        wrong_type = dict(original)
        wrong_type["report_type"] = "anything-else"
        variants.append(wrong_type)
        for value in variants:
            with self.subTest(value=value):
                self.assertIsInstance(parse_usage_report(json.dumps(value).encode()), Err)

        self.assertIsInstance(parse_issue_body("```json\n{}\n```\n```json\n{}\n```"), Err)
        self.assertIsInstance(parse_issue_body("x" * 70_000), Err)


if __name__ == "__main__":
    unittest.main()
