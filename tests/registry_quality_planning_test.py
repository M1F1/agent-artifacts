from __future__ import annotations

import json
import unittest
from pathlib import Path

from agent_artifacts.domain.result import Ok
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.hashing import json_digest
from agent_artifacts.protocol.json import JsonObject
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.protocol.registry_schema import parse_registry_index, parse_registry_lock
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.registry_commands.planning import (
    audit_registry_workspace,
    plan_registry_build,
    plan_registry_format,
    plan_registry_lock,
    project_registry_workspace_plan,
    validate_registry_workspace,
)
from agent_artifacts.registry_commands.planning import (
    test_registry_compatibility as check_registry_compatibility,
)
from agent_artifacts.registry_maintenance.model import NativeReferenceAcquisition
from agent_artifacts.registry_maintenance.planning import (
    plan_registry_entry_add,
    project_registry_mutation,
)
from agent_artifacts.security.attestation_schema import attestation_bytes, security_index_bytes
from agent_artifacts.security.attestations import (
    AssessmentCacheKey,
    AttestationOrigin,
    AttestationOriginKind,
    SecurityAttestation,
    SecurityIndex,
    SecurityIndexEntry,
    attestation_digest,
)
from agent_artifacts.security.baseline import BASELINE_RULES_DIGEST, not_scanned_assessment
from tests.registry_maintenance_fixtures import (
    append_snapshot_file,
    empty_registry_snapshot,
    native_snapshot,
    registry_entry,
    replace_snapshot_file,
    snapshot_file,
    tree_snapshot,
)

CAPABILITIES = (
    Capability("artifact-manifest-v1"),
    Capability("lockfile-v1"),
    Capability("registry-entry-v1"),
)
VERSION = SemVer(1, 0, 0)


def _authored_registry():
    snapshot = empty_registry_snapshot()
    entry = plan_registry_entry_add(snapshot, registry_entry())
    assert isinstance(entry, Ok)
    projected = project_registry_mutation(snapshot, entry.value)
    assert isinstance(projected, Ok)
    return projected.value


def _acquisition():
    return NativeReferenceAcquisition(
        "https://github.com/example/reference-skills.git",
        "main",
        "a" * 40,
        native_snapshot(),
    )


class RegistryQualityPlanningTest(unittest.TestCase):
    def test_format_is_canonical_and_checkable_without_mutation(self) -> None:
        snapshot = replace_snapshot_file(
            empty_registry_snapshot(),
            "aart-registry.json",
            b'{ "schema_version": 1, "protocol_version": 1, "registry_id": "test-registry", '
            b'"display_name": "Test Registry", "requires_aart": {"min_inclusive": "1.0.0", '
            b'"max_exclusive": "2.0.0"}, "required_capabilities": [], '
            b'"default_channel": "main", "services": {} }',
        )
        plan = plan_registry_format(snapshot)
        assert isinstance(plan, Ok), plan
        self.assertEqual(plan.value.changed_paths, 2)
        projected = project_registry_workspace_plan(snapshot, plan.value)
        assert isinstance(projected, Ok)
        canonical = plan_registry_format(projected.value)
        assert isinstance(canonical, Ok)
        self.assertEqual(canonical.value.changed_paths, 0)

    def test_format_never_rewrites_json_that_belongs_to_artifact_payload(self) -> None:
        payload = b'{ "command": "leave-byte-exact" }\n'
        snapshot = append_snapshot_file(
            empty_registry_snapshot(),
            "artifacts/mcp/demo/payload/mcp.json",
            payload,
        )

        planned = plan_registry_format(snapshot)
        assert isinstance(planned, Ok)
        projected = project_registry_workspace_plan(snapshot, planned.value)
        assert isinstance(projected, Ok)

        self.assertEqual(
            snapshot_file(projected.value, "artifacts/mcp/demo/payload/mcp.json"),
            payload,
        )

    def test_lock_then_build_produces_exact_payload_free_outputs(self) -> None:
        authored = _authored_registry()
        locked = plan_registry_lock(
            authored,
            (_acquisition(),),
            executable_version=VERSION,
            available_capabilities=CAPABILITIES,
        )
        assert isinstance(locked, Ok), locked
        with_lock = project_registry_workspace_plan(authored, locked.value)
        assert isinstance(with_lock, Ok)
        lock = parse_registry_lock(snapshot_file(with_lock.value, "aart.lock.json"))
        assert isinstance(lock, Ok)
        self.assertEqual(lock.value.entries[0][1].resolved_commit, "a" * 40)

        built = plan_registry_build(
            with_lock.value,
            (_acquisition(),),
            executable_version=VERSION,
            available_capabilities=CAPABILITIES,
        )
        assert isinstance(built, Ok), built
        complete = project_registry_workspace_plan(with_lock.value, built.value)
        assert isinstance(complete, Ok)
        index = parse_registry_index(snapshot_file(complete.value, "aart.index.json"))
        assert isinstance(index, Ok)
        self.assertEqual(str(index.value.artifacts[0].source_id), "reference-native-source")
        self.assertNotIn(b"# Code review", snapshot_file(complete.value, "aart.index.json"))

    def test_validate_audit_and_minimum_latest_matrix_are_read_only(self) -> None:
        fixture = tree_snapshot(
            Path("tests/fixtures/protocol/registry-v1"),
            SnapshotOrigin.LOCAL,
        )
        formatted = plan_registry_format(fixture)
        assert isinstance(formatted, Ok)
        self.assertEqual(formatted.value.changed_paths, 0)
        validated = validate_registry_workspace(
            fixture,
            executable_version=VERSION,
            available_capabilities=CAPABILITIES,
            require_compiled=True,
        )
        assert isinstance(validated, Ok), validated
        self.assertTrue(validated.value.passed)
        audited = audit_registry_workspace(fixture)
        assert isinstance(audited, Ok), audited
        self.assertTrue(audited.value.passed)
        matrix = check_registry_compatibility(
            fixture,
            minimum=SemVer(1, 0, 0),
            latest=SemVer(1, 9, 9),
            available_capabilities=CAPABILITIES,
        )
        assert isinstance(matrix, Ok), matrix
        self.assertEqual(tuple(item.name for item in matrix.value.checks), ("minimum", "latest"))
        self.assertTrue(matrix.value.passed)

    def test_audit_verifies_complete_digest_bound_registry_security_index(self) -> None:
        fixture = tree_snapshot(
            Path("tests/fixtures/protocol/registry-v1"),
            SnapshotOrigin.LOCAL,
        )
        compiled = parse_registry_index(snapshot_file(fixture, "aart.index.json"))
        assert isinstance(compiled, Ok)
        empty_digest = json_digest(JsonObject(()))
        attestations = tuple(
            SecurityAttestation(
                1,
                AssessmentCacheKey(
                    1,
                    artifact.object_digest,
                    "aart-baseline",
                    "1",
                    BASELINE_RULES_DIGEST,
                    empty_digest,
                    empty_digest,
                ),
                AttestationOrigin(
                    AttestationOriginKind.REGISTRY_CI,
                    compiled.value.registry_id,
                    "a" * 40,
                    compiled.value.registry_inputs_digest,
                ),
                not_scanned_assessment(
                    artifact.object_digest,
                    "Registry CI deliberately recorded baseline assessment coverage.",
                ),
            )
            for artifact in compiled.value.artifacts
        )
        entries = []
        with_security = fixture
        for attestation in attestations:
            digest = attestation_digest(attestation)
            raw_path = f"security/attestations/{digest.value}.json"
            parsed_path = parse_relative_path(raw_path)
            assert isinstance(parsed_path, Ok)
            entries.append(SecurityIndexEntry(attestation.cache_key, digest, parsed_path.value))
            with_security = append_snapshot_file(
                with_security,
                raw_path,
                attestation_bytes(attestation),
            )
        security_index = SecurityIndex(
            1,
            compiled.value.registry_id,
            compiled.value.registry_inputs_digest,
            tuple(entries),
        )
        with_security = append_snapshot_file(
            with_security,
            "security/index.json",
            security_index_bytes(security_index),
        )

        audited = audit_registry_workspace(with_security)

        assert isinstance(audited, Ok)
        messages = tuple(
            item.message for check in audited.value.checks for item in check.diagnostics
        )
        self.assertFalse(any("no per-object" in message for message in messages))
        self.assertFalse(any("security index" in message for message in messages))

        tampered = replace_snapshot_file(
            with_security,
            str(entries[0].path),
            b"{}\n",
        )
        rejected = audit_registry_workspace(tampered)
        assert isinstance(rejected, Ok)
        self.assertFalse(rejected.value.passed)
        rejected_messages = tuple(
            item.message for check in rejected.value.checks for item in check.diagnostics
        )
        self.assertTrue(any("bytes do not match" in message for message in rejected_messages))

    def test_audit_fails_an_unapproved_external_reference(self) -> None:
        snapshot = empty_registry_snapshot()
        entry = plan_registry_entry_add(snapshot, registry_entry(review_status="pending"))
        assert isinstance(entry, Ok)
        projected = project_registry_mutation(snapshot, entry.value)
        assert isinstance(projected, Ok)

        audited = audit_registry_workspace(projected.value)

        assert isinstance(audited, Ok)
        self.assertFalse(audited.value.passed)
        messages = tuple(
            item.message for check in audited.value.checks for item in check.diagnostics
        )
        self.assertTrue(any("not approved" in message for message in messages))

    def test_audit_requires_a_lock_for_approved_external_references(self) -> None:
        authored = _authored_registry()

        audited = audit_registry_workspace(authored)

        assert isinstance(audited, Ok)
        self.assertFalse(audited.value.passed)
        messages = tuple(
            item.message for check in audited.value.checks for item in check.diagnostics
        )
        self.assertTrue(any("committed lock" in message for message in messages))

    def test_compiled_outputs_must_be_regular_files(self) -> None:
        paths = []
        for raw in ("aart.lock.json", "aart.index.json"):
            parsed = parse_relative_path(raw)
            assert isinstance(parsed, Ok)
            paths.append(SnapshotEntry(parsed.value, SnapshotEntryKind.DIRECTORY))
        base = empty_registry_snapshot()
        malformed = SourceSnapshot(base.origin, (*base.entries, *paths))

        validated = validate_registry_workspace(
            malformed,
            executable_version=VERSION,
            available_capabilities=CAPABILITIES,
            require_compiled=True,
        )

        assert isinstance(validated, Ok)
        self.assertFalse(validated.value.passed)

    def test_validate_rejects_an_index_that_disagrees_with_the_committed_lock(self) -> None:
        fixture = tree_snapshot(
            Path("tests/fixtures/protocol/registry-v1"),
            SnapshotOrigin.LOCAL,
        )
        raw_index = json.loads(snapshot_file(fixture, "aart.index.json"))
        external = next(
            artifact
            for artifact in raw_index["artifacts"]
            if artifact["type"] == "mcp" and artifact["name"] == "atlassian"
        )
        external["manifest_digest"] = "sha256:" + "f" * 64
        forged = replace_snapshot_file(
            fixture,
            "aart.index.json",
            json.dumps(raw_index).encode(),
        )

        validated = validate_registry_workspace(
            forged,
            executable_version=VERSION,
            available_capabilities=CAPABILITIES,
            require_compiled=True,
        )

        assert isinstance(validated, Ok)
        self.assertFalse(validated.value.passed)

    def test_validate_binds_index_provenance_to_the_locked_origin(self) -> None:
        fixture = tree_snapshot(
            Path("tests/fixtures/protocol/registry-v1"),
            SnapshotOrigin.LOCAL,
        )
        raw_index = json.loads(snapshot_file(fixture, "aart.index.json"))
        external = next(
            artifact
            for artifact in raw_index["artifacts"]
            if artifact["type"] == "mcp" and artifact["name"] == "atlassian"
        )
        external["provenance"]["resolved_commit"] = "b" * 40
        forged = replace_snapshot_file(
            fixture,
            "aart.index.json",
            json.dumps(raw_index).encode(),
        )

        validated = validate_registry_workspace(
            forged,
            executable_version=VERSION,
            available_capabilities=CAPABILITIES,
            require_compiled=True,
        )

        assert isinstance(validated, Ok)
        self.assertFalse(validated.value.passed)


if __name__ == "__main__":
    unittest.main()
