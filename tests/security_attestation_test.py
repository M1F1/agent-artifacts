from __future__ import annotations

import unittest

from agent_artifacts.domain.identifiers import SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.marketplace.model import TrustClass
from agent_artifacts.protocol.hashing import sha256_bytes
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.security.application import verify_security_index
from agent_artifacts.security.attestation_schema import (
    attestation_bytes,
    parse_attestation,
    parse_security_index,
    security_index_bytes,
)
from agent_artifacts.security.attestations import (
    AssessmentCacheKey,
    AttestationOrigin,
    AttestationOriginKind,
    AttestationTrust,
    AttestationTrustContext,
    EvidenceFreshness,
    SecurityAttestation,
    SecurityIndex,
    SecurityIndexEntry,
    attestation_digest,
    cache_key_digest,
    resolve_attestation,
)
from agent_artifacts.security.model import (
    AssessmentCoverage,
    AssessmentStatus,
    FindingSeverity,
    InstallationRisk,
    ProviderAssessment,
    SecurityAssessment,
    mark_assessment_stale_value,
)

OBJECT = sha256_bytes(b"object")
RULES = sha256_bytes(b"rules")
OPTIONS = sha256_bytes(b"options")
POLICY = sha256_bytes(b"policy")
REGISTRY_INPUTS = sha256_bytes(b"registry-inputs")


def _assessment() -> SecurityAssessment:
    coverage = AssessmentCoverage(1, 1)
    provider = ProviderAssessment(
        "aart-baseline",
        "1",
        RULES,
        AssessmentStatus.COMPLETE,
        coverage,
        "Baseline completed with normalized evidence.",
    )
    return SecurityAssessment(
        1,
        OBJECT,
        AssessmentStatus.COMPLETE,
        InstallationRisk.LOW,
        FindingSeverity.UNKNOWN,
        coverage,
        (),
        (provider,),
    )


def _key(**changes: object) -> AssessmentCacheKey:
    values: dict[str, object] = {
        "schema_version": 1,
        "object_digest": OBJECT,
        "provider_id": "aart-baseline",
        "provider_version": "1",
        "rules_digest": RULES,
        "options_digest": OPTIONS,
        "policy_digest": POLICY,
    }
    values.update(changes)
    return AssessmentCacheKey(**values)  # type: ignore[arg-type]


def _origin() -> AttestationOrigin:
    return AttestationOrigin(
        AttestationOriginKind.REGISTRY_CI,
        SourceId("company-registry"),
        "a" * 40,
        REGISTRY_INPUTS,
    )


def _attestation() -> SecurityAttestation:
    return SecurityAttestation(1, _key(), _origin(), _assessment())


class SecurityAttestationTest(unittest.TestCase):
    def test_cache_key_and_attestation_bind_every_effective_input(self) -> None:
        baseline = _key()
        variants = (
            _key(object_digest=sha256_bytes(b"other")),
            _key(provider_id="other"),
            _key(provider_version="2"),
            _key(rules_digest=sha256_bytes(b"other-rules")),
            _key(options_digest=sha256_bytes(b"other-options")),
            _key(policy_digest=sha256_bytes(b"other-policy")),
        )

        self.assertEqual(len({cache_key_digest(item) for item in (baseline, *variants)}), 7)
        self.assertEqual(_attestation().assessment.object_digest, baseline.object_digest)

        with self.assertRaises(ValueError):
            SecurityAttestation(
                1,
                _key(provider_version="2"),
                _origin(),
                _assessment(),
            )

    def test_attestation_and_index_have_one_strict_canonical_representation(self) -> None:
        attestation = _attestation()
        encoded = attestation_bytes(attestation)
        self.assertEqual(parse_attestation(encoded), Ok(attestation))
        self.assertEqual(attestation_bytes(parse_attestation(encoded).value), encoded)  # type: ignore[union-attr]

        path = parse_relative_path(
            f"security/attestations/{attestation_digest(attestation).value}.json"
        )
        assert isinstance(path, Ok)
        entry = SecurityIndexEntry(
            _key(),
            attestation_digest(attestation),
            path.value,
        )
        index = SecurityIndex(1, SourceId("company-registry"), REGISTRY_INPUTS, (entry,))
        index_encoded = security_index_bytes(index)
        self.assertEqual(parse_security_index(index_encoded), Ok(index))
        self.assertEqual(
            security_index_bytes(parse_security_index(index_encoded).value), index_encoded
        )  # type: ignore[union-attr]

        invalid_attestations = (
            encoded.replace(b'"schema_version":1', b'"extra":true,"schema_version":1'),
            encoded.replace(str(OBJECT).encode(), str(sha256_bytes(b"other")).encode(), 1),
            encoded.rstrip(b"\n"),
            b"not-json",
        )
        for invalid in invalid_attestations:
            with self.subTest(invalid=invalid[:60]):
                self.assertIsInstance(parse_attestation(invalid), Err)

        invalid_indexes = (
            index_encoded.replace(b'"schema_version":1', b'"unknown":0,"schema_version":1'),
            index_encoded.replace(b'"registry_id":"company-registry"', b'"registry_id":"Bad"'),
            index_encoded.rstrip(b"\n"),
        )
        for invalid in invalid_indexes:
            with self.subTest(invalid=invalid[:60]):
                self.assertIsInstance(parse_security_index(invalid), Err)

    def test_freshness_marks_evidence_stale_on_any_cache_identity_change(self) -> None:
        attestation = _attestation()
        current = resolve_attestation(attestation, _key(), trust_context=None)
        self.assertIs(current.freshness, EvidenceFreshness.CURRENT)
        self.assertEqual(current.assessment, attestation.assessment)

        for expected in (
            _key(object_digest=sha256_bytes(b"changed-object")),
            _key(provider_version="2"),
            _key(rules_digest=sha256_bytes(b"changed-rules")),
            _key(options_digest=sha256_bytes(b"changed-options")),
            _key(policy_digest=sha256_bytes(b"changed-policy")),
        ):
            with self.subTest(expected=expected):
                result = resolve_attestation(attestation, expected, trust_context=None)
                self.assertIs(result.freshness, EvidenceFreshness.STALE)
                self.assertEqual(result.assessment, mark_assessment_stale_value(_assessment()))

    def test_registry_attestation_trust_is_derived_from_exact_local_context(self) -> None:
        attestation = _attestation()
        company = AttestationTrustContext(
            SourceId("company-registry"),
            REGISTRY_INPUTS,
            TrustClass.COMPANY_REVIEWED,
        )
        reviewed = resolve_attestation(attestation, _key(), trust_context=company)
        self.assertIs(reviewed.trust, AttestationTrust.COMPANY_REVIEWED)

        contexts = (
            None,
            AttestationTrustContext(
                SourceId("other-registry"), REGISTRY_INPUTS, TrustClass.COMPANY_REVIEWED
            ),
            AttestationTrustContext(
                SourceId("company-registry"),
                sha256_bytes(b"changed-registry"),
                TrustClass.COMPANY_REVIEWED,
            ),
            AttestationTrustContext(
                SourceId("company-registry"), REGISTRY_INPUTS, TrustClass.DIRECT_SOURCE
            ),
        )
        for context in contexts:
            with self.subTest(context=context):
                result = resolve_attestation(attestation, _key(), trust_context=context)
                self.assertIs(result.trust, AttestationTrust.UNVERIFIED)

        local = SecurityAttestation(
            1,
            _key(),
            AttestationOrigin(AttestationOriginKind.LOCAL),
            _assessment(),
        )
        self.assertIs(
            resolve_attestation(local, _key(), trust_context=None).trust,
            AttestationTrust.LOCAL,
        )

    def test_invalid_values_and_duplicate_index_keys_fail_closed(self) -> None:
        invalid_keys = (
            lambda: _key(schema_version=2),
            lambda: _key(provider_id="Bad ID"),
            lambda: _key(provider_version="bad version"),
            lambda: _key(object_digest=object()),
        )
        for constructor in invalid_keys:
            with self.subTest(constructor=constructor), self.assertRaises(ValueError):
                constructor()

        with self.assertRaises(ValueError):
            AttestationOrigin(AttestationOriginKind.LOCAL, SourceId("registry"))
        with self.assertRaises(ValueError):
            AttestationOrigin(
                AttestationOriginKind.REGISTRY_CI,
                SourceId("registry"),
                "moving-main",
                REGISTRY_INPUTS,
            )

        digest = attestation_digest(_attestation())
        path = parse_relative_path(f"security/attestations/{digest.value}.json")
        assert isinstance(path, Ok)
        entry = SecurityIndexEntry(_key(), digest, path.value)
        with self.assertRaises(ValueError):
            SecurityIndex(1, SourceId("registry"), REGISTRY_INPUTS, (entry, entry))

    def test_registry_index_verifies_document_digest_key_and_exact_publisher(self) -> None:
        attestation = _attestation()
        digest = attestation_digest(attestation)
        path = parse_relative_path(f"security/attestations/{digest.value}.json")
        assert isinstance(path, Ok)
        entry = SecurityIndexEntry(_key(), digest, path.value)
        index = SecurityIndex(1, SourceId("company-registry"), REGISTRY_INPUTS, (entry,))

        verified = verify_security_index(index, ((path.value, attestation_bytes(attestation)),))
        self.assertIsInstance(verified, Ok)
        assert isinstance(verified, Ok)
        self.assertEqual(verified.value.attestations, (attestation,))

        local = SecurityAttestation(
            1,
            _key(),
            AttestationOrigin(AttestationOriginKind.LOCAL),
            _assessment(),
        )
        failures = (
            (),
            ((path.value, attestation_bytes(local)),),
            ((path.value, attestation_bytes(attestation) + b" "),),
        )
        for documents in failures:
            with self.subTest(documents=documents):
                self.assertIsInstance(verify_security_index(index, documents), Err)


if __name__ == "__main__":
    unittest.main()
