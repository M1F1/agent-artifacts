"""Strict installation manifest v2 contracts."""

from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from agent_artifacts.configuration.model import SourceKind
from agent_artifacts.domain.identifiers import (
    ArtifactCoordinate,
    ArtifactIdentity,
    ObjectDigest,
    SourceAlias,
    SourceId,
)
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.install_state.model import (
    ArtifactEvidence,
    EffectProof,
    InstallationRecord,
    InstallState,
    SourceEvidence,
)
from agent_artifacts.install_state.schema import install_state_bytes, parse_install_state
from agent_artifacts.protocol.hashing import json_digest
from agent_artifacts.protocol.json import JsonArray
from agent_artifacts.protocol.semver import SemVer


def _digest(character: str) -> ObjectDigest:
    return ObjectDigest("sha256", character * 64)


def _record() -> InstallationRecord:
    identity = ArtifactIdentity("mcp", "atlassian")
    return InstallationRecord(
        coordinate=ArtifactCoordinate(SourceAlias("company"), identity),
        source=SourceEvidence(
            alias=SourceAlias("company"),
            declared_id=SourceId("company-agent-artifacts"),
            kind=SourceKind.REGISTRY_GIT,
            origin="https://github.com/acme/agent-artifacts-registry.git",
            resolved_commit="a" * 40,
            subscription_ref="main",
        ),
        artifact=ArtifactEvidence(
            identity=identity,
            version=SemVer(2, 1, 0),
            manifest_digest=_digest("1"),
            payload_digest=_digest("2"),
            object_digest=_digest("3"),
        ),
        profile="tabnine",
        profile_version=1,
        scope="project",
        requested_mode="symlink",
        effects=(
            EffectProof(
                kind="merge-json",
                destination=".mcp.json",
                actual_mode="copy",
                installed_digest=_digest("4"),
                json_path="mcpServers.atlassian",
                merge_mode="key",
                identity_digest=json_digest(JsonArray(("atlassian",))),
                identity_evidence=JsonArray(("atlassian",)),
                created_destination=False,
                overwrote=False,
            ),
        ),
        setup_state_ref="setup-atlassian-tabnine",
    )


class InstallStateSchemaTests(unittest.TestCase):
    fixtures = Path(__file__).resolve().parent / "fixtures" / "install-state"

    def test_err01_recognized_v01_state_currently_reports_v2_field_errors(self) -> None:
        """Characterize ERR01 before ERR02 gives the recognized legacy shape its own code."""

        result = parse_install_state(
            (self.fixtures / "legacy-v01-manifest.json").read_bytes(),
            path="/fixture/project/.agent-artifacts/manifest.json",
        )

        self.assertIsInstance(result, Err)
        assert isinstance(result, Err)
        self.assertEqual(
            tuple(diagnostic.code.value for diagnostic in result.diagnostics),
            (
                "protocol-schema-missing-field",
                "protocol-schema-missing-field",
                "protocol-schema-unknown-field",
                "protocol-schema-unknown-field",
            ),
        )
        self.assertEqual(
            tuple(diagnostic.message for diagnostic in result.diagnostics),
            (
                "missing required field 'installations'",
                "missing required field 'schema_version'",
                "unknown field 'installed'",
                "unknown field 'repo'",
            ),
        )
        self.assertTrue(
            all(
                diagnostic.location is not None
                and diagnostic.location.path == "/fixture/project/.agent-artifacts/manifest.json"
                for diagnostic in result.diagnostics
            )
        )

    def test_err01_malformed_v2_fixture_is_a_distinct_current_parser_case(self) -> None:
        """ERR02 must not mistake a malformed v2 shape for the bounded legacy signature."""

        result = parse_install_state(
            (self.fixtures / "malformed-v2-manifest.json").read_bytes(),
            path="/fixture/project/.agent-artifacts/manifest.json",
        )

        self.assertIsInstance(result, Err)
        assert isinstance(result, Err)
        self.assertEqual(
            tuple(diagnostic.code.value for diagnostic in result.diagnostics),
            ("install-state-invalid",),
        )
        self.assertEqual(
            tuple(diagnostic.message for diagnostic in result.diagnostics),
            ("installations must be an array",),
        )

    def test_v2_round_trip_is_canonical_and_deterministic(self) -> None:
        state = InstallState(schema_version=2, installations=(_record(),))

        first = install_state_bytes(state)
        parsed = parse_install_state(first)

        self.assertEqual(parsed, Ok(state))
        self.assertEqual(install_state_bytes(parsed.value), first)
        self.assertTrue(first.endswith(b"\n"))
        self.assertIn(b'"schema_version":2', first)
        self.assertIn(b'"subscription_ref":"main"', first)
        self.assertIn(b'"identity_evidence":["atlassian"]', first)

    def test_unknown_fields_and_duplicate_keys_are_rejected(self) -> None:
        valid = install_state_bytes(InstallState(2, (_record(),))).decode().rstrip()
        unknown = valid[:-1] + ',"raw_setup_output":"secret"}'
        duplicate = valid.replace('"schema_version":2', '"schema_version":2,"schema_version":2')

        for payload in (unknown, duplicate):
            with self.subTest(payload=payload[:60]):
                result = parse_install_state(payload)
                self.assertIsInstance(result, Err)

    def test_corrupt_version_digest_commit_and_effect_shape_are_rejected(self) -> None:
        valid = install_state_bytes(InstallState(2, (_record(),))).decode()
        invalid_documents = (
            valid.replace('"version":"2.1.0"', '"version":"latest"'),
            valid.replace("sha256:" + "1" * 64, "sha256:bad"),
            valid.replace('"resolved_commit":"' + "a" * 40 + '"', '"resolved_commit":"main"'),
            valid.replace('"kind":"merge-json"', '"kind":"copy-tree"'),
        )

        for payload in invalid_documents:
            with self.subTest(payload=payload[:80]):
                self.assertIsInstance(parse_install_state(payload), Err)

    def test_credential_bearing_origin_is_rejected_before_serialization(self) -> None:
        with self.assertRaisesRegex(ValueError, "credential-free"):
            SourceEvidence(
                alias=SourceAlias("company"),
                declared_id=SourceId("company-agent-artifacts"),
                kind=SourceKind.REGISTRY_GIT,
                origin="https://token@github.com/acme/private.git",
                resolved_commit="a" * 40,
                subscription_ref="main",
            )

    def test_git_source_requires_a_safe_recorded_subscription_ref(self) -> None:
        with self.assertRaisesRegex(ValueError, "safe subscription"):
            replace(_record().source, subscription_ref="../moving")

    def test_local_source_uses_explicit_local_revision_without_a_subscription_ref(self) -> None:
        original = _record()
        source = SourceEvidence(
            SourceAlias("local"),
            SourceId("local-artifacts"),
            SourceKind.SOURCE_LOCAL,
            "/work/artifacts",
            "local",
        )
        record = replace(
            original,
            coordinate=ArtifactCoordinate(SourceAlias("local"), original.artifact.identity),
            source=source,
        )
        state = InstallState(2, (record,))

        self.assertEqual(parse_install_state(install_state_bytes(state)), Ok(state))
        with self.assertRaisesRegex(ValueError, "local source origin"):
            replace(source, resolved_commit="a" * 40)

    def test_local_source_accepts_snapshot_bound_revision(self) -> None:
        source = SourceEvidence(
            SourceAlias("local"),
            SourceId("local-artifacts"),
            SourceKind.SOURCE_LOCAL,
            "/work/artifacts",
            "local:" + "a" * 64,
        )

        self.assertEqual(source.resolved_commit, "local:" + "a" * 64)

    def test_state_rejects_duplicate_installation_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique"):
            InstallState(2, (_record(), _record()))

    def test_state_rejects_two_installations_claiming_the_same_effect(self) -> None:
        original = _record()
        other_identity = ArtifactIdentity("mcp", "jira")
        other = replace(
            original,
            coordinate=ArtifactCoordinate(SourceAlias("company"), other_identity),
            artifact=replace(original.artifact, identity=other_identity),
        )

        with self.assertRaisesRegex(ValueError, "effect ownership"):
            InstallState(2, (original, other))

    def test_merge_effects_with_distinct_identities_can_share_a_json_path(self) -> None:
        original = _record()
        other_identity = ArtifactIdentity("mcp", "jira")
        other = replace(
            original,
            coordinate=ArtifactCoordinate(SourceAlias("company"), other_identity),
            artifact=replace(original.artifact, identity=other_identity),
            effects=(
                replace(
                    original.effects[0],
                    identity_digest=json_digest(JsonArray(("jira",))),
                    identity_evidence=JsonArray(("jira",)),
                ),
            ),
        )

        state = InstallState(2, (original, other))

        self.assertEqual(len(state.installations), 2)

    def test_project_and_user_effect_destinations_do_not_cross_scope(self) -> None:
        project_effect = EffectProof(
            kind="write-file",
            destination="/Users/example/.claude/rules.md",
            actual_mode="copy",
            installed_digest=_digest("6"),
            source_path="payload/rules.md",
        )
        with self.assertRaisesRegex(ValueError, "project.*relative"):
            replace(_record(), effects=(project_effect,))

    def test_memory_mode_round_trips_but_is_rejected_for_other_artifact_types(self) -> None:
        original = _record()
        identity = ArtifactIdentity("memory", "house")
        memory = replace(
            original,
            coordinate=ArtifactCoordinate(SourceAlias("company"), identity),
            artifact=replace(original.artifact, identity=identity),
            requested_mode="copy",
            effects=(
                EffectProof(
                    kind="managed-block",
                    destination="CLAUDE.md",
                    actual_mode="copy",
                    installed_digest=_digest("8"),
                ),
            ),
            memory_mode="append",
            setup_state_ref=None,
        )

        encoded = install_state_bytes(InstallState(2, (memory,)))

        self.assertIn(b'"memory_mode":"append"', encoded)
        self.assertEqual(parse_install_state(encoded), Ok(InstallState(2, (memory,))))
        with self.assertRaisesRegex(ValueError, "installation record"):
            replace(original, memory_mode="append")

    def test_invalid_memory_mode_is_rejected_during_parse(self) -> None:
        original = _record()
        identity = ArtifactIdentity("memory", "house")
        memory = replace(
            original,
            coordinate=ArtifactCoordinate(SourceAlias("company"), identity),
            artifact=replace(original.artifact, identity=identity),
            requested_mode="copy",
            effects=(
                EffectProof(
                    kind="managed-block",
                    destination="CLAUDE.md",
                    actual_mode="copy",
                    installed_digest=_digest("8"),
                ),
            ),
            setup_state_ref=None,
        )
        encoded = install_state_bytes(InstallState(2, (memory,))).decode()
        invalid = encoded.replace('"effects":', '"memory_mode":"overlay","effects":')

        self.assertIsInstance(parse_install_state(invalid), Err)

    def test_non_symlink_effect_cannot_claim_symlink_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-symlink"):
            EffectProof(
                kind="write-file",
                destination=".claude/rules.md",
                actual_mode="symlink",
                installed_digest=_digest("7"),
                source_path="payload/rules.md",
            )


if __name__ == "__main__":
    unittest.main()
