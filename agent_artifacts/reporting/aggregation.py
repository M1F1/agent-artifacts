"""Bounded aggregation of untrusted GitHub issue exports into a static dashboard."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.json import (
    JsonArray,
    JsonObject,
    JsonValue,
    canonical_json_bytes,
    parse_json,
)

from .schema import parse_issue_body

REPORTING_AGGREGATE_INVALID = DiagnosticCode("reporting-aggregate-invalid")
_MAX_EXPORT_BYTES = 10 * 1024 * 1024
_MAX_ISSUES = 10_000
_CREATED_RE = re.compile(r"^(?P<day>[0-9]{4}-[0-9]{2}-[0-9]{2})T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")


@dataclass(frozen=True, slots=True)
class UsageAggregate:
    accepted: int
    rejected: int
    dimensions: tuple[tuple[str, tuple[tuple[str, int], ...]], ...]

    def __post_init__(self) -> None:
        if (
            self.accepted < 0
            or self.rejected < 0
            or tuple(sorted(self.dimensions)) != self.dimensions
        ):
            raise ValueError("usage aggregate is invalid")


@dataclass(frozen=True, slots=True)
class DashboardFiles:
    json: bytes
    html: bytes


def _error(message: str) -> Err:
    return Err((Diagnostic(REPORTING_AGGREGATE_INVALID, Severity.ERROR, message),))


def _record(value: JsonValue) -> tuple[str, str] | None:
    if not isinstance(value, JsonObject):
        return None
    fields = dict(value.entries)
    if set(fields) != {"body", "createdAt"}:
        return None
    body = fields["body"]
    created = fields["createdAt"]
    if not isinstance(body, str) or not isinstance(created, str):
        return None
    matched = _CREATED_RE.fullmatch(created)
    if matched is None:
        return None
    try:
        datetime.fromisoformat(created.removesuffix("Z") + "+00:00")
    except ValueError:
        return None
    return (body, matched.group("day"))


def _increment(counts: dict[str, dict[str, int]], dimension: str, value: str) -> None:
    values = counts.setdefault(dimension, {})
    values[value] = values.get(value, 0) + 1


def aggregate_issue_export(data: bytes | str) -> Result[UsageAggregate]:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if len(raw) > _MAX_EXPORT_BYTES:
        return _error("usage-report issue export exceeds the maximum size")
    parsed = parse_json(raw, max_depth=12, max_string_length=70_000)
    if isinstance(parsed, Err):
        return parsed
    if not isinstance(parsed.value, JsonArray) or len(parsed.value.items) > _MAX_ISSUES:
        return _error("usage-report issue export must be a bounded array")
    counts: dict[str, dict[str, int]] = {}
    accepted = 0
    rejected = 0
    for raw_record in parsed.value.items:
        record = _record(raw_record)
        if record is None:
            rejected += 1
            continue
        report = parse_issue_body(record[0])
        if isinstance(report, Err):
            rejected += 1
            continue
        accepted += 1
        event = report.value
        _increment(counts, "day", record[1])
        _increment(counts, "aart_version", event.aart_version)
        _increment(counts, "action", event.action)
        _increment(counts, "interface", event.interface)
        _increment(counts, "platform", event.platform)
        _increment(counts, "session_outcome", event.session_outcome)
        for item in event.results:
            _increment(counts, "artifact", f"{item.artifact_type}/{item.artifact_name}")
            _increment(counts, "artifact_type", item.artifact_type)
            _increment(counts, "artifact_outcome", item.artifact_outcome)
            _increment(counts, "setup_outcome", item.setup_outcome)
            _increment(counts, "profile", item.profile)
            _increment(counts, "scope", item.scope)
            _increment(counts, "requested_mode", item.requested_mode)
            for mode in item.actual_modes:
                _increment(counts, "actual_mode", mode)
    dimensions = tuple(
        (dimension, tuple(sorted(values.items()))) for dimension, values in sorted(counts.items())
    )
    return Ok(UsageAggregate(accepted, rejected, dimensions))


def _aggregate_json(aggregate: UsageAggregate) -> JsonObject:
    return JsonObject(
        (
            ("accepted_reports", aggregate.accepted),
            (
                "dimensions",
                JsonObject(
                    tuple(
                        (name, JsonObject(tuple(values))) for name, values in aggregate.dimensions
                    )
                ),
            ),
            ("rejected_reports", aggregate.rejected),
            ("schema_version", 1),
        )
    )


def dashboard_files(aggregate: UsageAggregate) -> DashboardFiles:
    json_bytes = canonical_json_bytes(_aggregate_json(aggregate))
    sections = []
    for name, values in aggregate.dimensions:
        rows = "".join(
            f"<tr><td>{html.escape(value)}</td><td>{count}</td></tr>" for value, count in values
        )
        sections.append(
            f"<section><h2>{html.escape(name.replace('_', ' ').title())}</h2>"
            f"<table><thead><tr><th>Value</th><th>Count</th></tr></thead><tbody>{rows}"
            "</tbody></table></section>"
        )
    document = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>AART usage dashboard</title><style>body{font-family:system-ui;max-width:70rem;"
        "margin:auto;padding:2rem}table{border-collapse:collapse}th,td{border:1px solid #bbb;"
        "padding:.35rem .6rem;text-align:left}section{margin-block:2rem}</style>"
        "<h1>AART usage dashboard</h1>"
        "<p>Voluntary, redacted usage reports. Counts describe submitted sessions and are not a "
        "complete measure of all AART use.</p>"
        f"<p>Accepted reports: {aggregate.accepted}; rejected records: {aggregate.rejected}.</p>"
        + "".join(sections)
        + "</html>"
    ).encode("utf-8")
    return DashboardFiles(json_bytes, document)


__all__ = [
    "DashboardFiles",
    "UsageAggregate",
    "aggregate_issue_export",
    "dashboard_files",
]
