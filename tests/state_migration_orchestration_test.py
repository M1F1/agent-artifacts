"""0.1 filesystem/source evidence resolution into canonical migration candidates."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_artifacts.application.legacy_state_migration import (
    LegacyStateMigrationRequest,
    build_legacy_migration_candidates,
    parse_source_mappings,
)
from agent_artifacts.configuration.model import SourceKind
from agent_artifacts.consumer.model import ConsumerContext
from agent_artifacts.domain.identifiers import SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.installation.io import LocalInstallAdapter
from agent_artifacts.manifest import dump_manifest
from agent_artifacts.marketplace.catalog import build_marketplace
from agent_artifacts.model import (
    CatalogSubscription,
    InstallLink,
    InstallProof,
    Manifest,
    ManifestEntry,
    MergeProof,
)
from agent_artifacts.profiles.builtin import builtin
from agent_artifacts.protocol.hashing import json_digest
from agent_artifacts.protocol.json import JsonArray, JsonObject
from tests.canonical_symlink_test import _fixture
from tests.marketplace_fixtures import (
    configured_source,
    effective_configuration,
    graph,
    source_state,
)


def _context(fixture) -> ConsumerContext:
    _project, _checkout, paths, location, _request, catalog, effective = fixture
    return ConsumerContext(catalog, effective, builtin(), location, paths)


class LegacyStateMigrationOrchestrationTest(unittest.TestCase):
    def test_invalid_legacy_shape_is_rejected_before_any_effect_read(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            context = _context(_fixture(Path(raw), "skill"))
            legacy = b'{"repo":"x","installed":[{"artifact":7}]}'
            adapter = LocalInstallAdapter()

            with patch.object(
                adapter,
                "inspect_path",
                side_effect=AssertionError("invalid state must not inspect effects"),
            ):
                result = build_legacy_migration_candidates(
                    LegacyStateMigrationRequest(legacy, "project"),
                    context,
                    adapter,
                )

            self.assertIsInstance(result, Err)
            self.assertEqual(result.diagnostics[0].code.value, "state-migration-invalid")

    def test_copy_tree_uses_disk_proof_but_is_not_mislabeled_as_current_marketplace_bytes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            context = _context(_fixture(Path(raw), "skill"))
            destination = ".claude/skills/review"
            installed = Path(context.location.project_root, destination)
            installed.mkdir(parents=True)
            (installed / "SKILL.md").write_bytes(b"# legacy installed bytes\n")
            configured = context.effective.configuration.sources[0]
            legacy = dump_manifest(
                Manifest(
                    "M1F1/agent-artifacts",
                    (
                        ManifestEntry(
                            "review",
                            "skill",
                            "claude",
                            "main:" + "9" * 40,
                            files={destination: ""},
                            subscription=CatalogSubscription(
                                "github", configured.location, configured.ref
                            ),
                        ),
                    ),
                )
            ).encode()

            result = build_legacy_migration_candidates(
                LegacyStateMigrationRequest(legacy, "project"),
                context,
                LocalInstallAdapter(),
            )

            self.assertIsInstance(result, Ok)
            candidate = result.value[0]
            self.assertEqual(candidate.effects[0].kind, "copy-tree")
            self.assertEqual(candidate.effects[0].installed_digest.algorithm, "sha256")
            current = context.catalog.items[0].artifact.artifact
            self.assertNotEqual(candidate.artifact.object_digest, current.object_digest)
            self.assertEqual(candidate.source.alias.value, "direct")

    def test_key_merge_converts_full_legacy_path_to_canonical_identity_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            context = _context(_fixture(Path(raw), "mcp"))
            destination = ".mcp.json"
            value = {"command": "legacy-mcp"}
            Path(context.location.project_root, destination).write_text(
                '{"mcpServers":{"review":{"command":"legacy-mcp"}}}',
                encoding="utf-8",
            )
            from agent_artifacts.hashing import sha256_bytes

            legacy = dump_manifest(
                Manifest(
                    "M1F1/agent-artifacts",
                    (
                        ManifestEntry(
                            "review",
                            "mcp",
                            "claude",
                            "pin:" + "8" * 40,
                            merge=MergeProof(
                                destination,
                                "mcpServers.review",
                                "key",
                                {},
                                sha256_bytes(repr(value).encode()),
                            ),
                        ),
                    ),
                )
            ).encode()

            result = build_legacy_migration_candidates(
                LegacyStateMigrationRequest(legacy, "project"),
                context,
                LocalInstallAdapter(),
            )

            self.assertIsInstance(result, Ok)
            effect = result.value[0].effects[0]
            self.assertEqual(effect.json_path, "mcpServers")
            self.assertEqual(effect.identity_evidence, JsonArray(("review",)))
            self.assertEqual(
                effect.installed_digest,
                json_digest(JsonObject((("command", "legacy-mcp"),))),
            )

    def test_symlink_retains_exact_target_and_target_content_digest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = _fixture(Path(raw), "skill", source_kind=SourceKind.SOURCE_LOCAL)
            context = _context(fixture)
            target = Path(fixture[1], "skills", "review")
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("# live legacy\n", encoding="utf-8")
            destination = Path(context.location.project_root, ".claude/skills/review")
            destination.parent.mkdir(parents=True)
            destination.symlink_to(target, target_is_directory=True)
            logical = ".claude/skills/review"
            legacy = dump_manifest(
                Manifest(
                    "M1F1/agent-artifacts",
                    (
                        ManifestEntry(
                            "review",
                            "skill",
                            "claude",
                            "local:" + str(fixture[1]),
                            files={logical: ""},
                            install=InstallProof(
                                "symlink",
                                "symlink",
                                (InstallLink(logical, str(target)),),
                            ),
                            subscription=CatalogSubscription("local", str(fixture[1])),
                        ),
                    ),
                )
            ).encode()

            result = build_legacy_migration_candidates(
                LegacyStateMigrationRequest(legacy, "project"),
                context,
                LocalInstallAdapter(),
            )

            self.assertIsInstance(result, Ok)
            effect = result.value[0].effects[0]
            self.assertEqual(effect.kind, "symlink-tree")
            self.assertEqual(effect.link_target, str(target))
            self.assertEqual(effect.link_semantics, "mutable-local")

    def test_duplicate_artifact_requires_explicit_alias_instead_of_default_order(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = _fixture(Path(raw), "skill")
            project, _checkout, paths, location, _request, original, original_effective = fixture
            first_source = original_effective.configuration.sources[0]
            second_source = configured_source("other", SourceKind.SOURCE_GIT)
            first_artifact = original.items[0].artifact.artifact
            second_artifact = replace(first_artifact, source_id=SourceId("other-source"))
            effective = effective_configuration((first_source, second_source))
            catalog = build_marketplace(
                graph(
                    (first_source, "direct-source", (first_artifact,)),
                    (second_source, "other-source", (second_artifact,)),
                ),
                effective,
                (
                    source_state(first_source, "direct-source", display_order=0),
                    source_state(second_source, "other-source", display_order=1),
                ),
            )
            self.assertIsInstance(catalog, Ok)
            assert isinstance(catalog, Ok)
            context = ConsumerContext(catalog.value, effective, builtin(), location, paths)
            destination = ".claude/skills/review"
            installed = project / destination
            installed.mkdir(parents=True)
            (installed / "SKILL.md").write_text("# legacy\n", encoding="utf-8")
            legacy = dump_manifest(
                Manifest(
                    "M1F1/agent-artifacts",
                    (
                        ManifestEntry(
                            "review",
                            "skill",
                            "claude",
                            "main:" + "7" * 40,
                            files={destination: ""},
                        ),
                    ),
                )
            ).encode()

            ambiguous = build_legacy_migration_candidates(
                LegacyStateMigrationRequest(legacy, "project"),
                context,
                LocalInstallAdapter(),
            )
            mappings = parse_source_mappings(("skill/review@claude=other",))
            assert isinstance(mappings, Ok)
            resolved = build_legacy_migration_candidates(
                LegacyStateMigrationRequest(legacy, "project", mappings.value),
                context,
                LocalInstallAdapter(),
            )

            self.assertIsInstance(ambiguous, Err)
            self.assertEqual(
                ambiguous.diagnostics[0].code.value, "state-migration-source-ambiguous"
            )
            self.assertIsInstance(resolved, Ok)
            self.assertEqual(resolved.value[0].source.alias.value, "other")

    def test_source_mapping_syntax_is_strict_and_duplicates_are_rejected(self) -> None:
        parsed = parse_source_mappings(("skill/review@claude=direct",))
        duplicate = parse_source_mappings(
            ("skill/review@claude=direct", "skill/review@claude=other")
        )
        unsafe = parse_source_mappings(("../review@claude=direct",))

        self.assertIsInstance(parsed, Ok)
        self.assertEqual(parsed.value[0].alias.value, "direct")
        self.assertIsInstance(duplicate, Err)
        self.assertIsInstance(unsafe, Err)

    def test_invalid_legacy_identity_is_rejected_before_source_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            context = _context(_fixture(Path(raw), "skill"))
            legacy = dump_manifest(
                Manifest(
                    "M1F1/agent-artifacts",
                    (
                        ManifestEntry(
                            "../review",
                            "skill",
                            "claude",
                            "main:" + "7" * 40,
                            files={".claude/skills/review": ""},
                        ),
                    ),
                )
            ).encode()

            result = build_legacy_migration_candidates(
                LegacyStateMigrationRequest(legacy, "project"),
                context,
                LocalInstallAdapter(),
            )

            self.assertIsInstance(result, Err)
            self.assertEqual(result.diagnostics[0].code.value, "state-migration-resolution-invalid")


if __name__ == "__main__":
    unittest.main()
