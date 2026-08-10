"""Strict parsing for untrusted usage-report JSON and GitHub issue bodies."""

from __future__ import annotations

import re

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.json import JsonArray, JsonObject, JsonValue, parse_json

from .model import MAX_USAGE_REPORT_BYTES, ReportingFailure, UsageReport, UsageResult

REPORT_INVALID = DiagnosticCode("report-invalid")
_MAX_ISSUE_BODY = 64 * 1024
_FENCE_RE = re.compile(r"```json[ \t]*\n(?P<payload>.*?)\n```", re.DOTALL)


def _error(message: str) -> Err:
    return Err((Diagnostic(REPORT_INVALID, Severity.ERROR, message),))


def _fields(
    value: JsonValue,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> Result[dict[str, JsonValue]]:
    if not isinstance(value, JsonObject):
        return _error("report value must be an object")
    fields = dict(value.entries)
    names = set(fields)
    if not required <= names or not names <= required | optional:
        return _error("report object has missing or unknown fields")
    return Ok(fields)


def _string(fields: dict[str, JsonValue], name: str) -> Result[str]:
    value = fields.get(name)
    return Ok(value) if isinstance(value, str) else _error(f"report field {name} must be a string")


def _strings(fields: dict[str, JsonValue], names: tuple[str, ...]) -> Result[dict[str, str]]:
    converted: dict[str, str] = {}
    for name in names:
        result = _string(fields, name)
        if isinstance(result, Err):
            return result
        converted[name] = result.value
    return Ok(converted)


def _failure(value: JsonValue) -> Result[ReportingFailure]:
    parsed = _fields(
        value,
        frozenset({"phase", "category", "code", "interrupted", "retryable"}),
        frozenset({"exit_code", "fingerprint"}),
    )
    if isinstance(parsed, Err):
        return parsed
    fields = parsed.value
    strings = _strings(fields, ("phase", "category", "code"))
    if isinstance(strings, Err):
        return strings
    interrupted = fields["interrupted"]
    retryable = fields["retryable"]
    exit_code = fields.get("exit_code")
    fingerprint = fields.get("fingerprint")
    if (
        not isinstance(interrupted, bool)
        or not isinstance(retryable, bool)
        or (
            exit_code is not None
            and (not isinstance(exit_code, int) or isinstance(exit_code, bool))
        )
        or (fingerprint is not None and not isinstance(fingerprint, str))
    ):
        return _error("report failure fields have invalid types")
    try:
        return Ok(
            ReportingFailure(
                strings.value["phase"],
                strings.value["category"],
                strings.value["code"],
                exit_code,
                interrupted,
                retryable,
                fingerprint,
            )
        )
    except ValueError as error:
        return _error(str(error))


def _result(value: JsonValue) -> Result[UsageResult]:
    parsed = _fields(
        value,
        frozenset(
            {
                "actual_modes",
                "artifact_name",
                "artifact_outcome",
                "artifact_type",
                "profile",
                "requested_mode",
                "scope",
                "setup_outcome",
            }
        ),
        frozenset({"installer_digest", "failure"}),
    )
    if isinstance(parsed, Err):
        return parsed
    fields = parsed.value
    strings = _strings(
        fields,
        (
            "artifact_name",
            "artifact_outcome",
            "artifact_type",
            "profile",
            "requested_mode",
            "scope",
            "setup_outcome",
        ),
    )
    if isinstance(strings, Err):
        return strings
    modes = fields["actual_modes"]
    if not isinstance(modes, JsonArray) or any(not isinstance(item, str) for item in modes.items):
        return _error("report actual_modes must be an array of strings")
    raw_digest = fields.get("installer_digest")
    digest = None
    if raw_digest is not None:
        if not isinstance(raw_digest, str) or not raw_digest.startswith("sha256:"):
            return _error("report installer_digest must be a sha256 digest")
        digest = ObjectDigest("sha256", raw_digest.removeprefix("sha256:"))
    raw_failure = fields.get("failure")
    failure = None if raw_failure is None else _failure(raw_failure)
    if isinstance(failure, Err):
        return failure
    try:
        return Ok(
            UsageResult(
                strings.value["artifact_type"],
                strings.value["artifact_name"],
                strings.value["profile"],
                strings.value["scope"],
                strings.value["requested_mode"],
                tuple(item for item in modes.items if isinstance(item, str)),
                strings.value["artifact_outcome"],
                strings.value["setup_outcome"],
                digest,
                None if failure is None else failure.value,
            )
        )
    except ValueError as error:
        return _error(str(error))


def parse_usage_report(data: bytes | str) -> Result[UsageReport]:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if len(raw) > MAX_USAGE_REPORT_BYTES:
        return _error("usage report exceeds the maximum size")
    parsed = parse_json(raw, max_depth=8, max_string_length=512)
    if isinstance(parsed, Err):
        return parsed
    root = _fields(
        parsed.value,
        frozenset(
            {
                "aart_version",
                "action",
                "interface",
                "platform",
                "report_type",
                "results",
                "schema_version",
                "session_outcome",
                "summary",
            }
        ),
    )
    if isinstance(root, Err):
        return root
    fields = root.value
    if fields["schema_version"] != 1 or fields["report_type"] != "aart-usage-session":
        return _error("unsupported usage report schema or report type")
    strings = _strings(
        fields,
        ("aart_version", "action", "interface", "platform", "session_outcome"),
    )
    if isinstance(strings, Err):
        return strings
    raw_results = fields["results"]
    if not isinstance(raw_results, JsonArray):
        return _error("report results must be an array")
    results = []
    for item in raw_results.items:
        converted = _result(item)
        if isinstance(converted, Err):
            return converted
        results.append(converted.value)
    try:
        report = UsageReport(
            strings.value["aart_version"],
            strings.value["interface"],
            strings.value["platform"],
            strings.value["action"],
            tuple(results),
        )
    except ValueError as error:
        return _error(str(error))
    summary = fields["summary"]
    if not isinstance(summary, JsonObject):
        return _error("report summary must be an object")
    raw_summary = dict(summary.entries)
    if any(not isinstance(value, int) or isinstance(value, bool) for value in raw_summary.values()):
        return _error("report summary counts must be integers")
    if strings.value["session_outcome"] != report.session_outcome or raw_summary != dict(
        report.summary
    ):
        return _error("report summary or session outcome is inconsistent")
    return Ok(report)


def parse_issue_body(body: str) -> Result[UsageReport]:
    if not isinstance(body, str) or len(body.encode("utf-8")) > _MAX_ISSUE_BODY:
        return _error("usage-report issue body exceeds the maximum size")
    matches = tuple(_FENCE_RE.finditer(body))
    if len(matches) != 1:
        return _error("usage-report issue must contain exactly one fenced JSON payload")
    return parse_usage_report(matches[0].group("payload"))
