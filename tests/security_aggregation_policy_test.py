from __future__ import annotations

import unittest

from agent_artifacts.domain.identifiers import ArtifactCoordinate, ArtifactIdentity, SourceAlias
from agent_artifacts.protocol.hashing import sha256_bytes
from agent_artifacts.security.aggregation import (
    ArtifactSecurityEvidence,
    summarize_bundle_security,
)
from agent_artifacts.security.attestations import AttestationTrust
from agent_artifacts.security.model import (
    AssessmentCoverage,
    AssessmentStatus,
    FindingSeverity,
    ProviderAssessment,
    SecurityAssessment,
    make_finding,
    risk_from_evidence,
)
from agent_artifacts.security.policy import (
    SecurityInstallPolicy,
    SecurityPolicyAction,
    evaluate_security_policy,
)


def _coordinate(name: str) -> ArtifactCoordinate:
    return ArtifactCoordinate(
        SourceAlias("company"),
        ArtifactIdentity("skill", name),
        "1.0.0",
    )


def _assessment(
    name: str,
    status: AssessmentStatus,
    severity: FindingSeverity = FindingSeverity.UNKNOWN,
    *,
    provider_id: str = "aart-baseline",
) -> SecurityAssessment:
    complete = status in {AssessmentStatus.COMPLETE, AssessmentStatus.STALE}
    coverage = AssessmentCoverage(
        1 if complete else 0,
        1,
        () if complete else (f"{provider_id}:incomplete",),
    )
    provider = ProviderAssessment(
        provider_id,
        "1",
        sha256_bytes(f"rules:{provider_id}".encode()),
        status,
        coverage,
        "Provider evidence has the declared terminal status.",
    )
    findings = (
        ()
        if severity is FindingSeverity.UNKNOWN
        else (
            make_finding(
                f"rule-{name}",
                severity,
                f"Provider observed normalized rule for {name}.",
                "Review the exact immutable artifact before installation.",
                provider_id=provider_id,
            ),
        )
    )
    return SecurityAssessment(
        1,
        sha256_bytes(f"object:{name}".encode()),
        status,
        risk_from_evidence(status, severity),
        severity,
        coverage,
        findings,
        (provider,),
    )


def _evidence(
    name: str,
    status: AssessmentStatus,
    severity: FindingSeverity = FindingSeverity.UNKNOWN,
    *,
    trust: AttestationTrust = AttestationTrust.LOCAL,
    provider_id: str = "aart-baseline",
) -> ArtifactSecurityEvidence:
    return ArtifactSecurityEvidence(
        _coordinate(name),
        _assessment(name, status, severity, provider_id=provider_id),
        trust,
    )


class SecurityAggregationPolicyTest(unittest.TestCase):
    def test_summary_deduplicates_and_exposes_worst_range_mean_counts_and_coverage(self) -> None:
        low = _evidence("low", AssessmentStatus.COMPLETE)
        critical = _evidence(
            "critical",
            AssessmentStatus.COMPLETE,
            FindingSeverity.CRITICAL,
            trust=AttestationTrust.COMPANY_REVIEWED,
        )

        summary = summarize_bundle_security((critical, low, low))

        self.assertEqual(summary.artifact_count, 2)
        self.assertEqual(summary.artifacts, (_coordinate("critical"), _coordinate("low")))
        self.assertEqual(summary.worst_installation_risk.value, "critical")
        self.assertEqual(summary.risk_min.value, "low")
        self.assertEqual(summary.risk_max.value, "critical")
        self.assertEqual(summary.mean_risk_milli, 2500)
        self.assertEqual(summary.known_risk_count, 2)
        self.assertEqual(summary.max_finding_severity, FindingSeverity.CRITICAL)
        self.assertEqual(summary.worst_artifacts, (_coordinate("critical"),))
        self.assertEqual(dict(summary.finding_counts)[FindingSeverity.CRITICAL], 1)
        self.assertEqual(dict(summary.status_counts)[AssessmentStatus.COMPLETE], 2)
        self.assertEqual(summary.coverage, AssessmentCoverage(2, 2))
        self.assertIs(summary.weakest_attestation_trust, AttestationTrust.LOCAL)

    def test_unknown_and_stale_members_remain_explicit_and_do_not_enter_the_mean(self) -> None:
        low = _evidence("low", AssessmentStatus.COMPLETE)
        unknown = _evidence("unknown", AssessmentStatus.PARTIAL)
        stale = _evidence("stale", AssessmentStatus.STALE)

        summary = summarize_bundle_security((low, unknown, stale))

        self.assertEqual(summary.worst_installation_risk.value, "low")
        self.assertEqual(summary.mean_risk_milli, 1000)
        self.assertEqual(summary.known_risk_count, 1)
        self.assertEqual(summary.unknown_artifacts, (_coordinate("stale"), _coordinate("unknown")))
        self.assertEqual(summary.stale_artifacts, (_coordinate("stale"),))
        self.assertEqual(dict(summary.status_counts)[AssessmentStatus.PARTIAL], 1)
        self.assertEqual(dict(summary.status_counts)[AssessmentStatus.STALE], 1)
        self.assertFalse(summary.coverage.complete)

    def test_same_coordinate_with_different_evidence_is_rejected(self) -> None:
        first = _evidence("same", AssessmentStatus.COMPLETE)
        changed = _evidence("same", AssessmentStatus.PARTIAL)
        with self.assertRaises(ValueError):
            summarize_bundle_security((first, changed))
        with self.assertRaises(ValueError):
            summarize_bundle_security(())

    def test_policy_uses_unknown_and_worst_risk_never_the_favorable_mean(self) -> None:
        evidence = (
            _evidence("low", AssessmentStatus.COMPLETE),
            _evidence("unknown", AssessmentStatus.PARTIAL),
        )
        summary = summarize_bundle_security(evidence)
        policy = SecurityInstallPolicy(
            unknown_action=SecurityPolicyAction.BLOCK,
            high_action=SecurityPolicyAction.WARN,
            critical_action=SecurityPolicyAction.WARN,
        )

        decision = evaluate_security_policy(summary, evidence, policy, scope="project")

        self.assertIs(decision.action, SecurityPolicyAction.BLOCK)
        self.assertIn(_coordinate("unknown"), decision.affected_artifacts)
        self.assertTrue(any("unknown" in reason.casefold() for reason in decision.reasons))
        self.assertNotIn("mean", " ".join(decision.reasons).casefold())

        critical_evidence = (
            _evidence("low", AssessmentStatus.COMPLETE),
            _evidence("critical", AssessmentStatus.COMPLETE, FindingSeverity.CRITICAL),
        )
        critical_summary = summarize_bundle_security(critical_evidence)
        critical_decision = evaluate_security_policy(
            critical_summary,
            critical_evidence,
            SecurityInstallPolicy(
                critical_action=SecurityPolicyAction.BLOCK,
                high_action=SecurityPolicyAction.ALLOW,
            ),
            scope="project",
        )
        self.assertEqual(critical_summary.mean_risk_milli, 2500)
        self.assertIs(critical_decision.action, SecurityPolicyAction.BLOCK)

    def test_policy_can_require_provider_suite_trust_and_scope_without_forcing_defaults(
        self,
    ) -> None:
        evidence = (
            _evidence(
                "direct",
                AssessmentStatus.COMPLETE,
                trust=AttestationTrust.UNVERIFIED,
            ),
        )
        summary = summarize_bundle_security(evidence)
        strict = SecurityInstallPolicy(
            minimum_attestation_trust=AttestationTrust.COMPANY_REVIEWED,
            insufficient_trust_action=SecurityPolicyAction.BLOCK,
            required_provider_ids=("aart-baseline", "ruff"),
            missing_provider_action=SecurityPolicyAction.CONFIRM,
            scopes=("user",),
        )

        project = evaluate_security_policy(summary, evidence, strict, scope="project")
        self.assertIs(project.action, SecurityPolicyAction.ALLOW)

        user = evaluate_security_policy(summary, evidence, strict, scope="user")
        self.assertIs(user.action, SecurityPolicyAction.BLOCK)
        self.assertTrue(any("trust" in reason.casefold() for reason in user.reasons))
        self.assertTrue(any("provider" in reason.casefold() for reason in user.reasons))

        default = evaluate_security_policy(
            summarize_bundle_security((_evidence("unknown", AssessmentStatus.NOT_SCANNED),)),
            (_evidence("unknown", AssessmentStatus.NOT_SCANNED),),
            SecurityInstallPolicy(),
            scope="project",
        )
        self.assertIs(default.action, SecurityPolicyAction.WARN)


if __name__ == "__main__":
    unittest.main()
