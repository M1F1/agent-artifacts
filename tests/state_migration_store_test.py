"""Atomic state migration adapter and application-service tests."""

from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_artifacts.application.state_migration import StateMigrationService
from agent_artifacts.configuration.model import SourceKind
from agent_artifacts.domain.identifiers import (
    ArtifactIdentity,
    ObjectDigest,
    SourceAlias,
    SourceId,
)
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.install_state.model import (
    ArtifactEvidence,
    EffectProof,
    LegacyMigrationCandidate,
    SourceEvidence,
)
from agent_artifacts.install_state.paths import install_state_paths
from agent_artifacts.io.state_store import LocalStateStore
from agent_artifacts.manifest import dump_manifest
from agent_artifacts.model import InstallProof, Manifest, ManifestEntry
from agent_artifacts.protocol.semver import SemVer


def _digest(character: str) -> ObjectDigest:
    return ObjectDigest("sha256", character * 64)


def _candidate(destination: str) -> LegacyMigrationCandidate:
    identity = ArtifactIdentity("skill", "code-review")
    return LegacyMigrationCandidate(
        "code-review",
        "skill",
        "claude",
        "pin:legacy-sha",
        SourceEvidence(
            SourceAlias("company"),
            SourceId("company-agent-artifacts"),
            SourceKind.REGISTRY_GIT,
            "https://github.com/acme/registry.git",
            "a" * 40,
            "main",
        ),
        ArtifactEvidence(identity, SemVer(1, 0, 0), _digest("1"), _digest("2"), _digest("3")),
        1,
        (
            EffectProof(
                "write-file",
                destination,
                "copy",
                _digest("4"),
                source_path="payload/SKILL.md",
            ),
        ),
    )


def _legacy(destination: str) -> bytes:
    return dump_manifest(
        Manifest(
            "M1F1/agent-artifacts",
            (
                ManifestEntry(
                    "code-review",
                    "skill",
                    "claude",
                    "pin:legacy-sha",
                    files={destination: str(_digest("4"))},
                    install=InstallProof(),
                ),
            ),
        )
    ).encode()


class StateMigrationStoreTests(unittest.TestCase):
    def test_user_apply_is_idempotent_and_rollback_restores_legacy_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            data = root / "data"
            destination = str(home / ".claude/skills/code-review/SKILL.md")
            paths = install_state_paths(
                "user",
                project_root=str(root / "project"),
                user_home=str(home),
                data_root=str(data),
            )
            legacy = _legacy(destination)
            legacy_path = Path(paths.legacy_path)
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_bytes(legacy)
            service = StateMigrationService(LocalStateStore())

            prepared = service.prepare(paths, (_candidate(destination),))
            self.assertIsInstance(prepared, Ok)
            self.assertFalse(Path(paths.destination_path).exists())

            applied = service.apply(prepared.value)
            self.assertIsInstance(applied, Ok)
            self.assertTrue(applied.value.changed)
            self.assertFalse(legacy_path.exists())
            self.assertTrue(Path(paths.destination_path).is_file())
            self.assertEqual(Path(prepared.value.backup_path).read_bytes(), legacy)
            self.assertEqual(stat.S_IMODE(Path(paths.destination_path).stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(Path(prepared.value.backup_path).stat().st_mode), 0o600)

            repeated = service.apply(prepared.value)
            self.assertEqual(repeated, Ok(applied.value.current()))

            rolled_back = service.rollback(applied.value)
            self.assertIsInstance(rolled_back, Ok)
            self.assertTrue(rolled_back.value.changed)
            self.assertEqual(legacy_path.read_bytes(), legacy)
            self.assertFalse(Path(paths.destination_path).exists())

    def test_project_apply_replaces_in_place_and_rollback_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            paths = install_state_paths(
                "project",
                project_root=str(project),
                user_home=str(root / "home"),
                data_root=str(root / "data"),
            )
            destination = ".claude/skills/code-review/SKILL.md"
            legacy = _legacy(destination)
            path = Path(paths.legacy_path)
            path.parent.mkdir(parents=True)
            path.write_bytes(legacy)
            service = StateMigrationService(LocalStateStore())

            plan = service.prepare(paths, (_candidate(destination),)).value
            receipt = service.apply(plan).value

            self.assertEqual(path.read_bytes(), plan.replacement)
            service.rollback(receipt)
            self.assertEqual(path.read_bytes(), legacy)

    def test_stale_review_refuses_apply_without_creating_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = install_state_paths(
                "project",
                project_root=str(root / "project"),
                user_home=str(root / "home"),
                data_root=str(root / "data"),
            )
            legacy_path = Path(paths.legacy_path)
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_bytes(_legacy(".claude/skills/code-review/SKILL.md"))
            service = StateMigrationService(LocalStateStore())
            plan = service.prepare(
                paths, (_candidate(".claude/skills/code-review/SKILL.md"),)
            ).value
            legacy_path.write_bytes(b'{"repo":"changed","installed":[]}')

            result = service.apply(plan)

            self.assertIsInstance(result, Err)
            self.assertFalse(Path(plan.backup_path).exists())
            self.assertEqual(legacy_path.read_bytes(), b'{"repo":"changed","installed":[]}')

    def test_partial_apply_failure_preserves_usable_legacy_and_no_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            data = root / "data"
            destination = str(home / ".claude/skills/code-review/SKILL.md")
            paths = install_state_paths(
                "user",
                project_root=str(root / "project"),
                user_home=str(home),
                data_root=str(data),
            )
            legacy = _legacy(destination)
            legacy_path = Path(paths.legacy_path)
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_bytes(legacy)
            service = StateMigrationService(LocalStateStore())
            plan = service.prepare(paths, (_candidate(destination),)).value

            from agent_artifacts.io import state_store

            real_write = state_store._write_private_atomic
            calls = 0

            def fail_destination(path: Path, content: bytes) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected destination failure")
                real_write(path, content)

            with patch.object(state_store, "_write_private_atomic", side_effect=fail_destination):
                result = service.apply(plan)

            self.assertIsInstance(result, Err)
            self.assertEqual(legacy_path.read_bytes(), legacy)
            self.assertFalse(Path(paths.destination_path).exists())

    def test_failure_after_destination_replace_is_compensated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            destination = str(home / ".claude/skills/code-review/SKILL.md")
            paths = install_state_paths(
                "user",
                project_root=str(root / "project"),
                user_home=str(home),
                data_root=str(root / "data"),
            )
            legacy = _legacy(destination)
            legacy_path = Path(paths.legacy_path)
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_bytes(legacy)
            service = StateMigrationService(LocalStateStore())
            plan = service.prepare(paths, (_candidate(destination),)).value

            from agent_artifacts.io import state_store

            real_write = state_store._write_private_atomic
            failed = False

            def replace_then_fail(path: Path, content: bytes) -> None:
                nonlocal failed
                real_write(path, content)
                if path == Path(plan.destination_path) and not failed:
                    failed = True
                    raise OSError("injected post-replace failure")

            with patch.object(state_store, "_write_private_atomic", side_effect=replace_then_fail):
                result = service.apply(plan)

            self.assertIsInstance(result, Err)
            self.assertEqual(legacy_path.read_bytes(), legacy)
            self.assertFalse(Path(paths.destination_path).exists())

    def test_failure_after_legacy_unlink_restores_legacy_and_removes_partial_v2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            destination = str(home / ".claude/skills/code-review/SKILL.md")
            paths = install_state_paths(
                "user",
                project_root=str(root / "project"),
                user_home=str(home),
                data_root=str(root / "data"),
            )
            legacy = _legacy(destination)
            legacy_path = Path(paths.legacy_path)
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_bytes(legacy)
            service = StateMigrationService(LocalStateStore())
            plan = service.prepare(paths, (_candidate(destination),)).value

            from agent_artifacts.io import state_store

            real_unlink = state_store._unlink
            failed = False

            def unlink_then_fail(path: Path) -> None:
                nonlocal failed
                real_unlink(path)
                if path == legacy_path and not failed:
                    failed = True
                    raise OSError("injected post-unlink failure")

            with patch.object(state_store, "_unlink", side_effect=unlink_then_fail):
                result = service.apply(plan)

            self.assertIsInstance(result, Err)
            self.assertEqual(legacy_path.read_bytes(), legacy)
            self.assertFalse(Path(plan.destination_path).exists())
            self.assertFalse(Path(plan.journal_path).exists())

    def test_failed_rollback_is_compensated_back_to_migrated_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            destination = str(home / ".claude/skills/code-review/SKILL.md")
            paths = install_state_paths(
                "user",
                project_root=str(root / "project"),
                user_home=str(home),
                data_root=str(root / "data"),
            )
            legacy_path = Path(paths.legacy_path)
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_bytes(_legacy(destination))
            service = StateMigrationService(LocalStateStore())
            plan = service.prepare(paths, (_candidate(destination),)).value
            receipt = service.apply(plan).value

            from agent_artifacts.io import state_store

            real_unlink = state_store._unlink
            failed = False

            def unlink_then_fail(path: Path) -> None:
                nonlocal failed
                real_unlink(path)
                if path == Path(plan.destination_path) and not failed:
                    failed = True
                    raise OSError("injected rollback failure")

            with patch.object(state_store, "_unlink", side_effect=unlink_then_fail):
                result = service.rollback(receipt)

            self.assertIsInstance(result, Err)
            self.assertFalse(legacy_path.exists())
            self.assertEqual(Path(plan.destination_path).read_bytes(), plan.replacement)
            self.assertEqual(Path(plan.journal_path).read_bytes(), plan.journal_content)
            self.assertIsInstance(service.rollback(receipt), Ok)

    def test_symlink_legacy_state_is_rejected_without_following_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = install_state_paths(
                "project",
                project_root=str(root / "project"),
                user_home=str(root / "home"),
                data_root=str(root / "data"),
            )
            target = root / "outside.json"
            target.write_bytes(_legacy(".claude/skills/code-review/SKILL.md"))
            legacy_path = Path(paths.legacy_path)
            legacy_path.parent.mkdir(parents=True)
            legacy_path.symlink_to(target)

            result = StateMigrationService(LocalStateStore()).prepare(
                paths, (_candidate(".claude/skills/code-review/SKILL.md"),)
            )

            self.assertIsInstance(result, Err)
            self.assertEqual(target.read_bytes(), _legacy(".claude/skills/code-review/SKILL.md"))


if __name__ == "__main__":
    unittest.main()
