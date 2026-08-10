from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from agent_artifacts.domain.identifiers import SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.io.security_cache import read_cached_attestation, write_cached_attestation
from agent_artifacts.protocol.hashing import sha256_bytes
from agent_artifacts.security.attestations import (
    AssessmentCacheKey,
    AttestationOrigin,
    AttestationOriginKind,
    SecurityAttestation,
    cache_key_digest,
)
from agent_artifacts.security.cache import security_cache_paths
from agent_artifacts.security.model import (
    AssessmentCoverage,
    AssessmentStatus,
    FindingSeverity,
    InstallationRisk,
    ProviderAssessment,
    SecurityAssessment,
)

OBJECT = sha256_bytes(b"cache-object")
RULES = sha256_bytes(b"cache-rules")
OPTIONS = sha256_bytes(b"cache-options")
POLICY = sha256_bytes(b"cache-policy")
REGISTRY_INPUTS = sha256_bytes(b"cache-registry")


def _key() -> AssessmentCacheKey:
    return AssessmentCacheKey(
        1,
        OBJECT,
        "example-provider",
        "1.2.3",
        RULES,
        OPTIONS,
        POLICY,
    )


def _assessment() -> SecurityAssessment:
    coverage = AssessmentCoverage(1, 1)
    provider = ProviderAssessment(
        "example-provider",
        "1.2.3",
        RULES,
        AssessmentStatus.COMPLETE,
        coverage,
        "Provider completed with normalized evidence.",
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


def _attestation(*, local: bool = True) -> SecurityAttestation:
    origin = (
        AttestationOrigin(AttestationOriginKind.LOCAL)
        if local
        else AttestationOrigin(
            AttestationOriginKind.REGISTRY_CI,
            SourceId("registry"),
            "a" * 40,
            REGISTRY_INPUTS,
        )
    )
    return SecurityAttestation(1, _key(), origin, _assessment())


class SecurityCacheTest(unittest.TestCase):
    def test_atomic_private_round_trip_and_idempotent_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = security_cache_paths(str(Path(temporary) / "security-cache"))
            first = write_cached_attestation(paths, _attestation())
            self.assertIsInstance(first, Ok)
            assert isinstance(first, Ok)
            self.assertTrue(first.value.created)
            self.assertEqual(oct(os.stat(first.value.path).st_mode & 0o777), "0o600")

            loaded = read_cached_attestation(paths, _key())
            self.assertEqual(loaded, Ok(_attestation()))
            second = write_cached_attestation(paths, _attestation())
            self.assertIsInstance(second, Ok)
            assert isinstance(second, Ok)
            self.assertFalse(second.value.created)
            self.assertEqual(second.value.path, first.value.path)

    def test_same_cache_identity_cannot_be_silently_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = security_cache_paths(str(Path(temporary) / "security-cache"))
            self.assertIsInstance(write_cached_attestation(paths, _attestation()), Ok)
            collision = write_cached_attestation(paths, _attestation(local=False))
            self.assertIsInstance(collision, Err)
            self.assertEqual(read_cached_attestation(paths, _key()), Ok(_attestation()))

    def test_corrupt_file_and_symlinked_cache_component_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = security_cache_paths(str(Path(temporary) / "security-cache"))
            written = write_cached_attestation(paths, _attestation())
            assert isinstance(written, Ok)
            os.chmod(written.value.path, 0o600)
            Path(written.value.path).write_bytes(b"not-json")
            self.assertIsInstance(read_cached_attestation(paths, _key()), Err)

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "target"
            target.mkdir()
            root = Path(temporary) / "security-cache"
            root.symlink_to(target, target_is_directory=True)
            paths = security_cache_paths(str(root))
            self.assertIsInstance(write_cached_attestation(paths, _attestation()), Err)

    def test_paths_are_exactly_derived_from_cache_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = security_cache_paths(str(Path(temporary) / "security-cache"))
            written = write_cached_attestation(paths, _attestation())
            assert isinstance(written, Ok)
            digest = cache_key_digest(_key()).value
            self.assertTrue(written.value.path.endswith(f"/{digest[:2]}/{digest[2:]}.json"))

        for root in ("relative", "/"):
            with self.subTest(root=root), self.assertRaises(ValueError):
                security_cache_paths(root)


if __name__ == "__main__":
    unittest.main()
