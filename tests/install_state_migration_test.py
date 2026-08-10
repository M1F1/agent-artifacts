"""Pure 0.1.x manifest-to-v2 migration planning contracts."""

from __future__ import annotations

import ast
import unittest
from dataclasses import replace
from pathlib import Path

from agent_artifacts.configuration.model import SourceKind
from agent_artifacts.domain.identifiers import (
    ArtifactIdentity,
    ObjectDigest,
    SourceAlias,
    SourceId,
)
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.install_state.migration import plan_legacy_migration
from agent_artifacts.install_state.model import (
    ArtifactEvidence,
    EffectProof,
    LegacyMigrationCandidate,
    SourceEvidence,
)
from agent_artifacts.install_state.paths import install_state_paths
from agent_artifacts.install_state.schema import parse_install_state
from agent_artifacts.manifest import dump_manifest
from agent_artifacts.model import (
    CatalogSubscription,
    InstallLink,
    InstallProof,
    Manifest,
    ManifestEntry,
    MergeProof,
)
from agent_artifacts.protocol.hashing import json_digest, sha256_bytes
from agent_artifacts.protocol.json import JsonObject
from agent_artifacts.protocol.semver import SemVer


def _digest(character: str) -> ObjectDigest:
    return ObjectDigest("sha256", character * 64)


def _legacy(scope: str = "project") -> bytes:
    destination = (
        ".claude/skills/code-review/SKILL.md"
        if scope == "project"
        else "/Users/test/.claude/skills/code-review/SKILL.md"
    )
    return dump_manifest(
        Manifest(
            repo="M1F1/agent-artifacts",
            installed=(
                ManifestEntry(
                    artifact="code-review",
                    type="skill",
                    profile="claude",
                    source="pin:legacy-sha",
                    files={destination: str(_digest("4"))},
                    install=InstallProof(mode="copy", requested_mode="copy"),
                    installed_at="2026-08-10T00:00:00Z",
                ),
            ),
        )
    ).encode()


def _candidate(scope: str = "project") -> LegacyMigrationCandidate:
    destination = (
        ".claude/skills/code-review/SKILL.md"
        if scope == "project"
        else "/Users/test/.claude/skills/code-review/SKILL.md"
    )
    identity = ArtifactIdentity("skill", "code-review")
    return LegacyMigrationCandidate(
        legacy_artifact="code-review",
        legacy_type="skill",
        legacy_profile="claude",
        legacy_source="pin:legacy-sha",
        source=SourceEvidence(
            SourceAlias("company"),
            SourceId("company-agent-artifacts"),
            SourceKind.REGISTRY_GIT,
            "https://github.com/acme/agent-artifacts-registry.git",
            "a" * 40,
            "main",
        ),
        artifact=ArtifactEvidence(
            identity,
            SemVer(1, 4, 0),
            _digest("1"),
            _digest("2"),
            _digest("3"),
        ),
        profile_version=1,
        effects=(
            EffectProof(
                kind="write-file",
                destination=destination,
                actual_mode="copy",
                installed_digest=_digest("4"),
                source_path="payload/SKILL.md",
            ),
        ),
    )


class StateMigrationPlanningTests(unittest.TestCase):
    def test_project_migration_is_deterministic_in_place_with_backup(self) -> None:
        paths = install_state_paths(
            "project",
            project_root="/workspace/project",
            user_home="/Users/test",
            data_root="/data/aart",
        )

        first = plan_legacy_migration(_legacy(), (_candidate(),), paths)
        second = plan_legacy_migration(_legacy(), (_candidate(),), paths)

        self.assertEqual(first, second)
        self.assertIsInstance(first, Ok)
        plan = first.value
        self.assertEqual(plan.legacy_path, "/workspace/project/.agent-artifacts/manifest.json")
        self.assertEqual(plan.destination_path, plan.legacy_path)
        self.assertIn(str(sha256_bytes(_legacy())).removeprefix("sha256:")[:16], plan.backup_path)
        state = parse_install_state(plan.replacement)
        self.assertIsInstance(state, Ok)
        record = state.value.installations[0]
        self.assertEqual(str(record.coordinate), "company/skill/code-review")
        self.assertEqual(record.scope, "project")
        self.assertEqual(record.source.resolved_commit, "a" * 40)

    def test_user_migration_moves_destination_to_platform_data_root(self) -> None:
        paths = install_state_paths(
            "user",
            project_root="/workspace/project",
            user_home="/Users/test",
            data_root="/Users/test/Library/Application Support/agent-artifacts",
        )
        result = plan_legacy_migration(_legacy("user"), (_candidate("user"),), paths)

        self.assertIsInstance(result, Ok)
        self.assertEqual(result.value.legacy_path, "/Users/test/.agent-artifacts/manifest.json")
        self.assertEqual(
            result.value.destination_path,
            "/Users/test/Library/Application Support/agent-artifacts/state/manifest.json",
        )

    def test_ambiguous_or_missing_legacy_source_is_an_error(self) -> None:
        paths = install_state_paths(
            "project",
            project_root="/workspace/project",
            user_home="/Users/test",
            data_root="/data/aart",
        )
        for candidates, code in (
            ((), "state-migration-source-missing"),
            ((_candidate(), _candidate()), "state-migration-source-ambiguous"),
        ):
            with self.subTest(code=code):
                result = plan_legacy_migration(_legacy(), candidates, paths)
                self.assertIsInstance(result, Err)
                self.assertIn(code, {str(item.code) for item in result.diagnostics})

    def test_candidate_effects_must_prove_exact_legacy_destinations(self) -> None:
        candidate = _candidate()
        invalid = LegacyMigrationCandidate(
            legacy_artifact=candidate.legacy_artifact,
            legacy_type=candidate.legacy_type,
            legacy_profile=candidate.legacy_profile,
            legacy_source=candidate.legacy_source,
            source=candidate.source,
            artifact=candidate.artifact,
            profile_version=candidate.profile_version,
            effects=(),
        )
        paths = install_state_paths(
            "project",
            project_root="/workspace/project",
            user_home="/Users/test",
            data_root="/data/aart",
        )

        result = plan_legacy_migration(_legacy(), (invalid,), paths)

        self.assertIsInstance(result, Err)
        self.assertIn(
            "state-migration-proof-mismatch", {str(item.code) for item in result.diagnostics}
        )

    def test_legacy_symlink_cannot_be_silently_reinterpreted_as_copy(self) -> None:
        destination = ".claude/skills/code-review/SKILL.md"
        legacy = dump_manifest(
            Manifest(
                "M1F1/agent-artifacts",
                (
                    ManifestEntry(
                        "code-review",
                        "skill",
                        "claude",
                        "pin:legacy-sha",
                        files={destination: str(_digest("4"))},
                        install=InstallProof(
                            mode="symlink",
                            requested_mode="symlink",
                            links=(InstallLink(destination, "/legacy/target"),),
                        ),
                    ),
                ),
            )
        ).encode()
        paths = install_state_paths(
            "project",
            project_root="/workspace/project",
            user_home="/Users/test",
            data_root="/data/aart",
        )

        result = plan_legacy_migration(legacy, (_candidate(),), paths)

        self.assertIsInstance(result, Err)
        self.assertIn(
            "state-migration-proof-mismatch", {str(item.code) for item in result.diagnostics}
        )

    def test_plan_constructor_rejects_content_changed_after_review(self) -> None:
        paths = install_state_paths(
            "project",
            project_root="/workspace/project",
            user_home="/Users/test",
            data_root="/data/aart",
        )
        plan = plan_legacy_migration(_legacy(), (_candidate(),), paths).value

        with self.assertRaisesRegex(ValueError, "reviewed digests"):
            replace(plan, replacement=b'{"schema_version":2,"installations":[]}\n')

    def test_merge_identity_digest_must_bind_the_legacy_selector(self) -> None:
        legacy = dump_manifest(
            Manifest(
                "M1F1/agent-artifacts",
                (
                    ManifestEntry(
                        "code-review",
                        "skill",
                        "claude",
                        "pin:legacy-sha",
                        merge=MergeProof(
                            ".claude/settings.json",
                            "hooks.PreToolUse",
                            "key",
                            {"matcher": "Edit|Write"},
                            str(_digest("4")),
                        ),
                    ),
                ),
            )
        ).encode()
        candidate = replace(
            _candidate(),
            effects=(
                EffectProof(
                    "merge-json",
                    ".claude/settings.json",
                    "copy",
                    _digest("4"),
                    json_path="hooks.PreToolUse",
                    merge_mode="key",
                    identity_digest=json_digest(JsonObject((("matcher", "Edit|Write"),))),
                ),
            ),
        )
        paths = install_state_paths(
            "project",
            project_root="/workspace/project",
            user_home="/Users/test",
            data_root="/data/aart",
        )

        self.assertIsInstance(plan_legacy_migration(legacy, (candidate,), paths), Ok)
        forged = replace(
            candidate,
            effects=(replace(candidate.effects[0], identity_digest=_digest("9")),),
        )
        self.assertIsInstance(plan_legacy_migration(legacy, (forged,), paths), Err)

    def test_credential_bearing_legacy_subscription_is_not_copied_into_backup(self) -> None:
        legacy = dump_manifest(
            Manifest(
                "M1F1/agent-artifacts",
                (
                    ManifestEntry(
                        "code-review",
                        "skill",
                        "claude",
                        "pin:legacy-sha",
                        files={".claude/skills/code-review/SKILL.md": str(_digest("4"))},
                        subscription=CatalogSubscription(
                            "github",
                            "https://token@github.com/acme/private.git",
                            "main",
                        ),
                    ),
                ),
            )
        ).encode()
        paths = install_state_paths(
            "project",
            project_root="/workspace/project",
            user_home="/Users/test",
            data_root="/data/aart",
        )

        result = plan_legacy_migration(legacy, (_candidate(),), paths)

        self.assertIsInstance(result, Err)
        self.assertIn("credential-bearing", result.diagnostics[0].message)

    def test_duplicate_legacy_json_keys_are_rejected_instead_of_silently_reinterpreted(
        self,
    ) -> None:
        duplicate = _legacy().replace(
            b'"repo": "M1F1/agent-artifacts"',
            b'"repo":"first","repo":"M1F1/agent-artifacts"',
        )
        paths = install_state_paths(
            "project",
            project_root="/workspace/project",
            user_home="/Users/test",
            data_root="/data/aart",
        )

        result = plan_legacy_migration(duplicate, (_candidate(),), paths)

        self.assertIsInstance(result, Err)
        self.assertIn("strict JSON", result.diagnostics[0].message)

    def test_unknown_legacy_fields_are_rejected_instead_of_silently_dropped(self) -> None:
        unknown = _legacy().replace(
            b'"installed": [', b'"raw_setup_output":"secret","installed": ['
        )
        paths = install_state_paths(
            "project",
            project_root="/workspace/project",
            user_home="/Users/test",
            data_root="/data/aart",
        )

        result = plan_legacy_migration(unknown, (_candidate(),), paths)

        self.assertIsInstance(result, Err)
        self.assertIn("unknown", result.diagnostics[0].message)

    def test_functional_migration_core_does_not_import_io_modules(self) -> None:
        root = Path(__file__).parents[1]
        tree = ast.parse((root / "agent_artifacts/install_state/migration.py").read_text())
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertFalse(imports & {"os", "pathlib", "shutil", "tempfile", "agent_artifacts.io"})


if __name__ == "__main__":
    unittest.main()
