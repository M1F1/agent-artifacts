"""Immutable evidence values for installation-risk assessment."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum

from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.protocol.hashing import json_digest
from agent_artifacts.protocol.json import JsonObject
from agent_artifacts.protocol.paths import SafeRelativePath

_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_FINDINGS = 256
_MAX_MESSAGE = 1024
_MAX_REMEDIATION = 512
_MAX_DETAIL = 512


def _valid_digest(value: ObjectDigest) -> bool:
    return (
        isinstance(value, ObjectDigest)
        and value.algorithm == "sha256"
        and _HEX_RE.fullmatch(value.value) is not None
    )


def _one_line(value: str, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= maximum
        and "\r" not in value
        and "\n" not in value
    )


class AssessmentStatus(str, Enum):
    NOT_SCANNED = "not-scanned"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    STALE = "stale"


class FindingSeverity(str, Enum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _RANK[self.value]


class InstallationRisk(str, Enum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _RANK[self.value]


_RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass(frozen=True, slots=True)
class AssessmentCoverage:
    completed: int
    expected: int
    skipped: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized = tuple(sorted(set(self.skipped)))
        if (
            not isinstance(self.completed, int)
            or isinstance(self.completed, bool)
            or not isinstance(self.expected, int)
            or isinstance(self.expected, bool)
            or self.completed < 0
            or self.expected < 1
            or self.completed > self.expected
            or len(normalized) > 512
            or any(not _one_line(item, 512) for item in normalized)
        ):
            raise ValueError("assessment coverage is invalid")
        object.__setattr__(self, "skipped", normalized)

    @property
    def complete(self) -> bool:
        return self.completed == self.expected and not self.skipped


@dataclass(frozen=True, slots=True)
class SecurityFinding:
    provider_id: str
    rule_id: str
    severity: FindingSeverity
    message: str
    remediation: str
    fingerprint: ObjectDigest
    path: SafeRelativePath | None = None
    line: int | None = None

    def __post_init__(self) -> None:
        valid_identity = (
            isinstance(self.provider_id, str)
            and isinstance(self.rule_id, str)
            and (self.path is None or isinstance(self.path, SafeRelativePath))
            and (
                self.line is None
                or (
                    isinstance(self.line, int)
                    and not isinstance(self.line, bool)
                    and 1 <= self.line <= 10_000_000
                    and self.path is not None
                )
            )
        )
        expected_fingerprint = (
            _finding_fingerprint(self.provider_id, self.rule_id, self.path, self.line)
            if valid_identity
            else None
        )
        if (
            not valid_identity
            or _ID_RE.fullmatch(self.provider_id) is None
            or _ID_RE.fullmatch(self.rule_id) is None
            or not isinstance(self.severity, FindingSeverity)
            or not _one_line(self.message, _MAX_MESSAGE)
            or not _one_line(self.remediation, _MAX_REMEDIATION)
            or not _valid_digest(self.fingerprint)
            or self.fingerprint != expected_fingerprint
        ):
            raise ValueError("security finding is invalid")

    @property
    def sort_key(self) -> tuple[str, str, str, int, str]:
        return (
            self.provider_id,
            self.rule_id,
            "" if self.path is None else str(self.path),
            -1 if self.line is None else self.line,
            str(self.fingerprint),
        )


def _finding_fingerprint(
    provider_id: str,
    rule_id: str,
    path: SafeRelativePath | None,
    line: int | None,
) -> ObjectDigest:
    return json_digest(
        JsonObject(
            (
                ("line", line),
                ("path", None if path is None else str(path)),
                ("provider_id", provider_id),
                ("rule_id", rule_id),
            )
        )
    )


def make_finding(
    rule_id: str,
    severity: FindingSeverity,
    message: str,
    remediation: str,
    *,
    path: SafeRelativePath | None = None,
    line: int | None = None,
    provider_id: str = "aart-baseline",
) -> SecurityFinding:
    fingerprint = _finding_fingerprint(provider_id, rule_id, path, line)
    return SecurityFinding(
        provider_id,
        rule_id,
        severity,
        message,
        remediation,
        fingerprint,
        path,
        line,
    )


@dataclass(frozen=True, slots=True)
class ProviderAssessment:
    id: str
    version: str
    rules_digest: ObjectDigest
    status: AssessmentStatus
    coverage: AssessmentCoverage
    detail: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, str)
            or _ID_RE.fullmatch(self.id) is None
            or not _one_line(self.version, 64)
            or not _valid_digest(self.rules_digest)
            or not isinstance(self.status, AssessmentStatus)
            or not isinstance(self.coverage, AssessmentCoverage)
            or not _one_line(self.detail, _MAX_DETAIL)
            or (self.status is AssessmentStatus.COMPLETE and not self.coverage.complete)
            or (self.status is AssessmentStatus.NOT_SCANNED and self.coverage.completed != 0)
            or (
                self.status in {AssessmentStatus.PARTIAL, AssessmentStatus.FAILED}
                and self.coverage.complete
            )
        ):
            raise ValueError("provider assessment is invalid")


def risk_from_evidence(
    status: AssessmentStatus,
    maximum: FindingSeverity,
) -> InstallationRisk:
    if maximum.rank >= FindingSeverity.HIGH.rank:
        return InstallationRisk(maximum.value)
    if status is not AssessmentStatus.COMPLETE:
        return InstallationRisk.UNKNOWN
    if maximum is FindingSeverity.UNKNOWN:
        return InstallationRisk.LOW
    return InstallationRisk(maximum.value)


@dataclass(frozen=True, slots=True)
class SecurityAssessment:
    schema_version: int
    object_digest: ObjectDigest
    status: AssessmentStatus
    installation_risk: InstallationRisk
    max_finding_severity: FindingSeverity
    coverage: AssessmentCoverage
    findings: tuple[SecurityFinding, ...]
    providers: tuple[ProviderAssessment, ...]

    def __post_init__(self) -> None:
        findings = tuple(sorted(self.findings, key=lambda item: item.sort_key))
        providers = tuple(sorted(self.providers, key=lambda item: (item.id, item.version)))
        fingerprints = tuple(item.fingerprint for item in findings)
        provider_ids = tuple(item.id for item in providers)
        expected_max = max(
            (item.severity for item in findings),
            key=lambda item: item.rank,
            default=FindingSeverity.UNKNOWN,
        )
        if (
            self.schema_version != 1
            or not _valid_digest(self.object_digest)
            or not isinstance(self.status, AssessmentStatus)
            or not isinstance(self.installation_risk, InstallationRisk)
            or not isinstance(self.max_finding_severity, FindingSeverity)
            or not isinstance(self.coverage, AssessmentCoverage)
            or not providers
            or len(findings) > _MAX_FINDINGS
            or len(set(fingerprints)) != len(fingerprints)
            or len(set(provider_ids)) != len(provider_ids)
            or any(item.provider_id not in provider_ids for item in findings)
            or expected_max is not self.max_finding_severity
            or self.installation_risk
            is not risk_from_evidence(self.status, self.max_finding_severity)
            or (self.status is AssessmentStatus.COMPLETE and not self.coverage.complete)
            or (
                self.status in {AssessmentStatus.PARTIAL, AssessmentStatus.FAILED}
                and self.coverage.complete
            )
            or (
                self.status is AssessmentStatus.COMPLETE
                and any(item.status is not AssessmentStatus.COMPLETE for item in providers)
            )
            or (
                self.status is AssessmentStatus.NOT_SCANNED
                and (
                    self.coverage.completed != 0
                    or findings
                    or any(item.status is not AssessmentStatus.NOT_SCANNED for item in providers)
                )
            )
            or (
                self.status is AssessmentStatus.STALE
                and not any(item.status is AssessmentStatus.STALE for item in providers)
            )
            or (
                self.status is AssessmentStatus.FAILED
                and not any(item.status is AssessmentStatus.FAILED for item in providers)
            )
            or (
                len(providers) == 1
                and (
                    providers[0].status is not self.status or providers[0].coverage != self.coverage
                )
            )
        ):
            raise ValueError("security assessment is invalid")
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "providers", providers)

    @property
    def finding_counts(self) -> tuple[tuple[FindingSeverity, int], ...]:
        return tuple(
            (severity, sum(item.severity is severity for item in self.findings))
            for severity in FindingSeverity
        )


def mark_assessment_stale_value(
    assessment: SecurityAssessment,
) -> SecurityAssessment:
    providers = tuple(replace(item, status=AssessmentStatus.STALE) for item in assessment.providers)
    maximum = assessment.max_finding_severity
    return replace(
        assessment,
        status=AssessmentStatus.STALE,
        installation_risk=risk_from_evidence(AssessmentStatus.STALE, maximum),
        providers=providers,
    )


MAX_FINDINGS = _MAX_FINDINGS
