from __future__ import annotations

import unittest

from agent_artifacts.domain.identifiers import ArtifactCoordinate, ArtifactIdentity, SourceAlias
from agent_artifacts.protocol.hashing import sha256_bytes
from agent_artifacts.protocol.json import JsonArray, JsonObject
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
    evaluate_security_policy,
)
from agent_artifacts.security.projections import (
    artifact_security_value,
    bundle_security_value,
    policy_decision_value,
)
from agent_artifacts.security.suites import BUILTIN_ANALYZER_SUITES
from agent_artifacts.security.tool_adapters import BUILTIN_TOOL_ADAPTERS


def _evidence() -> ArtifactSecurityEvidence:
    coordinate = ArtifactCoordinate(
        SourceAlias("company"), ArtifactIdentity("skill", "review"), "1.2.3"
    )
    coverage = AssessmentCoverage(1, 2, ("ruff:not-installed",))
    provider = ProviderAssessment(
        "ruff",
        "0.9.1",
        sha256_bytes(b"ruff-rules"),
        AssessmentStatus.PARTIAL,
        coverage,
        "Optional analyzer completed part of the expected assessment.",
    )
    finding = make_finding(
        "unsafe-call",
        FindingSeverity.HIGH,
        "A reviewed rule matched this immutable artifact.",
        "Inspect the matching call before installation.",
        provider_id="ruff",
    )
    assessment = SecurityAssessment(
        1,
        sha256_bytes(b"artifact"),
        AssessmentStatus.PARTIAL,
        risk_from_evidence(AssessmentStatus.PARTIAL, FindingSeverity.HIGH),
        FindingSeverity.HIGH,
        coverage,
        (finding,),
        (provider,),
    )
    return ArtifactSecurityEvidence(
        coordinate,
        assessment,
        AttestationTrust.REGISTRY_REVIEWED,
        321,
    )


def _mapping(value: JsonObject) -> dict[str, object]:
    return dict(value.entries)


class SecurityProjectionSuitesTest(unittest.TestCase):
    def test_artifact_projection_exposes_explainable_installation_risk(self) -> None:
        value = _mapping(artifact_security_value(_evidence()))

        self.assertEqual(value["coordinate"], "company/skill/review@1.2.3")
        self.assertEqual(value["installation_risk"], "high")
        self.assertEqual(value["assessment_status"], "partial")
        self.assertEqual(value["attestation_trust"], "registry-reviewed")
        self.assertEqual(value["evidence_age_seconds"], 321)
        self.assertEqual(
            value["coverage"],
            JsonObject(
                (("completed", 1), ("expected", 2), ("skipped", JsonArray(("ruff:not-installed",))))
            ),
        )
        providers = value["providers"]
        self.assertIsInstance(providers, JsonArray)
        assert isinstance(providers, JsonArray)
        self.assertEqual(_mapping(providers.items[0])["version"], "0.9.1")
        self.assertEqual(
            _mapping(providers.items[0])["rules_digest"], str(sha256_bytes(b"ruff-rules"))
        )
        self.assertEqual(
            value["remediation"],
            JsonArray(("Inspect the matching call before installation.",)),
        )
        self.assertNotIn("safe", value)

    def test_bundle_and_policy_projections_keep_worst_unknown_and_reasons(self) -> None:
        evidence = (_evidence(),)
        summary = summarize_bundle_security(evidence)
        decision = evaluate_security_policy(
            summary,
            evidence,
            SecurityInstallPolicy(),
            scope="project",
        )

        bundle = _mapping(bundle_security_value(summary))
        policy = _mapping(policy_decision_value(decision))

        self.assertEqual(bundle["worst_installation_risk"], "high")
        self.assertEqual(bundle["risk_range"], JsonObject((("max", "high"), ("min", "high"))))
        self.assertEqual(bundle["mean_known_risk_milli"], 3000)
        self.assertEqual(
            bundle["coverage"],
            JsonObject(
                (
                    ("completed", 1),
                    ("expected", 2),
                    ("skipped", JsonArray(("company/skill/review@1.2.3:ruff:not-installed",))),
                )
            ),
        )
        self.assertEqual(policy["action"], "confirm")
        self.assertIsInstance(policy["reasons"], JsonArray)

    def test_builtin_suites_reference_known_providers_and_keep_optional_tools_optional(
        self,
    ) -> None:
        providers = {item.provider_id for item in BUILTIN_TOOL_ADAPTERS}
        names = tuple(item.id for item in BUILTIN_ANALYZER_SUITES)

        self.assertEqual(names, ("baseline", "extended", "recommended"))
        self.assertEqual(BUILTIN_ANALYZER_SUITES[0].required_provider_ids, ("aart-baseline",))
        for suite in BUILTIN_ANALYZER_SUITES:
            self.assertEqual(
                tuple(sorted(set(suite.optional_provider_ids))), suite.optional_provider_ids
            )
            self.assertTrue(set(suite.optional_provider_ids) <= providers)
            self.assertNotIn("aart-baseline", suite.optional_provider_ids)


if __name__ == "__main__":
    unittest.main()
