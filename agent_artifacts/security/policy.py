"""Pure installation-risk policy decisions that never rely on bundle mean risk."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from agent_artifacts.domain.identifiers import ArtifactCoordinate

from .aggregation import (
    ArtifactSecurityEvidence,
    BundleSecuritySummary,
    summarize_bundle_security,
)
from .attestations import AttestationTrust
from .model import AssessmentStatus, InstallationRisk

_PROVIDER_RE = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_TRUST_RANK = {
    AttestationTrust.UNVERIFIED: 0,
    AttestationTrust.LOCAL: 1,
    AttestationTrust.REGISTRY_REVIEWED: 2,
    AttestationTrust.COMPANY_REVIEWED: 3,
}


class SecurityPolicyAction(str, Enum):
    ALLOW = "allow"
    WARN = "warn"
    CONFIRM = "confirm"
    BLOCK = "block"

    @property
    def rank(self) -> int:
        return tuple(SecurityPolicyAction).index(self)


@dataclass(frozen=True, slots=True)
class SecurityInstallPolicy:
    unknown_action: SecurityPolicyAction = SecurityPolicyAction.WARN
    stale_action: SecurityPolicyAction = SecurityPolicyAction.WARN
    failed_action: SecurityPolicyAction = SecurityPolicyAction.WARN
    high_action: SecurityPolicyAction = SecurityPolicyAction.CONFIRM
    critical_action: SecurityPolicyAction = SecurityPolicyAction.BLOCK
    minimum_attestation_trust: AttestationTrust | None = None
    insufficient_trust_action: SecurityPolicyAction = SecurityPolicyAction.WARN
    required_provider_ids: tuple[str, ...] = ()
    missing_provider_action: SecurityPolicyAction = SecurityPolicyAction.WARN
    scopes: tuple[str, ...] = ("project", "user")

    def __post_init__(self) -> None:
        action_values = (
            self.unknown_action,
            self.stale_action,
            self.failed_action,
            self.high_action,
            self.critical_action,
            self.insufficient_trust_action,
            self.missing_provider_action,
        )
        providers = tuple(sorted(set(self.required_provider_ids)))
        scopes = tuple(sorted(set(self.scopes)))
        if (
            any(not isinstance(item, SecurityPolicyAction) for item in action_values)
            or (
                self.minimum_attestation_trust is not None
                and not isinstance(self.minimum_attestation_trust, AttestationTrust)
            )
            or not isinstance(self.required_provider_ids, tuple)
            or providers != self.required_provider_ids
            or any(_PROVIDER_RE.fullmatch(item) is None for item in providers)
            or not isinstance(self.scopes, tuple)
            or not scopes
            or scopes != self.scopes
            or any(scope not in {"project", "user"} for scope in scopes)
        ):
            raise ValueError("security installation policy is invalid")


@dataclass(frozen=True, slots=True)
class SecurityPolicyDecision:
    action: SecurityPolicyAction
    reasons: tuple[str, ...]
    affected_artifacts: tuple[ArtifactCoordinate, ...]

    def __post_init__(self) -> None:
        reasons = tuple(sorted(set(self.reasons)))
        affected = tuple(sorted(set(self.affected_artifacts), key=str))
        if (
            not isinstance(self.action, SecurityPolicyAction)
            or not reasons
            or any(not reason or "\n" in reason or "\r" in reason for reason in reasons)
            or affected != self.affected_artifacts
        ):
            raise ValueError("security policy decision is invalid")
        object.__setattr__(self, "reasons", reasons)


def evaluate_security_policy(
    summary: BundleSecuritySummary,
    evidence: tuple[ArtifactSecurityEvidence, ...],
    policy: SecurityInstallPolicy,
    *,
    scope: str,
) -> SecurityPolicyDecision:
    """Evaluate worst/unknown facts; mean risk is intentionally never consulted."""

    if scope not in {"project", "user"}:
        raise ValueError("security policy scope is invalid")
    normalized = summarize_bundle_security(evidence)
    if summary != normalized:
        raise ValueError("security policy summary does not match artifact evidence")
    if scope not in policy.scopes:
        return SecurityPolicyDecision(
            SecurityPolicyAction.ALLOW,
            (f"Security installation policy does not apply to {scope} scope.",),
            (),
        )

    triggered: list[tuple[SecurityPolicyAction, str, tuple[ArtifactCoordinate, ...]]] = []
    if summary.unknown_artifacts:
        triggered.append(
            (
                policy.unknown_action,
                "One or more artifacts have unknown installation risk.",
                summary.unknown_artifacts,
            )
        )
    if summary.stale_artifacts:
        triggered.append(
            (
                policy.stale_action,
                "One or more artifacts have stale assessment evidence.",
                summary.stale_artifacts,
            )
        )
    failed = tuple(
        item.coordinate for item in evidence if item.assessment.status is AssessmentStatus.FAILED
    )
    if failed:
        triggered.append(
            (
                policy.failed_action,
                "One or more artifact assessments failed.",
                failed,
            )
        )
    if summary.risk_max is InstallationRisk.CRITICAL:
        triggered.append(
            (
                policy.critical_action,
                "Worst observed installation risk is critical.",
                summary.worst_artifacts,
            )
        )
    elif summary.risk_max is InstallationRisk.HIGH:
        triggered.append(
            (
                policy.high_action,
                "Worst observed installation risk is high.",
                summary.worst_artifacts,
            )
        )
    if policy.minimum_attestation_trust is not None:
        insufficient = tuple(
            item.coordinate
            for item in evidence
            if _TRUST_RANK[item.attestation_trust] < _TRUST_RANK[policy.minimum_attestation_trust]
        )
        if insufficient:
            triggered.append(
                (
                    policy.insufficient_trust_action,
                    "One or more artifacts have insufficient locally derived attestation trust.",
                    insufficient,
                )
            )
    if policy.required_provider_ids:
        missing = tuple(
            item.coordinate
            for item in evidence
            if not set(policy.required_provider_ids)
            <= {provider.id for provider in item.assessment.providers}
        )
        if missing:
            triggered.append(
                (
                    policy.missing_provider_action,
                    "One or more artifacts are missing a required assessment provider suite.",
                    missing,
                )
            )
    if not triggered:
        return SecurityPolicyDecision(
            SecurityPolicyAction.ALLOW,
            ("Installation-risk evidence satisfies the configured policy.",),
            (),
        )
    action = max((item[0] for item in triggered), key=lambda item: item.rank)
    affected = tuple(
        sorted(
            {coordinate for _action, _reason, items in triggered for coordinate in items}, key=str
        )
    )
    return SecurityPolicyDecision(
        action,
        tuple(reason for _action, reason, _items in triggered),
        affected,
    )


__all__ = [
    "SecurityInstallPolicy",
    "SecurityPolicyAction",
    "SecurityPolicyDecision",
    "evaluate_security_policy",
]
