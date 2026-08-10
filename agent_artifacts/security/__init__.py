"""Zero-dependency installation-risk evidence and baseline rules."""

from .baseline import (
    BASELINE_RULES_DIGEST,
    BaselineScanRequest,
    assess_installation_risk,
    mark_assessment_stale,
    not_scanned_assessment,
)
from .model import (
    AssessmentCoverage,
    AssessmentStatus,
    FindingSeverity,
    InstallationRisk,
    ProviderAssessment,
    SecurityAssessment,
    SecurityFinding,
)
from .schema import assessment_bytes, assessment_value, parse_assessment

__all__ = [
    "BASELINE_RULES_DIGEST",
    "AssessmentCoverage",
    "AssessmentStatus",
    "BaselineScanRequest",
    "FindingSeverity",
    "InstallationRisk",
    "ProviderAssessment",
    "SecurityAssessment",
    "SecurityFinding",
    "assess_installation_risk",
    "assessment_bytes",
    "assessment_value",
    "mark_assessment_stale",
    "not_scanned_assessment",
    "parse_assessment",
]
