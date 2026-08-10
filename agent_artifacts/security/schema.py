"""Canonical JSON projection for normalized installation-risk evidence."""

from __future__ import annotations

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.hashing import parse_sha256
from agent_artifacts.protocol.json import (
    JsonArray,
    JsonObject,
    JsonValue,
    canonical_json_bytes,
    parse_json,
)
from agent_artifacts.protocol.paths import parse_relative_path

from .model import (
    MAX_FINDINGS,
    AssessmentCoverage,
    AssessmentStatus,
    FindingSeverity,
    InstallationRisk,
    ProviderAssessment,
    SecurityAssessment,
    SecurityFinding,
)

ASSESSMENT_INVALID = DiagnosticCode("security-assessment-invalid")
_MAX_ASSESSMENT_BYTES = 2 * 1024 * 1024
_MAX_PROVIDERS = 64
_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "object_digest",
        "status",
        "installation_risk",
        "max_finding_severity",
        "coverage",
        "findings",
        "finding_counts",
        "providers",
    }
)


def _error(message: str) -> Err:
    return Err((Diagnostic(ASSESSMENT_INVALID, Severity.ERROR, message),))


def _coverage_value(value: AssessmentCoverage) -> JsonObject:
    return JsonObject(
        (
            ("completed", value.completed),
            ("expected", value.expected),
            ("skipped", JsonArray(value.skipped)),
        )
    )


def _finding_value(value: SecurityFinding) -> JsonObject:
    return JsonObject(
        (
            ("fingerprint", str(value.fingerprint)),
            ("line", value.line),
            ("message", value.message),
            ("path", None if value.path is None else str(value.path)),
            ("provider_id", value.provider_id),
            ("remediation", value.remediation),
            ("rule_id", value.rule_id),
            ("severity", value.severity.value),
        )
    )


def _provider_value(value: ProviderAssessment) -> JsonObject:
    return JsonObject(
        (
            ("coverage", _coverage_value(value.coverage)),
            ("detail", value.detail),
            ("id", value.id),
            ("rules_digest", str(value.rules_digest)),
            ("status", value.status.value),
            ("version", value.version),
        )
    )


def assessment_value(value: SecurityAssessment) -> JsonObject:
    return JsonObject(
        (
            ("coverage", _coverage_value(value.coverage)),
            (
                "finding_counts",
                JsonObject(
                    tuple((severity.value, count) for severity, count in value.finding_counts)
                ),
            ),
            ("findings", JsonArray(tuple(_finding_value(item) for item in value.findings))),
            ("installation_risk", value.installation_risk.value),
            ("max_finding_severity", value.max_finding_severity.value),
            ("object_digest", str(value.object_digest)),
            ("providers", JsonArray(tuple(_provider_value(item) for item in value.providers))),
            ("schema_version", value.schema_version),
            ("status", value.status.value),
        )
    )


def assessment_bytes(value: SecurityAssessment) -> bytes:
    return canonical_json_bytes(assessment_value(value))


def _fields(value: JsonValue, expected: frozenset[str], label: str) -> Result[dict[str, JsonValue]]:
    if not isinstance(value, JsonObject):
        return _error(f"{label} must be an object")
    fields = dict(value.entries)
    if frozenset(fields) != expected:
        return _error(f"{label} fields are invalid")
    return Ok(fields)


def _coverage(value: JsonValue) -> Result[AssessmentCoverage]:
    fields = _fields(value, frozenset({"completed", "expected", "skipped"}), "coverage")
    if isinstance(fields, Err):
        return fields
    completed = fields.value["completed"]
    expected = fields.value["expected"]
    skipped = fields.value["skipped"]
    if (
        not isinstance(completed, int)
        or isinstance(completed, bool)
        or not isinstance(expected, int)
        or isinstance(expected, bool)
        or not isinstance(skipped, JsonArray)
        or len(skipped.items) > 512
        or any(not isinstance(item, str) for item in skipped.items)
    ):
        return _error("coverage field types are invalid")
    try:
        return Ok(AssessmentCoverage(completed, expected, tuple(skipped.items)))  # type: ignore[arg-type]
    except ValueError:
        return _error("coverage values are invalid")


def _finding(value: JsonValue) -> Result[SecurityFinding]:
    expected = frozenset(
        {
            "fingerprint",
            "line",
            "message",
            "path",
            "provider_id",
            "remediation",
            "rule_id",
            "severity",
        }
    )
    fields = _fields(value, expected, "finding")
    if isinstance(fields, Err):
        return fields
    raw = fields.value
    strings = ("fingerprint", "message", "provider_id", "remediation", "rule_id", "severity")
    if any(not isinstance(raw[name], str) for name in strings):
        return _error("finding string field types are invalid")
    path = None
    if raw["path"] is not None:
        if not isinstance(raw["path"], str):
            return _error("finding path is invalid")
        parsed_path = parse_relative_path(raw["path"])
        if isinstance(parsed_path, Err):
            return _error("finding path is unsafe")
        path = parsed_path.value
    line = raw["line"]
    if line is not None and (not isinstance(line, int) or isinstance(line, bool)):
        return _error("finding line is invalid")
    digest = parse_sha256(raw["fingerprint"])  # type: ignore[arg-type]
    if isinstance(digest, Err):
        return _error("finding fingerprint is invalid")
    try:
        return Ok(
            SecurityFinding(
                raw["provider_id"],  # type: ignore[arg-type]
                raw["rule_id"],  # type: ignore[arg-type]
                FindingSeverity(raw["severity"]),
                raw["message"],  # type: ignore[arg-type]
                raw["remediation"],  # type: ignore[arg-type]
                digest.value,
                path,
                line,
            )
        )
    except ValueError:
        return _error("finding values are invalid")


def _provider(value: JsonValue) -> Result[ProviderAssessment]:
    expected = frozenset({"coverage", "detail", "id", "rules_digest", "status", "version"})
    fields = _fields(value, expected, "provider")
    if isinstance(fields, Err):
        return fields
    raw = fields.value
    if any(
        not isinstance(raw[name], str)
        for name in ("detail", "id", "rules_digest", "status", "version")
    ):
        return _error("provider field types are invalid")
    coverage = _coverage(raw["coverage"])
    digest = parse_sha256(raw["rules_digest"])  # type: ignore[arg-type]
    if isinstance(coverage, Err) or isinstance(digest, Err):
        return _error("provider evidence is invalid")
    try:
        return Ok(
            ProviderAssessment(
                raw["id"],  # type: ignore[arg-type]
                raw["version"],  # type: ignore[arg-type]
                digest.value,
                AssessmentStatus(raw["status"]),
                coverage.value,
                raw["detail"],  # type: ignore[arg-type]
            )
        )
    except ValueError:
        return _error("provider values are invalid")


def parse_assessment(data: bytes | str) -> Result[SecurityAssessment]:
    if not isinstance(data, (bytes, str)):
        return _error("assessment must be UTF-8 bytes or text")
    try:
        encoded = data.encode("utf-8") if isinstance(data, str) else data
    except UnicodeEncodeError:
        return _error("assessment is not valid UTF-8")
    if len(encoded) > _MAX_ASSESSMENT_BYTES:
        return _error("assessment exceeds the maximum encoded size")
    parsed = parse_json(encoded)
    if isinstance(parsed, Err):
        return _error("assessment is not strict JSON")
    root = _fields(parsed.value, _ROOT_FIELDS, "assessment")
    if isinstance(root, Err):
        return root
    raw = root.value
    string_fields = ("object_digest", "status", "installation_risk", "max_finding_severity")
    if (
        raw["schema_version"] != 1
        or isinstance(raw["schema_version"], bool)
        or any(not isinstance(raw[name], str) for name in string_fields)
        or not isinstance(raw["findings"], JsonArray)
        or not isinstance(raw["providers"], JsonArray)
        or len(raw["findings"].items) > MAX_FINDINGS
        or len(raw["providers"].items) > _MAX_PROVIDERS
    ):
        return _error("assessment field types are invalid")
    coverage = _coverage(raw["coverage"])
    object_digest = parse_sha256(raw["object_digest"])  # type: ignore[arg-type]
    if isinstance(coverage, Err) or isinstance(object_digest, Err):
        return _error("assessment evidence is invalid")
    findings: list[SecurityFinding] = []
    for value in raw["findings"].items:
        finding = _finding(value)
        if isinstance(finding, Err):
            return finding
        findings.append(finding.value)
    providers: list[ProviderAssessment] = []
    for value in raw["providers"].items:
        provider = _provider(value)
        if isinstance(provider, Err):
            return provider
        providers.append(provider.value)
    counts = _fields(
        raw["finding_counts"],
        frozenset(item.value for item in FindingSeverity),
        "finding_counts",
    )
    if isinstance(counts, Err) or any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in counts.value.values()
    ):
        return _error("finding counts are invalid")
    try:
        assessment = SecurityAssessment(
            1,
            object_digest.value,
            AssessmentStatus(raw["status"]),
            InstallationRisk(raw["installation_risk"]),
            FindingSeverity(raw["max_finding_severity"]),
            coverage.value,
            tuple(findings),
            tuple(providers),
        )
    except ValueError:
        return _error("assessment values are invalid")
    expected_counts = {severity.value: count for severity, count in assessment.finding_counts}
    if counts.value != expected_counts or assessment_bytes(assessment) != encoded:
        return _error("assessment is not canonical or finding counts do not match")
    return Ok(assessment)
