"""Pure deterministic aggregation for deduplicated artifact installation-risk evidence."""

from __future__ import annotations

from dataclasses import dataclass

from agent_artifacts.domain.identifiers import ArtifactCoordinate

from .attestations import AttestationTrust
from .model import (
    AssessmentCoverage,
    AssessmentStatus,
    FindingSeverity,
    InstallationRisk,
    SecurityAssessment,
)

_RISK_SCORE = {
    InstallationRisk.LOW: 1,
    InstallationRisk.MEDIUM: 2,
    InstallationRisk.HIGH: 3,
    InstallationRisk.CRITICAL: 4,
}
_TRUST_RANK = {
    AttestationTrust.UNVERIFIED: 0,
    AttestationTrust.LOCAL: 1,
    AttestationTrust.REGISTRY_REVIEWED: 2,
    AttestationTrust.COMPANY_REVIEWED: 3,
}


def _coordinate_key(value: ArtifactCoordinate) -> str:
    return str(value)


@dataclass(frozen=True, slots=True)
class ArtifactSecurityEvidence:
    coordinate: ArtifactCoordinate
    assessment: SecurityAssessment
    attestation_trust: AttestationTrust
    evidence_age_seconds: int | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.coordinate, ArtifactCoordinate)
            or not isinstance(self.assessment, SecurityAssessment)
            or not isinstance(self.attestation_trust, AttestationTrust)
            or (
                self.evidence_age_seconds is not None
                and (
                    not isinstance(self.evidence_age_seconds, int)
                    or isinstance(self.evidence_age_seconds, bool)
                    or not 0 <= self.evidence_age_seconds <= 2**63 - 1
                )
            )
        ):
            raise ValueError("artifact security evidence is invalid")


@dataclass(frozen=True, slots=True)
class BundleSecuritySummary:
    artifacts: tuple[ArtifactCoordinate, ...]
    artifact_count: int
    worst_installation_risk: InstallationRisk
    risk_min: InstallationRisk
    risk_max: InstallationRisk
    mean_risk_milli: int | None
    known_risk_count: int
    max_finding_severity: FindingSeverity
    finding_counts: tuple[tuple[FindingSeverity, int], ...]
    status_counts: tuple[tuple[AssessmentStatus, int], ...]
    coverage: AssessmentCoverage
    worst_artifacts: tuple[ArtifactCoordinate, ...]
    unknown_artifacts: tuple[ArtifactCoordinate, ...]
    stale_artifacts: tuple[ArtifactCoordinate, ...]
    provider_ids: tuple[str, ...]
    weakest_attestation_trust: AttestationTrust

    def __post_init__(self) -> None:
        artifacts = tuple(sorted(set(self.artifacts), key=_coordinate_key))
        worst = tuple(sorted(set(self.worst_artifacts), key=_coordinate_key))
        unknown = tuple(sorted(set(self.unknown_artifacts), key=_coordinate_key))
        stale = tuple(sorted(set(self.stale_artifacts), key=_coordinate_key))
        if (
            not artifacts
            or artifacts != self.artifacts
            or self.artifact_count != len(artifacts)
            or not isinstance(self.worst_installation_risk, InstallationRisk)
            or not isinstance(self.risk_min, InstallationRisk)
            or not isinstance(self.risk_max, InstallationRisk)
            or (
                self.mean_risk_milli is not None
                and (
                    not isinstance(self.mean_risk_milli, int)
                    or isinstance(self.mean_risk_milli, bool)
                    or not 1000 <= self.mean_risk_milli <= 4000
                )
            )
            or not 0 <= self.known_risk_count <= self.artifact_count
            or (self.known_risk_count == 0) != (self.mean_risk_milli is None)
            or not isinstance(self.max_finding_severity, FindingSeverity)
            or not isinstance(self.coverage, AssessmentCoverage)
            or any(item not in artifacts for item in (*worst, *unknown, *stale))
            or not isinstance(self.weakest_attestation_trust, AttestationTrust)
            or tuple(sorted(set(self.provider_ids))) != self.provider_ids
            or tuple(severity for severity, _count in self.finding_counts) != tuple(FindingSeverity)
            or tuple(status for status, _count in self.status_counts) != tuple(AssessmentStatus)
            or any(
                not isinstance(count, int) or isinstance(count, bool) or count < 0
                for _key, count in (*self.finding_counts, *self.status_counts)
            )
        ):
            raise ValueError("bundle security summary is invalid")
        object.__setattr__(self, "worst_artifacts", worst)
        object.__setattr__(self, "unknown_artifacts", unknown)
        object.__setattr__(self, "stale_artifacts", stale)


def _deduplicate(
    evidence: tuple[ArtifactSecurityEvidence, ...],
) -> tuple[ArtifactSecurityEvidence, ...]:
    if not isinstance(evidence, tuple) or any(
        not isinstance(item, ArtifactSecurityEvidence) for item in evidence
    ):
        raise ValueError("bundle security evidence is invalid")
    by_coordinate: dict[ArtifactCoordinate, ArtifactSecurityEvidence] = {}
    for item in evidence:
        existing = by_coordinate.get(item.coordinate)
        if existing is not None and existing != item:
            raise ValueError("one artifact coordinate has conflicting security evidence")
        by_coordinate[item.coordinate] = item
    result = tuple(
        sorted(by_coordinate.values(), key=lambda item: _coordinate_key(item.coordinate))
    )
    if not result:
        raise ValueError("bundle security evidence cannot be empty")
    return result


def summarize_bundle_security(
    evidence: tuple[ArtifactSecurityEvidence, ...],
) -> BundleSecuritySummary:
    """Deduplicate exact coordinates and preserve unknown/stale facts outside the mean."""

    items = _deduplicate(evidence)
    known = tuple(
        (item, _RISK_SCORE[item.assessment.installation_risk])
        for item in items
        if item.assessment.installation_risk in _RISK_SCORE
    )
    if known:
        minimum_score = min(score for _item, score in known)
        maximum_score = max(score for _item, score in known)
        risk_by_score = {score: risk for risk, score in _RISK_SCORE.items()}
        risk_min = risk_by_score[minimum_score]
        risk_max = risk_by_score[maximum_score]
        mean_milli = (sum(score for _item, score in known) * 1000 + len(known) // 2) // len(known)
        worst_artifacts = tuple(item.coordinate for item, score in known if score == maximum_score)
    else:
        risk_min = InstallationRisk.UNKNOWN
        risk_max = InstallationRisk.UNKNOWN
        mean_milli = None
        worst_artifacts = tuple(item.coordinate for item in items)
    unknown = tuple(
        item.coordinate
        for item in items
        if item.assessment.installation_risk is InstallationRisk.UNKNOWN
    )
    stale = tuple(
        item.coordinate for item in items if item.assessment.status is AssessmentStatus.STALE
    )
    maximum_severity = max(
        (item.assessment.max_finding_severity for item in items),
        key=lambda severity: severity.rank,
        default=FindingSeverity.UNKNOWN,
    )
    finding_counts = tuple(
        (
            severity,
            sum(
                finding.severity is severity
                for item in items
                for finding in item.assessment.findings
            ),
        )
        for severity in FindingSeverity
    )
    status_counts = tuple(
        (status, sum(item.assessment.status is status for item in items))
        for status in AssessmentStatus
    )
    skipped = tuple(
        f"{item.coordinate}:{reason}"
        for item in items
        for reason in item.assessment.coverage.skipped
    )
    coverage = AssessmentCoverage(
        sum(item.assessment.coverage.completed for item in items),
        sum(item.assessment.coverage.expected for item in items),
        skipped,
    )
    provider_ids = tuple(
        sorted({provider.id for item in items for provider in item.assessment.providers})
    )
    weakest_trust = min(
        (item.attestation_trust for item in items),
        key=lambda trust: _TRUST_RANK[trust],
    )
    return BundleSecuritySummary(
        tuple(item.coordinate for item in items),
        len(items),
        risk_max,
        risk_min,
        risk_max,
        mean_milli,
        len(known),
        maximum_severity,
        finding_counts,
        status_counts,
        coverage,
        worst_artifacts,
        unknown,
        stale,
        provider_ids,
        weakest_trust,
    )


__all__ = [
    "ArtifactSecurityEvidence",
    "BundleSecuritySummary",
    "summarize_bundle_security",
]
