"""Normalized explainable installation-risk projections shared by CLI and TUI skins."""

from __future__ import annotations

from agent_artifacts.protocol.json import JsonArray, JsonObject

from .aggregation import ArtifactSecurityEvidence, BundleSecuritySummary
from .model import AssessmentCoverage, SecurityAssessment
from .policy import SecurityPolicyDecision


def _coverage_value(value: AssessmentCoverage) -> JsonObject:
    return JsonObject(
        (
            ("completed", value.completed),
            ("expected", value.expected),
            ("skipped", JsonArray(value.skipped)),
        )
    )


def assessment_security_value(assessment: SecurityAssessment) -> JsonObject:
    """Project provider evidence without presenting an assessment as a safety guarantee."""

    providers = JsonArray(
        tuple(
            JsonObject(
                (
                    ("coverage", _coverage_value(provider.coverage)),
                    ("detail", provider.detail),
                    ("id", provider.id),
                    ("rules_digest", str(provider.rules_digest)),
                    ("status", provider.status.value),
                    ("version", provider.version),
                )
            )
            for provider in assessment.providers
        )
    )
    remediation = JsonArray(tuple(sorted({item.remediation for item in assessment.findings})))
    return JsonObject(
        (
            ("assessment_status", assessment.status.value),
            ("coverage", _coverage_value(assessment.coverage)),
            ("installation_risk", assessment.installation_risk.value),
            ("max_finding_severity", assessment.max_finding_severity.value),
            ("object_digest", str(assessment.object_digest)),
            ("providers", providers),
            ("remediation", remediation),
        )
    )


def artifact_security_value(value: ArtifactSecurityEvidence) -> JsonObject:
    """Project one artifact with its coordinate, evidence age, and derived trust."""

    common = assessment_security_value(value.assessment)
    return JsonObject(
        (
            *common.entries,
            ("attestation_trust", value.attestation_trust.value),
            ("coordinate", str(value.coordinate)),
            ("evidence_age_seconds", value.evidence_age_seconds),
        )
    )


def bundle_security_value(value: BundleSecuritySummary) -> JsonObject:
    """Project aggregate evidence while keeping unknown and stale members visible."""

    return JsonObject(
        (
            ("artifact_count", value.artifact_count),
            ("artifacts", JsonArray(tuple(map(str, value.artifacts)))),
            ("coverage", _coverage_value(value.coverage)),
            (
                "finding_counts",
                JsonObject(tuple((key.value, count) for key, count in value.finding_counts)),
            ),
            ("known_risk_count", value.known_risk_count),
            ("max_finding_severity", value.max_finding_severity.value),
            ("mean_known_risk_milli", value.mean_risk_milli),
            ("provider_ids", JsonArray(value.provider_ids)),
            (
                "risk_range",
                JsonObject((("max", value.risk_max.value), ("min", value.risk_min.value))),
            ),
            (
                "status_counts",
                JsonObject(tuple((key.value, count) for key, count in value.status_counts)),
            ),
            ("stale_artifacts", JsonArray(tuple(map(str, value.stale_artifacts)))),
            ("unknown_artifacts", JsonArray(tuple(map(str, value.unknown_artifacts)))),
            ("weakest_attestation_trust", value.weakest_attestation_trust.value),
            ("worst_artifacts", JsonArray(tuple(map(str, value.worst_artifacts)))),
            ("worst_installation_risk", value.worst_installation_risk.value),
        )
    )


def policy_decision_value(value: SecurityPolicyDecision) -> JsonObject:
    return JsonObject(
        (
            ("action", value.action.value),
            ("affected_artifacts", JsonArray(tuple(map(str, value.affected_artifacts)))),
            ("reasons", JsonArray(value.reasons)),
        )
    )


__all__ = [
    "assessment_security_value",
    "artifact_security_value",
    "bundle_security_value",
    "policy_decision_value",
]
