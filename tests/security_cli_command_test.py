from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_artifacts.commands import security
from agent_artifacts.domain.identifiers import SourceId
from agent_artifacts.marketplace.model import TrustClass
from agent_artifacts.model import Request
from agent_artifacts.protocol.hashing import json_digest, sha256_bytes
from agent_artifacts.protocol.json import JsonObject, canonical_json_bytes
from agent_artifacts.protocol.registry_models import RegistryIndex
from agent_artifacts.protocol.registry_schema import registry_index_to_json
from agent_artifacts.security.attestation_schema import attestation_bytes
from agent_artifacts.security.attestations import (
    AssessmentCacheKey,
    AttestationOrigin,
    AttestationOriginKind,
    SecurityAttestation,
)
from agent_artifacts.security.baseline import BASELINE_RULES_DIGEST
from tests.security_baseline_test import _fixture


class SecurityCliCommandTest(unittest.TestCase):
    def test_analyzers_and_suites_are_machine_readable_without_installing(self) -> None:
        documents = {}
        for action in ("analyzers", "suites"):
            output = io.StringIO()
            with (
                patch.object(security, "resolve_executable", return_value=None),
                contextlib.redirect_stdout(output),
            ):
                code = security.run(Request("security", security_action=action, json=True))
            self.assertEqual(code, 0)
            value = json.loads(output.getvalue())
            documents[action] = value
            self.assertEqual(value["schema_version"], 1)
        self.assertTrue(all(not item["available"] for item in documents["analyzers"]["analyzers"]))

    def test_show_and_verify_report_current_then_stale_evidence(self) -> None:
        candidate, artifact, _lock = _fixture()
        assessment = security.assess_installation_risk(
            security.BaselineScanRequest(candidate, artifact)
        )
        empty = json_digest(JsonObject(()))
        key = AssessmentCacheKey(
            1,
            candidate.digest,
            "aart-baseline",
            "1",
            BASELINE_RULES_DIGEST,
            empty,
            empty,
        )
        attestation = SecurityAttestation(
            1,
            key,
            AttestationOrigin(AttestationOriginKind.LOCAL),
            assessment,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "attestation.json"
            path.write_bytes(attestation_bytes(attestation))
            shown = io.StringIO()
            with contextlib.redirect_stdout(shown):
                self.assertEqual(
                    security.run(
                        Request(
                            "security",
                            security_action="show",
                            security_input=str(path),
                            json=True,
                        )
                    ),
                    0,
                )
            self.assertEqual(json.loads(shown.getvalue())["installation_risk"], "medium")

            verified = io.StringIO()
            with contextlib.redirect_stdout(verified):
                self.assertEqual(
                    security.run(
                        Request(
                            "security",
                            security_action="verify",
                            security_input=str(path),
                            json=True,
                        )
                    ),
                    0,
                )
            self.assertEqual(json.loads(verified.getvalue())["freshness"], "current")

            stale = io.StringIO()
            with contextlib.redirect_stdout(stale):
                self.assertEqual(
                    security.run(
                        Request(
                            "security",
                            security_action="verify",
                            security_input=str(path),
                            security_object_digest=str(sha256_bytes(b"new object")),
                            json=True,
                        )
                    ),
                    1,
                )
            self.assertEqual(json.loads(stale.getvalue())["freshness"], "stale")

    def test_scan_publishes_idempotent_digest_bound_cache_entry(self) -> None:
        candidate, artifact, _lock = _fixture()
        registry_inputs_digest = sha256_bytes(b"registry inputs")
        index = RegistryIndex(
            1,
            1,
            SourceId("company"),
            registry_inputs_digest,
            (artifact,),
            (),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            object_path = root / "object.json"
            index_path = root / "aart.index.json"
            cache_path = root / "cache"
            object_path.write_bytes(candidate.canonical_bytes)
            index_path.write_bytes(canonical_json_bytes(registry_index_to_json(index)))
            request = Request(
                "security",
                security_action="scan",
                security_input=str(object_path),
                registry_index=str(index_path),
                security_artifact=str(artifact.identity),
                security_cache=str(cache_path),
                json=True,
            )

            outputs = []
            for _attempt in range(2):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(security.run(request), 0)
                outputs.append(json.loads(output.getvalue()))

            self.assertTrue(outputs[0]["cache_created"])
            self.assertFalse(outputs[1]["cache_created"])
            self.assertEqual(outputs[0]["cache_path"], outputs[1]["cache_path"])
            self.assertTrue(Path(outputs[0]["cache_path"]).is_file())

    def test_registry_ci_trust_is_derived_only_from_exact_local_context(self) -> None:
        candidate, artifact, _lock = _fixture()
        assessment = security.assess_installation_risk(
            security.BaselineScanRequest(candidate, artifact)
        )
        empty = json_digest(JsonObject(()))
        key = AssessmentCacheKey(
            1,
            candidate.digest,
            "aart-baseline",
            "1",
            BASELINE_RULES_DIGEST,
            empty,
            empty,
        )
        inputs = sha256_bytes(b"inputs")
        attestation = SecurityAttestation(
            1,
            key,
            AttestationOrigin(
                AttestationOriginKind.REGISTRY_CI,
                SourceId("company"),
                "a" * 40,
                inputs,
            ),
            assessment,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "attestation.json"
            path.write_bytes(attestation_bytes(attestation))
            request = Request(
                "security",
                security_action="verify",
                security_input=str(path),
                publisher_source_id="company",
                security_registry_inputs_digest=str(inputs),
                publisher_trust=TrustClass.COMPANY_REVIEWED.value,
                json=True,
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(security.run(request), 0)
            self.assertEqual(json.loads(output.getvalue())["trust"], "company-reviewed")

            invalid = io.StringIO()
            with contextlib.redirect_stderr(invalid):
                self.assertEqual(
                    security.run(
                        Request(
                            "security",
                            security_action="verify",
                            security_input=str(path),
                            security_provider_version="invalid version",
                        )
                    ),
                    1,
                )
            self.assertIn("cache identity", invalid.getvalue())


if __name__ == "__main__":
    unittest.main()
